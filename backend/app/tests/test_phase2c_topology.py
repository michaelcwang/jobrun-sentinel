import json
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base, DbSessionSnapshot, JobRun, JobRunNodeBinding, QueryTemplate, RuntimeNode, RuntimeNodeMetricSample
from app.models.base import utcnow
from app.seed import seed_database, seed_scale_test_data
from app.services.evaluation import EvaluationService
from app.services.query_catalog import QueryCatalogImporter
from app.services.query_execution import QueryTemplateExecutionService
from app.services.topology import RuntimeTopologyService


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSession()
    seed_database(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session: Session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _apj_run(db: Session) -> JobRun:
    run = db.scalar(select(JobRun).where(JobRun.run_key == "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT"))
    assert run is not None
    return run


def test_runtime_node_upsert_is_idempotent(db_session: Session) -> None:
    service = RuntimeTopologyService(db_session)
    first = service.upsert_node(
        customer_key="CUST_A",
        environment="PROD",
        node_type="db_instance",
        node_key="db-instance-test",
        display_name="DBRAC_test",
        instance_name="DBRAC_test",
        tags={"source": "test"},
    )
    second = service.upsert_node(
        customer_key="CUST_A",
        environment="PROD",
        node_type="db_instance",
        node_key="db-instance-test",
        display_name="DBRAC_test_renamed",
        instance_name="DBRAC_test",
        tags={"source": "test"},
    )
    db_session.commit()

    assert first.id == second.id
    assert second.display_name == "DBRAC_test_renamed"


def test_db_session_snapshot_mapping_and_binding_confidence(db_session: Session) -> None:
    run = _apj_run(db_session)
    result = RuntimeTopologyService(db_session).correlate_run(run.id)
    db_session.commit()

    snapshot = db_session.scalar(select(DbSessionSnapshot).where(DbSessionSnapshot.run_id == run.id))
    assert snapshot is not None
    assert snapshot.inst_id == 1
    assert snapshot.instance_name == "DBRAC_inst1"
    assert snapshot.sql_id == "dp9u1803k8k7f"
    assert snapshot.wait_class == "User I/O"

    binding = db_session.scalar(
        select(JobRunNodeBinding).where(JobRunNodeBinding.run_id == run.id, JobRunNodeBinding.binding_type == "db_instance_confirmed")
    )
    assert binding is not None
    assert binding.confidence == "confirmed"
    assert result.app_server_confidence == "inferred"


def test_active_db_session_query_template_executes_through_mock(db_session: Session) -> None:
    QueryCatalogImporter(db_session).import_bundled()
    template = db_session.scalar(select(QueryTemplate).where(QueryTemplate.template_id == "active_db_session_by_ecid_or_client_identifier"))
    assert template is not None

    summary = QueryTemplateExecutionService(db_session).execute(
        template,
        customer_key="CUST_A",
        environment_name="PROD",
        parameters=template.default_parameters,
        initiated_by="test",
    )
    db_session.commit()

    assert summary.log.status == "success"
    assert summary.log.row_count == 1
    assert summary.log.sample_result[0]["SQL_ID"] == "dp9u1803k8k7f"
    assert "password" not in json.dumps(summary.log.sample_result).lower()


def test_connector_driven_topology_ingestion_persists_provenance(db_session: Session) -> None:
    QueryCatalogImporter(db_session).import_bundled()
    run = _apj_run(db_session)
    result = RuntimeTopologyService(db_session).ingest_topology_for_run(run.id)
    db_session.commit()

    snapshot = db_session.scalar(select(DbSessionSnapshot).where(DbSessionSnapshot.run_id == run.id).order_by(DbSessionSnapshot.id.desc()))
    binding = db_session.scalar(
        select(JobRunNodeBinding)
        .where(JobRunNodeBinding.run_id == run.id, JobRunNodeBinding.binding_type == "db_instance_confirmed")
        .order_by(JobRunNodeBinding.id.desc())
    )

    assert result["status"] == "success"
    assert result["active_sql_id"] == "dp9u1803k8k7f"
    assert snapshot is not None
    assert snapshot.query_execution_id is not None
    assert snapshot.sql_id == "dp9u1803k8k7f"
    assert binding is not None
    assert binding.query_execution_id == snapshot.query_execution_id


def test_heat_score_computation_uses_waits_metrics_and_slow_jobs(db_session: Session) -> None:
    run = _apj_run(db_session)
    service = RuntimeTopologyService(db_session)
    result = service.correlate_run(run.id)
    node = db_session.scalar(select(RuntimeNode).where(RuntimeNode.node_key == "db-instance-1"))
    assert node is not None
    session = db_session.scalar(select(DbSessionSnapshot).where(DbSessionSnapshot.run_id == run.id))
    binding = db_session.scalar(select(JobRunNodeBinding).where(JobRunNodeBinding.run_id == run.id, JobRunNodeBinding.node_id == node.id))
    metric = RuntimeNodeMetricSample(
        node_id=node.id,
        sampled_at=utcnow(),
        metric_name="db_io_wait_samples",
        metric_value=Decimal("40"),
        unit="samples",
        source="test",
    )
    db_session.add(metric)
    db_session.flush()

    score, breakdown = service.compute_heat_score([session], [binding], [metric])

    assert result.active_sql_id == "dp9u1803k8k7f"
    assert score >= 70
    assert breakdown["active_slow_jobs"] == 1
    assert breakdown["db_io_wait_samples"] == 40


def test_topology_correlation_for_apj_seeded_run(db_session: Session) -> None:
    run = _apj_run(db_session)
    result = RuntimeTopologyService(db_session).correlate_run(run.id)

    assert result.db_instance_node is not None
    assert result.db_instance_node.display_name == "DBRAC_inst1"
    assert result.db_host_node is not None
    assert result.db_host_node.display_name == "dbhost-a"
    assert result.app_server_node is not None
    assert result.app_server_node.display_name == "ESS_SOAServer_as24_01"
    assert result.active_sql_id == "dp9u1803k8k7f"
    assert result.plan_hash_value == "51543091"
    assert result.problem_classification == "customer_query_udq_problem"
    assert "plan regression / UDQ risk" in (result.explanation or "")


def test_missing_ecid_falls_back_to_client_identifier_module_action(db_session: Session) -> None:
    run = db_session.scalar(select(JobRun).where(JobRun.run_key == "CUST_A-PROD-AMER-LATAM-COLLECT-CURRENT"))
    assert run is not None
    result = RuntimeTopologyService(db_session).correlate_run(run.id)

    assert result.ecid is None
    assert result.client_identifier == "ess-collect-55431-6621"
    assert any("ECID not known" in item for item in result.missing_inputs)
    assert result.recommended_next_query in {"active_db_session_by_ess_request", "instance_health_snapshot"}


def test_heatmap_handles_ash_unavailable_and_redacts_ips(db_session: Session) -> None:
    run = db_session.scalar(select(JobRun).where(JobRun.run_key == "CUST_A-PROD-AMER-LATAM-COLLECT-CURRENT"))
    assert run is not None
    service = RuntimeTopologyService(db_session)
    result = service.correlate_run(run.id)
    heatmap = service.heatmap(customer_key="CUST_A", environment="PROD", from_at=utcnow() - timedelta(minutes=60), to_at=utcnow())
    payload = heatmap.model_dump(mode="json")

    assert any("GV$ACTIVE_SESSION_HISTORY unavailable" in item for item in result.missing_inputs)
    assert heatmap.rows
    assert "ip_address" not in json.dumps(payload).lower()
    assert "10.0.0." not in json.dumps(payload)


def test_connector_topology_handles_missing_ash_privileges(db_session: Session) -> None:
    QueryCatalogImporter(db_session).import_bundled()
    run = db_session.scalar(select(JobRun).where(JobRun.run_key == "CUST_A-PROD-AMER-LATAM-COLLECT-CURRENT"))
    assert run is not None

    result = RuntimeTopologyService(db_session).correlate_run(run.id)

    assert result.active_sessions
    assert result.active_sessions[0].wait_class == "Scheduler"
    assert any("GV$ACTIVE_SESSION_HISTORY unavailable" in item for item in result.missing_inputs)


def test_alert_payload_includes_topology_summary(db_session: Session) -> None:
    run = _apj_run(db_session)
    RuntimeTopologyService(db_session).correlate_run(run.id)
    result = EvaluationService(db_session).evaluate_run(run.id)

    assert result.slack_payload is not None
    topology = result.slack_payload["topology"]
    assert topology["db_instance"] == "DBRAC_inst1"
    assert topology["db_host"] == "dbhost-a"
    assert topology["app_server"] == "ESS_SOAServer_as24_01"
    assert topology["active_sql_id"] == "dp9u1803k8k7f"
    assert topology["top_wait_event"] == "cell single block physical read"


def test_topology_api_endpoints_return_structured_payloads(client: TestClient, db_session: Session) -> None:
    run = _apj_run(db_session)

    current = client.get("/api/topology/current?customer_key=CUST_A&environment=PROD")
    heatmap = client.get("/api/topology/heatmap?customer_key=CUST_A&environment=PROD&bucket_minutes=10")
    run_topology = client.get(f"/api/runs/{run.id}/topology")
    nodes = client.get("/api/nodes?customer_key=CUST_A&environment=PROD")
    imported = client.post("/api/query-catalog/import-topology-templates")

    assert current.status_code == 200
    assert any(node["display_name"] == "DBRAC_inst1" for node in current.json()["nodes"])
    assert any(node["display_name"] == "SQL_ID dp9u1803k8k7f" for node in current.json()["nodes"])
    assert heatmap.status_code == 200
    assert heatmap.json()["rows"]
    assert run_topology.status_code == 200
    assert run_topology.json()["active_sql_id"] == "dp9u1803k8k7f"
    assert nodes.status_code == 200
    assert any(node["node_type"] == "db_instance" for node in nodes.json())
    assert imported.status_code == 200
    assert imported.json()["imported"] + imported.json()["updated"] >= 7


def test_scale_seed_adds_topology_for_each_demo_customer(db_session: Session) -> None:
    counts = seed_scale_test_data(db_session, customer_count=10, jobs_per_customer=25)
    db_session.commit()

    assert counts["topology_nodes"] >= 140
    assert counts["topology_sessions"] == 250
    assert counts["topology_bindings"] >= 250

    service = RuntimeTopologyService(db_session)
    for index in range(1, 11):
        customer_key = f"DEMO_CUST_{index:02d}"
        nodes = service.list_nodes(customer_key=customer_key, environment="PROD")
        sessions = list(
            db_session.scalars(
                select(DbSessionSnapshot)
                .join(JobRun, DbSessionSnapshot.run_id == JobRun.id)
                .where(JobRun.run_key.like(f"{customer_key}-PROD-%-CURRENT"))
            )
        )
        heatmap = service.heatmap(customer_key=customer_key, environment="PROD", from_at=utcnow() - timedelta(minutes=60), to_at=utcnow())

        assert len([node for node in nodes if node.node_type == "db_instance"]) == 4
        assert len(sessions) == 25
        assert heatmap.rows
        assert any(cell.heat_score > 0 for row in heatmap.rows for cell in row.cells)


def test_demo_customer_topology_correlation_has_distinct_server_and_sql_evidence(db_session: Session) -> None:
    seed_scale_test_data(db_session, customer_count=3, jobs_per_customer=25)
    db_session.commit()

    run = db_session.scalar(
        select(JobRun).where(
            JobRun.run_key.like("DEMO_CUST_02-PROD-%-CURRENT"),
            JobRun.sql_id.like("%slow"),
        )
    )
    assert run is not None

    result = RuntimeTopologyService(db_session).correlate_run(run.id)

    assert result.db_instance_node is not None
    assert result.db_instance_node.display_name.startswith("DBRAC_inst")
    assert result.app_server_node is not None
    assert result.app_server_confidence == "inferred"
    assert result.active_sql_id == run.sql_id
    assert result.plan_hash_value == run.plan_hash_value
    assert result.heat_summary["server_heat_score"] > 0
    assert result.problem_classification in {
        "customer_query_udq_problem",
        "middleware_pressure_possible",
        "middleware_or_scheduler_pressure",
        "db_node_pressure_possible",
        "job_sql_specific",
    }
