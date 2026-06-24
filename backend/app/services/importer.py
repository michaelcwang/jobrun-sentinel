import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    Environment,
    ExpectationRecord,
    ImportBatch,
    ImportedPlanRow,
    JobDefinition,
    JobRun,
    VolumeSnapshot,
)
from app.models.base import utcnow


COLUMN_ALIASES = {
    "step": ["Step", "step", "Job Step", "Name"],
    "status": ["Status", "status"],
    "process_id": ["Process ID", "ProcessId", "process_id", "Process"],
    "actual_minutes": ["Actual Execution Time (Minutes)", "Actual Minutes", "Actual"],
    "estimated_minutes": ["Estimated Run Time", "Estimated Run Time (Minutes)", "Estimate"],
    "started_at": ["Start Timestamp", "Start", "Started At"],
    "ended_at": ["End Timestamp", "End", "Ended At"],
    "owner": ["Owner/Who", "Owner", "Who"],
    "comment": ["Comment", "Notes", "comment"],
    "volume": ["Volume", "Rows", "Transactions"],
}


@dataclass
class ImportResult:
    batch: ImportBatch
    created_runs: int
    created_expectations: int


class ManualPlanImporter:
    def __init__(self, db: Session):
        self.db = db

    def import_csv(
        self,
        filename: str,
        content: bytes,
        *,
        customer_key: str = "CUST_A",
        environment_name: str = "PROD",
        created_by: str = "operator",
    ) -> ImportResult:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        customer = self._customer(customer_key)
        environment = self._environment(customer, environment_name)
        batch = ImportBatch(
            filename=filename,
            source_type="manual_plan_csv",
            status="imported",
            created_by=created_by,
            updated_by=created_by,
            notes="CSV import complete. XLSX support is wired as a documented extension point.",
        )
        self.db.add(batch)
        self.db.flush()

        created_runs = 0
        created_expectations = 0
        for row_number, raw in enumerate(reader, start=1):
            normalized = {key: self._get(raw, aliases) for key, aliases in COLUMN_ALIASES.items()}
            plan_row = ImportedPlanRow(
                import_batch_id=batch.id,
                row_number=row_number,
                step=normalized["step"],
                status=normalized["status"],
                process_id=normalized["process_id"],
                actual_execution_minutes=self._decimal(normalized["actual_minutes"]),
                estimated_run_minutes=self._decimal(normalized["estimated_minutes"]),
                started_at=self._parse_datetime(normalized["started_at"]),
                ended_at=self._parse_datetime(normalized["ended_at"]),
                owner=normalized["owner"],
                comment=normalized["comment"],
                volume=self._decimal(normalized["volume"]),
                raw=raw,
            )
            self.db.add(plan_row)
            batch.row_count += 1

            if plan_row.step and plan_row.process_id:
                job_definition = self._job_definition(customer, plan_row.step)
                started_at = plan_row.started_at or utcnow()
                ended_at = plan_row.ended_at
                if ended_at is None and plan_row.actual_execution_minutes is not None:
                    ended_at = started_at + timedelta(minutes=float(plan_row.actual_execution_minutes))
                run = JobRun(
                    run_key=f"import-{batch.id}-{row_number}-{plan_row.process_id}",
                    customer_id=customer.id,
                    environment_id=environment.id,
                    job_definition_id=job_definition.id,
                    job_family=job_definition.job_family,
                    job_type=job_definition.job_type,
                    job_name=job_definition.job_name,
                    region=job_definition.default_region,
                    workstream=job_definition.default_workstream,
                    started_at=started_at,
                    ended_at=ended_at,
                    status=self._normalize_status(plan_row.status),
                    process_id=plan_row.process_id,
                    expected_minutes_at_start=plan_row.estimated_run_minutes,
                    notes=plan_row.comment,
                )
                self.db.add(run)
                self.db.flush()
                plan_row.mapped_run_id = run.id
                created_runs += 1
                if plan_row.volume is not None:
                    self.db.add(
                        VolumeSnapshot(
                            run_id=run.id,
                            metric_name="transactions",
                            metric_value=plan_row.volume,
                            baseline_value=None,
                            unit="rows",
                            shape_tags=[],
                        )
                    )
                if plan_row.estimated_run_minutes is not None:
                    self.db.add(
                        ExpectationRecord(
                            customer_key=customer.customer_key,
                            environment=environment.name,
                            job_family=job_definition.job_family,
                            job_type=job_definition.job_type,
                            job_name=job_definition.job_name,
                            region=job_definition.default_region,
                            workstream=job_definition.default_workstream,
                            baseline_method="imported_plan",
                            expected_minutes=plan_row.estimated_run_minutes,
                            warning_threshold_pct=25,
                            critical_threshold_pct=75,
                            confidence_score=Decimal("0.50"),
                            owner=plan_row.owner,
                            notes=f"Imported from {filename}, row {row_number}.",
                        )
                    )
                    created_expectations += 1

        return ImportResult(batch=batch, created_runs=created_runs, created_expectations=created_expectations)

    def _customer(self, customer_key: str) -> Customer:
        customer = self.db.scalar(select(Customer).where(Customer.customer_key == customer_key))
        if customer:
            return customer
        customer = Customer(customer_key=customer_key, display_name=customer_key.replace("_", " "))
        self.db.add(customer)
        self.db.flush()
        return customer

    def _environment(self, customer: Customer, name: str) -> Environment:
        environment = self.db.scalar(
            select(Environment).where(Environment.customer_id == customer.id, Environment.name == name)
        )
        if environment:
            return environment
        environment = Environment(customer_id=customer.id, name=name, region="global", lifecycle="prod")
        self.db.add(environment)
        self.db.flush()
        return environment

    def _job_definition(self, customer: Customer, step: str) -> JobDefinition:
        job = self.db.scalar(
            select(JobDefinition).where(
                JobDefinition.customer_id == customer.id,
                JobDefinition.job_name == step,
                JobDefinition.job_type == "Imported Plan Step",
            )
        )
        if job:
            return job
        job = JobDefinition(
            customer_id=customer.id,
            job_family="Manual Plan",
            job_type="Imported Plan Step",
            job_name=step,
            default_region="global",
            default_workstream="manual",
            process_name=step,
        )
        self.db.add(job)
        self.db.flush()
        return job

    @staticmethod
    def _get(raw: dict[str, str], aliases: list[str]) -> str | None:
        for alias in aliases:
            if alias in raw and raw[alias] != "":
                return raw[alias]
        return None

    @staticmethod
    def _decimal(value: str | None) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value).replace(",", ""))
        except InvalidOperation:
            return None

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _normalize_status(status: str | None) -> str:
        if not status:
            return "UNKNOWN"
        normalized = status.upper()
        if normalized in {"DONE", "COMPLETE", "COMPLETED", "SUCCESS", "SUCCEEDED"}:
            return "SUCCESS"
        if normalized in {"RUNNING", "IN PROGRESS"}:
            return "RUNNING"
        if normalized in {"FAILED", "ERROR"}:
            return "FAILED"
        return normalized
