from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import SessionLocal, engine
from app.core.schema_compat import ensure_sqlite_phase2_columns
from app.models import (
    Alert,
    Base,
    Customer,
    Environment,
    ExpectationRecord,
    JobDefinition,
    JobRun,
    RuntimeNode,
    RuntimeNodeMetricSample,
    SqlObservation,
    VolumeSnapshot,
)
from app.models.base import utcnow
from app.seed import ensure_phase2b_seed_data, ensure_phase2c_seed_data, seed_database
from app.services.diagnostics import DiagnosticAnalysisService
from app.services.evaluation import EvaluationService
from app.services.topology import RuntimeTopologyService


@dataclass(frozen=True)
class IncidentScenario:
    key: str
    customer_key: str
    customer_name: str
    job_family: str
    job_type: str
    job_name: str
    region: str
    workstream: str
    api_operation: str | None
    expected_minutes: int | None
    baseline_sql_id: str | None
    baseline_plan_hash: str | None
    baseline_udq_hash: str | None
    current_sql_id: str | None
    current_plan_hash: str | None
    udq_name: str | None
    current_udq_hash: str | None
    elapsed_sequence: tuple[int, ...]
    progress_sequence: tuple[int, ...]
    volume_ratio_sequence: tuple[float, ...]
    wait_class: str | None
    event: str | None
    app_server: str
    inst_id: int
    db_host_name: str
    query_shape_tags: tuple[str, ...]
    recommendation: str
    top_wait_event: str | None = None
    ash_available: bool = True
    row_wait_obj: str | None = None
    sql_profile: str | None = None
    blocking_instance: int | None = None
    blocking_session: int | None = None
    source_type: str = "live_simulator"
    generate_diagnostic: bool = False


SCENARIOS: dict[str, IncidentScenario] = {
    "customer-a-apj-udq": IncidentScenario(
        key="customer-a-apj-udq",
        customer_key="CUST_A",
        customer_name="Customer A",
        job_family="ICM Calculation",
        job_type="CalculatePVT",
        job_name="LIVE APJ Direct CalculatePVT",
        region="APJ",
        workstream="Direct",
        api_operation="CalculatePVT",
        expected_minutes=350,
        baseline_sql_id="5gk9apjbase",
        baseline_plan_hash="184029177",
        baseline_udq_hash="sha256:live-apj-direct-v1",
        current_sql_id="dp9u1803k8k7f",
        current_plan_hash="51543091",
        udq_name="MTQ_ICM_OBA_BY_BADGE_VS",
        current_udq_hash="sha256:live-apj-direct-v2",
        elapsed_sequence=(210, 360, 520, 740, 830),
        progress_sequence=(58, 62, 64, 65, 66),
        volume_ratio_sequence=(1.05, 1.18, 1.32, 1.48, 1.52),
        wait_class="User I/O",
        event="cell single block physical read",
        app_server="ESS_SOAServer_as24_01",
        inst_id=1,
        db_host_name="dbhost-a",
        query_shape_tags=("OR predicate", "full scan", "unstable plan"),
        recommendation=(
            "Compare current data window, volume, SQL_ID, plan hash, and UDQ hash before treating this "
            "as an Oracle runtime regression. Review the OR predicate pattern and consider UNION ALL or "
            "separate SQL branches, then validate with execution statistics."
        ),
        top_wait_event="cell single block physical read",
        row_wait_obj="HZ_REF_ENTITIES",
        sql_profile="LIVE_ICM_APJ_PROFILE",
        generate_diagnostic=True,
    ),
    "customer-a-middleware-gc": IncidentScenario(
        key="customer-a-middleware-gc",
        customer_key="CUST_A",
        customer_name="Customer A",
        job_family="ICM Collection",
        job_type="Collect",
        job_name="LIVE AMER Collect Credits Middleware Pressure",
        region="AMER",
        workstream="Collections",
        api_operation=None,
        expected_minutes=140,
        baseline_sql_id="2collectbase",
        baseline_plan_hash="77192011",
        baseline_udq_hash=None,
        current_sql_id="livecolgc01",
        current_plan_hash="77192011",
        udq_name=None,
        current_udq_hash=None,
        elapsed_sequence=(85, 132, 180, 230, 260),
        progress_sequence=(45, 54, 57, 58, 58),
        volume_ratio_sequence=(1.02, 1.05, 1.08, 1.09, 1.1),
        wait_class="Scheduler",
        event="ESS scheduler wait",
        app_server="ESS_SOAServer_as27_01",
        inst_id=3,
        db_host_name="dbhost-c",
        query_shape_tags=("stuck progress",),
        recommendation="Check ESS/WLS worker health and GC pressure before treating this as a SQL plan regression.",
        top_wait_event="ESS scheduler wait",
        ash_available=False,
    ),
    "customer-b-revert-regression": IncidentScenario(
        key="customer-b-revert-regression",
        customer_key="CUST_B",
        customer_name="Customer B",
        job_family="ICM Maintenance",
        job_type="Run Revert",
        job_name="LIVE Run Revert Regression",
        region="GLOBAL",
        workstream="Revert",
        api_operation=None,
        expected_minutes=65,
        baseline_sql_id="7revertbase",
        baseline_plan_hash="1149012",
        baseline_udq_hash=None,
        current_sql_id="b7revertlive",
        current_plan_hash="8842197",
        udq_name=None,
        current_udq_hash=None,
        elapsed_sequence=(75, 140, 240, 380, 420),
        progress_sequence=(68, 69, 69, 69, 70),
        volume_ratio_sequence=(1.0, 1.08, 1.2, 1.35, 1.38),
        wait_class="User I/O",
        event="db file sequential read",
        app_server="MWServer_as11_01",
        inst_id=4,
        db_host_name="dbhost-d",
        query_shape_tags=("new SQL_ID", "plan change"),
        recommendation="Run read-only DB status and SQL plan comparison queries before escalating the revert as a platform regression.",
        top_wait_event="db file sequential read",
    ),
    "customer-b-learning-mode": IncidentScenario(
        key="customer-b-learning-mode",
        customer_key="CUST_B",
        customer_name="Customer B",
        job_family="ICM Calculation",
        job_type="CalculatePVT",
        job_name="LIVE New Territory Model CalculatePVT",
        region="APJ",
        workstream="Pilot",
        api_operation="CalculatePVT",
        expected_minutes=None,
        baseline_sql_id=None,
        baseline_plan_hash=None,
        baseline_udq_hash=None,
        current_sql_id="bnewmodel01",
        current_plan_hash="3901455",
        udq_name="NEW_TERRITORY_MODEL",
        current_udq_hash="sha256:live-new-territory-v1",
        elapsed_sequence=(40, 90, 150, 210, 260),
        progress_sequence=(12, 22, 28, 34, 41),
        volume_ratio_sequence=(1.0, 1.0, 1.0, 1.0, 1.0),
        wait_class="Other",
        event="unclassified job startup",
        app_server="ESS_SOAServer_as12_01",
        inst_id=2,
        db_host_name="dbhost-b",
        query_shape_tags=("learning mode",),
        recommendation="Keep in learning mode until enough successful history exists; collect SQL and volume telemetry only.",
        top_wait_event="unclassified job startup",
        ash_available=False,
    ),
}

SCENARIO_GROUPS = {
    "all": tuple(SCENARIOS),
    "customer-a": ("customer-a-apj-udq", "customer-a-middleware-gc"),
    "customer-b": ("customer-b-revert-regression", "customer-b-learning-mode"),
}


def run_live_traffic(
    db: Session,
    *,
    scenario_names: list[str],
    cycles: int = 1,
    interval_seconds: float = 0,
    generate_diagnostics: bool = True,
    reset_live: bool = False,
    base_url: str = "http://127.0.0.1:8000",
) -> dict[str, Any]:
    bootstrap_local_demo(db)
    scenarios = _resolve_scenarios(scenario_names)
    if reset_live:
        _reset_live_runs(db, [scenario.customer_key for scenario in scenarios])
        db.commit()

    cycle_summaries: list[dict[str, Any]] = []
    for cycle in range(max(cycles, 1)):
        now = utcnow().replace(second=0, microsecond=0)
        cycle_results = [
            _apply_scenario(
                db,
                scenario,
                step=cycle,
                now=now,
                generate_diagnostic=generate_diagnostics and scenario.generate_diagnostic,
                base_url=base_url,
            )
            for scenario in scenarios
        ]
        db.commit()
        cycle_summaries.append({"cycle": cycle + 1, "generated_at": now.isoformat(), "runs": cycle_results})
        if interval_seconds > 0 and cycle < cycles - 1:
            time.sleep(interval_seconds)

    return {
        "scenario_count": len(scenarios),
        "cycles": cycle_summaries,
        "dashboard_urls": sorted(
            {
                f"{base_url.removesuffix('/api')}/api/dashboard?customer_key={scenario.customer_key}&environment=PROD"
                for scenario in scenarios
            }
        ),
    }


def bootstrap_local_demo(db: Session) -> None:
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_phase2_columns(engine)
    if db.scalar(select(Customer.id).limit(1)) is None:
        seed_database(db)
    ensure_phase2b_seed_data(db)
    ensure_phase2c_seed_data(db)


def _apply_scenario(
    db: Session,
    scenario: IncidentScenario,
    *,
    step: int,
    now: datetime,
    generate_diagnostic: bool,
    base_url: str,
) -> dict[str, Any]:
    customer = _get_or_create_customer(db, scenario.customer_key, scenario.customer_name)
    environment = _get_or_create_environment(db, customer, "PROD")
    job_definition = _get_or_create_job_definition(db, customer, scenario)
    expectation = _upsert_expectation(db, scenario) if scenario.expected_minutes is not None else None
    elapsed = _sequence_value(scenario.elapsed_sequence, step)
    progress = _sequence_value(scenario.progress_sequence, step)
    volume_ratio = _sequence_value(scenario.volume_ratio_sequence, step)
    run = _upsert_run(db, customer, environment, job_definition, scenario, now, elapsed, progress, volume_ratio)
    _upsert_volume_snapshot(db, run, scenario, volume_ratio)
    _upsert_sql_observation(db, run, scenario, elapsed)
    db.flush()

    topology_service = RuntimeTopologyService(db)
    topology = topology_service.correlate_run(run.id, persist=True)
    _upsert_node_metrics(db, topology_service, run, scenario, now, step)
    topology = topology_service.correlate_run(run.id, persist=True)
    evaluation = EvaluationService(db).evaluate_run(run.id, create_alert=True, send_mock_slack=False)
    diagnostic_id = None
    if generate_diagnostic:
        diagnostic = DiagnosticAnalysisService(db).generate_report(run_id=run.id, collector_mode="live-simulator")
        diagnostic_id = diagnostic.report.id
        evaluation = EvaluationService(db).evaluate_run(run.id, create_alert=True, send_mock_slack=False)

    latest_alert = db.scalar(select(Alert).where(Alert.run_id == run.id).order_by(Alert.updated_at.desc()))
    return {
        "scenario": scenario.key,
        "customer_key": scenario.customer_key,
        "run_id": run.id,
        "run_key": run.run_key,
        "job_name": run.job_name,
        "elapsed_minutes": elapsed,
        "expected_minutes": float(expectation.expected_minutes) if expectation and expectation.expected_minutes else None,
        "runtime_state": evaluation.runtime_state,
        "severity": evaluation.severity,
        "reason_codes": evaluation.reason_codes,
        "top_suspected_cause": evaluation.top_suspected_cause,
        "active_sql_id": topology.active_sql_id,
        "db_instance": topology.db_instance_node.display_name if topology.db_instance_node else None,
        "app_server": topology.app_server_node.display_name if topology.app_server_node else None,
        "problem_classification": topology.problem_classification,
        "diagnostic_report_id": diagnostic_id,
        "alert_id": latest_alert.id if latest_alert else None,
        "links": _sample_calls(base_url, run.id, scenario.customer_key, diagnostic_id),
    }


def _upsert_run(
    db: Session,
    customer: Customer,
    environment: Environment,
    job_definition: JobDefinition,
    scenario: IncidentScenario,
    now: datetime,
    elapsed_minutes: int,
    progress: int,
    volume_ratio: float,
) -> JobRun:
    run_key = f"LIVE-{scenario.customer_key}-{scenario.key.upper().replace('-', '_')}"
    run = db.scalar(
        select(JobRun)
        .where(JobRun.run_key == run_key)
        .options(selectinload(JobRun.volume_snapshots), selectinload(JobRun.sql_observations))
    )
    started_at = now - timedelta(minutes=elapsed_minutes)
    last_progress_at = now - timedelta(minutes=90 if elapsed_minutes >= (scenario.expected_minutes or 180) else 12)
    scope = {
        "live_traffic": True,
        "scenario": scenario.key,
        "scenario_step": elapsed_minutes,
        "ecid": f"live-{scenario.customer_key.lower()}-{scenario.key}",
        "client_identifier": f"live-{scenario.customer_key.lower()}-{scenario.key}-{elapsed_minutes}",
        "volume_ratio": volume_ratio,
        "topology_seed": {
            "inst_id": scenario.inst_id,
            "db_host_name": scenario.db_host_name,
            "machine": scenario.app_server,
            "sql_id": scenario.current_sql_id,
            "plan_hash_value": scenario.current_plan_hash,
            "wait_class": scenario.wait_class,
            "event": scenario.event,
            "module": scenario.job_family,
            "action": scenario.api_operation or scenario.job_name,
            "ecid": f"live-{scenario.customer_key.lower()}-{scenario.key}",
            "client_identifier": f"live-{scenario.customer_key.lower()}-{scenario.key}-{elapsed_minutes}",
            "ash_available": scenario.ash_available,
            "row_wait_obj": scenario.row_wait_obj,
            "blocking_instance": scenario.blocking_instance,
            "blocking_session": scenario.blocking_session,
            "last_call_et_seconds": elapsed_minutes * 60,
        },
    }
    values = {
        "customer_id": customer.id,
        "environment_id": environment.id,
        "job_definition_id": job_definition.id,
        "job_family": scenario.job_family,
        "job_type": scenario.job_type,
        "job_name": scenario.job_name,
        "region": scenario.region,
        "workstream": scenario.workstream,
        "period": "FY26-Q4",
        "business_scope": scope,
        "data_window_start": now - timedelta(days=46 if volume_ratio >= 1.25 else 31),
        "data_window_end": now,
        "started_at": started_at,
        "ended_at": None,
        "status": "RUNNING",
        "ess_request_id": f"LIVE-ESS-{scenario.customer_key}-{scenario.key}",
        "job_id": f"LIVE-JOB-{scenario.customer_key}-{scenario.key}",
        "process_id": f"LIVE-PROC-{scenario.customer_key}-{scenario.key}",
        "api_operation": scenario.api_operation,
        "sql_id": scenario.current_sql_id,
        "plan_hash_value": scenario.current_plan_hash,
        "udq_name": scenario.udq_name,
        "udq_hash": scenario.current_udq_hash,
        "expected_minutes_at_start": Decimal(str(scenario.expected_minutes)) if scenario.expected_minutes is not None else None,
        "current_progress_pct": Decimal(str(progress)),
        "last_progress_at": last_progress_at,
        "notes": "Live traffic simulator synthetic run. Read-only observations only; no remediation is executed.",
        "source_type": scenario.source_type,
        "ingested_at": now,
    }
    if run is None:
        run = JobRun(run_key=run_key, **values)
        db.add(run)
    else:
        for key, value in values.items():
            setattr(run, key, value)
    db.flush()
    return run


def _upsert_expectation(db: Session, scenario: IncidentScenario) -> ExpectationRecord:
    expectation = db.scalar(
        select(ExpectationRecord).where(
            ExpectationRecord.customer_key == scenario.customer_key,
            ExpectationRecord.environment == "PROD",
            ExpectationRecord.job_name == scenario.job_name,
        )
    )
    values = {
        "customer_key": scenario.customer_key,
        "environment": "PROD",
        "job_family": scenario.job_family,
        "job_type": scenario.job_type,
        "job_name": scenario.job_name,
        "region": scenario.region,
        "workstream": scenario.workstream,
        "period": "FY26-Q4",
        "process_name": scenario.job_name,
        "api_operation": scenario.api_operation,
        "sql_id": scenario.baseline_sql_id,
        "sql_plan_hash": scenario.baseline_plan_hash,
        "udq_name": scenario.udq_name,
        "udq_hash": scenario.baseline_udq_hash,
        "baseline_method": "manual_goal",
        "expected_minutes": Decimal(str(scenario.expected_minutes)),
        "warning_threshold_pct": Decimal("20.00"),
        "critical_threshold_pct": Decimal("60.00"),
        "customer_goal_minutes": Decimal(str(round(scenario.expected_minutes * 1.45, 2))),
        "minimum_history_count": 3,
        "confidence_score": Decimal("0.84"),
        "owner": "Live Simulator",
        "alert_channel": "#jobrun-sentinel-live",
        "notes": "Synthetic live simulator expectation.",
        "risk_assumptions": "Comparable only when SQL_ID, plan hash, UDQ hash, volume, and data window remain stable.",
        "last_reviewed_by": "live-simulator",
        "last_reviewed_at": utcnow(),
        "active_from": utcnow() - timedelta(days=1),
    }
    if expectation is None:
        expectation = ExpectationRecord(**values)
        db.add(expectation)
    else:
        for key, value in values.items():
            setattr(expectation, key, value)
    db.flush()
    return expectation


def _upsert_volume_snapshot(db: Session, run: JobRun, scenario: IncidentScenario, volume_ratio: float) -> None:
    baseline = Decimal("1100000") if scenario.job_type == "CalculatePVT" else Decimal("420000")
    current = (baseline * Decimal(str(volume_ratio))).quantize(Decimal("1"))
    tags = []
    if volume_ratio > 1.2:
        tags.extend(["volume drift", "data window mismatch"])
    if scenario.expected_minutes is None:
        tags.append("learning mode")
    snapshot = db.scalar(
        select(VolumeSnapshot).where(VolumeSnapshot.run_id == run.id, VolumeSnapshot.metric_name == "transactions")
    )
    values = {
        "metric_value": current,
        "baseline_value": baseline,
        "unit": "rows",
        "data_window_start": run.data_window_start,
        "data_window_end": run.data_window_end,
        "shape_tags": tags,
    }
    if snapshot is None:
        db.add(VolumeSnapshot(run_id=run.id, metric_name="transactions", **values))
    else:
        for key, value in values.items():
            setattr(snapshot, key, value)


def _upsert_sql_observation(db: Session, run: JobRun, scenario: IncidentScenario, elapsed_minutes: int) -> None:
    observation = db.scalar(select(SqlObservation).where(SqlObservation.run_id == run.id).order_by(SqlObservation.id.asc()))
    values = {
        "sql_id": scenario.current_sql_id,
        "plan_hash_value": scenario.current_plan_hash,
        "child_number": 0,
        "sql_profile": scenario.sql_profile,
        "module": scenario.job_family,
        "action": scenario.api_operation or scenario.job_name,
        "elapsed_time_delta": Decimal(str(elapsed_minutes * 60)),
        "buffer_gets_delta": Decimal(str(max(elapsed_minutes, 1) * 875000)),
        "rows_processed_delta": Decimal("1000000"),
        "top_wait_event": scenario.top_wait_event or scenario.event,
        "udq_name": scenario.udq_name,
        "udq_hash": scenario.current_udq_hash,
        "query_text_available": False,
        "query_shape_tags": list(scenario.query_shape_tags),
        "index_profile_notes": "Live simulator: compare current SQL_ID/plan against expectation before remediation.",
        "recommendation_text": scenario.recommendation,
    }
    if observation is None:
        db.add(SqlObservation(run_id=run.id, **values))
    else:
        for key, value in values.items():
            setattr(observation, key, value)


def _upsert_node_metrics(
    db: Session,
    topology_service: RuntimeTopologyService,
    run: JobRun,
    scenario: IncidentScenario,
    now: datetime,
    step: int,
) -> None:
    db_node = topology_service.upsert_node(
        customer_key=scenario.customer_key,
        environment="PROD",
        node_type="db_instance",
        node_key=f"db-instance-{scenario.inst_id}",
        display_name=f"DBRAC_inst{scenario.inst_id}",
        host_name=scenario.db_host_name,
        instance_name=f"DBRAC_inst{scenario.inst_id}",
        cluster_name="DBRAC",
        service_name="ICM_PRD",
        region=scenario.region,
        tags={"source": "live-simulator", "rac_inst_id": scenario.inst_id},
    )
    app_node = topology_service.upsert_node(
        customer_key=scenario.customer_key,
        environment="PROD",
        node_type="ess_server" if scenario.app_server.startswith("ESS") else "app_server",
        node_key=f"app-{topology_service._safe_key(scenario.app_server)}",
        display_name=scenario.app_server,
        server_name=scenario.app_server,
        cluster_name="ESSCluster" if scenario.app_server.startswith("ESS") else "WLSCluster",
        region=scenario.region,
        tags={"source": "live-simulator", "telemetry_confirmed": False},
    )
    pressure = min(100, 25 + step * 18)
    for offset in (20, 10, 0):
        sampled_at = now - timedelta(minutes=offset)
        if scenario.wait_class == "User I/O":
            _upsert_metric(db, db_node, sampled_at, "db_io_wait_samples", Decimal(str(18 + pressure // 2)), "samples")
        elif scenario.wait_class == "Application":
            _upsert_metric(db, db_node, sampled_at, "db_application_wait_samples", Decimal(str(14 + pressure // 3)), "samples")
        elif scenario.wait_class == "Scheduler":
            _upsert_metric(db, db_node, sampled_at, "db_active_sessions", Decimal(str(16 + pressure // 5)), "sessions")
        else:
            _upsert_metric(db, db_node, sampled_at, "db_active_sessions", Decimal(str(8 + pressure // 10)), "sessions")
        _upsert_metric(db, db_node, sampled_at, "cpu_utilization_pct", Decimal(str(48 + min(step * 4, 24))), "pct")
        wls_gc = Decimal(str(42 if "middleware" in scenario.key and offset <= 10 else 6 + step))
        _upsert_metric(db, app_node, sampled_at, "wls_full_gc_pct", wls_gc, "pct")


def _upsert_metric(
    db: Session,
    node: RuntimeNode,
    sampled_at: datetime,
    metric_name: str,
    metric_value: Decimal,
    unit: str,
) -> None:
    metric = db.scalar(
        select(RuntimeNodeMetricSample).where(
            RuntimeNodeMetricSample.node_id == node.id,
            RuntimeNodeMetricSample.sampled_at == sampled_at,
            RuntimeNodeMetricSample.metric_name == metric_name,
        )
    )
    if metric is None:
        db.add(
            RuntimeNodeMetricSample(
                node_id=node.id,
                sampled_at=sampled_at,
                metric_name=metric_name,
                metric_value=metric_value,
                unit=unit,
                source="mock",
                source_ref="live-traffic-simulator",
            )
        )
    else:
        metric.metric_value = metric_value
        metric.unit = unit
        metric.source = "mock"
        metric.source_ref = "live-traffic-simulator"


def _get_or_create_customer(db: Session, customer_key: str, display_name: str) -> Customer:
    customer = db.scalar(select(Customer).where(Customer.customer_key == customer_key))
    if customer:
        return customer
    customer = Customer(customer_key=customer_key, display_name=display_name, tier="live-demo")
    db.add(customer)
    db.flush()
    return customer


def _get_or_create_environment(db: Session, customer: Customer, name: str) -> Environment:
    environment = db.scalar(select(Environment).where(Environment.customer_id == customer.id, Environment.name == name))
    if environment:
        return environment
    environment = Environment(customer_id=customer.id, name=name, region="global", lifecycle="prod")
    db.add(environment)
    db.flush()
    return environment


def _get_or_create_job_definition(db: Session, customer: Customer, scenario: IncidentScenario) -> JobDefinition:
    job = db.scalar(
        select(JobDefinition).where(
            JobDefinition.customer_id == customer.id,
            JobDefinition.job_family == scenario.job_family,
            JobDefinition.job_type == scenario.job_type,
            JobDefinition.job_name == scenario.job_name,
        )
    )
    values = {
        "default_region": scenario.region,
        "default_workstream": scenario.workstream,
        "ess_request_name": scenario.job_name,
        "process_name": scenario.job_name,
        "api_operation": scenario.api_operation,
        "active": True,
    }
    if job is None:
        job = JobDefinition(
            customer_id=customer.id,
            job_family=scenario.job_family,
            job_type=scenario.job_type,
            job_name=scenario.job_name,
            **values,
        )
        db.add(job)
    else:
        for key, value in values.items():
            setattr(job, key, value)
    db.flush()
    return job


def _reset_live_runs(db: Session, customer_keys: list[str]) -> None:
    runs = list(
        db.scalars(
            select(JobRun)
            .join(Customer, JobRun.customer_id == Customer.id)
            .where(Customer.customer_key.in_(sorted(set(customer_keys))), JobRun.run_key.like("LIVE-%"))
        )
    )
    for run in runs:
        run.status = "RUNNING"
        run.ended_at = None
        run.current_progress_pct = Decimal("1.00")
        run.last_progress_at = utcnow()


def _resolve_scenarios(names: list[str]) -> list[IncidentScenario]:
    selected: list[str] = []
    for name in names or ["all"]:
        if name in SCENARIO_GROUPS:
            selected.extend(SCENARIO_GROUPS[name])
        elif name in SCENARIOS:
            selected.append(name)
        else:
            valid = ", ".join(sorted(set(SCENARIOS) | set(SCENARIO_GROUPS)))
            raise ValueError(f"Unknown scenario '{name}'. Valid values: {valid}")
    deduped = list(dict.fromkeys(selected))
    return [SCENARIOS[name] for name in deduped]


def _sequence_value(values: tuple[Any, ...], step: int) -> Any:
    return values[min(step, len(values) - 1)]


def _sample_calls(base_url: str, run_id: int, customer_key: str, diagnostic_id: int | None) -> dict[str, str]:
    api = base_url.rstrip("/")
    calls = {
        "dashboard": f"GET {api}/api/dashboard?customer_key={customer_key}&environment=PROD",
        "run_detail": f"GET {api}/api/runs/{run_id}",
        "evaluate": f"POST {api}/api/evaluate/{run_id}",
        "correlate_topology": f"POST {api}/api/runs/{run_id}/correlate-topology",
        "run_topology": f"GET {api}/api/runs/{run_id}/topology",
        "heatmap": f"GET {api}/api/topology/heatmap?customer_key={customer_key}&environment=PROD&bucket_minutes=10",
    }
    if diagnostic_id:
        calls["diagnostic"] = f"GET {api}/api/diagnostics/{diagnostic_id}"
    else:
        calls["generate_diagnostic"] = f"POST {api}/api/diagnostics/run -d '{{\"run_id\": {run_id}}}'"
    return calls


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate live synthetic JobRun Sentinel incidents for local demos.")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(set(SCENARIOS) | set(SCENARIO_GROUPS)),
        help="Scenario or group to run. Can be repeated. Defaults to all.",
    )
    parser.add_argument("--cycles", type=int, default=1, help="Number of update cycles to generate.")
    parser.add_argument("--interval-seconds", type=float, default=0, help="Delay between cycles for live dashboard demos.")
    parser.add_argument("--no-diagnostics", action="store_true", help="Skip diagnostic report generation.")
    parser.add_argument("--reset-live", action="store_true", help="Reset existing LIVE-* runs before applying scenarios.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL used in sample calls.")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    ensure_sqlite_phase2_columns(engine)
    db = SessionLocal()
    try:
        summary = run_live_traffic(
            db,
            scenario_names=args.scenario or ["all"],
            cycles=args.cycles,
            interval_seconds=args.interval_seconds,
            generate_diagnostics=not args.no_diagnostics,
            reset_live=args.reset_live,
            base_url=args.base_url,
        )
        print(json.dumps(summary, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
