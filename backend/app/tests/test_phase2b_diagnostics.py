import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker, selectinload
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base, DiagnosticFinding, DiagnosticReport, JobRun, QueryExecutionLog
from app.seed import seed_database
from app.services.diagnostics import (
    EXAMPLE_ESS_REQUEST_ID,
    DiagnosticAnalysisService,
    contains_destructive_command,
)
from app.services.evaluation import EvaluationService


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


def _seed_report(db: Session) -> DiagnosticReport:
    report = db.scalar(
        select(DiagnosticReport)
        .where(DiagnosticReport.ess_request_id == EXAMPLE_ESS_REQUEST_ID)
        .options(
            selectinload(DiagnosticReport.findings).selectinload(DiagnosticFinding.evidence),
            selectinload(DiagnosticReport.findings).selectinload(DiagnosticFinding.runbook_steps),
            selectinload(DiagnosticReport.ruled_out_alternatives),
            selectinload(DiagnosticReport.data_quality_checks),
        )
    )
    assert report is not None
    return report


def test_seeded_diagnostic_report_has_two_high_confidence_findings(db_session: Session) -> None:
    report = _seed_report(db_session)

    assert report.report_title.startswith("ECID Slow Job Diagnostic")
    assert report.ecid == "0598914d69b56a3ce534410a606b4a9b"
    assert report.incident_state == "active"
    assert len(report.findings) == 2
    assert {finding.confidence for finding in report.findings} == {"high"}


def test_plan_regression_finding_contains_required_evidence_and_metrics(db_session: Session) -> None:
    report = _seed_report(db_session)
    finding = next(item for item in report.findings if item.finding_type == "PLAN_REGRESSION")

    assert finding.finding_key == "dp9u1803k8k7f"
    assert finding.source_plan_hash_value == "51543091"
    assert finding.historical_plan_hash_value == "3256752871"
    assert finding.metrics["current_index"] == "HZ_REF_ENTITIES_X26"
    assert finding.metrics["historical_index"] == "HZ_REF_ENTITIES_N1"
    assert finding.metrics["cost_ratio"] == 27.8
    assert finding.metrics["executions"] == 12150000
    assert finding.metrics["elapsed_sec"] == 192901
    assert finding.metrics["cpu_sec"] == 191153
    assert "DBA sign-off" in finding.approval_gate
    assert "Restore prior table stats" in finding.rollback_plan
    assert {evidence.evidence_type for evidence in finding.evidence} >= {
        "GV_SESSION",
        "GV_SQL",
        "DBA_HIST_SQL_PLAN",
    }


def test_generated_formula_cache_defect_confirmed_vs_potential_exposure(db_session: Session) -> None:
    report = _seed_report(db_session)
    finding = next(item for item in report.findings if item.finding_type == "CODE_GENERATION_DEFECT")

    assert finding.package_name == "ADXX_CN_FORMULA_111141_PKG"
    assert finding.value_set_code == "MTQ_ICM_OBA_BY_BADGE_VS"
    assert finding.confirmed_count == 2
    assert finding.scope_count == 1157
    assert finding.unverified_count == 1155
    assert "Only 2 packages are confirmed" in finding.metrics["exposure_wording"]
    assert "Do not hand-edit" in finding.recommended_action
    assert finding.metrics["redundant_call_pct"] == 58.5


def test_confidence_scoring_and_data_quality_gate(db_session: Session) -> None:
    service = DiagnosticAnalysisService(db_session)
    high, high_reason = service.score_confidence(["GV_SQL", "DBA_HIST_SQL_PLAN"], [])
    low, low_reason = service.score_confidence([], ["GV_SQL"])
    report = _seed_report(db_session)

    assert high == "high"
    assert "two independent evidence sources" in high_reason
    assert low == "low"
    assert "incomplete" in low_reason
    statuses = {check.check_key: check.status for check in report.data_quality_checks}
    assert statuses["high_confidence_supported"] == "passed"
    assert statuses["confirmed_vs_potential_exposure"] == "passed"
    assert statuses["remediation_non_executable"] == "passed"
    assert "failed" not in statuses.values()


def test_ruled_out_alternatives_and_secondary_no_action_items(db_session: Session) -> None:
    report = _seed_report(db_session)
    alternatives = {item.alternative_type: item for item in report.ruled_out_alternatives}

    assert alternatives["RAC_INTERCONNECT"].status == "ruled_out"
    assert "scattered across unrelated SQL_IDs" in alternatives["RAC_INTERCONNECT"].reason
    assert alternatives["ESS_QUEUE"].status == "ruled_out"
    assert alternatives["SECONDARY_SQL"].status == "secondary"
    assert "gwxtms3bcc9hs" in alternatives["SECONDARY_SQL"].reason


def test_remediation_commands_are_text_only_and_raw_sql_is_disabled(db_session: Session) -> None:
    report = _seed_report(db_session)
    destructive_steps = [
        step
        for finding in report.findings
        for step in finding.runbook_steps
        if contains_destructive_command(step.command_text or "")
    ]
    logs = list(db_session.scalars(select(QueryExecutionLog).where(QueryExecutionLog.initiated_by == "diagnostic")))

    assert destructive_steps
    assert all(step.executable_by_app is False for step in destructive_steps)
    assert all(step.requires_approval is True for step in destructive_steps)
    assert logs
    assert all(log.raw_sql_storage_enabled is False for log in logs)
    assert "raw_query_text" not in str([e.raw_sample for f in report.findings for e in f.evidence]).lower()


def test_generating_diagnostic_from_seeded_run_is_idempotent(db_session: Session) -> None:
    run = db_session.scalar(select(JobRun).where(JobRun.ess_request_id == EXAMPLE_ESS_REQUEST_ID))
    assert run is not None
    service = DiagnosticAnalysisService(db_session)

    first = service.generate_report(run_id=run.id)
    second = service.generate_report(run_id=run.id)
    db_session.commit()

    assert first.report.id == second.report.id
    assert second.finding_count == 2
    assert len(second.report.findings) == 2


def test_alert_payload_includes_top_diagnostic_finding(db_session: Session) -> None:
    run = db_session.scalar(select(JobRun).where(JobRun.ess_request_id == EXAMPLE_ESS_REQUEST_ID))
    assert run is not None
    result = EvaluationService(db_session).evaluate_run(run.id)

    assert result.slack_payload is not None
    diagnostic = result.slack_payload["diagnostic"]
    assert diagnostic["top_finding"] == "Plan regression on HZ_REF_ENTITIES lookup"
    assert diagnostic["confidence"] == "high"
    assert diagnostic["actionability"] == "READY_TO_ACT_WITH_SIGNOFF"
    assert diagnostic["source_sql_id"] == "dp9u1803k8k7f"


def test_diagnostics_endpoints_return_structured_report(client: TestClient) -> None:
    reports_response = client.get("/api/diagnostics")
    assert reports_response.status_code == 200
    reports = reports_response.json()
    report_id = reports[0]["id"]

    detail_response = client.get(f"/api/diagnostics/{report_id}")
    render_response = client.get(f"/api/diagnostics/{report_id}/render")
    evidence_response = client.get(f"/api/diagnostics/{report_id}/evidence")
    glossary_response = client.get("/api/glossary")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["ess_request_id"] == EXAMPLE_ESS_REQUEST_ID
    assert len(detail["findings"]) == 2
    assert detail["top_finding"]["finding_type"] == "PLAN_REGRESSION"
    assert render_response.status_code == 200
    assert "If you do only one thing today" in render_response.json()["markdown"]
    assert evidence_response.status_code == 200
    assert len(evidence_response.json()) >= 6
    assert glossary_response.status_code == 200
    assert any(item["term"] == "ECID" for item in glossary_response.json())


def test_post_diagnostic_run_endpoint_refreshes_report(client: TestClient, db_session: Session) -> None:
    run = db_session.scalar(select(JobRun).where(JobRun.ess_request_id == EXAMPLE_ESS_REQUEST_ID))
    assert run is not None
    response = client.post("/api/diagnostics/run", json={"run_id": run.id, "lookback_minutes": 720})

    assert response.status_code == 200
    payload = response.json()
    assert payload["finding_count"] == 2
    assert payload["summary"]["top_finding"]["finding_key"] == "dp9u1803k8k7f"
