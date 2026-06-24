from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Alert,
    Customer,
    DbSessionSnapshot,
    Environment,
    JobRun,
    JobRunNodeBinding,
    RuntimeNode,
    RuntimeNodeMetricSample,
)
from app.models.base import utcnow
from app.schemas import (
    DbSessionSnapshotRead,
    JobRunNodeBindingRead,
    RuntimeNodeRead,
    RuntimeTopologyEdgeRead,
    RuntimeTopologyMapRead,
    RuntimeTopologyNodeRead,
    ServerHeatmapCellRead,
    ServerHeatmapResponse,
    ServerHeatmapRowRead,
    TopologyCorrelationRead,
)
from app.services.baseline import duration_minutes


TOPOLOGY_COLLECTOR_VERSION = "2C.1"


class RuntimeTopologyService:
    """Correlate slow jobs to runtime nodes, sessions, SQL, and server-time heat."""

    def __init__(self, db: Session):
        self.db = db

    def correlate_run(self, run_id: int, *, lookback_minutes: int = 120, persist: bool = True) -> TopologyCorrelationRead:
        run = self._load_run(run_id)
        now = utcnow()
        rows = self._session_rows_for_run(run, now)
        missing_inputs: list[str] = []
        if not rows:
            missing_inputs.append("No GV$SESSION-like row available. Try client_identifier, module/action, or SQL_ID fallback.")
            rows = [self._metadata_only_session_row(run, now)]
        if not self._has_ecid(run, rows):
            if self._first_value(rows, "CLIENT_IDENTIFIER") or (run.business_scope or {}).get("client_identifier"):
                missing_inputs.append("ECID not known; using client_identifier/module/action fallback.")
            else:
                missing_inputs.append("ECID not known; using ESS request, process, SQL_ID, module/action, or session machine fallback.")
        if not any(row.get("ASH_AVAILABLE", True) for row in rows):
            missing_inputs.append("GV$ACTIVE_SESSION_HISTORY unavailable or not granted; heat uses current sessions and node metrics.")

        db_instance_node: RuntimeNode | None = None
        db_host_node: RuntimeNode | None = None
        app_server_node: RuntimeNode | None = None
        active_sessions: list[DbSessionSnapshot] = []
        bindings: list[JobRunNodeBinding] = []

        for row in rows:
            row.setdefault("SYNTHETIC_TOPOLOGY_SEED", True)
            session = self._upsert_session_snapshot(run, row) if persist else self._transient_session(run, row)
            active_sessions.append(session)
            if row.get("INST_ID") is not None:
                db_instance_node = self.upsert_node(
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
                        db_instance_node,
                        "db_instance_confirmed",
                        "confirmed",
                        f"Confirmed from GV$SESSION.INST_ID={row.get('INST_ID')} and GV$INSTANCE.INSTANCE_NAME.",
                        row,
                    )
                    if persist
                    else self._transient_binding(run, db_instance_node, "db_instance_confirmed", "confirmed", row)
                )
            if row.get("DB_HOST_NAME"):
                db_host_node = self.upsert_node(
                    customer_key=run.customer.customer_key,
                    environment=run.environment.name,
                    node_type="db_host",
                    node_key=f"db-host-{self._safe_key(row.get('DB_HOST_NAME'))}",
                    display_name=row.get("DB_HOST_NAME"),
                    host_name=row.get("DB_HOST_NAME"),
                    cluster_name=row.get("CLUSTER_NAME") or "DBRAC",
                    region=run.region,
                    tags={"source": "gv$instance", "ip_redacted": True},
                )
                bindings.append(
                    self._upsert_binding(
                        run,
                        db_host_node,
                        "db_host_confirmed",
                        "confirmed",
                        "Confirmed from GV$INSTANCE.HOST_NAME joined to active session.",
                        row,
                    )
                    if persist
                    else self._transient_binding(run, db_host_node, "db_host_confirmed", "confirmed", row)
                )
            if row.get("MACHINE") or row.get("PROGRAM"):
                app_server_node = self.upsert_node(
                    customer_key=run.customer.customer_key,
                    environment=run.environment.name,
                    node_type="ess_server" if "ESS" in str(row.get("MACHINE", "")).upper() else "app_server",
                    node_key=f"app-{self._safe_key(row.get('MACHINE') or row.get('PROGRAM'))}",
                    display_name=row.get("MACHINE") or row.get("PROGRAM"),
                    server_name=row.get("MACHINE"),
                    region=run.region,
                    tags={"source": "gv$session.machine_program", "telemetry_confirmed": False},
                )
                bindings.append(
                    self._upsert_binding(
                        run,
                        app_server_node,
                        "app_server_inferred",
                        "medium",
                        "Inferred from GV$SESSION.MACHINE/PROGRAM; confirm with WLS or telemetry later.",
                        row,
                    )
                    if persist
                    else self._transient_binding(run, app_server_node, "app_server_inferred", "medium", row)
                )

        if persist:
            self.db.flush()

        active_sql_id = self._first_value(rows, "SQL_ID") or run.sql_id
        plan_hash_value = self._first_value(rows, "PLAN_HASH_VALUE") or run.plan_hash_value
        heat_summary = self._run_heat_summary(run, db_instance_node, app_server_node)
        classification = self._classify_problem(run, heat_summary, rows)
        evidence = self._correlation_evidence(run, rows, db_instance_node, db_host_node, app_server_node, heat_summary)

        return TopologyCorrelationRead(
            run_id=run.id,
            selected_at=now,
            job_identity={
                "customer_key": run.customer.customer_key,
                "customer": run.customer.display_name,
                "environment": run.environment.name,
                "job_name": run.job_name,
                "job_type": run.job_type,
                "region": run.region,
                "workstream": run.workstream,
                "status": run.status,
                "elapsed_minutes": round(duration_minutes(run, now=now), 1),
                "source_type": run.source_type,
            },
            ess_request_id=run.ess_request_id,
            process_id=run.process_id,
            ecid=self._first_value(rows, "ECID") or (run.business_scope or {}).get("ecid"),
            client_identifier=self._first_value(rows, "CLIENT_IDENTIFIER")
            or (run.business_scope or {}).get("client_identifier"),
            active_sql_id=active_sql_id,
            plan_hash_value=plan_hash_value,
            db_instance_node=RuntimeNodeRead.model_validate(db_instance_node) if db_instance_node else None,
            db_host_node=RuntimeNodeRead.model_validate(db_host_node) if db_host_node else None,
            app_server_node=RuntimeNodeRead.model_validate(app_server_node) if app_server_node else None,
            app_server_confidence="inferred" if app_server_node else "unknown",
            active_sessions=[
                DbSessionSnapshotRead.model_validate(session)
                for session in sorted(active_sessions, key=lambda item: item.last_call_et_seconds or 0, reverse=True)
            ],
            bindings=[
                JobRunNodeBindingRead.model_validate(binding)
                for binding in sorted(bindings, key=lambda item: item.binding_type)
                if getattr(binding, "id", None) is not None
            ],
            heat_summary=heat_summary,
            problem_classification=classification,
            evidence=evidence,
            missing_inputs=missing_inputs,
            recommended_next_query=self._recommended_next_query(rows, missing_inputs),
            explanation=self._plain_explanation(run, classification, db_instance_node, active_sql_id, rows),
        )

    def current_topology(
        self,
        *,
        customer_key: str | None = None,
        environment: str | None = None,
        selected_run_id: int | None = None,
    ) -> RuntimeTopologyMapRead:
        self.ensure_seed_topology(customer_key=customer_key, environment=environment)
        now = utcnow()
        nodes = self._node_query(customer_key=customer_key, environment=environment)
        bindings = self._bindings_for_scope(customer_key=customer_key, environment=environment)
        sessions = self._sessions_for_scope(customer_key=customer_key, environment=environment)
        selected = selected_run_id or self._default_selected_run_id(customer_key, environment)
        topology_nodes: dict[str, RuntimeTopologyNodeRead] = {}

        for node in nodes:
            related_sessions = [session for session in sessions if self._session_matches_node(session, node)]
            related_bindings = [binding for binding in bindings if binding.node_id == node.id]
            heat = self._node_heat(node, related_sessions, related_bindings)
            topology_nodes[node.node_key] = RuntimeTopologyNodeRead(
                node_key=node.node_key,
                display_name=node.display_name,
                node_type=node.node_type,
                tier=self._tier_for_node(node),
                severity=self._severity_from_score(heat["heat_score"]),
                heat_score=heat["heat_score"],
                confidence=heat["confidence"],
                active_run_count=len({binding.run_id for binding in related_bindings}),
                active_session_count=len(related_sessions),
                top_sql_id=heat.get("top_sql_id"),
                top_wait_class=heat.get("top_wait_class"),
                top_event=heat.get("top_event"),
                metrics=heat.get("metrics", {}),
                last_refreshed_at=max(
                    [node.updated_at]
                    + [session.sampled_at for session in related_sessions]
                    + [binding.updated_at for binding in related_bindings]
                ),
                details={
                    "host_name": node.host_name,
                    "instance_name": node.instance_name,
                    "server_name": node.server_name,
                    "cluster_name": node.cluster_name,
                    "source": (node.tags or {}).get("source"),
                },
            )

        selected_bindings = [binding for binding in bindings if not selected or binding.run_id == selected]
        selected_run_ids = sorted({binding.run_id for binding in selected_bindings})
        if selected and selected not in selected_run_ids:
            run = self.db.get(JobRun, selected)
            if run:
                selected_run_ids.append(run.id)
        for run_id in selected_run_ids[:4]:
            run = self.db.get(JobRun, run_id)
            if not run:
                continue
            session = next((item for item in sessions if item.run_id == run_id), None)
            state = self._run_state(run)
            topology_nodes[f"job-{run.id}"] = RuntimeTopologyNodeRead(
                node_key=f"job-{run.id}",
                display_name=run.job_name,
                node_type="job_run",
                tier="Job",
                severity=state,
                heat_score=85 if state == "critical" else 55 if state == "warning" else 35 if state == "watch" else 10,
                confidence="confirmed",
                active_run_count=1,
                active_session_count=1 if session else 0,
                top_sql_id=session.sql_id if session else run.sql_id,
                top_wait_class=session.wait_class if session else None,
                top_event=session.event if session else None,
                last_refreshed_at=session.sampled_at if session else run.updated_at,
                details={
                    "customer": run.customer.display_name,
                    "environment": run.environment.name,
                    "ess_request_id": run.ess_request_id,
                    "process_id": run.process_id,
                    "elapsed_minutes": round(duration_minutes(run), 1),
                },
            )
            topology_nodes[f"ess-{run.id}"] = RuntimeTopologyNodeRead(
                node_key=f"ess-{run.id}",
                display_name=run.ess_request_id or run.process_id or "ESS/API request",
                node_type="ess_request",
                tier="ESS/API",
                severity=state,
                heat_score=70 if state in {"critical", "warning"} else 25,
                confidence="confirmed" if run.ess_request_id or run.process_id else "unknown",
                active_run_count=1,
                active_session_count=1 if session else 0,
                top_sql_id=session.sql_id if session else run.sql_id,
                top_wait_class=session.wait_class if session else None,
                top_event=session.event if session else None,
                last_refreshed_at=session.sampled_at if session else run.updated_at,
                details={"api_operation": run.api_operation, "job_id": run.job_id},
            )
            sql_id = session.sql_id if session and session.sql_id else run.sql_id
            if sql_id:
                topology_nodes[f"sql-{sql_id}"] = RuntimeTopologyNodeRead(
                    node_key=f"sql-{sql_id}",
                    display_name=f"SQL_ID {sql_id}",
                    node_type="sql_id",
                    tier="SQL",
                    severity=state,
                    heat_score=88 if sql_id == "dp9u1803k8k7f" else 60 if state in {"critical", "warning"} else 20,
                    confidence="confirmed" if session else "likely",
                    active_run_count=1,
                    active_session_count=1 if session else 0,
                    top_sql_id=sql_id,
                    top_wait_class=session.wait_class if session else None,
                    top_event=session.event if session else None,
                    last_refreshed_at=session.sampled_at if session else run.updated_at,
                    details={
                        "plan_hash_value": session.plan_hash_value if session else run.plan_hash_value,
                        "wait_class": session.wait_class if session else None,
                        "event": session.event if session else None,
                    },
                )

        edges = self._topology_edges(bindings, selected_run_id=selected)
        explanations = self._topology_explanations(topology_nodes, sessions)
        return RuntimeTopologyMapRead(
            generated_at=now,
            selected_run_id=selected,
            nodes=list(topology_nodes.values()),
            edges=edges,
            explanations=explanations,
        )

    def heatmap(
        self,
        *,
        customer_key: str | None = None,
        environment: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
        bucket_minutes: int = 10,
        node_type: str | None = None,
        job_type: str | None = None,
    ) -> ServerHeatmapResponse:
        self.ensure_seed_topology(customer_key=customer_key, environment=environment)
        to_at = to_at or utcnow()
        from_at = from_at or to_at - timedelta(minutes=60)
        bucket_minutes = max(min(bucket_minutes, 60), 5)
        nodes = [
            node
            for node in self._node_query(customer_key=customer_key, environment=environment)
            if not node_type or node.node_type == node_type
        ]
        sessions = self._sessions_for_scope(customer_key=customer_key, environment=environment, from_at=from_at, to_at=to_at)
        bindings = self._bindings_for_scope(customer_key=customer_key, environment=environment)
        metrics = self._metrics_for_nodes([node.id for node in nodes], from_at=from_at, to_at=to_at)
        bucket_starts = list(self._bucket_range(from_at, to_at, bucket_minutes))
        rows: list[ServerHeatmapRowRead] = []

        for node in sorted(nodes, key=lambda item: (self._tier_for_node(item), item.display_name)):
            cells: list[ServerHeatmapCellRead] = []
            for bucket_start in bucket_starts:
                bucket_end = bucket_start + timedelta(minutes=bucket_minutes)
                node_sessions = [
                    session
                    for session in sessions
                    if bucket_start <= session.sampled_at < bucket_end and self._session_matches_node(session, node)
                ]
                node_bindings = [binding for binding in bindings if binding.node_id == node.id]
                if job_type:
                    node_bindings = [binding for binding in node_bindings if binding.run and binding.run.job_type == job_type]
                node_metrics = [
                    metric
                    for metric in metrics
                    if metric.node_id == node.id and bucket_start <= metric.sampled_at < bucket_end
                ]
                score, breakdown = self.compute_heat_score(node_sessions, node_bindings, node_metrics)
                cells.append(
                    ServerHeatmapCellRead(
                        node_id=node.id,
                        bucket_start=bucket_start,
                        bucket_end=bucket_end,
                        heat_score=score,
                        severity=self._severity_from_score(score),
                        contributing_run_ids=sorted({binding.run_id for binding in node_bindings if score > 0}),
                        contributing_sql_ids=sorted({session.sql_id for session in node_sessions if session.sql_id}),
                        top_wait_class=self._most_common([session.wait_class for session in node_sessions]),
                        top_event=self._most_common([session.event for session in node_sessions]),
                        metric_breakdown=breakdown,
                        explanation=self._heat_explanation(node, score, node_sessions, node_bindings, breakdown),
                    )
                )
            rows.append(
                ServerHeatmapRowRead(
                    node=RuntimeNodeRead.model_validate(node),
                    tier=self._tier_for_node(node),
                    cells=cells,
                )
            )
        return ServerHeatmapResponse(generated_at=utcnow(), bucket_minutes=bucket_minutes, rows=rows)

    def list_nodes(self, *, customer_key: str | None = None, environment: str | None = None) -> list[RuntimeNode]:
        self.ensure_seed_topology(customer_key=customer_key, environment=environment)
        return self._node_query(customer_key=customer_key, environment=environment)

    def get_node(self, node_id: int) -> RuntimeNode | None:
        self.ensure_seed_topology()
        return self.db.get(RuntimeNode, node_id)

    def node_metrics(self, node_id: int) -> dict[str, Any]:
        self.ensure_seed_topology()
        node = self.db.get(RuntimeNode, node_id)
        if not node:
            raise ValueError(f"Runtime node {node_id} was not found")
        metrics = list(
            self.db.scalars(
                select(RuntimeNodeMetricSample)
                .where(RuntimeNodeMetricSample.node_id == node_id)
                .order_by(RuntimeNodeMetricSample.sampled_at.desc())
                .limit(100)
            )
        )
        bindings = list(
            self.db.scalars(
                select(JobRunNodeBinding)
                .where(JobRunNodeBinding.node_id == node_id)
                .options(selectinload(JobRunNodeBinding.run), selectinload(JobRunNodeBinding.node))
                .order_by(JobRunNodeBinding.updated_at.desc())
            )
        )
        return {
            "node": RuntimeNodeRead.model_validate(node).model_dump(mode="json"),
            "metrics": [RuntimeNodeMetricSampleRead.model_validate(metric).model_dump(mode="json") for metric in metrics],
            "bindings": [JobRunNodeBindingRead.model_validate(binding).model_dump(mode="json") for binding in bindings],
        }

    def ensure_seed_topology(
        self,
        *,
        now: datetime | None = None,
        customer_key: str | None = None,
        environment: str | None = None,
    ) -> dict[str, int]:
        now = now or utcnow().replace(second=0, microsecond=0)
        counts = {"customers": 0, "nodes": 0, "metrics": 0, "sessions": 0, "bindings": 0}

        for scoped_customer, scoped_environment in self._seed_scopes(customer_key=customer_key, environment=environment):
            counts["customers"] += 1
            for node_data in self._seed_node_definitions(scoped_customer.customer_key, scoped_environment.name):
                existing = self.db.scalar(
                    select(RuntimeNode).where(
                        RuntimeNode.customer_key == node_data["customer_key"],
                        RuntimeNode.environment == node_data["environment"],
                        RuntimeNode.node_key == node_data["node_key"],
                    )
                )
                if not existing:
                    self.db.add(RuntimeNode(**node_data))
                    counts["nodes"] += 1
            self.db.flush()

            runs = list(
                self.db.scalars(
                    select(JobRun)
                    .where(
                        JobRun.customer_id == scoped_customer.id,
                        JobRun.environment_id == scoped_environment.id,
                        JobRun.status == "RUNNING",
                    )
                    .options(selectinload(JobRun.customer), selectinload(JobRun.environment), selectinload(JobRun.sql_observations))
                )
            )
            for run in runs:
                if run.run_key == "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT":
                    run.sql_id = "dp9u1803k8k7f"
                    run.plan_hash_value = "51543091"
                    self._update_apj_business_scope(run)
                existing_session_count = self.db.scalar(
                    select(DbSessionSnapshot.id).where(DbSessionSnapshot.run_id == run.id).limit(1)
                )
                existing_binding_count = self.db.scalar(
                    select(JobRunNodeBinding.id).where(JobRunNodeBinding.run_id == run.id).limit(1)
                )
                self.correlate_run(run.id, persist=True)
                if existing_session_count is None and self.db.scalar(
                    select(DbSessionSnapshot.id).where(DbSessionSnapshot.run_id == run.id).limit(1)
                ):
                    counts["sessions"] += 1
                if existing_binding_count is None:
                    new_binding_count = self.db.scalar(
                        select(JobRunNodeBinding.id).where(JobRunNodeBinding.run_id == run.id).limit(1)
                    )
                    if new_binding_count is not None:
                        counts["bindings"] += 1

            for metric_data in self._seed_metric_samples(scoped_customer.customer_key, scoped_environment.name, now):
                metric = dict(metric_data)
                node = self.db.scalar(
                    select(RuntimeNode).where(
                        RuntimeNode.customer_key == scoped_customer.customer_key,
                        RuntimeNode.environment == scoped_environment.name,
                        RuntimeNode.node_key == metric.pop("node_key"),
                    )
                )
                if not node:
                    continue
                exists = self.db.scalar(
                    select(RuntimeNodeMetricSample.id).where(
                        RuntimeNodeMetricSample.node_id == node.id,
                        RuntimeNodeMetricSample.sampled_at == metric["sampled_at"],
                        RuntimeNodeMetricSample.metric_name == metric["metric_name"],
                    )
                )
                if not exists:
                    self.db.add(RuntimeNodeMetricSample(node_id=node.id, **metric))
                    counts["metrics"] += 1
            self.db.flush()
        return counts

    def upsert_node(self, **values: Any) -> RuntimeNode:
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

    def compute_heat_score(
        self,
        sessions: list[DbSessionSnapshot],
        bindings: list[JobRunNodeBinding],
        metrics: list[RuntimeNodeMetricSample],
    ) -> tuple[float, dict[str, Any]]:
        active_slow_jobs = len(
            {
                binding.run_id
                for binding in bindings
                if binding.run and binding.run.status == "RUNNING" and self._run_is_slowish(binding.run)
            }
        )
        wait_samples = len([session for session in sessions if session.wait_class and session.wait_class.lower() not in {"cpu", "idle"}])
        sql_concentration = max(
            [len([session for session in sessions if session.sql_id == sql_id]) for sql_id in {session.sql_id for session in sessions if session.sql_id}] or [0]
        )
        metric_values = {metric.metric_name: float(metric.metric_value) for metric in metrics}
        cpu = metric_values.get("cpu_utilization_pct", 0)
        gc = metric_values.get("wls_full_gc_pct", 0)
        cluster_waits = metric_values.get("db_cluster_wait_samples", 0)
        io_waits = metric_values.get("db_io_wait_samples", 0)
        app_waits = metric_values.get("db_application_wait_samples", 0)
        active_sessions = metric_values.get("db_active_sessions", 0)
        score = (
            active_slow_jobs * 22
            + wait_samples * 8
            + sql_concentration * 5
            + max(cpu - 60, 0) * 0.7
            + gc * 1.6
            + min(cluster_waits, 30) * 0.7
            + min(io_waits, 45) * 1.0
            + min(app_waits, 30) * 0.8
            + min(active_sessions, 50) * 0.45
        )
        return round(min(score, 100), 1), {
            "active_slow_jobs": active_slow_jobs,
            "wait_samples": wait_samples,
            "sql_concentration": sql_concentration,
            "cpu_utilization_pct": cpu,
            "wls_full_gc_pct": gc,
            "db_cluster_wait_samples": cluster_waits,
            "db_io_wait_samples": io_waits,
            "db_application_wait_samples": app_waits,
            "db_active_sessions": active_sessions,
        }

    def _load_run(self, run_id: int) -> JobRun:
        run = self.db.get(JobRun, run_id)
        if not run:
            raise ValueError(f"Run {run_id} was not found")
        return run

    def _session_rows_for_run(self, run: JobRun, now: datetime) -> list[dict[str, Any]]:
        key = run.run_key
        scope = run.business_scope or {}
        if isinstance(scope.get("topology_seed"), dict):
            return [self._session_row_from_scope(run, now, scope["topology_seed"])]
        if key == "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT":
            return [
                {
                    "SAMPLED_AT": now - timedelta(minutes=4),
                    "INST_ID": 1,
                    "INSTANCE_NAME": "DBRAC_inst1",
                    "DB_HOST_NAME": "dbhost-a",
                    "CLUSTER_NAME": "DBRAC",
                    "SID": 7716,
                    "SERIAL_NUMBER": "4435",
                    "SESSION_STATUS": "ACTIVE",
                    "USERNAME": "FUSION_RUNTIME",
                    "SERVICE_NAME": "ICM_PRD",
                    "MODULE": "CN_TP_CALCULATIONS_PVT.CALCULATE",
                    "ACTION": "CalculatePVT APJ Direct",
                    "CLIENT_IDENTIFIER": "ess-apj-90045-8841",
                    "ECID": scope.get("ecid") or "apj-direct-calculatepvt-ecid",
                    "MACHINE": "ESS_SOAServer_as24_01",
                    "PROGRAM": "JDBC Thin Client",
                    "PROCESS": run.process_id,
                    "SQL_ID": "dp9u1803k8k7f",
                    "SQL_CHILD_NUMBER": 0,
                    "SQL_EXEC_START": now - timedelta(hours=13, minutes=40),
                    "LAST_CALL_ET_SECONDS": 49320,
                    "EVENT": "cell single block physical read",
                    "WAIT_CLASS": "User I/O",
                    "STATE": "WAITING",
                    "BLOCKING_INSTANCE": None,
                    "BLOCKING_SESSION": None,
                    "PLAN_HASH_VALUE": "51543091",
                    "ROW_WAIT_OBJ": "HZ_REF_ENTITIES",
                    "ASH_AVAILABLE": True,
                }
            ]
        if key == "CUST_A-PROD-AMER-LATAM-COLLECT-CURRENT":
            return [
                {
                    "SAMPLED_AT": now - timedelta(minutes=5),
                    "INST_ID": 3,
                    "INSTANCE_NAME": "DBRAC_inst3",
                    "DB_HOST_NAME": "dbhost-c",
                    "CLUSTER_NAME": "DBRAC",
                    "SID": 1842,
                    "SERIAL_NUMBER": "5512",
                    "SESSION_STATUS": "ACTIVE",
                    "SERVICE_NAME": "ICM_PRD",
                    "MODULE": "ICM_COLLECT",
                    "ACTION": "Collect Credits",
                    "CLIENT_IDENTIFIER": "ess-collect-55431-6621",
                    "ECID": None,
                    "MACHINE": "ESS_SOAServer_as27_01",
                    "PROGRAM": "ESS Java Worker",
                    "PROCESS": run.process_id,
                    "SQL_ID": run.sql_id,
                    "SQL_CHILD_NUMBER": 0,
                    "SQL_EXEC_START": now - timedelta(minutes=150),
                    "LAST_CALL_ET_SECONDS": 9040,
                    "EVENT": "scheduler wait",
                    "WAIT_CLASS": "Scheduler",
                    "STATE": "WAITING",
                    "PLAN_HASH_VALUE": run.plan_hash_value,
                    "ASH_AVAILABLE": False,
                }
            ]
        if key == "CUST_A-PROD-EMEA-DIRECT-CALC-CURRENT":
            return [
                {
                    "SAMPLED_AT": now - timedelta(minutes=6),
                    "INST_ID": 2,
                    "INSTANCE_NAME": "DBRAC_inst2",
                    "DB_HOST_NAME": "dbhost-b",
                    "CLUSTER_NAME": "DBRAC",
                    "SID": 2441,
                    "SERIAL_NUMBER": "9021",
                    "SESSION_STATUS": "ACTIVE",
                    "SERVICE_NAME": "ICM_PRD",
                    "MODULE": "ICM CalculatePVT",
                    "ACTION": "EMEA Direct calculation",
                    "CLIENT_IDENTIFIER": "ess-emea-77421-1120",
                    "ECID": None,
                    "MACHINE": "ESS_SOAServer_as12_01",
                    "PROGRAM": "JDBC Thin Client",
                    "PROCESS": run.process_id,
                    "SQL_ID": run.sql_id,
                    "SQL_CHILD_NUMBER": 0,
                    "SQL_EXEC_START": now - timedelta(minutes=90),
                    "LAST_CALL_ET_SECONDS": 5400,
                    "EVENT": "CPU",
                    "WAIT_CLASS": "CPU",
                    "STATE": "ON CPU",
                    "PLAN_HASH_VALUE": run.plan_hash_value,
                    "ASH_AVAILABLE": True,
                }
            ]
        if run.ess_request_id == "13729027":
            return [
                {
                    "SAMPLED_AT": now - timedelta(minutes=3),
                    "INST_ID": 1,
                    "INSTANCE_NAME": "DBRAC_inst1",
                    "DB_HOST_NAME": "dbhost-a",
                    "CLUSTER_NAME": "DBRAC",
                    "SID": 7716,
                    "SERIAL_NUMBER": "1434435",
                    "SESSION_STATUS": "ACTIVE",
                    "USERNAME": "FUSION_RUNTIME",
                    "SERVICE_NAME": "ICM_PRD",
                    "MODULE": "CN_TP_CALCULATIONS_PVT.CALCULATE",
                    "ACTION": "Calculate_pvt",
                    "CLIENT_IDENTIFIER": "ess13729027-1434435",
                    "ECID": "0598914d69b56a3ce534410a606b4a9b",
                    "MACHINE": "ESS_SOAServer_as24_01",
                    "PROGRAM": "JDBC Thin Client",
                    "PROCESS": run.process_id,
                    "SQL_ID": "dp9u1803k8k7f",
                    "SQL_CHILD_NUMBER": 0,
                    "SQL_EXEC_START": now - timedelta(seconds=47537),
                    "LAST_CALL_ET_SECONDS": 47537,
                    "EVENT": "cell single block physical read",
                    "WAIT_CLASS": "User I/O",
                    "STATE": "WAITING",
                    "PLAN_HASH_VALUE": "51543091",
                    "ROW_WAIT_OBJ": "HZ_REF_ENTITIES",
                    "ASH_AVAILABLE": True,
                }
            ]
        if self._is_scale_seed_run(run):
            return [self._scale_session_row_for_run(run, now)]
        if run.status == "RUNNING":
            return [self._metadata_only_session_row(run, now)]
        return []

    def _session_row_from_scope(self, run: JobRun, now: datetime, seed: dict[str, Any]) -> dict[str, Any]:
        inst_id = int(seed.get("inst_id") or 1)
        host_name = seed.get("db_host_name") or seed.get("host_name") or f"dbhost-{chr(96 + max(min(inst_id, 4), 1))}"
        machine = seed.get("machine") or seed.get("app_server") or "ESS_SOAServer_as24_01"
        sampled_at = self._parse_dt(seed.get("sampled_at")) or now - timedelta(minutes=int(seed.get("sample_age_minutes") or 2))
        last_call_et = seed.get("last_call_et_seconds")
        if last_call_et is None:
            last_call_et = int(duration_minutes(run, now=now) * 60)
        return {
            "SAMPLED_AT": sampled_at,
            "INST_ID": inst_id,
            "INSTANCE_NAME": seed.get("instance_name") or f"DBRAC_inst{inst_id}",
            "DB_HOST_NAME": host_name,
            "CLUSTER_NAME": seed.get("cluster_name") or "DBRAC",
            "SID": int(seed.get("sid") or (7000 + run.id % 1000)),
            "SERIAL_NUMBER": str(seed.get("serial_number") or (140000 + run.id)),
            "SESSION_STATUS": seed.get("session_status") or ("ACTIVE" if run.status == "RUNNING" else "INACTIVE"),
            "USERNAME": seed.get("username") or "FUSION_RUNTIME",
            "SERVICE_NAME": seed.get("service_name") or "ICM_PRD",
            "MODULE": seed.get("module") or run.job_family or run.job_type,
            "ACTION": seed.get("action") or run.api_operation or run.job_name,
            "CLIENT_IDENTIFIER": seed.get("client_identifier") or (run.business_scope or {}).get("client_identifier"),
            "ECID": seed.get("ecid") or (run.business_scope or {}).get("ecid"),
            "MACHINE": machine,
            "PROGRAM": seed.get("program") or ("ESS Java Worker" if "ESS" in machine.upper() else "JDBC Thin Client"),
            "PROCESS": seed.get("process") or run.process_id,
            "SQL_ID": seed.get("sql_id") or run.sql_id,
            "SQL_CHILD_NUMBER": int(seed.get("sql_child_number") or 0),
            "SQL_EXEC_START": self._parse_dt(seed.get("sql_exec_start")) or run.started_at,
            "LAST_CALL_ET_SECONDS": int(last_call_et),
            "EVENT": seed.get("event"),
            "WAIT_CLASS": seed.get("wait_class"),
            "STATE": seed.get("state") or ("WAITING" if seed.get("wait_class") and seed.get("wait_class") != "CPU" else "ON CPU"),
            "BLOCKING_INSTANCE": seed.get("blocking_instance"),
            "BLOCKING_SESSION": seed.get("blocking_session"),
            "PLAN_HASH_VALUE": seed.get("plan_hash_value") or run.plan_hash_value,
            "ROW_WAIT_OBJ": seed.get("row_wait_obj"),
            "ASH_AVAILABLE": bool(seed.get("ash_available", True)),
            "SYNTHETIC_TOPOLOGY_SEED": True,
        }

    def _scale_session_row_for_run(self, run: JobRun, now: datetime) -> dict[str, Any]:
        scope = run.business_scope or {}
        customer_number = self._customer_ordinal(run.customer.customer_key)
        job_index = self._job_index(run)
        state = str(scope.get("scale_seed_state") or "normal")
        inst_id = ((customer_number + job_index) % 4) + 1
        app_servers = [
            "ESS_SOAServer_as12_01",
            "ESS_SOAServer_as24_01",
            "ESS_SOAServer_as27_01",
            "MWServer_as1_01",
            "MWServer_as11_01",
        ]
        machine = app_servers[(customer_number * 2 + job_index) % len(app_servers)]
        wait_class = "CPU"
        event = "CPU"
        session_state = "ON CPU"
        ash_available = job_index % 7 != 0
        blocking_instance = None
        blocking_session = None
        row_wait_obj = None

        if state == "critical":
            pattern = job_index % 5
            if pattern == 0:
                inst_id = 3
                machine = "ESS_SOAServer_as27_01"
                wait_class = "Scheduler"
                event = "ESS scheduler wait"
                session_state = "WAITING"
                ash_available = False
            elif pattern == 1:
                wait_class = "User I/O"
                event = "db file sequential read"
                session_state = "WAITING"
                row_wait_obj = "HZ_REF_ENTITIES" if run.job_type == "CalculatePVT" else "ICM_RUNTIME_FACT"
            elif pattern == 2:
                wait_class = "Cluster"
                event = "gc buffer busy acquire"
                session_state = "WAITING"
            elif pattern == 3:
                wait_class = "Application"
                event = "enq: TX - row lock contention"
                session_state = "WAITING"
                blocking_instance = ((inst_id + 1) % 4) + 1
                blocking_session = 4200 + job_index
            else:
                wait_class = "User I/O"
                event = "cell single block physical read"
                session_state = "WAITING"
        elif state == "warning":
            wait_class = "User I/O" if job_index % 2 else "Concurrency"
            event = "db file sequential read" if wait_class == "User I/O" else "cursor: pin S wait on X"
            session_state = "WAITING"
        elif state == "watch":
            wait_class = "CPU" if job_index % 2 else "User I/O"
            event = "CPU" if wait_class == "CPU" else "db file scattered read"
            session_state = "ON CPU" if wait_class == "CPU" else "WAITING"
        elif state == "unknown_baseline":
            wait_class = "Other"
            event = "unclassified job startup"
            session_state = "WAITING"
            ash_available = False

        host_name = ["dbhost-a", "dbhost-b", "dbhost-c", "dbhost-d"][inst_id - 1]
        sampled_at = now - timedelta(minutes=(job_index % 6) + 1)
        ecid = None if job_index % 5 == 0 else f"ecid-{run.customer.customer_key.lower()}-{job_index:02d}"
        client_identifier = f"ess-{run.customer.customer_key.lower()}-{job_index:02d}-{run.id}"
        elapsed_seconds = int(duration_minutes(run, now=now) * 60)

        return {
            "SAMPLED_AT": sampled_at,
            "INST_ID": inst_id,
            "INSTANCE_NAME": f"DBRAC_inst{inst_id}",
            "DB_HOST_NAME": host_name,
            "CLUSTER_NAME": "DBRAC",
            "SID": 1000 + customer_number * 100 + job_index,
            "SERIAL_NUMBER": str(5000 + run.id),
            "SESSION_STATUS": "ACTIVE",
            "USERNAME": "FUSION_RUNTIME",
            "SERVICE_NAME": "ICM_PRD",
            "MODULE": run.job_family or run.job_type,
            "ACTION": run.api_operation or run.job_name,
            "CLIENT_IDENTIFIER": client_identifier,
            "ECID": ecid,
            "MACHINE": machine,
            "PROGRAM": "ESS Java Worker" if machine.startswith("ESS") else "JDBC Thin Client",
            "PROCESS": run.process_id,
            "SQL_ID": run.sql_id,
            "SQL_CHILD_NUMBER": job_index % 3,
            "SQL_EXEC_START": run.started_at,
            "LAST_CALL_ET_SECONDS": elapsed_seconds,
            "EVENT": event,
            "WAIT_CLASS": wait_class,
            "STATE": session_state,
            "BLOCKING_INSTANCE": blocking_instance,
            "BLOCKING_SESSION": blocking_session,
            "PLAN_HASH_VALUE": run.plan_hash_value,
            "ROW_WAIT_OBJ": row_wait_obj,
            "ASH_AVAILABLE": ash_available,
        }

    def _metadata_only_session_row(self, run: JobRun, now: datetime) -> dict[str, Any]:
        return {
            "SAMPLED_AT": now,
            "SESSION_STATUS": "UNKNOWN",
            "CLIENT_IDENTIFIER": (run.business_scope or {}).get("client_identifier"),
            "ECID": (run.business_scope or {}).get("ecid"),
            "PROCESS": run.process_id,
            "SQL_ID": run.sql_id,
            "PLAN_HASH_VALUE": run.plan_hash_value,
            "EVENT": None,
            "WAIT_CLASS": None,
            "ASH_AVAILABLE": False,
        }

    def _upsert_session_snapshot(self, run: JobRun, row: dict[str, Any]) -> DbSessionSnapshot:
        sampled_at = self._parse_dt(row.get("SAMPLED_AT")) or utcnow()
        if row.get("SYNTHETIC_TOPOLOGY_SEED"):
            existing = self.db.scalar(
                select(DbSessionSnapshot)
                .where(
                    DbSessionSnapshot.run_id == run.id,
                    DbSessionSnapshot.sid == row.get("SID"),
                    DbSessionSnapshot.inst_id == row.get("INST_ID"),
                )
                .order_by(DbSessionSnapshot.sampled_at.desc())
            )
        else:
            existing = self.db.scalar(
                select(DbSessionSnapshot).where(
                    DbSessionSnapshot.run_id == run.id,
                    DbSessionSnapshot.sampled_at == sampled_at,
                    DbSessionSnapshot.sid == row.get("SID"),
                    DbSessionSnapshot.inst_id == row.get("INST_ID"),
                )
            )
        snapshot = existing or DbSessionSnapshot(run_id=run.id, sampled_at=sampled_at)
        snapshot.sampled_at = sampled_at
        self._apply_session_row(snapshot, row)
        if not existing:
            self.db.add(snapshot)
            self.db.flush()
        return snapshot

    def _transient_session(self, run: JobRun, row: dict[str, Any]) -> DbSessionSnapshot:
        snapshot = DbSessionSnapshot(run_id=run.id, sampled_at=self._parse_dt(row.get("SAMPLED_AT")) or utcnow())
        self._apply_session_row(snapshot, row)
        return snapshot

    def _apply_session_row(self, snapshot: DbSessionSnapshot, row: dict[str, Any]) -> None:
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
                value = self._parse_dt(value)
            if attr in {"serial_number", "row_wait_obj"} and value is not None:
                value = str(value)
            setattr(snapshot, attr, value)

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
            binding = JobRunNodeBinding(
                run_id=run.id,
                node_id=node.id,
                binding_type=binding_type,
                first_seen_at=now,
            )
            self.db.add(binding)
        binding.confidence = confidence
        binding.last_seen_at = now
        binding.evidence_summary = evidence_summary
        binding.evidence_json = self._sanitize_evidence(evidence)
        self.db.flush()
        return binding

    def _transient_binding(
        self,
        run: JobRun,
        node: RuntimeNode,
        binding_type: str,
        confidence: str,
        evidence: dict[str, Any],
    ) -> JobRunNodeBinding:
        return JobRunNodeBinding(
            id=-1,
            run_id=run.id,
            node_id=node.id,
            node=node,
            binding_type=binding_type,
            confidence=confidence,
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
            evidence_summary="Transient correlation result.",
            evidence_json=self._sanitize_evidence(evidence),
        )

    def _node_query(self, *, customer_key: str | None = None, environment: str | None = None) -> list[RuntimeNode]:
        stmt = select(RuntimeNode).where(RuntimeNode.active.is_(True)).order_by(RuntimeNode.node_type, RuntimeNode.display_name)
        if customer_key:
            stmt = stmt.where(RuntimeNode.customer_key == customer_key)
        if environment:
            stmt = stmt.where(RuntimeNode.environment == environment)
        return list(self.db.scalars(stmt))

    def _bindings_for_scope(self, *, customer_key: str | None = None, environment: str | None = None) -> list[JobRunNodeBinding]:
        stmt = (
            select(JobRunNodeBinding)
            .join(JobRun, JobRunNodeBinding.run_id == JobRun.id)
            .join(Customer, JobRun.customer_id == Customer.id)
            .join(Environment, JobRun.environment_id == Environment.id)
            .options(selectinload(JobRunNodeBinding.run), selectinload(JobRunNodeBinding.node))
            .order_by(JobRunNodeBinding.updated_at.desc())
        )
        if customer_key:
            stmt = stmt.where(Customer.customer_key == customer_key)
        if environment:
            stmt = stmt.where(Environment.name == environment)
        return list(self.db.scalars(stmt))

    def _sessions_for_scope(
        self,
        *,
        customer_key: str | None = None,
        environment: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> list[DbSessionSnapshot]:
        stmt = (
            select(DbSessionSnapshot)
            .join(JobRun, DbSessionSnapshot.run_id == JobRun.id)
            .join(Customer, JobRun.customer_id == Customer.id)
            .join(Environment, JobRun.environment_id == Environment.id)
            .options(selectinload(DbSessionSnapshot.run))
            .order_by(DbSessionSnapshot.sampled_at.desc())
        )
        if customer_key:
            stmt = stmt.where(Customer.customer_key == customer_key)
        if environment:
            stmt = stmt.where(Environment.name == environment)
        if from_at:
            stmt = stmt.where(DbSessionSnapshot.sampled_at >= from_at)
        if to_at:
            stmt = stmt.where(DbSessionSnapshot.sampled_at <= to_at)
        return list(self.db.scalars(stmt))

    def _metrics_for_nodes(
        self,
        node_ids: list[int],
        *,
        from_at: datetime,
        to_at: datetime,
    ) -> list[RuntimeNodeMetricSample]:
        if not node_ids:
            return []
        return list(
            self.db.scalars(
                select(RuntimeNodeMetricSample).where(
                    RuntimeNodeMetricSample.node_id.in_(node_ids),
                    RuntimeNodeMetricSample.sampled_at >= from_at,
                    RuntimeNodeMetricSample.sampled_at <= to_at,
                )
            )
        )

    def _topology_edges(
        self,
        bindings: list[JobRunNodeBinding],
        *,
        selected_run_id: int | None,
    ) -> list[RuntimeTopologyEdgeRead]:
        edges: list[RuntimeTopologyEdgeRead] = []
        by_run: dict[int, list[JobRunNodeBinding]] = {}
        for binding in bindings:
            if selected_run_id and binding.run_id != selected_run_id:
                continue
            by_run.setdefault(binding.run_id, []).append(binding)
        for run_id, run_bindings in by_run.items():
            run = run_bindings[0].run
            job_key = f"job-{run_id}"
            ess_key = f"ess-{run_id}"
            edges.append(RuntimeTopologyEdgeRead(from_node_key=job_key, to_node_key=ess_key, label="ESS/API", confidence="confirmed", run_id=run_id))
            app_binding = self._first_binding(run_bindings, "app_server_inferred")
            db_binding = self._first_binding(run_bindings, "db_instance_confirmed")
            host_binding = self._first_binding(run_bindings, "db_host_confirmed")
            if app_binding:
                edges.append(
                    RuntimeTopologyEdgeRead(
                        from_node_key=ess_key,
                        to_node_key=app_binding.node.node_key,
                        label="session machine",
                        confidence="inferred",
                        run_id=run_id,
                        evidence=app_binding.evidence_summary,
                    )
                )
            if db_binding:
                from_key = app_binding.node.node_key if app_binding else ess_key
                edges.append(
                    RuntimeTopologyEdgeRead(
                        from_node_key=from_key,
                        to_node_key=db_binding.node.node_key,
                        label="active DB session",
                        confidence="confirmed",
                        run_id=run_id,
                        evidence=db_binding.evidence_summary,
                    )
                )
            if db_binding and host_binding:
                edges.append(
                    RuntimeTopologyEdgeRead(
                        from_node_key=db_binding.node.node_key,
                        to_node_key=host_binding.node.node_key,
                        label="host placement",
                        confidence="confirmed",
                        run_id=run_id,
                        evidence=host_binding.evidence_summary,
                    )
                )
            session = self.db.scalar(
                select(DbSessionSnapshot).where(DbSessionSnapshot.run_id == run_id).order_by(DbSessionSnapshot.sampled_at.desc())
            )
            if db_binding and session and session.sql_id:
                sql_key = f"sql-{session.sql_id}"
                edges.append(
                    RuntimeTopologyEdgeRead(
                        from_node_key=db_binding.node.node_key,
                        to_node_key=sql_key,
                        label=session.wait_class or "active SQL",
                        confidence="confirmed",
                        run_id=run_id,
                        evidence=f"SQL_ID {session.sql_id}, plan {session.plan_hash_value}, event {session.event or 'n/a'}",
                    )
                )
        return edges

    def _topology_explanations(
        self,
        nodes: dict[str, RuntimeTopologyNodeRead],
        sessions: list[DbSessionSnapshot],
    ) -> list[str]:
        explanations: list[str] = []
        sql_ids = {session.sql_id for session in sessions if session.sql_id}
        if "dp9u1803k8k7f" in sql_ids:
            explanations.append(
                "This is not a cluster-wide outage. Heat is concentrated on DB instance 1 and SQL_ID dp9u1803k8k7f."
            )
            explanations.append(
                "Node CPU is moderate; SQL/plan/UDQ evidence is stronger than infrastructure pressure for APJ Direct CalculatePVT."
            )
        if any(node.metrics.get("wls_full_gc_pct", 0) >= 20 for node in nodes.values()):
            explanations.append("Multiple jobs share an ESS/WLS server during a GC spike; investigate middleware pressure for those jobs.")
        if not explanations:
            explanations.append("No concentrated node heat is visible in the selected scope.")
        return explanations

    def _seed_scopes(
        self,
        *,
        customer_key: str | None = None,
        environment: str | None = None,
    ) -> list[tuple[Customer, Environment]]:
        stmt = (
            select(Customer, Environment)
            .join(Environment, Environment.customer_id == Customer.id)
            .where(Customer.active.is_(True))
            .order_by(Customer.customer_key, Environment.name)
        )
        if customer_key:
            stmt = stmt.where(Customer.customer_key == customer_key)
        if environment:
            stmt = stmt.where(Environment.name == environment)
        return [(customer, env) for customer, env in self.db.execute(stmt).all()]

    def _seed_node_definitions(self, customer_key: str, environment: str) -> list[dict[str, Any]]:
        names = [
            ("ESS_SOAServer_as12_01", "ess_server", "as12"),
            ("ESS_SOAServer_as24_01", "ess_server", "as24"),
            ("ESS_SOAServer_as27_01", "ess_server", "as27"),
            ("MWServer_as1_01", "wls_managed_server", "as1"),
            ("MWServer_as11_01", "wls_managed_server", "as11"),
        ]
        nodes = [
            {
                "customer_key": customer_key,
                "environment": environment,
                "node_type": node_type,
                "node_key": f"app-{self._safe_key(name)}",
                "display_name": name,
                "server_name": name,
                "cluster_name": "ESSCluster" if node_type == "ess_server" else "WLSCluster",
                "region": "global",
                "tags": {"source": "mock", "telemetry_confirmed": False, "site": site},
                "active": True,
            }
            for name, node_type, site in names
        ]
        for inst_id, host in [(1, "dbhost-a"), (2, "dbhost-b"), (3, "dbhost-c"), (4, "dbhost-d")]:
            nodes.append(
                {
                    "customer_key": customer_key,
                    "environment": environment,
                    "node_type": "db_instance",
                    "node_key": f"db-instance-{inst_id}",
                    "display_name": f"DBRAC_inst{inst_id}",
                    "host_name": host,
                    "instance_name": f"DBRAC_inst{inst_id}",
                    "cluster_name": "DBRAC",
                    "service_name": "ICM_PRD",
                    "region": "global",
                    "tags": {"source": "mock", "rac_inst_id": inst_id},
                    "active": True,
                }
            )
            nodes.append(
                {
                    "customer_key": customer_key,
                    "environment": environment,
                    "node_type": "db_host",
                    "node_key": f"db-host-{self._safe_key(host)}",
                    "display_name": host,
                    "host_name": host,
                    "cluster_name": "DBRAC",
                    "region": "global",
                    "tags": {"source": "mock", "ip_redacted": True},
                    "active": True,
                }
            )
        nodes.append(
            {
                "customer_key": customer_key,
                "environment": environment,
                "node_type": "rac_cluster",
                "node_key": "rac-cluster-dbrac",
                "display_name": "DBRAC cluster",
                "cluster_name": "DBRAC",
                "region": "global",
                "tags": {"source": "mock", "rac_instances": 4},
                "active": True,
            }
        )
        return nodes

    def _seed_metric_samples(self, customer_key: str, environment: str, now: datetime) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        customer_number = self._customer_ordinal(customer_key)
        hot_instance = 1 if customer_key == "CUST_A" else (customer_number % 4) + 1
        secondary_instance = ((customer_number + 1) % 4) + 1
        hot_app = ["app-ess_soaserver_as12_01", "app-ess_soaserver_as24_01", "app-ess_soaserver_as27_01"][
            customer_number % 3
        ]
        for offset in range(60, -1, -10):
            sampled_at = now - timedelta(minutes=offset)
            for inst_id in range(1, 5):
                is_hot_primary = inst_id == hot_instance and offset <= 50
                is_secondary = inst_id == secondary_instance and customer_number % 3 == 0 and 10 <= offset <= 40
                samples.append(
                    {
                        "node_key": f"db-instance-{inst_id}",
                        "sampled_at": sampled_at,
                        "metric_name": "db_active_sessions",
                        "metric_value": Decimal(
                            "34" if is_hot_primary else "22" if is_secondary else str(8 + inst_id + customer_number % 4)
                        ),
                        "unit": "sessions",
                        "source": "mock",
                        "source_ref": f"{customer_key}/{environment}/db-instance-{inst_id}",
                    }
                )
                samples.append(
                    {
                        "node_key": f"db-instance-{inst_id}",
                        "sampled_at": sampled_at,
                        "metric_name": "db_io_wait_samples",
                        "metric_value": Decimal("38" if is_hot_primary else "14" if is_secondary else "4"),
                        "unit": "samples",
                        "source": "mock",
                        "source_ref": f"{customer_key}/{environment}/db-instance-{inst_id}",
                    }
                )
                samples.append(
                    {
                        "node_key": f"db-instance-{inst_id}",
                        "sampled_at": sampled_at,
                        "metric_name": "cpu_utilization_pct",
                        "metric_value": Decimal(
                            "58" if is_hot_primary else "67" if is_secondary else str(36 + inst_id + customer_number % 5)
                        ),
                        "unit": "pct",
                        "source": "mock",
                        "source_ref": f"{customer_key}/{environment}/db-instance-{inst_id}",
                    }
                )
                if is_secondary:
                    samples.append(
                        {
                            "node_key": f"db-instance-{inst_id}",
                            "sampled_at": sampled_at,
                            "metric_name": "db_cluster_wait_samples",
                            "metric_value": Decimal("18"),
                            "unit": "samples",
                            "source": "mock",
                            "source_ref": f"{customer_key}/{environment}/db-instance-{inst_id}",
                        }
                    )
            samples.append(
                {
                    "node_key": hot_app,
                    "sampled_at": sampled_at,
                    "metric_name": "wls_full_gc_pct",
                    "metric_value": Decimal("32" if 10 <= offset <= 40 else "5"),
                    "unit": "pct",
                    "source": "mock",
                    "source_ref": f"{customer_key}/{environment}/mock-wls-gc",
                }
            )
            samples.append(
                {
                    "node_key": "app-ess_soaserver_as24_01",
                    "sampled_at": sampled_at,
                    "metric_name": "wls_full_gc_pct",
                    "metric_value": Decimal("4"),
                    "unit": "pct",
                    "source": "mock",
                    "source_ref": f"{customer_key}/{environment}/mock-wls-gc",
                }
            )
        return samples

    def _run_heat_summary(
        self,
        run: JobRun,
        db_instance_node: RuntimeNode | None,
        app_server_node: RuntimeNode | None,
    ) -> dict[str, Any]:
        nodes = [node for node in [db_instance_node, app_server_node] if node]
        now = utcnow()
        summary: dict[str, Any] = {"server_heat_score": 0, "node_pressure_supports_alert": False}
        for node in nodes:
            metrics = list(
                self.db.scalars(
                    select(RuntimeNodeMetricSample).where(
                        RuntimeNodeMetricSample.node_id == node.id,
                        RuntimeNodeMetricSample.sampled_at >= now - timedelta(minutes=20),
                    )
                )
            )
            sessions = list(
                self.db.scalars(
                    select(DbSessionSnapshot).where(
                        DbSessionSnapshot.run_id == run.id,
                        DbSessionSnapshot.sampled_at >= now - timedelta(minutes=30),
                    )
                )
            )
            bindings = list(
                self.db.scalars(
                    select(JobRunNodeBinding)
                    .where(JobRunNodeBinding.run_id == run.id, JobRunNodeBinding.node_id == node.id)
                    .options(selectinload(JobRunNodeBinding.run))
                )
            )
            score, breakdown = self.compute_heat_score(sessions, bindings, metrics)
            if score > summary["server_heat_score"]:
                summary = {
                    "server_heat_score": score,
                    "hottest_node": node.display_name,
                    "hottest_node_type": node.node_type,
                    "node_pressure_supports_alert": score >= 65,
                    "breakdown": breakdown,
                }
        return summary

    def _classify_problem(self, run: JobRun, heat_summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
        tags = set()
        for observation in run.sql_observations:
            tags.update(observation.query_shape_tags or [])
        wait_classes = {str(row.get("WAIT_CLASS") or "").lower() for row in rows}
        if "OR predicate" in tags or run.udq_hash and run.udq_name:
            return "customer_query_udq_problem"
        if heat_summary.get("hottest_node_type") in {"ess_server", "wls_managed_server"} and heat_summary.get("server_heat_score", 0) >= 65:
            return "middleware_pressure_possible"
        if "scheduler" in wait_classes:
            return "middleware_or_scheduler_pressure"
        if heat_summary.get("server_heat_score", 0) >= 75:
            return "db_node_pressure_possible"
        if rows and any(row.get("SQL_ID") for row in rows):
            return "job_sql_specific"
        return "unknown"

    def _correlation_evidence(
        self,
        run: JobRun,
        rows: list[dict[str, Any]],
        db_instance_node: RuntimeNode | None,
        db_host_node: RuntimeNode | None,
        app_server_node: RuntimeNode | None,
        heat_summary: dict[str, Any],
    ) -> list[str]:
        evidence: list[str] = []
        first = rows[0] if rows else {}
        if db_instance_node:
            evidence.append(
                f"Confirmed: {run.job_name} is active on {db_instance_node.display_name} with SQL_ID {first.get('SQL_ID') or run.sql_id}."
            )
        if db_host_node:
            evidence.append(f"Confirmed: database host is {db_host_node.display_name}; raw IP is not exposed.")
        if app_server_node:
            evidence.append(
                f"Inferred: client machine appears to be {app_server_node.display_name}; confirm with WLS/OCI telemetry."
            )
        if first.get("WAIT_CLASS") or first.get("EVENT"):
            evidence.append(f"Runtime signal: wait class {first.get('WAIT_CLASS') or 'n/a'}, event {first.get('EVENT') or 'n/a'}.")
        if heat_summary:
            evidence.append(
                f"Heat score {heat_summary.get('server_heat_score', 0)} on {heat_summary.get('hottest_node', 'unknown node')}."
            )
        return evidence

    def _plain_explanation(
        self,
        run: JobRun,
        classification: str,
        db_instance_node: RuntimeNode | None,
        active_sql_id: str | None,
        rows: list[dict[str, Any]],
    ) -> str:
        if db_instance_node and active_sql_id == "dp9u1803k8k7f":
            return (
                f"Confirmed: {run.job_name} is currently active on {db_instance_node.display_name} "
                "with SQL_ID dp9u1803k8k7f and User I/O waits. DB node heat is concentrated on this SQL path, "
                "so the stronger explanation is plan regression / UDQ risk rather than a cluster-wide outage."
            )
        if classification == "middleware_pressure_possible":
            return "Multiple jobs share an ESS/WLS server with elevated GC. Middleware pressure may be contributing."
        if classification == "middleware_or_scheduler_pressure":
            return "The active session is waiting in scheduler-related work; verify ESS/WLS progress and queueing."
        if rows and db_instance_node:
            return f"Confirmed: active DB session is mapped to {db_instance_node.display_name}; review SQL_ID and wait event."
        return "Topology correlation is incomplete; run the active-session template with ECID/client identifier fallback."

    def _recommended_next_query(self, rows: list[dict[str, Any]], missing_inputs: list[str]) -> str | None:
        if any("ECID" in item for item in missing_inputs):
            return "active_db_session_by_ess_request"
        if any("ASH" in item for item in missing_inputs):
            return "instance_health_snapshot"
        if not rows or not rows[0].get("SQL_ID"):
            return "active_db_session_by_ecid_or_client_identifier"
        return "ash_samples_by_ecid_or_sql_id"

    def _has_ecid_or_client_identifier(self, run: JobRun, rows: list[dict[str, Any]]) -> bool:
        scope = run.business_scope or {}
        return bool(scope.get("ecid") or scope.get("client_identifier") or self._first_value(rows, "ECID") or self._first_value(rows, "CLIENT_IDENTIFIER"))

    def _has_ecid(self, run: JobRun, rows: list[dict[str, Any]]) -> bool:
        scope = run.business_scope or {}
        return bool(scope.get("ecid") or self._first_value(rows, "ECID"))

    def _node_heat(
        self,
        node: RuntimeNode,
        sessions: list[DbSessionSnapshot],
        bindings: list[JobRunNodeBinding],
    ) -> dict[str, Any]:
        now = utcnow()
        metrics = list(
            self.db.scalars(
                select(RuntimeNodeMetricSample)
                .where(RuntimeNodeMetricSample.node_id == node.id, RuntimeNodeMetricSample.sampled_at >= now - timedelta(minutes=20))
                .order_by(RuntimeNodeMetricSample.sampled_at.desc())
            )
        )
        score, breakdown = self.compute_heat_score(sessions, bindings, metrics)
        return {
            "heat_score": score,
            "confidence": "confirmed" if sessions or any("confirmed" in binding.binding_type for binding in bindings) else "inferred",
            "top_sql_id": self._most_common([session.sql_id for session in sessions]),
            "top_wait_class": self._most_common([session.wait_class for session in sessions]),
            "top_event": self._most_common([session.event for session in sessions]),
            "metrics": breakdown,
        }

    def _session_matches_node(self, session: DbSessionSnapshot, node: RuntimeNode) -> bool:
        if node.node_type == "db_instance":
            return bool(session.instance_name and session.instance_name == node.instance_name) or (
                session.inst_id is not None and node.node_key == f"db-instance-{session.inst_id}"
            )
        if node.node_type == "db_host":
            return bool(session.db_host_name and session.db_host_name == node.host_name)
        if node.node_type in {"app_server", "ess_server", "wls_managed_server"}:
            return bool(session.machine and self._safe_key(session.machine) in node.node_key)
        return False

    def _default_selected_run_id(self, customer_key: str | None, environment: str | None) -> int | None:
        stmt = (
            select(JobRun)
            .join(Customer, JobRun.customer_id == Customer.id)
            .join(Environment, JobRun.environment_id == Environment.id)
            .where(JobRun.status == "RUNNING")
            .order_by(JobRun.started_at.asc())
        )
        if customer_key:
            stmt = stmt.where(Customer.customer_key == customer_key)
        if environment:
            stmt = stmt.where(Environment.name == environment)
        run = self.db.scalar(stmt)
        return run.id if run else None

    def _first_binding(self, bindings: list[JobRunNodeBinding], binding_type: str) -> JobRunNodeBinding | None:
        return next((binding for binding in bindings if binding.binding_type == binding_type), None)

    def _tier_for_node(self, node: RuntimeNode) -> str:
        if node.node_type in {"ess_server", "wls_managed_server", "app_server"}:
            return "ESS/WLS"
        if node.node_type in {"db_instance", "db_host", "rac_cluster"}:
            return "DB"
        return "Unknown/Inferred"

    def _severity_from_score(self, score: float) -> str:
        if score >= 75:
            return "critical"
        if score >= 50:
            return "warning"
        if score >= 25:
            return "watch"
        if score > 0:
            return "normal"
        return "unknown"

    def _heat_explanation(
        self,
        node: RuntimeNode,
        score: float,
        sessions: list[DbSessionSnapshot],
        bindings: list[JobRunNodeBinding],
        breakdown: dict[str, Any],
    ) -> str:
        if score <= 0:
            return f"{node.display_name}: no active slow-job or metric pressure in this bucket."
        jobs = sorted({binding.run.job_name for binding in bindings if binding.run})
        sql_ids = sorted({session.sql_id for session in sessions if session.sql_id})
        wait = self._most_common([session.wait_class for session in sessions]) or "no dominant wait"
        return (
            f"{node.display_name}: heat {score} from {breakdown.get('active_slow_jobs', 0)} slow job(s), "
            f"wait {wait}, SQL {', '.join(sql_ids) if sql_ids else 'n/a'}, jobs {', '.join(jobs[:3]) if jobs else 'n/a'}."
        )

    def _run_is_slowish(self, run: JobRun) -> bool:
        latest = self.db.scalar(
            select(Alert).where(Alert.run_id == run.id).order_by(Alert.created_at.desc())
        )
        if latest and latest.runtime_state in {"warning", "critical"}:
            return True
        if latest and latest.runtime_state == "watch":
            expected = float(run.expected_minutes_at_start or 0)
            return expected > 0 and duration_minutes(run) > expected * 1.1
        expected = float(run.expected_minutes_at_start or 0)
        if expected <= 0:
            return False
        return duration_minutes(run) > expected * 1.35

    def _run_state(self, run: JobRun) -> str:
        latest = self.db.scalar(
            select(Alert).where(Alert.run_id == run.id).order_by(Alert.created_at.desc())
        )
        if latest and latest.runtime_state:
            return latest.runtime_state
        if run.status in {"SUCCESS", "COMPLETED", "SUCCEEDED"}:
            return "complete"
        return "unknown_baseline" if run.expected_minutes_at_start is None else "normal"

    def _is_scale_seed_run(self, run: JobRun) -> bool:
        scope = run.business_scope or {}
        return bool(scope.get("scale_seed_state")) or run.run_key.startswith("DEMO_CUST_")

    def _job_index(self, run: JobRun) -> int:
        scope = run.business_scope or {}
        raw_value = scope.get("job_index")
        try:
            if raw_value is not None:
                return max(int(raw_value), 1)
        except (TypeError, ValueError):
            pass
        marker = "-PROD-"
        if marker in run.run_key:
            token = run.run_key.split(marker, 1)[1].split("-", 1)[0]
            try:
                return max(int(token), 1)
            except ValueError:
                pass
        return max(run.id % 25, 1)

    def _customer_ordinal(self, customer_key: str) -> int:
        if customer_key == "CUST_A":
            return 1
        if customer_key == "CUST_B":
            return 2
        digits = "".join(ch for ch in customer_key if ch.isdigit())
        return int(digits[-2:] or digits or "1")

    def _bucket_range(self, from_at: datetime, to_at: datetime, bucket_minutes: int):
        cursor = from_at.replace(second=0, microsecond=0)
        while cursor < to_at:
            yield cursor
            cursor += timedelta(minutes=bucket_minutes)

    def _most_common(self, values: list[str | None]) -> str | None:
        counts: dict[str, int] = {}
        for value in values:
            if not value:
                continue
            counts[value] = counts.get(value, 0) + 1
        if not counts:
            return None
        return sorted(counts.items(), key=lambda item: item[1], reverse=True)[0][0]

    def _first_value(self, rows: list[dict[str, Any]], key: str) -> Any:
        return next((row.get(key) for row in rows if row.get(key) is not None), None)

    def _safe_key(self, value: Any) -> str:
        return str(value).strip().lower().replace(" ", "-").replace("/", "-").replace("_", "_")

    def _parse_dt(self, value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _sanitize_evidence(self, evidence: dict[str, Any]) -> dict[str, Any]:
        redacted_keys = {"USERNAME", "IP_ADDRESS", "PASSWORD", "DSN", "WALLET"}
        return {
            key.lower(): ("[redacted]" if key.upper() in redacted_keys else self._json_safe(value))
            for key, value in evidence.items()
            if key.upper() not in {"RAW_SQL_TEXT", "QUERY_TEXT"}
        }

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        return value

    def _update_apj_business_scope(self, run: JobRun) -> None:
        scope = dict(run.business_scope or {})
        scope.setdefault("topology", {})
        scope["topology"].update(
            {
                "collector_version": TOPOLOGY_COLLECTOR_VERSION,
                "db_instance": "DBRAC_inst1",
                "db_host": "dbhost-a",
                "app_server_inferred": "ESS_SOAServer_as24_01",
                "mapping_confidence": {"db_instance": "confirmed", "app_server": "inferred"},
            }
        )
        run.business_scope = scope
