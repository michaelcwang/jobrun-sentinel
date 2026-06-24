from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Alert,
    Customer,
    DbSessionSnapshot,
    DiagnosticFinding,
    DiagnosticReport,
    Environment,
    JobRun,
    SqlObservation,
    VolumeSnapshot,
)
from app.models.base import utcnow
from app.schemas import CustomerCriticalEventSummary, CustomerExecutiveSummaryResponse
from app.services.evaluation import EvaluationService


class CustomerExecutiveSummaryService:
    """Builds a local AI-style synthesis from runtime, diagnostic, SQL, volume, and topology evidence."""

    generation_mode = "local_ai_synthesis"

    def __init__(self, db: Session):
        self.db = db
        self.evaluation_service = EvaluationService(db)

    def generate(
        self,
        customer_key: str,
        *,
        environment: str | None = None,
        limit: int = 100,
    ) -> CustomerExecutiveSummaryResponse:
        # Keep the executive summary backend-owned so every client sees the same
        # critical-event ordering and a future LLM provider can reuse this evidence contract.
        customer = self.db.scalar(select(Customer).where(Customer.customer_key == customer_key))
        if not customer:
            raise ValueError(f"Customer {customer_key} was not found")

        stmt = (
            select(JobRun)
            .join(Environment, JobRun.environment_id == Environment.id)
            .where(
                JobRun.customer_id == customer.id,
                JobRun.status.in_(["RUNNING", "WATCH"]),
            )
            .options(
                selectinload(JobRun.customer),
                selectinload(JobRun.environment),
                selectinload(JobRun.alerts),
                selectinload(JobRun.sql_observations),
                selectinload(JobRun.volume_snapshots),
                selectinload(JobRun.db_session_snapshots),
                selectinload(JobRun.diagnostic_reports).selectinload(DiagnosticReport.findings),
            )
            .order_by(JobRun.started_at.asc())
        )
        if environment:
            stmt = stmt.where(Environment.name == environment)

        events: list[tuple[JobRun, Any]] = []
        for run in self.db.scalars(stmt):
            evaluation = self.evaluation_service.evaluate_run(run.id)
            if evaluation.runtime_state == "critical" or evaluation.severity == "critical":
                events.append((run, evaluation))

        events.sort(
            key=lambda item: (
                -(item[1].variance_pct or 0),
                item[0].started_at,
                item[0].id,
            )
        )
        bullets = [self._event_summary(run, evaluation) for run, evaluation in events[:limit]]
        headline = (
            f"{len(events)} critical event{'s' if len(events) != 1 else ''} need executive attention."
            if events
            else "No active critical events in this customer scope."
        )

        return CustomerExecutiveSummaryResponse(
            generated_at=utcnow(),
            customer_key=customer.customer_key,
            customer_name=customer.display_name,
            environment=environment,
            generation_mode=self.generation_mode,
            headline=headline,
            critical_event_count=len(events),
            data_points_used=[
                "runtime evaluation",
                "active alerts",
                "diagnostic findings",
                "SQL/UDQ observations",
                "volume snapshots",
                "runtime topology/session snapshots",
            ],
            bullets=bullets,
        )

    def _event_summary(self, run: JobRun, evaluation: Any) -> CustomerCriticalEventSummary:
        # The customer page stays concise: elapsed vs expected, likely issue, and fix.
        # Full evidence remains on Explore run, diagnostics, topology, SQL/UDQ, and alerts.
        latest_diagnostic = self._latest_diagnostic(run)
        top_finding = self._top_finding(latest_diagnostic)
        latest_alert = self._latest_alert(run)
        sql_observation = self._primary_sql_observation(run)
        volume_summary = self._volume_summary(run.volume_snapshots)
        topology_summary = self._topology_summary(run)
        proposed_solution = self._proposed_solution(
            evaluation=evaluation,
            finding=top_finding,
            sql_observation=sql_observation,
        )
        supporting_analysis = self._supporting_analysis(
            evaluation=evaluation,
            finding=top_finding,
            alert=latest_alert,
            sql_observation=sql_observation,
            volume_summary=volume_summary,
            topology_summary=topology_summary,
        )

        return CustomerCriticalEventSummary(
            run_id=run.id,
            job_name=run.job_name,
            job_type=run.job_type,
            environment=run.environment.name,
            region=run.region,
            workstream=run.workstream,
            status=run.status,
            started_at=run.started_at,
            elapsed_minutes=evaluation.elapsed_minutes,
            expected_minutes=evaluation.expected_minutes,
            variance_pct=evaluation.variance_pct,
            top_suspected_cause=evaluation.top_suspected_cause,
            proposed_solution=proposed_solution,
            supporting_analysis=supporting_analysis,
            reason_codes=evaluation.reason_codes,
            diagnostic_id=latest_diagnostic.id if latest_diagnostic else None,
            diagnostic_title=latest_diagnostic.report_title if latest_diagnostic else None,
            diagnostic_top_finding=top_finding.title if top_finding else None,
            topology_summary=topology_summary,
        )

    @staticmethod
    def _latest_diagnostic(run: JobRun) -> DiagnosticReport | None:
        reports = sorted(run.diagnostic_reports, key=lambda item: (item.updated_at, item.created_at), reverse=True)
        return reports[0] if reports else None

    @staticmethod
    def _top_finding(report: DiagnosticReport | None) -> DiagnosticFinding | None:
        if not report or not report.findings:
            return None
        return sorted(report.findings, key=lambda item: (item.severity != "critical", item.finding_number))[0]

    @staticmethod
    def _latest_alert(run: JobRun) -> Alert | None:
        return sorted(run.alerts, key=lambda item: item.created_at, reverse=True)[0] if run.alerts else None

    @staticmethod
    def _primary_sql_observation(run: JobRun) -> SqlObservation | None:
        if not run.sql_observations:
            return None
        return sorted(
            run.sql_observations,
            key=lambda item: (float(item.elapsed_time_delta or 0), float(item.buffer_gets_delta or 0)),
            reverse=True,
        )[0]

    @staticmethod
    def _volume_summary(snapshots: list[VolumeSnapshot]) -> str | None:
        for snapshot in snapshots:
            if snapshot.baseline_value and float(snapshot.baseline_value) > 0:
                ratio = float(snapshot.metric_value) / float(snapshot.baseline_value)
                if ratio >= 1.2:
                    return f"{snapshot.metric_name} is {ratio:.1f}x baseline"
            if snapshot.shape_tags:
                return ", ".join(str(tag) for tag in snapshot.shape_tags[:2])
        return None

    @staticmethod
    def _topology_summary(run: JobRun) -> str | None:
        session = sorted(
            run.db_session_snapshots,
            key=lambda item: (item.sampled_at, item.last_call_et_seconds or 0),
            reverse=True,
        )[0] if run.db_session_snapshots else None
        if not session:
            return None
        return (
            f"Active on {session.instance_name or 'unknown DB instance'}"
            f" with SQL_ID {session.sql_id or run.sql_id or 'unknown'}"
            f" and wait {session.wait_class or session.event or 'unknown'}."
        )

    def _proposed_solution(
        self,
        *,
        evaluation: Any,
        finding: DiagnosticFinding | None,
        sql_observation: SqlObservation | None,
    ) -> str:
        if finding and finding.recommended_action:
            return finding.recommended_action
        if sql_observation and sql_observation.recommendation_text:
            return sql_observation.recommendation_text
        if evaluation.recommended_actions:
            return evaluation.recommended_actions[0]
        return "Open the run diagnostic and validate the active SQL, plan, volume, and progress evidence."

    def _supporting_analysis(
        self,
        *,
        evaluation: Any,
        finding: DiagnosticFinding | None,
        alert: Alert | None,
        sql_observation: SqlObservation | None,
        volume_summary: str | None,
        topology_summary: str | None,
    ) -> list[str]:
        analysis: list[str] = []
        if evaluation.expected_minutes is not None:
            analysis.append(
                f"Elapsed {evaluation.elapsed_minutes:g}m vs expected {evaluation.expected_minutes:g}m"
                + (f" ({evaluation.variance_pct:g}% variance)." if evaluation.variance_pct is not None else ".")
            )
        if evaluation.top_suspected_cause:
            analysis.append(f"Likely driver: {evaluation.top_suspected_cause}.")
        if finding:
            analysis.append(
                f"Diagnostic finding: {finding.title}"
                + (f" ({finding.confidence} confidence, {finding.actionability})." if finding.confidence else ".")
            )
        if sql_observation:
            details = [
                f"SQL_ID {sql_observation.sql_id}" if sql_observation.sql_id else None,
                f"plan {sql_observation.plan_hash_value}" if sql_observation.plan_hash_value else None,
                f"UDQ {sql_observation.udq_name}" if sql_observation.udq_name else None,
                f"wait {sql_observation.top_wait_event}" if sql_observation.top_wait_event else None,
            ]
            analysis.append("SQL/UDQ evidence: " + ", ".join(item for item in details if item) + ".")
        if volume_summary:
            analysis.append(f"Volume/scope signal: {volume_summary}.")
        if topology_summary:
            analysis.append(f"Topology: {topology_summary}")
        if alert and alert.state:
            analysis.append(f"Alert state: {alert.state}.")
        if not analysis:
            analysis.append("Critical evaluation is based on runtime threshold breach and available run metadata.")
        return analysis[:6]
