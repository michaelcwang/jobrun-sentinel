from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Environment, JobDefinition, JobRun, QueryTemplate, SqlObservation, VolumeSnapshot
from app.models.base import utcnow
from app.services.evaluation import EvaluationService
from app.services.query_execution import QueryExecutionSummary, QueryTemplateExecutionService


@dataclass
class IngestionSummary:
    execution: QueryExecutionSummary
    ingested_entity_counts: dict[str, int] = field(default_factory=dict)
    affected_run_ids: list[int] = field(default_factory=list)
    evaluations: list[dict[str, Any]] = field(default_factory=list)


class QueryTemplateIngestionService:
    def __init__(self, db: Session):
        self.db = db
        self.execution_service = QueryTemplateExecutionService(db)

    def ingest(
        self,
        template: QueryTemplate,
        *,
        customer_key: str,
        environment_name: str,
        parameters: dict[str, Any] | None = None,
        connector_config_key: str | None = None,
        initiated_by: str = "user",
        executed_by: str = "operator",
    ) -> IngestionSummary:
        execution = self.execution_service.execute(
            template,
            customer_key=customer_key,
            environment_name=environment_name,
            parameters=parameters,
            connector_config_key=connector_config_key,
            initiated_by=initiated_by,
            executed_by=executed_by,
        )
        counts: dict[str, int] = {}
        affected: list[int] = []
        mapping = template.output_mapping or {}
        entity = mapping.get("entity")
        for row in execution.rows:
            if entity == "job_run":
                run = self._upsert_job_run(row, mapping, customer_key, environment_name, template, execution.log.id)
                counts["job_run"] = counts.get("job_run", 0) + 1
                affected.append(run.id)
            elif entity == "volume_snapshot":
                snapshot = self._upsert_volume(row, mapping)
                if snapshot:
                    counts["volume_snapshot"] = counts.get("volume_snapshot", 0) + 1
                    affected.append(snapshot.run_id)
            elif entity == "sql_observation":
                observation = self._upsert_sql_observation(row, mapping, template, execution.log.id)
                if observation:
                    counts["sql_observation"] = counts.get("sql_observation", 0) + 1
                    affected.append(observation.run_id)

        affected = sorted(set(affected))
        evaluations = [
            EvaluationService(self.db).evaluate_run(run_id, create_alert=True).model_dump(mode="json")
            for run_id in affected
        ]
        execution.log.ingested_entity_counts = counts
        self.db.flush()
        return IngestionSummary(
            execution=execution,
            ingested_entity_counts=counts,
            affected_run_ids=affected,
            evaluations=evaluations,
        )

    def _upsert_job_run(
        self,
        row: dict[str, Any],
        mapping: dict[str, Any],
        customer_key: str,
        environment_name: str,
        template: QueryTemplate,
        execution_log_id: int,
    ) -> JobRun:
        fields = mapping.get("fields", {})
        customer = self._get_or_create_customer(customer_key)
        environment = self._get_or_create_environment(customer, environment_name)
        job_name = _get(row, fields, "job_name") or "Imported Oracle Job"
        job_type = _get(row, fields, "api_operation") or _get(row, fields, "job_type") or "Oracle Job"
        region = _get(row, fields, "region")
        workstream = _get(row, fields, "workstream")
        job_definition = self._get_or_create_job_definition(customer, job_type, job_name, region, workstream)
        external_id = _get(row, fields, "external_run_id") or _get(row, fields, "process_id") or _get(row, fields, "ess_request_id")
        run_key = str(external_id or f"{customer_key}-{environment_name}-{job_name}").replace(" ", "-")
        run = self.db.scalar(select(JobRun).where(JobRun.run_key == run_key))
        started_at = _dt(_get(row, fields, "started_at"))
        elapsed = _float(_get(row, fields, "elapsed_minutes"))
        if started_at is None:
            started_at = utcnow() - timedelta(minutes=elapsed or 0)
        ended_at = _dt(_get(row, fields, "ended_at"))
        if run is None:
            run = JobRun(
                run_key=run_key,
                customer_id=customer.id,
                environment_id=environment.id,
                job_definition_id=job_definition.id,
                started_at=started_at,
                status=_get(row, fields, "status") or "RUNNING",
                job_type=job_type,
                job_name=job_name,
            )
            self.db.add(run)
        run.customer_id = customer.id
        run.environment_id = environment.id
        run.job_definition_id = job_definition.id
        run.job_family = template.job_family or "ICM Calculation"
        run.job_type = job_type
        run.job_name = job_name
        run.region = region
        run.workstream = workstream
        run.period = _get(row, fields, "business_period")
        run.started_at = started_at
        run.ended_at = ended_at
        run.status = _get(row, fields, "status") or run.status
        run.ess_request_id = _get(row, fields, "ess_request_id")
        run.process_id = _get(row, fields, "process_id")
        run.api_operation = _get(row, fields, "api_operation")
        run.sql_id = row.get("SQL_ID") or row.get("sql_id") or run.sql_id
        run.plan_hash_value = row.get("PLAN_HASH_VALUE") or row.get("plan_hash_value") or run.plan_hash_value
        run.udq_name = row.get("UDQ_NAME") or row.get("udq_name") or run.udq_name
        run.udq_hash = row.get("UDQ_HASH") or row.get("udq_hash") or run.udq_hash
        run.source_type = "direct_db_query"
        run.source_connector = "oracle_db"
        run.source_template_id = template.template_id
        run.source_query_execution_id = execution_log_id
        run.ingested_at = utcnow()
        run.business_scope = {
            **(run.business_scope or {}),
            "provenance": {
                "source_connector": "oracle_db",
                "template_id": template.template_id,
                "query_execution_log_id": execution_log_id,
                "ingested_at": run.ingested_at.isoformat(),
            },
        }
        self.db.flush()
        return run

    def _upsert_volume(self, row: dict[str, Any], mapping: dict[str, Any]) -> VolumeSnapshot | None:
        fields = mapping.get("fields", {})
        run = self._run_by_mapping(row, fields)
        if not run:
            return None
        metric_name = _get(row, fields, "metric_name") or "transactions"
        snapshot = self.db.scalar(
            select(VolumeSnapshot).where(VolumeSnapshot.run_id == run.id, VolumeSnapshot.metric_name == metric_name)
        )
        if snapshot is None:
            snapshot = VolumeSnapshot(run_id=run.id, metric_name=metric_name, metric_value=Decimal("0"))
            self.db.add(snapshot)
        snapshot.metric_value = _decimal(_get(row, fields, "metric_value")) or Decimal("0")
        snapshot.baseline_value = _decimal(_get(row, fields, "baseline_value"))
        snapshot.unit = _get(row, fields, "unit")
        snapshot.shape_tags = _tags(_get(row, fields, "shape_tags"))
        self.db.flush()
        return snapshot

    def _upsert_sql_observation(
        self, row: dict[str, Any], mapping: dict[str, Any], template: QueryTemplate, execution_log_id: int
    ) -> SqlObservation | None:
        fields = mapping.get("fields", {})
        run = self._run_by_mapping(row, fields)
        if not run:
            return None
        sql_id = _get(row, fields, "sql_id")
        plan_hash = _get(row, fields, "plan_hash_value")
        observation = self.db.scalar(
            select(SqlObservation).where(
                SqlObservation.run_id == run.id,
                SqlObservation.sql_id == sql_id,
                SqlObservation.plan_hash_value == plan_hash,
            )
        )
        if observation is None:
            observation = SqlObservation(run_id=run.id, sql_id=sql_id, plan_hash_value=plan_hash)
            self.db.add(observation)
        observation.child_number = _int(_get(row, fields, "child_number"))
        observation.sql_profile = _get(row, fields, "sql_profile")
        observation.module = _get(row, fields, "module")
        observation.action = _get(row, fields, "action")
        observation.elapsed_time_delta = _decimal(_get(row, fields, "elapsed_time_delta"))
        observation.buffer_gets_delta = _decimal(_get(row, fields, "buffer_gets_delta"))
        observation.rows_processed_delta = _decimal(_get(row, fields, "rows_processed_delta"))
        observation.top_wait_event = _get(row, fields, "top_wait_event")
        observation.udq_name = _get(row, fields, "udq_name")
        observation.udq_hash = _get(row, fields, "udq_hash")
        observation.query_shape_tags = _tags(_get(row, fields, "query_shape_tags"))
        observation.index_profile_notes = _get(row, fields, "index_profile_notes")
        observation.recommendation_text = _get(row, fields, "recommendation_text")
        run.source_type = "direct_db_query"
        run.source_connector = "oracle_db"
        run.source_template_id = template.template_id
        run.source_query_execution_id = execution_log_id
        run.ingested_at = utcnow()
        self.db.flush()
        return observation

    def _run_by_mapping(self, row: dict[str, Any], fields: dict[str, str]) -> JobRun | None:
        run_key = _get(row, fields, "run_key")
        if not run_key:
            return None
        return self.db.scalar(select(JobRun).where(JobRun.run_key == run_key))

    def _get_or_create_customer(self, customer_key: str) -> Customer:
        customer = self.db.scalar(select(Customer).where(Customer.customer_key == customer_key))
        if customer:
            return customer
        customer = Customer(customer_key=customer_key, display_name=customer_key.replace("_", " "))
        self.db.add(customer)
        self.db.flush()
        return customer

    def _get_or_create_environment(self, customer: Customer, name: str) -> Environment:
        environment = self.db.scalar(select(Environment).where(Environment.customer_id == customer.id, Environment.name == name))
        if environment:
            return environment
        environment = Environment(customer_id=customer.id, name=name, lifecycle="prod", region="global")
        self.db.add(environment)
        self.db.flush()
        return environment

    def _get_or_create_job_definition(
        self, customer: Customer, job_type: str, job_name: str, region: str | None, workstream: str | None
    ) -> JobDefinition:
        job = self.db.scalar(
            select(JobDefinition).where(
                JobDefinition.customer_id == customer.id,
                JobDefinition.job_family == "ICM Calculation",
                JobDefinition.job_type == job_type,
                JobDefinition.job_name == job_name,
            )
        )
        if job:
            return job
        job = JobDefinition(
            customer_id=customer.id,
            job_family="ICM Calculation",
            job_type=job_type,
            job_name=job_name,
            default_region=region,
            default_workstream=workstream,
        )
        self.db.add(job)
        self.db.flush()
        return job


def _get(row: dict[str, Any], fields: dict[str, str], key: str) -> Any:
    column = fields.get(key)
    if not column:
        return row.get(key) or row.get(key.upper())
    return row.get(column) if column in row else row.get(column.upper())


def _dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [item.strip() for item in str(value).split(",") if item.strip()]
