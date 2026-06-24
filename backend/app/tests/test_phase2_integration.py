import os

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.connectors.oracle import OracleConnectorConfigResolver, RealOracleDbConnector
from app.core.config import Settings
from app.models import Base, ConnectorConfig, Customer, JobRun, QueryExecutionLog, QueryTemplate, SqlObservation, VolumeSnapshot
from app.seed import seed_database
from app.services.evaluation import EvaluationService
from app.services.ingestion import QueryTemplateIngestionService
from app.services.query_catalog import QueryCatalogImporter
from app.services.query_execution import QueryTemplateExecutionService
from app.services.query_guard import QueryValidationError, validate_read_only_template
from app.services.pod_onboarding import CustomerPodOnboardingService
from app.services.scheduler import run_sync_once, scheduler_enabled


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


def test_sql_guard_allows_select_and_with() -> None:
    assert validate_read_only_template("SELECT * FROM mock_status WHERE request_id = :request_id").is_valid
    assert validate_read_only_template(
        "WITH runs AS (SELECT * FROM mock_status WHERE request_id = :request_id) SELECT * FROM runs WHERE request_id = :request_id"
    ).is_valid


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE jobs SET status = :status",
        "DELETE FROM jobs WHERE id = :id",
        "DROP TABLE jobs",
        "BEGIN dbms_lock.sleep(:seconds); END;",
        "DECLARE v NUMBER; BEGIN SELECT 1 INTO v FROM dual; END;",
        "SELECT * FROM jobs WHERE id = :id; SELECT * FROM secrets WHERE id = :id",
        "SELECT * FROM jobs WHERE id = ${id}",
        "SELECT * FROM jobs",
    ],
)
def test_sql_guard_rejects_unsafe_sql(sql: str) -> None:
    with pytest.raises(QueryValidationError):
        validate_read_only_template(sql)


def test_sql_guard_comments_do_not_bypass_validation_and_strings_are_safe() -> None:
    assert validate_read_only_template("SELECT 'delete from x' AS label FROM dual WHERE id = :id").is_valid
    with pytest.raises(QueryValidationError):
        validate_read_only_template("/* harmless */ DELETE FROM jobs WHERE id = :id")


def test_oracle_connector_config_resolution_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBRUN_CONNECTOR_MODE", "oracle")
    monkeypatch.setenv("JOBRUN_ALLOW_ORACLE_CONNECTOR", "true")
    monkeypatch.setenv("JOBRUN_ORACLE_DEMO_USER", "demo_user")
    monkeypatch.setenv("JOBRUN_ORACLE_DEMO_PASSWORD", "secret")
    monkeypatch.setenv("JOBRUN_ORACLE_DEMO_DSN", "dbhost.example/service")
    resolved = OracleConnectorConfigResolver(Settings()).resolve("demo")

    assert resolved.enabled is True
    assert resolved.has_required_credentials is True
    assert resolved.safe_summary()["password_configured"] is True
    assert "secret" not in str(resolved.safe_summary())


def test_oracle_health_missing_credentials_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBRUN_CONNECTOR_MODE", "oracle")
    monkeypatch.setenv("JOBRUN_ALLOW_ORACLE_CONNECTOR", "true")
    monkeypatch.delenv("JOBRUN_ORACLE_DEMO_PASSWORD", raising=False)
    health = RealOracleDbConnector(OracleConnectorConfigResolver(Settings()).resolve("demo")).health_check()

    assert health["status"] in {"missing_credentials", "disabled"}
    assert "PASSWORD" not in health["message"].upper()


def test_catalog_import_and_template_validation(db_session: Session) -> None:
    result = QueryCatalogImporter(db_session).import_bundled()
    db_session.commit()

    assert result["imported"] >= 8
    template = db_session.scalar(select(QueryTemplate).where(QueryTemplate.template_id == "icm_sql_observation_by_sql_id"))
    assert template is not None
    assert template.is_read_only_validated is True
    assert template.template_category == "sql_observation"


def test_customer_pod_onboarding_applies_stock_templates_and_initial_fetch(db_session: Session) -> None:
    summary = CustomerPodOnboardingService(db_session).onboard(
        customer_key="customer pod 3",
        display_name="Customer Pod 3",
        environment_name="PROD",
        region="APJ",
        apply_stock_templates=True,
        run_initial_fetch=True,
        notes="Synthetic onboarding test. No credentials.",
    )
    db_session.commit()

    customer = db_session.scalar(select(Customer).where(Customer.customer_key == "CUSTOMER_POD_3"))
    connector = db_session.scalar(select(ConnectorConfig).where(ConnectorConfig.config_key == "customer_pod_3_prod"))
    run = db_session.scalar(
        select(JobRun)
        .join(Customer, JobRun.customer_id == Customer.id)
        .where(Customer.customer_key == "CUSTOMER_POD_3")
    )
    log = db_session.scalar(
        select(QueryExecutionLog).where(QueryExecutionLog.initiated_by == "pod_onboarding").order_by(QueryExecutionLog.id.desc())
    )

    assert customer is not None
    assert customer.display_name == "Customer Pod 3"
    assert connector is not None
    assert connector.config["secrets_are_persisted"] is False
    assert connector.env_var_prefix == "JOBRUN_ORACLE_CUSTOMER_POD_3_PROD"
    assert "icm_active_long_running_jobs" in summary.stock_template_ids
    assert summary.initial_fetch is not None
    assert summary.initial_fetch["status"] == "success"
    assert run is not None
    assert run.run_key.startswith("CUSTOMER_POD_3-ESS")
    assert log is not None
    assert "PASSWORD" not in str(log.parameters).upper()


def test_query_template_execution_through_mock_creates_audit_log(db_session: Session) -> None:
    QueryCatalogImporter(db_session).import_bundled()
    template = db_session.scalar(select(QueryTemplate).where(QueryTemplate.template_id == "icm_active_long_running_jobs"))
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
    assert summary.log.raw_sql_hash
    assert summary.log.parameter_hash


def test_ingestion_maps_volume_and_sql_observations_idempotently(db_session: Session) -> None:
    QueryCatalogImporter(db_session).import_bundled()
    volume_template = db_session.scalar(select(QueryTemplate).where(QueryTemplate.template_id == "icm_volume_snapshot_by_scope"))
    sql_template = db_session.scalar(select(QueryTemplate).where(QueryTemplate.template_id == "icm_sql_observation_by_sql_id"))
    assert volume_template is not None and sql_template is not None

    service = QueryTemplateIngestionService(db_session)
    volume_summary = service.ingest(
        volume_template,
        customer_key="CUST_A",
        environment_name="PROD",
        parameters=volume_template.default_parameters,
        initiated_by="test",
    )
    sql_summary = service.ingest(
        sql_template,
        customer_key="CUST_A",
        environment_name="PROD",
        parameters=sql_template.default_parameters,
        initiated_by="test",
    )
    sql_summary_again = service.ingest(
        sql_template,
        customer_key="CUST_A",
        environment_name="PROD",
        parameters=sql_template.default_parameters,
        initiated_by="test",
    )
    db_session.commit()

    assert volume_summary.ingested_entity_counts["volume_snapshot"] == 1
    assert sql_summary.ingested_entity_counts["sql_observation"] == 1
    assert sql_summary_again.ingested_entity_counts["sql_observation"] == 1
    run = db_session.scalar(select(JobRun).where(JobRun.run_key == "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT"))
    assert run is not None
    assert run.source_type == "direct_db_query"
    sql_count = db_session.scalar(
        select(func.count(SqlObservation.id)).where(SqlObservation.run_id == run.id, SqlObservation.sql_id == "9x3m1apjnew")
    )
    volume_count = db_session.scalar(
        select(func.count(VolumeSnapshot.id)).where(VolumeSnapshot.run_id == run.id, VolumeSnapshot.metric_name == "transactions")
    )
    assert sql_count == 1
    assert volume_count == 1


def test_scheduler_disabled_and_run_once_executes_mock_templates(db_session: Session) -> None:
    assert scheduler_enabled(Settings(scheduler_enabled=False)) is False
    QueryCatalogImporter(db_session).import_bundled()
    result = run_sync_once(db_session, initiated_by="test")
    db_session.commit()

    assert result["templates_considered"] >= 8
    assert result["executions"]


def test_apj_critical_explanation_contains_phase2_reason_codes(db_session: Session) -> None:
    run = db_session.scalar(select(JobRun).where(JobRun.run_key == "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT"))
    assert run is not None
    result = EvaluationService(db_session).evaluate_run(run.id)

    assert result.runtime_state == "critical"
    assert "ELAPSED_GT_CRITICAL_THRESHOLD" in result.reason_codes
    assert "NEW_UDQ_HASH" in result.reason_codes
    assert "SQL_PLAN_CHANGED" in result.reason_codes
    assert "CUSTOMER_UDQ_RISK" in result.reason_codes
    assert "VOLUME_OR_DATA_WINDOW_MISMATCH" in result.reason_codes
    assert any("OR predicate" in action for action in result.recommended_actions)


def test_execution_log_sanitizes_secret_parameters(db_session: Session) -> None:
    template = QueryTemplate(
        template_id="secret_param_test",
        name="Secret parameter test",
        sql_text="SELECT * FROM mock_status WHERE request_id = :request_id",
        required_parameters={"request_id": {"type": "string"}},
        default_parameters={"request_id": "ESS-1", "password": "super-secret"},
    )
    db_session.add(template)
    db_session.flush()

    summary = QueryTemplateExecutionService(db_session).execute(
        template,
        customer_key="CUST_A",
        environment_name="PROD",
        parameters={"request_id": "ESS-1", "password": "super-secret"},
        initiated_by="test",
    )

    assert summary.log.parameters["password"] == "[redacted]"
    assert "super-secret" not in str(summary.log.sample_result)
    assert "super-secret" not in str(summary.log.validation_result)
