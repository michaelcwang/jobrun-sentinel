import json
import zipfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.models import Base, DbSessionSnapshot, JobRun, JobRunNodeBinding, QueryTemplate, RuntimeNode, RuntimeNodeMetricSample
from app.models.base import utcnow
from app.seed import seed_database
from app.services.query_catalog import QueryCatalogImporter
from app.services.review_bundle import ReviewBundleOptions, create_review_bundle, redact
from app.services.topology import RuntimeTopologyService
from app.services.topology_ingestion import TopologyIngestionService
from app.services.topology_scoring import TopologyHeatScoreScorer


def _db_session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    seed_database(db)
    db.commit()
    return db


def _apj_run(db: Session) -> JobRun:
    run = db.scalar(select(JobRun).where(JobRun.run_key == "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT"))
    assert run is not None
    return run


def test_review_bundle_contains_required_files(tmp_path: Path) -> None:
    result = create_review_bundle(
        ReviewBundleOptions(output_dir=tmp_path, skip_commands=True, skip_screenshots=True)
    )

    with zipfile.ZipFile(result["zip_path"]) as bundle:
        names = set(bundle.namelist())

    assert "app_metadata.json" in names
    assert "manifest.json" in names
    assert "README.md" in names
    assert "page_inventory.json" in names
    assert "diagnostics_review.json" in names
    assert "design_review_notes.md" in names
    assert any(name.startswith("api_snapshots/dashboard") for name in names)
    assert any(name.startswith("test_results/") for name in names)
    assert any(name.startswith("screenshots/") for name in names)


def test_review_bundle_redacts_secrets_and_raw_sql() -> None:
    payload = {
        "password": "cleartext",
        "dsn": "host.example/service",
        "nested": {"token": "abc123"},
        "sql_text": "SELECT " + ", ".join([f"col{i}" for i in range(50)]) + " FROM customer_udq_table WHERE badge = :badge",
    }

    redacted = redact(payload)

    assert redacted["password"] == "[redacted]"
    assert redacted["dsn"] == "[redacted]"
    assert redacted["nested"]["token"] == "[redacted]"
    assert "customer_udq_table" not in json.dumps(redacted)


def test_ci_and_docker_paths_are_hardened() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    workflow = (repo_root / ".github/workflows/ci.yml").read_text()
    frontend_dockerfile = (repo_root / "frontend/Dockerfile").read_text()

    assert "npm ci" in workflow
    assert "docker compose build" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "concurrency:" in workflow
    assert "npm ci --no-audit --no-fund" in frontend_dockerfile


def test_topology_ingestion_service_maps_template_rows_to_canonical_entities() -> None:
    db = _db_session()
    try:
        QueryCatalogImporter(db).import_bundled()
        run = _apj_run(db)

        result = TopologyIngestionService(db).ingest_for_run(run)
        db.commit()

        snapshot = db.scalar(select(DbSessionSnapshot).where(DbSessionSnapshot.run_id == run.id).order_by(DbSessionSnapshot.id.desc()))
        instance = db.scalar(select(RuntimeNode).where(RuntimeNode.node_key == "db-instance-1"))
        binding = db.scalar(select(JobRunNodeBinding).where(JobRunNodeBinding.run_id == run.id, JobRunNodeBinding.binding_type == "db_instance_confirmed"))

        assert result.status == "success"
        assert result.log is not None
        assert snapshot is not None
        assert snapshot.query_execution_id == result.log.id
        assert snapshot.sql_id == "dp9u1803k8k7f"
        assert instance is not None
        assert binding is not None
        assert binding.query_execution_id == result.log.id
    finally:
        db.close()


def test_runtime_topology_service_uses_ingested_snapshots_when_present() -> None:
    db = _db_session()
    try:
        run = _apj_run(db)
        db.execute(delete(JobRunNodeBinding).where(JobRunNodeBinding.run_id == run.id))
        db.execute(delete(DbSessionSnapshot).where(DbSessionSnapshot.run_id == run.id))
        snapshot = DbSessionSnapshot(
            run_id=run.id,
            sampled_at=utcnow(),
            inst_id=4,
            instance_name="DBRAC_ingested",
            db_host_name="dbhost-ingested",
            sid=9901,
            session_status="ACTIVE",
            machine="ESS_SOAServer_ingested",
            sql_id="ingested1",
            wait_class="User I/O",
            event="db file sequential read",
            plan_hash_value="123456",
        )
        db.add(snapshot)
        db.commit()

        result = RuntimeTopologyService(db).correlate_run(run.id)

        assert result.active_sql_id == "ingested1"
        assert result.db_instance_node is not None
        assert result.db_instance_node.display_name == "DBRAC_ingested"
    finally:
        db.close()


def test_seed_fallback_only_runs_in_demo_or_mock_mode() -> None:
    db = _db_session()
    try:
        run = _apj_run(db)
        db.execute(delete(JobRunNodeBinding).where(JobRunNodeBinding.run_id == run.id))
        db.execute(delete(DbSessionSnapshot).where(DbSessionSnapshot.run_id == run.id))
        db.commit()
        settings = Settings(environment="production", connector_mode="oracle", allow_oracle_connector=False)

        result = RuntimeTopologyService(db, settings=settings).correlate_run(run.id)

        assert result.db_instance_node is None
        assert result.active_sql_id == run.sql_id
        assert any("No GV$SESSION-like row" in item for item in result.missing_inputs)
    finally:
        db.close()


def test_heat_score_scorer_isolated_inputs() -> None:
    run = JobRun(status="RUNNING", started_at=utcnow() - timedelta(hours=3), job_name="Synthetic Slow Run")
    session = DbSessionSnapshot(wait_class="User I/O", sql_id="abc123", event="db file sequential read")
    binding = JobRunNodeBinding(run_id=42, run=run)
    metric = RuntimeNodeMetricSample(metric_name="cpu_utilization_pct", metric_value=Decimal("85"), sampled_at=utcnow(), source="test")

    score, breakdown = TopologyHeatScoreScorer().score([session], [binding], [metric], slow_run_ids={42})

    assert score > 40
    assert breakdown["active_slow_jobs"] == 1
    assert breakdown["wait_samples"] == 1
    assert breakdown["cpu_utilization_pct"] == 85.0
