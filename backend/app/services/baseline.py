from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import BaselineSnapshot, JobRun, VolumeSnapshot
from app.models.base import utcnow

SUCCESS_STATUSES = {"SUCCESS", "SUCCEEDED", "COMPLETED"}


def to_float(value: Decimal | int | float | None) -> float | None:
    if value is None:
        return None
    return float(value)


def duration_minutes(run: JobRun, now: datetime | None = None) -> float:
    end = run.ended_at or now or utcnow()
    return max((end - run.started_at).total_seconds() / 60, 0)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def median_abs_deviation(values: list[float]) -> float | None:
    if not values:
        return None
    center = median(values)
    return float(median([abs(value - center) for value in values]))


def confidence_score(sample_count: int, mad: float | None, p50: float | None, minimum_history: int) -> float:
    if sample_count == 0:
        return 0.0
    sample_component = min(sample_count / max(minimum_history, 1), 1.0)
    if not p50 or not mad:
        stability_component = 0.75
    else:
        relative_mad = mad / max(p50, 1)
        stability_component = max(0.0, min(1.0, 1 - relative_mad / 0.5))
    score = 0.15 + sample_component * 0.55 + stability_component * 0.30
    if sample_count < minimum_history:
        score *= 0.55
    return round(min(score, 0.99), 2)


def run_signature(run: JobRun) -> str:
    return "|".join(
        [
            run.job_family or "",
            run.job_type or "",
            run.job_name or "",
            run.region or "",
            run.workstream or "",
            run.api_operation or "",
        ]
    )


@dataclass
class BaselineComputation:
    customer_key: str
    environment: str
    job_signature: str
    sample_count: int
    p50_minutes: float | None
    p75_minutes: float | None
    p90_minutes: float | None
    p95_minutes: float | None
    average_minutes: float | None
    median_abs_deviation: float | None
    last_successful_duration: float | None
    baseline_volume_metric: float | None
    throughput_per_minute: float | None
    confidence_score: float
    sample_run_ids: list[int]
    last_successful_sql_id: str | None = None
    last_successful_plan_hash: str | None = None
    last_successful_udq_hash: str | None = None


class BaselineService:
    def __init__(self, db: Session):
        self.db = db

    def matching_history(self, run: JobRun) -> list[JobRun]:
        stmt = select(JobRun).where(
            JobRun.customer_id == run.customer_id,
            JobRun.environment_id == run.environment_id,
            JobRun.status.in_(SUCCESS_STATUSES),
            JobRun.ended_at.is_not(None),
            JobRun.id != run.id,
        )
        if run.job_definition_id:
            stmt = stmt.where(JobRun.job_definition_id == run.job_definition_id)
        else:
            stmt = stmt.where(JobRun.job_type == run.job_type, JobRun.job_name == run.job_name)
        if run.region:
            stmt = stmt.where(JobRun.region == run.region)
        if run.workstream:
            stmt = stmt.where(JobRun.workstream == run.workstream)
        return list(
            self.db.scalars(
                stmt.options(selectinload(JobRun.volume_snapshots)).order_by(JobRun.started_at.asc())
            )
        )

    def compute_for_run(self, run: JobRun, minimum_history: int = 5) -> BaselineComputation:
        history = self.matching_history(run)
        durations = [duration_minutes(item, now=item.ended_at) for item in history]
        p50 = percentile(durations, 0.50)
        p75 = percentile(durations, 0.75)
        p90 = percentile(durations, 0.90)
        p95 = percentile(durations, 0.95)
        avg = mean(durations) if durations else None
        mad = median_abs_deviation(durations)
        last_duration = duration_minutes(history[-1], now=history[-1].ended_at) if history else None
        last_success = history[-1] if history else None
        volume_metric = self._baseline_volume_for_runs(history)
        throughput = volume_metric / p75 if volume_metric and p75 else None
        score = confidence_score(len(durations), mad, p50, minimum_history)
        return BaselineComputation(
            customer_key=run.customer.customer_key,
            environment=run.environment.name,
            job_signature=run_signature(run),
            sample_count=len(durations),
            p50_minutes=p50,
            p75_minutes=p75,
            p90_minutes=p90,
            p95_minutes=p95,
            average_minutes=avg,
            median_abs_deviation=mad,
            last_successful_duration=last_duration,
            baseline_volume_metric=volume_metric,
            throughput_per_minute=throughput,
            confidence_score=score,
            sample_run_ids=[item.id for item in history],
            last_successful_sql_id=last_success.sql_id if last_success else None,
            last_successful_plan_hash=last_success.plan_hash_value if last_success else None,
            last_successful_udq_hash=last_success.udq_hash if last_success else None,
        )

    def persist_snapshot(self, computation: BaselineComputation) -> BaselineSnapshot:
        snapshot = BaselineSnapshot(
            customer_key=computation.customer_key,
            environment=computation.environment,
            job_signature=computation.job_signature,
            baseline_method="historical_p75",
            p50_minutes=self._decimal(computation.p50_minutes),
            p75_minutes=self._decimal(computation.p75_minutes),
            p90_minutes=self._decimal(computation.p90_minutes),
            p95_minutes=self._decimal(computation.p95_minutes),
            average_minutes=self._decimal(computation.average_minutes),
            median_abs_deviation=self._decimal(computation.median_abs_deviation),
            sample_count=computation.sample_count,
            last_successful_duration=self._decimal(computation.last_successful_duration),
            baseline_volume_metric=self._decimal(computation.baseline_volume_metric),
            throughput_per_minute=self._decimal(computation.throughput_per_minute, places=4),
            confidence_score=self._decimal(computation.confidence_score),
            comparable_signature={"sample_run_ids": computation.sample_run_ids},
        )
        self.db.add(snapshot)
        self.db.flush()
        return snapshot

    def _baseline_volume_for_runs(self, runs: list[JobRun]) -> float | None:
        values: list[float] = []
        for run in runs:
            snapshot = next(
                (item for item in run.volume_snapshots if item.metric_name == "transactions"),
                None,
            )
            if snapshot and snapshot.metric_value is not None:
                values.append(float(snapshot.metric_value))
        if not values:
            return None
        return float(median(values))

    @staticmethod
    def _decimal(value: float | None, places: int = 2) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(round(value, places)))
