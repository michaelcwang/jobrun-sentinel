from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.connectors.mock import MockConnectorRegistry
from app.connectors.oracle import OracleConnectorConfigResolver, RealOracleDbConnector
from app.core.config import get_settings
from app.core.database import get_db
from app.models import (
    Alert,
    AlertEvent,
    AlertRule,
    ConnectorConfig,
    Customer,
    DbSessionSnapshot,
    DiagnosticEvidence,
    DiagnosticFinding,
    DiagnosticReport,
    Environment,
    ExpectationRecord,
    GlossaryTerm,
    ImportBatch,
    ImportedPlanRow,
    JobDefinition,
    JobRun,
    RuntimeNode,
    PlaybookNote,
    QueryExecutionLog,
    QueryTemplate,
)
from app.models.base import utcnow
from app.schemas import (
    AckRequest,
    AdHocMonitorCreate,
    AdHocMonitorRead,
    AlertCreate,
    AlertRead,
    ConnectorHealth,
    ConnectorTestRequest,
    ConnectorTestResponse,
    CustomerPodOnboardRequest,
    CustomerPodOnboardResponse,
    CustomerRead,
    CustomerExecutiveSummaryResponse,
    DashboardItem,
    DashboardResponse,
    DiagnosticEvidenceRead,
    DiagnosticRenderRead,
    DiagnosticReportRead,
    DiagnosticReportSummaryRead,
    DiagnosticRunRequest,
    DiagnosticRunResponse,
    EvaluationResult,
    ExpectationCreate,
    ExpectationRead,
    ExpectationUpdate,
    ImportPlanResponse,
    GlossaryTermRead,
    QueryCatalogImportRead,
    QueryExecuteRequest,
    QueryExecutionRead,
    QueryIngestResponse,
    QueryTemplateValidationRead,
    QueryTemplateCreate,
    QueryTemplateRead,
    ResolveRequest,
    RunCreate,
    RunDetail,
    RunListItem,
    RuntimeNodeRead,
    RuntimeTopologyMapRead,
    ServerHeatmapResponse,
    SyncRunResponse,
    TopologyCorrelationRead,
)
from app.services.baseline import BaselineService, duration_minutes
from app.services.diagnostics import DiagnosticAnalysisService
from app.services.evaluation import EvaluationService
from app.services.executive_summary import CustomerExecutiveSummaryService
from app.services.importer import ManualPlanImporter
from app.services.ingestion import QueryTemplateIngestionService
from app.services.pod_onboarding import CustomerPodOnboardingService
from app.services.query_catalog import QueryCatalogImporter
from app.services.query_execution import QueryTemplateExecutionService
from app.services.query_guard import QueryValidationError, validate_read_only_template
from app.services.scheduler import run_sync_once
from app.services.topology import RuntimeTopologyService

router = APIRouter(prefix="/api")


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    db: Session = Depends(get_db),
    customer_key: str | None = None,
    environment: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=400, ge=1, le=1000),
) -> DashboardResponse:
    stmt = (
        select(JobRun)
        .join(Customer, JobRun.customer_id == Customer.id)
        .join(Environment, JobRun.environment_id == Environment.id)
        .options(
            selectinload(JobRun.customer),
            selectinload(JobRun.environment),
            selectinload(JobRun.job_definition),
            selectinload(JobRun.alerts),
            selectinload(JobRun.sql_observations),
            selectinload(JobRun.volume_snapshots),
            selectinload(JobRun.diagnostic_reports).selectinload(DiagnosticReport.findings),
        )
        .order_by(JobRun.started_at.desc())
        .limit(limit)
    )
    if customer_key:
        stmt = stmt.where(Customer.customer_key == customer_key)
    if environment:
        stmt = stmt.where(Environment.name == environment)
    if status:
        stmt = stmt.where(JobRun.status == status)
    runs = list(db.scalars(stmt))
    service = EvaluationService(db)
    items: list[DashboardItem] = []
    for run in runs:
        evaluation = service.evaluate_run(run.id)
        if severity and evaluation.severity != severity:
            continue
        latest_alert = sorted(run.alerts, key=lambda item: item.created_at, reverse=True)[0] if run.alerts else None
        items.append(_dashboard_item(run, evaluation, latest_alert))

    counts: dict[str, int] = {}
    for item in items:
        counts[item.runtime_state] = counts.get(item.runtime_state, 0) + 1
    return DashboardResponse(generated_at=utcnow(), items=items, counts_by_state=counts)


@router.get("/customers/{customer_key}/executive-summary", response_model=CustomerExecutiveSummaryResponse)
def customer_executive_summary(
    customer_key: str,
    db: Session = Depends(get_db),
    environment: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
) -> CustomerExecutiveSummaryResponse:
    try:
        return CustomerExecutiveSummaryService(db).generate(
            customer_key,
            environment=environment,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/customer-pods", response_model=list[CustomerRead])
def list_customer_pods(db: Session = Depends(get_db)) -> list[Customer]:
    return list(db.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.customer_key.asc())))


@router.post("/customer-pods/onboard", response_model=CustomerPodOnboardResponse)
def onboard_customer_pod(
    payload: CustomerPodOnboardRequest,
    db: Session = Depends(get_db),
) -> CustomerPodOnboardResponse:
    try:
        summary = CustomerPodOnboardingService(db).onboard(
            customer_key=payload.customer_key,
            display_name=payload.display_name,
            environment_name=payload.environment,
            region=payload.region,
            lifecycle=payload.lifecycle,
            connector_type=payload.connector_type,
            config_key=payload.config_key,
            env_var_prefix=payload.env_var_prefix,
            apply_stock_templates=payload.apply_stock_templates,
            run_initial_fetch=payload.run_initial_fetch,
            minimum_elapsed_minutes=payload.minimum_elapsed_minutes,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(summary.customer)
    db.refresh(summary.environment)
    db.refresh(summary.connector_config)
    return CustomerPodOnboardResponse(
        customer=summary.customer,
        environment=summary.environment,
        connector_config_id=summary.connector_config.id,
        connector_config_key=summary.connector_config.config_key,
        env_var_prefix=summary.connector_config.env_var_prefix,
        stock_catalog=summary.stock_catalog,
        stock_template_ids=summary.stock_template_ids,
        validation_results=summary.validation_results,
        initial_fetch=summary.initial_fetch,
        next_steps=summary.next_steps,
    )


@router.get("/topology/current", response_model=RuntimeTopologyMapRead)
def current_topology(
    db: Session = Depends(get_db),
    customer_key: str | None = None,
    environment: str | None = None,
    selected_run_id: int | None = None,
) -> RuntimeTopologyMapRead:
    return RuntimeTopologyService(db).current_topology(
        customer_key=customer_key,
        environment=environment,
        selected_run_id=selected_run_id,
    )


@router.get("/topology/heatmap", response_model=ServerHeatmapResponse)
def topology_heatmap(
    db: Session = Depends(get_db),
    customer_key: str | None = None,
    environment: str | None = None,
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    bucket_minutes: int = Query(default=10, ge=5, le=60),
    node_type: str | None = None,
    job_type: str | None = None,
) -> ServerHeatmapResponse:
    return RuntimeTopologyService(db).heatmap(
        customer_key=customer_key,
        environment=environment,
        from_at=from_at,
        to_at=to_at,
        bucket_minutes=bucket_minutes,
        node_type=node_type,
        job_type=job_type,
    )


@router.get("/runs/{run_id}/topology", response_model=TopologyCorrelationRead)
def get_run_topology(run_id: int, db: Session = Depends(get_db)) -> TopologyCorrelationRead:
    try:
        return RuntimeTopologyService(db).correlate_run(run_id, persist=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/correlate-topology", response_model=TopologyCorrelationRead)
def correlate_run_topology(
    run_id: int,
    lookback_minutes: int = 120,
    db: Session = Depends(get_db),
) -> TopologyCorrelationRead:
    try:
        result = RuntimeTopologyService(db).correlate_run(run_id, lookback_minutes=lookback_minutes, persist=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return result


@router.get("/nodes", response_model=list[RuntimeNodeRead])
def list_runtime_nodes(
    db: Session = Depends(get_db),
    customer_key: str | None = None,
    environment: str | None = None,
) -> list[RuntimeNode]:
    return RuntimeTopologyService(db).list_nodes(customer_key=customer_key, environment=environment)


@router.get("/nodes/{node_id}", response_model=RuntimeNodeRead)
def get_runtime_node(node_id: int, db: Session = Depends(get_db)) -> RuntimeNode:
    node = RuntimeTopologyService(db).get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Runtime node not found")
    return node


@router.get("/nodes/{node_id}/metrics")
def get_runtime_node_metrics(node_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return RuntimeTopologyService(db).node_metrics(node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs", response_model=list[RunListItem])
def list_runs(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    customer_key: str | None = None,
    environment: str | None = None,
    status: str | None = None,
    limit: int = Query(default=500, ge=1, le=1500),
) -> list[RunListItem]:
    stmt = (
        select(JobRun)
        .join(Customer, JobRun.customer_id == Customer.id)
        .join(Environment, JobRun.environment_id == Environment.id)
        .options(selectinload(JobRun.customer), selectinload(JobRun.environment))
        .order_by(JobRun.started_at.desc())
        .limit(limit)
    )
    if customer_key:
        stmt = stmt.where(Customer.customer_key == customer_key)
    if environment:
        stmt = stmt.where(Environment.name == environment)
    if status:
        stmt = stmt.where(JobRun.status == status)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                JobRun.run_key.ilike(pattern),
                JobRun.job_name.ilike(pattern),
                JobRun.job_type.ilike(pattern),
                Customer.customer_key.ilike(pattern),
                JobRun.process_id.ilike(pattern),
                JobRun.ess_request_id.ilike(pattern),
            )
        )
    runs = list(db.scalars(stmt))
    service = EvaluationService(db)
    result: list[RunListItem] = []
    for run in runs:
        haystack = " ".join(
            [
                run.run_key,
                run.job_name,
                run.job_type,
                run.customer.customer_key,
                run.process_id or "",
                run.ess_request_id or "",
            ]
        ).lower()
        if q and q.lower() not in haystack:
            continue
        evaluation = service.evaluate_run(run.id)
        result.append(
            RunListItem(
                id=run.id,
                run_key=run.run_key,
                customer_key=run.customer.customer_key,
                customer_name=run.customer.display_name,
                environment=run.environment.name,
                job_type=run.job_type,
                job_name=run.job_name,
                region=run.region,
                workstream=run.workstream,
                status=run.status,
                process_id=run.process_id,
                ess_request_id=run.ess_request_id,
                started_at=run.started_at,
                ended_at=run.ended_at,
                elapsed_minutes=round(duration_minutes(run), 1),
                runtime_state=evaluation.runtime_state,
                severity=evaluation.severity,
                variance_pct=evaluation.variance_pct,
                reason_codes=evaluation.reason_codes,
            )
        )
    return result


@router.post("/runs", response_model=RunDetail)
def create_run(payload: RunCreate, db: Session = Depends(get_db)) -> RunDetail:
    customer = _get_or_create_customer(db, payload.customer_key)
    environment = _get_or_create_environment(db, customer, payload.environment)
    job_definition = _get_or_create_job_definition(
        db,
        customer,
        payload.job_family or "Ad Hoc",
        payload.job_type,
        payload.job_name,
        payload.region,
        payload.workstream,
        payload.api_operation,
    )
    run = JobRun(
        run_key=f"{payload.customer_key}-{payload.environment}-{uuid4().hex[:10]}",
        customer_id=customer.id,
        environment_id=environment.id,
        job_definition_id=job_definition.id,
        job_family=payload.job_family or job_definition.job_family,
        job_type=payload.job_type,
        job_name=payload.job_name,
        region=payload.region,
        workstream=payload.workstream,
        period=payload.period,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        status=payload.status,
        ess_request_id=payload.ess_request_id,
        job_id=payload.job_id,
        process_id=payload.process_id,
        api_operation=payload.api_operation,
        sql_id=payload.sql_id,
        plan_hash_value=payload.plan_hash_value,
        udq_name=payload.udq_name,
        udq_hash=payload.udq_hash,
        expected_minutes_at_start=_decimal(payload.expected_minutes_at_start),
        current_progress_pct=_decimal(payload.current_progress_pct),
        last_progress_at=utcnow() if payload.current_progress_pct is not None else None,
        notes=payload.notes,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return _run_detail(db, run.id)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int, db: Session = Depends(get_db)) -> RunDetail:
    return _run_detail(db, run_id)


@router.get("/expectations", response_model=list[ExpectationRead])
def list_expectations(
    db: Session = Depends(get_db), customer_key: str | None = None
) -> list[ExpectationRecord]:
    stmt = select(ExpectationRecord).order_by(ExpectationRecord.updated_at.desc())
    if customer_key:
        stmt = stmt.where(ExpectationRecord.customer_key == customer_key)
    return list(db.scalars(stmt))


@router.post("/expectations", response_model=ExpectationRead)
def create_expectation(payload: ExpectationCreate, db: Session = Depends(get_db)) -> ExpectationRecord:
    data = payload.model_dump()
    if data.get("active_from") is None:
        data["active_from"] = utcnow()
    expectation = ExpectationRecord(**data)
    db.add(expectation)
    db.commit()
    db.refresh(expectation)
    return expectation


@router.put("/expectations/{expectation_id}", response_model=ExpectationRead)
def update_expectation(
    expectation_id: int, payload: ExpectationUpdate, db: Session = Depends(get_db)
) -> ExpectationRecord:
    expectation = db.get(ExpectationRecord, expectation_id)
    if not expectation:
        raise HTTPException(status_code=404, detail="Expectation record not found")
    for key, value in payload.model_dump().items():
        if key == "active_from" and value is None:
            continue
        setattr(expectation, key, value)
    db.commit()
    db.refresh(expectation)
    return expectation


@router.post("/evaluate/{run_id}", response_model=EvaluationResult)
def evaluate_run(run_id: int, db: Session = Depends(get_db)) -> EvaluationResult:
    try:
        result = EvaluationService(db).evaluate_run(run_id, create_alert=True, send_mock_slack=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/evaluate-all", response_model=list[EvaluationResult])
def evaluate_all(db: Session = Depends(get_db)) -> list[EvaluationResult]:
    runs = list(db.scalars(select(JobRun).where(JobRun.status.in_(["RUNNING", "WATCH"]))))
    results = [
        EvaluationService(db).evaluate_run(run.id, create_alert=True, send_mock_slack=False)
        for run in runs
    ]
    db.commit()
    return results


@router.post("/diagnostics/run", response_model=DiagnosticRunResponse)
def run_diagnostic(payload: DiagnosticRunRequest, db: Session = Depends(get_db)) -> DiagnosticRunResponse:
    try:
        result = DiagnosticAnalysisService(db).generate_report(
            run_id=payload.run_id,
            ess_request_id=payload.ess_request_id,
            process_id=payload.process_id,
            ecid=payload.ecid,
            lookback_minutes=payload.lookback_minutes,
            collector_mode=payload.collector_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return DiagnosticRunResponse(
        diagnostic_report_id=result.report.id,
        finding_count=result.finding_count,
        summary={
            "report_title": result.report.report_title,
            "overall_confidence": result.report.overall_confidence,
            "incident_state": result.report.incident_state,
            "top_finding": _top_finding_summary(result.report),
        },
    )


@router.get("/diagnostics", response_model=list[DiagnosticReportSummaryRead])
def list_diagnostics(
    db: Session = Depends(get_db),
    customer_key: str | None = None,
    environment: str | None = None,
    ess_request_id: str | None = None,
    job: str | None = None,
    severity: str | None = None,
    confidence: str | None = None,
    finding_type: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[DiagnosticReportSummaryRead]:
    stmt = (
        select(DiagnosticReport)
        .options(selectinload(DiagnosticReport.findings))
        .order_by(DiagnosticReport.updated_at.desc())
        .limit(limit)
    )
    if customer_key:
        stmt = stmt.where(DiagnosticReport.customer_key == customer_key)
    if environment:
        stmt = stmt.where(DiagnosticReport.environment == environment)
    if ess_request_id:
        stmt = stmt.where(DiagnosticReport.ess_request_id == ess_request_id)
    if job:
        stmt = stmt.where(DiagnosticReport.job_name.ilike(f"%{job}%"))
    reports = list(db.scalars(stmt))
    if severity:
        reports = [report for report in reports if any(finding.severity == severity for finding in report.findings)]
    if confidence:
        reports = [report for report in reports if any(finding.confidence == confidence for finding in report.findings)]
    if finding_type:
        reports = [report for report in reports if any(finding.finding_type == finding_type for finding in report.findings)]
    return [_diagnostic_summary_read(report) for report in reports]


@router.get("/diagnostics/{diagnostic_id}", response_model=DiagnosticReportRead)
def get_diagnostic(diagnostic_id: int, db: Session = Depends(get_db)) -> DiagnosticReportRead:
    report = DiagnosticAnalysisService(db).get_report(diagnostic_id)
    if not report:
        raise HTTPException(status_code=404, detail="Diagnostic report not found")
    return _diagnostic_report_read(report)


@router.get("/diagnostics/{diagnostic_id}/render", response_model=DiagnosticRenderRead)
def render_diagnostic(diagnostic_id: int, db: Session = Depends(get_db)) -> DiagnosticRenderRead:
    service = DiagnosticAnalysisService(db)
    report = service.get_report(diagnostic_id)
    if not report:
        raise HTTPException(status_code=404, detail="Diagnostic report not found")
    structured = _diagnostic_report_read(report)
    return DiagnosticRenderRead(
        report_id=report.id,
        markdown=service.render_markdown(report),
        structured=structured,
    )


@router.post("/diagnostics/{diagnostic_id}/refresh", response_model=DiagnosticRunResponse)
def refresh_diagnostic(diagnostic_id: int, db: Session = Depends(get_db)) -> DiagnosticRunResponse:
    try:
        result = DiagnosticAnalysisService(db).refresh_report(diagnostic_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return DiagnosticRunResponse(
        diagnostic_report_id=result.report.id,
        finding_count=result.finding_count,
        summary={
            "report_title": result.report.report_title,
            "overall_confidence": result.report.overall_confidence,
            "incident_state": result.report.incident_state,
            "top_finding": _top_finding_summary(result.report),
        },
    )


@router.post("/diagnostics/{diagnostic_id}/promote-finding-to-alert", response_model=AlertRead)
def promote_diagnostic_to_alert(
    diagnostic_id: int,
    finding_id: int | None = None,
    db: Session = Depends(get_db),
) -> Alert:
    try:
        alert = DiagnosticAnalysisService(db).promote_finding_to_alert(diagnostic_id, finding_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/diagnostics/{diagnostic_id}/promote-finding-to-playbook-note")
def promote_diagnostic_to_playbook(
    diagnostic_id: int,
    finding_id: int | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        note = DiagnosticAnalysisService(db).promote_finding_to_playbook_note(diagnostic_id, finding_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return {"id": note.id, "title": note.title, "risk_level": note.risk_level, "owner": note.owner}


@router.get("/diagnostics/{diagnostic_id}/evidence", response_model=list[DiagnosticEvidenceRead])
def diagnostic_evidence(diagnostic_id: int, db: Session = Depends(get_db)) -> list[DiagnosticEvidence]:
    report = DiagnosticAnalysisService(db).get_report(diagnostic_id)
    if not report:
        raise HTTPException(status_code=404, detail="Diagnostic report not found")
    return [evidence for finding in report.findings for evidence in finding.evidence]


@router.get("/glossary", response_model=list[GlossaryTermRead])
def glossary(db: Session = Depends(get_db), domain: str | None = None) -> list[GlossaryTerm]:
    stmt = select(GlossaryTerm).where(GlossaryTerm.active.is_(True)).order_by(GlossaryTerm.term.asc())
    if domain:
        stmt = stmt.where(GlossaryTerm.domain == domain)
    return list(db.scalars(stmt))


@router.get("/alerts", response_model=list[AlertRead])
def list_alerts(
    db: Session = Depends(get_db),
    state: str | None = None,
    severity: str | None = None,
    customer_key: str | None = None,
    limit: int = Query(default=300, ge=1, le=1000),
) -> list[Alert]:
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if customer_key:
        stmt = stmt.join(JobRun, Alert.run_id == JobRun.id).join(Customer, JobRun.customer_id == Customer.id).where(Customer.customer_key == customer_key)
    if state:
        stmt = stmt.where(Alert.state == state)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    return list(db.scalars(stmt))


@router.post("/alerts", response_model=AlertRead)
def create_alert(payload: AlertCreate, db: Session = Depends(get_db)) -> Alert:
    result = EvaluationService(db).evaluate_run(
        payload.run_id, create_alert=True, send_mock_slack=payload.send_mock_slack
    )
    alert = db.scalar(select(Alert).where(Alert.run_id == payload.run_id).order_by(Alert.created_at.desc()))
    if not alert:
        raise HTTPException(status_code=500, detail=f"Evaluation did not create an alert: {result.runtime_state}")
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/alerts/{alert_id}/ack", response_model=AlertRead)
def ack_alert(alert_id: int, payload: AckRequest, db: Session = Depends(get_db)) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.state = "acknowledged"
    alert.acked_by = payload.actor
    alert.acked_at = utcnow()
    alert.ack_reason = payload.reason
    alert.events.append(
        AlertEvent(event_type="acknowledged", actor=payload.actor, message=payload.reason)
    )
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/alerts/{alert_id}/resolve", response_model=AlertRead)
def resolve_alert(alert_id: int, payload: ResolveRequest, db: Session = Depends(get_db)) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.state = "resolved"
    alert.resolved_by = payload.actor
    alert.resolved_at = utcnow()
    alert.resolution_note = payload.note
    alert.events.append(AlertEvent(event_type="resolved", actor=payload.actor, message=payload.note))
    db.commit()
    db.refresh(alert)
    return alert


@router.get("/ad-hoc-monitors", response_model=list[AdHocMonitorRead])
def list_ad_hoc(db: Session = Depends(get_db), customer_key: str | None = None) -> list[AlertRule]:
    stmt = select(AlertRule).where(AlertRule.rule_type == "ad_hoc").order_by(AlertRule.created_at.desc())
    if customer_key:
        stmt = stmt.join(Customer, AlertRule.customer_id == Customer.id).where(Customer.customer_key == customer_key)
    return list(db.scalars(stmt))


@router.post("/ad-hoc-monitors", response_model=AdHocMonitorRead)
def create_ad_hoc(payload: AdHocMonitorCreate, db: Session = Depends(get_db)) -> AlertRule:
    customer = _get_or_create_customer(db, payload.customer_key)
    environment = _get_or_create_environment(db, customer, payload.environment)
    job_definition = _get_or_create_job_definition(
        db,
        customer,
        "Ad Hoc",
        "Manual Monitor",
        payload.manual_job_name,
        None,
        None,
        payload.api_operation,
    )
    run = JobRun(
        run_key=f"adhoc-{payload.customer_key}-{uuid4().hex[:8]}",
        customer_id=customer.id,
        environment_id=environment.id,
        job_definition_id=job_definition.id,
        job_family="Ad Hoc",
        job_type="Manual Monitor",
        job_name=payload.manual_job_name,
        started_at=utcnow() - timedelta(minutes=30),
        status="RUNNING",
        ess_request_id=payload.ess_request_id,
        job_id=payload.job_id,
        process_id=payload.process_id,
        api_operation=payload.api_operation,
        sql_id=payload.sql_id,
        notes=payload.notes,
    )
    db.add(run)
    db.flush()
    if payload.expected_minutes is not None:
        db.add(
            ExpectationRecord(
                customer_key=customer.customer_key,
                environment=environment.name,
                job_family="Ad Hoc",
                job_type="Manual Monitor",
                job_name=payload.manual_job_name,
                api_operation=payload.api_operation,
                sql_id=payload.sql_id,
                baseline_method=payload.baseline_selection or "ad_hoc",
                expected_minutes=Decimal(str(payload.expected_minutes)),
                warning_threshold_pct=Decimal(str(payload.warning_threshold_pct)),
                critical_threshold_pct=Decimal(str(payload.critical_threshold_pct)),
                confidence_score=Decimal("0.50"),
                alert_channel=payload.destination,
                active_until=payload.expiration_time,
                notes=payload.notes,
            )
        )
    rule = AlertRule(
        name=f"Ad hoc: {payload.manual_job_name}",
        rule_type="ad_hoc",
        customer_id=customer.id,
        environment_id=environment.id,
        job_definition_id=job_definition.id,
        run_id=run.id,
        selector=payload.model_dump(mode="json"),
        expected_minutes=_decimal(payload.expected_minutes),
        warning_threshold_pct=Decimal(str(payload.warning_threshold_pct)),
        critical_threshold_pct=Decimal(str(payload.critical_threshold_pct)),
        expires_at=payload.expiration_time,
        destination=payload.destination,
        notes=payload.notes,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/query-templates", response_model=list[QueryTemplateRead])
def list_query_templates(
    db: Session = Depends(get_db),
    template_category: str | None = None,
    active: bool | None = None,
) -> list[QueryTemplate]:
    stmt = select(QueryTemplate).order_by(QueryTemplate.template_category.asc(), QueryTemplate.name.asc())
    if template_category:
        stmt = stmt.where(QueryTemplate.template_category == template_category)
    if active is not None:
        stmt = stmt.where(QueryTemplate.active.is_(active))
    return list(db.scalars(stmt))


@router.post("/query-templates", response_model=QueryTemplateRead)
def create_query_template(payload: QueryTemplateCreate, db: Session = Depends(get_db)) -> QueryTemplate:
    try:
        validate_read_only_template(payload.sql_text)
    except QueryValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    template = QueryTemplate(**payload.model_dump())
    template.is_read_only_validated = True
    template.last_validated_at = utcnow()
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.post("/query-templates/{template_id}/validate", response_model=QueryTemplateValidationRead)
def validate_query_template(template_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    template = db.get(QueryTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Query template not found")
    result = QueryTemplateExecutionService(db).validate_template(template)
    db.commit()
    return result


@router.post("/query-templates/{template_id}/execute", response_model=QueryExecutionRead)
def execute_query_template(
    template_id: int, payload: QueryExecuteRequest, db: Session = Depends(get_db)
) -> QueryExecutionLog:
    template = db.get(QueryTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Query template not found")
    summary = QueryTemplateExecutionService(db).execute(
        template,
        customer_key=payload.customer_key,
        environment_name=payload.environment,
        parameters=payload.parameters,
        connector_config_key=payload.connector_config_key,
        initiated_by=payload.initiated_by,
        executed_by=payload.executed_by,
        validate_only=payload.validate_only,
    )
    db.commit()
    db.refresh(summary.log)
    return summary.log


@router.post("/query-templates/{template_id}/ingest", response_model=QueryIngestResponse)
def ingest_query_template(
    template_id: int, payload: QueryExecuteRequest, db: Session = Depends(get_db)
) -> QueryIngestResponse:
    template = db.get(QueryTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Query template not found")
    if not payload.customer_key or not payload.environment:
        raise HTTPException(status_code=400, detail="customer_key and environment are required for ingestion.")
    summary = QueryTemplateIngestionService(db).ingest(
        template,
        customer_key=payload.customer_key,
        environment_name=payload.environment,
        parameters=payload.parameters,
        connector_config_key=payload.connector_config_key,
        initiated_by=payload.initiated_by,
        executed_by=payload.executed_by,
    )
    db.commit()
    return QueryIngestResponse(
        query_execution_id=summary.execution.log.query_execution_id,
        status=summary.execution.log.status,
        ingested_entity_counts=summary.ingested_entity_counts,
        affected_run_ids=summary.affected_run_ids,
        evaluations=summary.evaluations,
    )


@router.post("/query-catalog/import", response_model=QueryCatalogImportRead)
def import_query_catalog(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = QueryCatalogImporter(db).import_bundled()
    db.commit()
    return result


@router.post("/query-catalog/import-topology-templates", response_model=QueryCatalogImportRead)
def import_topology_query_templates(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = QueryCatalogImporter(db).import_bundled()
    db.commit()
    return result


@router.get("/query-executions", response_model=list[QueryExecutionRead])
def list_query_executions(
    db: Session = Depends(get_db),
    template_id: int | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[QueryExecutionLog]:
    stmt = select(QueryExecutionLog).order_by(QueryExecutionLog.started_at.desc()).limit(limit)
    if template_id:
        stmt = stmt.where(QueryExecutionLog.template_id == template_id)
    if status:
        stmt = stmt.where(QueryExecutionLog.status == status)
    return list(db.scalars(stmt))


@router.get("/query-executions/{execution_id}", response_model=QueryExecutionRead)
def get_query_execution(execution_id: int, db: Session = Depends(get_db)) -> QueryExecutionLog:
    log = db.get(QueryExecutionLog, execution_id)
    if not log:
        raise HTTPException(status_code=404, detail="Query execution log not found")
    return log


@router.post("/sync/run-once", response_model=SyncRunResponse)
def sync_run_once(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = run_sync_once(db, initiated_by="api")
    db.commit()
    return result


@router.get("/imports/plans", response_model=list[dict[str, Any]])
def list_imports(db: Session = Depends(get_db), customer_key: str | None = None) -> list[dict[str, Any]]:
    stmt = select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(50)
    if customer_key:
        stmt = (
            stmt.join(ImportedPlanRow, ImportedPlanRow.import_batch_id == ImportBatch.id)
            .join(JobRun, ImportedPlanRow.mapped_run_id == JobRun.id)
            .join(Customer, JobRun.customer_id == Customer.id)
            .where(Customer.customer_key == customer_key)
            .distinct()
        )
    batches = list(db.scalars(stmt))
    return [
        {
            "id": batch.id,
            "filename": batch.filename,
            "status": batch.status,
            "row_count": batch.row_count,
            "notes": batch.notes,
            "created_at": batch.created_at,
        }
        for batch in batches
    ]


@router.post("/imports/plans", response_model=ImportPlanResponse)
async def import_plan(
    file: UploadFile = File(...),
    customer_key: str = "CUST_A",
    environment: str = "PROD",
    db: Session = Depends(get_db),
) -> ImportPlanResponse:
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSV import is supported in the MVP. XLSX is a TODO.")
    content = await file.read()
    result = ManualPlanImporter(db).import_csv(
        file.filename, content, customer_key=customer_key, environment_name=environment
    )
    db.commit()
    return ImportPlanResponse(
        batch_id=result.batch.id,
        filename=result.batch.filename,
        row_count=result.batch.row_count,
        created_runs=result.created_runs,
        created_expectations=result.created_expectations,
        notes=result.batch.notes or "",
    )


@router.get("/sources/health", response_model=list[ConnectorHealth])
def source_health(db: Session = Depends(get_db)) -> list[ConnectorHealth]:
    settings = get_settings()
    configs = list(db.scalars(select(ConnectorConfig).order_by(ConnectorConfig.connector_type.asc())))
    health_items: list[ConnectorHealth] = []
    for config in configs:
        status = config.status
        message = config.health_message
        safe_config = {
            **(config.config or {}),
            "access_mode": settings.source_access_mode,
            "destructive_operations_allowed": settings.destructive_source_operations_allowed,
        }
        if config.connector_type == "OracleDbConnector":
            oracle_settings = OracleConnectorConfigResolver(settings).resolve(
                config.config_key or settings.oracle_default_config_key,
                config.env_var_prefix,
            )
            oracle_health = RealOracleDbConnector(oracle_settings).health_check()
            status = oracle_health["status"]
            message = oracle_health["message"]
            safe_config = {**safe_config, **oracle_health["config"]}
        health_items.append(
            ConnectorHealth(
            id=config.id,
            connector_type=config.connector_type,
            config_key=config.config_key,
            name=config.name,
            display_name=config.display_name,
            status=status,
            enabled=config.enabled,
            access_mode=settings.source_access_mode,
            destructive_operations_allowed=settings.destructive_source_operations_allowed,
            guardrails=_connector_guardrails(config.connector_type),
            last_checked_at=config.last_checked_at,
            last_successful_sync_at=config.last_successful_sync_at,
            last_failed_sync_at=config.last_failed_sync_at,
            scheduler_heartbeat_at=config.scheduler_heartbeat_at,
            health_message=message,
            config=safe_config,
        )
        )
    return health_items


@router.post("/connectors/test", response_model=ConnectorTestResponse)
def test_connector(payload: ConnectorTestRequest) -> ConnectorTestResponse:
    registry = MockConnectorRegistry()
    if payload.connector_type == "OracleDbConnector":
        settings = get_settings()
        if settings.connector_mode == "oracle" and settings.allow_oracle_connector:
            oracle_settings = OracleConnectorConfigResolver(settings).resolve(settings.oracle_default_config_key)
            health = RealOracleDbConnector(oracle_settings).health_check()
            return ConnectorTestResponse(
                connector_type=payload.connector_type,
                status=health["status"],
                message=health["message"],
                sample=health["config"],
            )
        sample = registry.oracle_db.execute_template(
            "SELECT * FROM mock_status WHERE request_id = :request_id",
            {"request_id": "ESS-APJ-90045"},
            timeout_seconds=30,
            row_limit=10,
        )[0]
    elif payload.connector_type == "EssApiConnector":
        sample = registry.ess_api.fetch_request_status(request_id="ESS-APJ-90045")
    elif payload.connector_type == "SlackConnector":
        sample = registry.slack.send_alert({"text": "JobRun Sentinel connector test"})
    else:
        sample = {"mocked": True, "customer_key": payload.customer_key, "environment": payload.environment}
    return ConnectorTestResponse(
        connector_type=payload.connector_type,
        status="ok",
        message="Mock connector is healthy. Source connectors are read-only and non-destructive by contract.",
        access_mode="read_only",
        destructive_operations_allowed=False,
        sample=sample,
    )


@router.get("/playbook")
def playbook(db: Session = Depends(get_db), customer_key: str | None = None) -> dict[str, Any]:
    service = EvaluationService(db)
    run_stmt = (
        select(JobRun)
        .join(Customer, JobRun.customer_id == Customer.id)
        .where(JobRun.status == "RUNNING")
        .order_by(JobRun.started_at.asc())
    )
    note_stmt = select(PlaybookNote).where(PlaybookNote.note_date == date.today())
    if customer_key:
        run_stmt = run_stmt.where(Customer.customer_key == customer_key)
        note_stmt = note_stmt.join(Customer, PlaybookNote.customer_id == Customer.id).where(Customer.customer_key == customer_key)
    active_runs = list(db.scalars(run_stmt))
    notes = list(db.scalars(note_stmt))
    evaluated = [service.evaluate_run(run.id).model_dump(mode="json") for run in active_runs]
    digest = service.daily_digest(customer_key=customer_key)
    return {
        "date": date.today().isoformat(),
        "planned_jobs": len(active_runs),
        "risk_runs": evaluated,
        "notes": [
            {
                "id": note.id,
                "title": note.title,
                "body": note.body,
                "risk_level": note.risk_level,
                "owner": note.owner,
            }
            for note in notes
        ],
        "daily_digest": digest,
    }


def _run_detail(db: Session, run_id: int) -> RunDetail:
    run = db.get(JobRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    evaluation = EvaluationService(db).evaluate_run(run.id)
    timeline = [
        {"ts": run.started_at.isoformat(), "label": "Started", "state": "start"},
    ]
    if run.last_progress_at:
        timeline.append(
            {
                "ts": run.last_progress_at.isoformat(),
                "label": f"Progress {run.current_progress_pct or 0}%",
                "state": "progress",
            }
        )
    if run.ended_at:
        timeline.append({"ts": run.ended_at.isoformat(), "label": run.status, "state": "end"})
    latest_diagnostic = _latest_diagnostic_for_run(db, run.id)
    return RunDetail(
        id=run.id,
        run_key=run.run_key,
        customer=run.customer,
        environment=run.environment,
        job_definition=run.job_definition,
        job_family=run.job_family,
        job_type=run.job_type,
        job_name=run.job_name,
        region=run.region,
        workstream=run.workstream,
        period=run.period,
        data_window_start=run.data_window_start,
        data_window_end=run.data_window_end,
        started_at=run.started_at,
        ended_at=run.ended_at,
        status=run.status,
        ess_request_id=run.ess_request_id,
        job_id=run.job_id,
        process_id=run.process_id,
        api_operation=run.api_operation,
        sql_id=run.sql_id,
        plan_hash_value=run.plan_hash_value,
        udq_name=run.udq_name,
        udq_hash=run.udq_hash,
        current_progress_pct=run.current_progress_pct,
        last_progress_at=run.last_progress_at,
        source_type=run.source_type,
        source_connector=run.source_connector,
        source_template_id=run.source_template_id,
        source_query_execution_id=run.source_query_execution_id,
        ingested_at=run.ingested_at,
        provenance=(run.business_scope or {}).get("provenance", {}),
        notes=run.notes,
        evaluation=evaluation,
        volumes=run.volume_snapshots,
        sql_observations=run.sql_observations,
        alerts=sorted(run.alerts, key=lambda item: item.created_at, reverse=True),
        timeline=timeline,
        latest_diagnostic=_diagnostic_summary_dict(latest_diagnostic) if latest_diagnostic else None,
    )


def _dashboard_item(run: JobRun, evaluation: EvaluationResult, latest_alert: Alert | None) -> DashboardItem:
    latest_diagnostic = _latest_diagnostic_for_run_object(run)
    # Diagnostics can be created before findings are attached. Dashboard cards
    # should still render and link to the report instead of failing on back-nav refreshes.
    latest_top_finding = _top_finding_summary(latest_diagnostic)
    return DashboardItem(
        run_id=run.id,
        run_key=run.run_key,
        customer=run.customer.display_name,
        customer_key=run.customer.customer_key,
        environment=run.environment.name,
        job_family=run.job_family,
        job_type=run.job_type,
        job_name=run.job_name,
        region=run.region,
        workstream=run.workstream,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
        elapsed_minutes=evaluation.elapsed_minutes,
        expected_minutes=evaluation.expected_minutes,
        variance_pct=evaluation.variance_pct,
        eta_at=evaluation.eta_at,
        confidence_score=evaluation.confidence_score,
        runtime_state=evaluation.runtime_state,
        latest_alert_state=latest_alert.state if latest_alert else None,
        latest_alert_severity=latest_alert.severity if latest_alert else None,
        cause_tags=evaluation.cause_tags,
        reason_codes=evaluation.reason_codes,
        top_suspected_cause=evaluation.top_suspected_cause,
        is_ad_hoc=bool(run.job_family == "Ad Hoc"),
        source_type=run.source_type,
        source_connector=run.source_connector,
        last_refreshed_at=run.ingested_at or run.updated_at,
        latest_diagnostic_id=latest_diagnostic.id if latest_diagnostic else None,
        latest_diagnostic_title=latest_diagnostic.report_title if latest_diagnostic else None,
        latest_diagnostic_top_finding=latest_top_finding.get("title") if latest_top_finding else None,
    )


def _latest_diagnostic_for_run(db: Session, run_id: int) -> DiagnosticReport | None:
    return db.scalar(
        select(DiagnosticReport)
        .where(DiagnosticReport.run_id == run_id)
        .options(selectinload(DiagnosticReport.findings))
        .order_by(DiagnosticReport.updated_at.desc(), DiagnosticReport.created_at.desc())
    )


def _latest_diagnostic_for_run_object(run: JobRun) -> DiagnosticReport | None:
    reports = sorted(run.diagnostic_reports, key=lambda item: (item.updated_at, item.created_at), reverse=True)
    return reports[0] if reports else None


def _diagnostic_summary_read(report: DiagnosticReport) -> DiagnosticReportSummaryRead:
    data = DiagnosticReportSummaryRead.model_validate(report).model_dump()
    data["top_finding"] = _top_finding_summary(report)
    return DiagnosticReportSummaryRead(**data)


def _diagnostic_report_read(report: DiagnosticReport) -> DiagnosticReportRead:
    data = DiagnosticReportRead.model_validate(report).model_dump()
    data["top_finding"] = _top_finding_summary(report)
    return DiagnosticReportRead(**data)


def _diagnostic_summary_dict(report: DiagnosticReport) -> dict[str, Any]:
    return _diagnostic_summary_read(report).model_dump(mode="json")


def _top_finding_summary(report: DiagnosticReport | None) -> dict[str, Any] | None:
    if not report or not report.findings:
        return None
    finding = sorted(report.findings, key=lambda item: (item.severity != "critical", item.finding_number))[0]
    return {
        "id": finding.id,
        "finding_key": finding.finding_key,
        "finding_type": finding.finding_type,
        "title": finding.title,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "actionability": finding.actionability,
        "owner_team": finding.owner_team,
    }


def _get_or_create_customer(db: Session, customer_key: str) -> Customer:
    customer = db.scalar(select(Customer).where(Customer.customer_key == customer_key))
    if customer:
        return customer
    customer = Customer(customer_key=customer_key, display_name=customer_key.replace("_", " "))
    db.add(customer)
    db.flush()
    return customer


def _get_or_create_environment(db: Session, customer: Customer, name: str) -> Environment:
    environment = db.scalar(
        select(Environment).where(Environment.customer_id == customer.id, Environment.name == name)
    )
    if environment:
        return environment
    environment = Environment(customer_id=customer.id, name=name, region="global", lifecycle="prod")
    db.add(environment)
    db.flush()
    return environment


def _get_or_create_job_definition(
    db: Session,
    customer: Customer,
    job_family: str,
    job_type: str,
    job_name: str,
    region: str | None,
    workstream: str | None,
    api_operation: str | None,
) -> JobDefinition:
    job = db.scalar(
        select(JobDefinition).where(
            JobDefinition.customer_id == customer.id,
            JobDefinition.job_family == job_family,
            JobDefinition.job_type == job_type,
            JobDefinition.job_name == job_name,
        )
    )
    if job:
        return job
    job = JobDefinition(
        customer_id=customer.id,
        job_family=job_family,
        job_type=job_type,
        job_name=job_name,
        default_region=region,
        default_workstream=workstream,
        api_operation=api_operation,
    )
    db.add(job)
    db.flush()
    return job


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _connector_guardrails(connector_type: str) -> list[str]:
    common = [
        "external pod access is read-only",
        "no customer-side writes or DDL",
        "secrets must come from environment variables or a secrets manager",
        "audit every external inspection call",
    ]
    if connector_type == "OracleDbConnector":
        return common + [
            "SELECT/WITH templates only",
            "named parameters required",
            "query timeout and row limit required",
            "connect with read-only database grants",
        ]
    if connector_type in {"EssApiConnector", "OciTelemetryConnector", "JobHistoryConnector"}:
        return common + ["status and telemetry reads only"]
    if connector_type in {"SqlObservationConnector", "VolumeSnapshotConnector"}:
        return common + ["metadata and metric reads only", "raw SQL text storage disabled by default"]
    if connector_type == "SlackConnector":
        return [
            "does not mutate customer pods",
            "no PII or raw SQL in payloads",
            "mocked locally unless production notification credentials are configured",
        ]
    return common
