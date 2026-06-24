from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.live_traffic import run_live_traffic
from app.main import app
from app.models import Alert, Base, DbSessionSnapshot, DiagnosticReport, JobRun, JobRunNodeBinding
from app.seed import seed_database
from app.services.evaluation import EvaluationService


def _session() -> Session:
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
    return db


def test_live_traffic_generates_customer_a_and_b_incidents() -> None:
    db = _session()
    try:
        summary = run_live_traffic(db, scenario_names=["all"], cycles=2, generate_diagnostics=True)
        db.commit()

        live_runs = list(db.scalars(select(JobRun).where(JobRun.run_key.like("LIVE-%"))))
        assert len(live_runs) == 4
        assert {run.customer.customer_key for run in live_runs} == {"CUST_A", "CUST_B"}
        assert summary["scenario_count"] == 4

        apj = db.scalar(select(JobRun).where(JobRun.run_key == "LIVE-CUST_A-CUSTOMER_A_APJ_UDQ"))
        assert apj is not None
        result = EvaluationService(db).evaluate_run(apj.id)
        assert result.runtime_state in {"warning", "critical"}
        assert "NEW_SQL_ID" in result.reason_codes
        assert "SQL_PLAN_CHANGED" in result.reason_codes
        assert "CUSTOMER_UDQ_RISK" in result.reason_codes

        session = db.scalar(select(DbSessionSnapshot).where(DbSessionSnapshot.run_id == apj.id))
        binding = db.scalar(select(JobRunNodeBinding).where(JobRunNodeBinding.run_id == apj.id))
        alert = db.scalar(select(Alert).where(Alert.run_id == apj.id))
        diagnostic = db.scalar(select(DiagnosticReport).where(DiagnosticReport.run_id == apj.id))

        assert session is not None
        assert session.sql_id == "dp9u1803k8k7f"
        assert session.instance_name == "DBRAC_inst1"
        assert binding is not None
        assert alert is not None
        assert alert.payload["topology"]["active_sql_id"] == "dp9u1803k8k7f"
        assert diagnostic is not None
        assert diagnostic.findings
    finally:
        db.close()
        app.dependency_overrides.pop(get_db, None)


def test_live_traffic_can_scope_to_customer_b_only() -> None:
    db = _session()
    try:
        summary = run_live_traffic(db, scenario_names=["customer-b"], cycles=1, generate_diagnostics=False)
        db.commit()

        live_runs = list(db.scalars(select(JobRun).where(JobRun.run_key.like("LIVE-%"))))
        assert len(live_runs) == 2
        assert {run.customer.customer_key for run in live_runs} == {"CUST_B"}
        assert all("CUST_B" in item["run_key"] for item in summary["cycles"][0]["runs"])
    finally:
        db.close()
