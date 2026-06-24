import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.mock import MockConnectorRegistry
from app.api.router import dashboard
from app.models import Alert, Base, Customer, DiagnosticReport, JobRun
from app.models.base import utcnow
from app.seed import seed_database, seed_scale_test_data
from app.services.baseline import BaselineService
from app.services.evaluation import EvaluationService
from app.services.executive_summary import CustomerExecutiveSummaryService
from app.services.query_guard import validate_read_only_template


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSession()
    seed_database(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()


def test_historical_baseline_computes_percentiles(db_session: Session) -> None:
    run = db_session.scalar(
        select(JobRun).where(JobRun.run_key == "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT")
    )
    assert run is not None

    baseline = BaselineService(db_session).compute_for_run(run)

    assert baseline.sample_count == 8
    assert baseline.p50_minutes == pytest.approx(349.5)
    assert baseline.p75_minutes == pytest.approx(356.0)
    assert baseline.p90_minutes == pytest.approx(359.9)
    assert baseline.last_successful_duration == pytest.approx(346.0)
    assert baseline.confidence_score >= 0.8


def test_apj_current_run_is_critical_with_sql_udq_and_volume_reasons(db_session: Session) -> None:
    run = db_session.scalar(
        select(JobRun).where(JobRun.run_key == "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT")
    )
    assert run is not None

    result = EvaluationService(db_session).evaluate_run(run.id, create_alert=True)

    assert result.runtime_state == "critical"
    assert result.severity == "critical"
    assert result.expected_source == "manual_goal"
    assert result.expected_minutes is not None
    assert result.expected_minutes > 350
    assert "ELAPSED_GT_CRITICAL_THRESHOLD" in result.reason_codes
    assert "CURRENT_VOLUME_GT_BASELINE" in result.reason_codes
    assert "DATA_WINDOW_MISMATCH" in result.reason_codes
    assert "NEW_UDQ_HASH" in result.reason_codes
    assert "NEW_SQL_ID" in result.reason_codes
    assert "SQL_PLAN_CHANGED" in result.reason_codes
    assert result.top_suspected_cause == "Customer-authored UDQ changed"


def test_learning_mode_when_history_is_insufficient(db_session: Session) -> None:
    run = db_session.scalar(
        select(JobRun).where(JobRun.run_key == "CUST_B-PROD-NEW-TERRITORY-FIRST-RUN")
    )
    assert run is not None

    result = EvaluationService(db_session).evaluate_run(run.id)

    assert result.runtime_state == "unknown_baseline"
    assert result.severity == "info"
    assert "NO_BASELINE" in result.reason_codes
    assert "FIRST_RUN_AT_SCALE" in result.reason_codes


def test_query_template_guard_accepts_parameterized_select() -> None:
    validate_read_only_template(
        "SELECT request_id, status_code FROM ess_request_history WHERE request_id = :request_id"
    )


def test_query_template_guard_rejects_write_sql() -> None:
    with pytest.raises(ValueError):
        validate_read_only_template("UPDATE ess_request_history SET status_code = :status")


def test_mock_oracle_connector_enforces_read_only_templates() -> None:
    with pytest.raises(ValueError):
        MockConnectorRegistry().oracle_db.execute_template(
            "DELETE FROM ess_request_history WHERE request_id = :request_id",
            {"request_id": "ESS-1"},
            timeout_seconds=30,
            row_limit=10,
        )


def test_scale_seed_creates_ten_customers_with_twenty_five_current_jobs_each(
    db_session: Session,
) -> None:
    counts = seed_scale_test_data(db_session, customer_count=10, jobs_per_customer=25)
    db_session.commit()

    assert counts["customers"] == 10
    assert counts["job_definitions"] == 250
    assert counts["current_runs"] == 250
    assert counts["alert_rules"] == 250
    assert counts["alerts"] == 200

    demo_customers = list(
        db_session.scalars(
            select(Customer).where(Customer.customer_key.like("DEMO_CUST_%")).order_by(Customer.customer_key)
        )
    )
    assert len(demo_customers) == 10

    for customer in demo_customers:
        current_run_count = db_session.scalar(
            select(func.count(JobRun.id)).where(
                JobRun.customer_id == customer.id,
                JobRun.status == "RUNNING",
                JobRun.run_key.like(f"{customer.customer_key}-PROD-%-CURRENT"),
            )
        )
        assert current_run_count == 25

    seeded_alert_count = db_session.scalar(
        select(func.count(Alert.id)).join(JobRun).where(JobRun.run_key.like("DEMO_CUST_%"))
    )
    assert seeded_alert_count == 200


def test_daily_digest_can_be_scoped_to_one_demo_customer(db_session: Session) -> None:
    seed_scale_test_data(db_session, customer_count=10, jobs_per_customer=25)
    db_session.commit()

    digest = EvaluationService(db_session).daily_digest(customer_key="DEMO_CUST_01")

    assert digest["headline"] == "25 active monitored runs"
    scoped_results = digest["critical"] + digest["watch"]
    assert scoped_results
    for item in scoped_results:
        run = db_session.get(JobRun, item["run_id"])
        assert run is not None
        assert run.customer.customer_key == "DEMO_CUST_01"


def test_customer_executive_summary_lists_critical_events_with_solutions(db_session: Session) -> None:
    summary = CustomerExecutiveSummaryService(db_session).generate("CUST_A")

    assert summary.customer_key == "CUST_A"
    assert summary.generation_mode == "local_ai_synthesis"
    assert summary.critical_event_count >= 1
    apj = next(item for item in summary.bullets if item.job_name == "APJ Direct CalculatePVT")
    assert apj.started_at is not None
    assert apj.proposed_solution
    assert "Elapsed" in " ".join(apj.supporting_analysis)
    assert "ELAPSED_GT_CRITICAL_THRESHOLD" in apj.reason_codes


def test_dashboard_tolerates_diagnostic_report_without_findings(db_session: Session) -> None:
    run = db_session.scalar(
        select(JobRun).where(JobRun.run_key == "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT")
    )
    assert run is not None
    now = utcnow()
    db_session.add(
        DiagnosticReport(
            run_id=run.id,
            customer_key=run.customer.customer_key,
            environment=run.environment.name,
            report_title="In-progress diagnostic without findings",
            diagnostic_type="slow_job",
            ess_request_id=run.ess_request_id,
            job_name=run.job_name,
            process_id=run.process_id,
            freshness_status="fresh",
            incident_state="active",
            overall_confidence="low",
            overall_status="warning",
            created_at=now,
            updated_at=now,
        )
    )
    db_session.commit()

    response = dashboard(db=db_session, customer_key="CUST_A", status="RUNNING", limit=100)

    apj = next(item for item in response.items if item.run_id == run.id)
    assert apj.latest_diagnostic_title == "In-progress diagnostic without findings"
    assert apj.latest_diagnostic_top_finding is None
