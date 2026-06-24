from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import DbSessionSnapshot, JobRun, JobRunNodeBinding, QueryExecutionLog, QueryTemplate, RuntimeNode
from app.models.base import utcnow
from app.services.query_execution import QueryTemplateExecutionService


@dataclass
class TopologyIngestionResult:
    status: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[DbSessionSnapshot] = field(default_factory=list)
    bindings: list[JobRunNodeBinding] = field(default_factory=list)
    log: QueryExecutionLog | None = None
    template_id: str | None = None
    message: str | None = None


class TopologyIngestionService:
    """Ingest runtime topology from approved read-only query templates.

    RuntimeTopologyService uses this as the production path. The service keeps
    connector execution, query audit provenance, and canonical session/node
    mapping together so the topology UI is not dependent on hard-coded seed rows.
    """

    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    def ingest_for_run(self, run: JobRun) -> TopologyIngestionResult:
        template = self._topology_template_for_run(run)
        if template is None:
            return TopologyIngestionResult(status="no_template", message="No active topology query template is registered.")

        summary = QueryTemplateExecutionService(self.db, settings=self.settings).execute(
            template,
            customer_key=run.customer.customer_key,
            environment_name=run.environment.name,
            parameters=self._parameters_for_run(run),
            initiated_by="topology_correlation",
            executed_by="topology_service",
        )
        if summary.log.status != "success":
            return TopologyIngestionResult(
                status=summary.log.status,
                log=summary.log,
                template_id=template.template_id,
                message=summary.validation_error or summary.log.sanitized_error_message,
            )

        rows = [self._normalize_row(row, summary.log.id) for row in summary.rows]
        snapshots: list[DbSessionSnapshot] = []
        bindings: list[JobRunNodeBinding] = []
        for row in rows:
            snapshot = self._upsert_session_snapshot(run, row)
            snapshots.append(snapshot)
            bindings.extend(self._upsert_bindings_for_row(run, row))
        self.db.flush()
        return TopologyIngestionResult(
            status="success",
            rows=rows,
            snapshots=snapshots,
            bindings=bindings,
            log=summary.log,
            template_id=template.template_id,
        )

    def _topology_template_for_run(self, run: JobRun) -> QueryTemplate | None:
        scope = run.business_scope or {}
        preferred = (
            "active_db_session_by_ecid_or_client_identifier"
            if scope.get("ecid") or scope.get("client_identifier") or run.sql_id
            else "active_db_session_by_ess_request"
        )
        template = self.db.scalar(select(QueryTemplate).where(QueryTemplate.template_id == preferred, QueryTemplate.active.is_(True)))
        if template is None and preferred != "active_db_session_by_ess_request":
            template = self.db.scalar(
                select(QueryTemplate).where(QueryTemplate.template_id == "active_db_session_by_ess_request", QueryTemplate.active.is_(True))
            )
        return template

    @staticmethod
    def _parameters_for_run(run: JobRun) -> dict[str, Any]:
        scope = run.business_scope or {}
        return {
            "ecid": scope.get("ecid"),
            "client_identifier": scope.get("client_identifier"),
            "sql_id": run.sql_id,
            "module_like": f"%{run.api_operation or run.job_type}%" if run.api_operation or run.job_type else None,
            "action_like": f"%{run.api_operation or run.job_name}%" if run.api_operation or run.job_name else None,
            "ess_request_token": f"%{run.ess_request_id}%" if run.ess_request_id else None,
            "process_id": run.process_id,
            "program_like": "%ESS%",
        }

    @staticmethod
    def _normalize_row(row: dict[str, Any], query_execution_id: int) -> dict[str, Any]:
        normalized = {str(key).upper(): value for key, value in row.items()}
        normalized["QUERY_EXECUTION_ID"] = query_execution_id
        normalized["SYNTHETIC_TOPOLOGY_SEED"] = False
        normalized.setdefault("SAMPLED_AT", utcnow())
        normalized.setdefault("ASH_AVAILABLE", True)
        return normalized

    def _upsert_session_snapshot(self, run: JobRun, row: dict[str, Any]) -> DbSessionSnapshot:
        sampled_at = _parse_dt(row.get("SAMPLED_AT")) or utcnow()
        snapshot = self.db.scalar(
            select(DbSessionSnapshot).where(
                DbSessionSnapshot.run_id == run.id,
                DbSessionSnapshot.sampled_at == sampled_at,
                DbSessionSnapshot.sid == row.get("SID"),
                DbSessionSnapshot.inst_id == row.get("INST_ID"),
            )
        )
        if snapshot is None:
            snapshot = DbSessionSnapshot(run_id=run.id, sampled_at=sampled_at)
            self.db.add(snapshot)
        _apply_session_row(snapshot, row, sampled_at)
        self.db.flush()
        return snapshot

    def _upsert_bindings_for_row(self, run: JobRun, row: dict[str, Any]) -> list[JobRunNodeBinding]:
        bindings: list[JobRunNodeBinding] = []
        if row.get("INST_ID") is not None:
            node = self._upsert_node(
                customer_key=run.customer.customer_key,
                environment=run.environment.name,
                node_type="db_instance",
                node_key=f"db-instance-{row.get('INST_ID')}",
                display_name=row.get("INSTANCE_NAME") or f"DBRAC_inst{row.get('INST_ID')}",
                host_name=row.get("DB_HOST_NAME"),
                instance_name=row.get("INSTANCE_NAME"),
                cluster_name=row.get("CLUSTER_NAME") or "DBRAC",
                service_name=row.get("SERVICE_NAME"),
                region=run.region,
                tags={"rac_inst_id": row.get("INST_ID"), "source": "gv$session"},
            )
            bindings.append(
                self._upsert_binding(
                    run,
                    node,
                    "db_instance_confirmed",
                    "confirmed",
                    f"Confirmed from GV$SESSION.INST_ID={row.get('INST_ID')} and GV$INSTANCE.INSTANCE_NAME.",
                    row,
                )
            )
        if row.get("DB_HOST_NAME"):
            node = self._upsert_node(
                customer_key=run.customer.customer_key,
                environment=run.environment.name,
                node_type="db_host",
                node_key=f"db-host-{_safe_key(row.get('DB_HOST_NAME'))}",
                display_name=row.get("DB_HOST_NAME"),
                host_name=row.get("DB_HOST_NAME"),
                cluster_name=row.get("CLUSTER_NAME") or "DBRAC",
                region=run.region,
                tags={"source": "gv$instance", "ip_redacted": True},
            )
            bindings.append(
                self._upsert_binding(
                    run,
                    node,
                    "db_host_confirmed",
                    "confirmed",
                    "Confirmed from GV$INSTANCE.HOST_NAME joined to active session.",
                    row,
                )
            )
        if row.get("MACHINE") or row.get("PROGRAM"):
            machine = row.get("MACHINE") or row.get("PROGRAM")
            node = self._upsert_node(
                customer_key=run.customer.customer_key,
                environment=run.environment.name,
                node_type="ess_server" if "ESS" in str(machine).upper() else "app_server",
                node_key=f"app-{_safe_key(machine)}",
                display_name=machine,
                server_name=row.get("MACHINE"),
                region=run.region,
                tags={"source": "gv$session.machine_program", "telemetry_confirmed": False},
            )
            bindings.append(
                self._upsert_binding(
                    run,
                    node,
                    "app_server_inferred",
                    "medium",
                    "Inferred from GV$SESSION.MACHINE/PROGRAM; confirm with WLS or telemetry later.",
                    row,
                )
            )
        return bindings

    def _upsert_node(self, **values: Any) -> RuntimeNode:
        node = self.db.scalar(
            select(RuntimeNode).where(
                RuntimeNode.customer_key == values["customer_key"],
                RuntimeNode.environment == values["environment"],
                RuntimeNode.node_key == values["node_key"],
            )
        )
        if node is None:
            node = RuntimeNode(**values)
            self.db.add(node)
            self.db.flush()
            return node
        for key, value in values.items():
            setattr(node, key, value)
        return node

    def _upsert_binding(
        self,
        run: JobRun,
        node: RuntimeNode,
        binding_type: str,
        confidence: str,
        evidence_summary: str,
        evidence: dict[str, Any],
    ) -> JobRunNodeBinding:
        now = utcnow()
        binding = self.db.scalar(
            select(JobRunNodeBinding).where(
                JobRunNodeBinding.run_id == run.id,
                JobRunNodeBinding.node_id == node.id,
                JobRunNodeBinding.binding_type == binding_type,
            )
        )
        if binding is None:
            binding = JobRunNodeBinding(run_id=run.id, node_id=node.id, binding_type=binding_type, first_seen_at=now)
            self.db.add(binding)
        binding.confidence = confidence
        binding.last_seen_at = now
        binding.evidence_summary = evidence_summary
        binding.evidence_json = _sanitize_evidence(evidence)
        binding.query_execution_id = evidence.get("QUERY_EXECUTION_ID")
        self.db.flush()
        return binding


def _apply_session_row(snapshot: DbSessionSnapshot, row: dict[str, Any], sampled_at: datetime) -> None:
    snapshot.sampled_at = sampled_at
    mapping = {
        "inst_id": "INST_ID",
        "instance_name": "INSTANCE_NAME",
        "db_host_name": "DB_HOST_NAME",
        "sid": "SID",
        "serial_number": "SERIAL_NUMBER",
        "session_status": "SESSION_STATUS",
        "username": "USERNAME",
        "service_name": "SERVICE_NAME",
        "module": "MODULE",
        "action": "ACTION",
        "client_identifier": "CLIENT_IDENTIFIER",
        "ecid": "ECID",
        "machine": "MACHINE",
        "program": "PROGRAM",
        "process": "PROCESS",
        "sql_id": "SQL_ID",
        "sql_child_number": "SQL_CHILD_NUMBER",
        "sql_exec_start": "SQL_EXEC_START",
        "last_call_et_seconds": "LAST_CALL_ET_SECONDS",
        "event": "EVENT",
        "wait_class": "WAIT_CLASS",
        "state": "STATE",
        "blocking_instance": "BLOCKING_INSTANCE",
        "blocking_session": "BLOCKING_SESSION",
        "plan_hash_value": "PLAN_HASH_VALUE",
        "row_wait_obj": "ROW_WAIT_OBJ",
        "query_execution_id": "QUERY_EXECUTION_ID",
    }
    for attr, key in mapping.items():
        value = row.get(key)
        if attr == "sql_exec_start":
            value = _parse_dt(value)
        if attr in {"serial_number", "row_wait_obj"} and value is not None:
            value = str(value)
        setattr(snapshot, attr, value)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _safe_key(value: Any) -> str:
    return str(value or "unknown").lower().replace(" ", "-").replace("_", "-").replace("/", "-")


def _sanitize_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(evidence)
    for key in list(sanitized.keys()):
        if "IP" in key.upper() or key.upper() in {"PASSWORD", "TOKEN", "SECRET", "DSN"}:
            sanitized[key] = "[redacted]"
    return json.loads(json.dumps(sanitized, default=str))
