from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RuntimeState = Literal["normal", "watch", "warning", "critical", "complete", "unknown_baseline"]
AlertSeverity = Literal["info", "watch", "warning", "critical"]


class CustomerRead(BaseModel):
    id: int
    customer_key: str
    display_name: str
    tier: str | None = None
    active: bool = True

    model_config = ConfigDict(from_attributes=True)


class EnvironmentRead(BaseModel):
    id: int
    name: str
    region: str | None = None
    lifecycle: str

    model_config = ConfigDict(from_attributes=True)


class JobDefinitionRead(BaseModel):
    id: int
    job_family: str
    job_type: str
    job_name: str
    default_region: str | None = None
    default_workstream: str | None = None
    ess_request_name: str | None = None
    process_name: str | None = None
    api_operation: str | None = None

    model_config = ConfigDict(from_attributes=True)


class EvaluationResult(BaseModel):
    run_id: int
    runtime_state: RuntimeState
    severity: AlertSeverity
    expected_minutes: float | None
    expected_source: str | None
    elapsed_minutes: float
    variance_pct: float | None
    eta_at: datetime | None = None
    confidence_score: float
    reason_codes: list[str] = Field(default_factory=list)
    cause_tags: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    top_suspected_cause: str | None = None
    historical_comparison: dict[str, Any] = Field(default_factory=dict)
    slack_payload: dict[str, Any] | None = None


class DashboardItem(BaseModel):
    run_id: int
    run_key: str
    customer: str
    customer_key: str
    environment: str
    job_family: str | None = None
    job_type: str
    job_name: str
    region: str | None = None
    workstream: str | None = None
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    elapsed_minutes: float
    expected_minutes: float | None = None
    variance_pct: float | None = None
    eta_at: datetime | None = None
    confidence_score: float
    runtime_state: RuntimeState
    latest_alert_state: str | None = None
    latest_alert_severity: str | None = None
    cause_tags: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    top_suspected_cause: str | None = None
    is_ad_hoc: bool = False
    source_type: str | None = None
    source_connector: str | None = None
    last_refreshed_at: datetime | None = None
    latest_diagnostic_id: int | None = None
    latest_diagnostic_title: str | None = None
    latest_diagnostic_top_finding: str | None = None


class DashboardResponse(BaseModel):
    generated_at: datetime
    items: list[DashboardItem]
    counts_by_state: dict[str, int]


class CustomerCriticalEventSummary(BaseModel):
    run_id: int
    job_name: str
    job_type: str
    environment: str
    region: str | None = None
    workstream: str | None = None
    status: str
    started_at: datetime
    elapsed_minutes: float
    expected_minutes: float | None = None
    variance_pct: float | None = None
    top_suspected_cause: str | None = None
    proposed_solution: str
    supporting_analysis: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    diagnostic_id: int | None = None
    diagnostic_title: str | None = None
    diagnostic_top_finding: str | None = None
    topology_summary: str | None = None


class CustomerExecutiveSummaryResponse(BaseModel):
    generated_at: datetime
    customer_key: str
    customer_name: str
    environment: str | None = None
    generation_mode: str = "local_ai_synthesis"
    headline: str
    data_points_used: list[str] = Field(default_factory=list)
    critical_event_count: int
    bullets: list[CustomerCriticalEventSummary] = Field(default_factory=list)


class RuntimeNodeRead(BaseModel):
    id: int
    customer_key: str
    environment: str
    node_type: str
    node_key: str
    display_name: str
    host_name: str | None = None
    instance_name: str | None = None
    server_name: str | None = None
    cluster_name: str | None = None
    service_name: str | None = None
    availability_domain: str | None = None
    region: str | None = None
    tags: dict[str, Any] | None = None
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RuntimeNodeMetricSampleRead(BaseModel):
    id: int
    node_id: int
    sampled_at: datetime
    metric_name: str
    metric_value: float
    unit: str | None = None
    source: str
    source_ref: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobRunNodeBindingRead(BaseModel):
    id: int
    run_id: int
    node_id: int
    binding_type: str
    confidence: str
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    evidence_summary: str | None = None
    evidence_json: dict[str, Any] | None = None
    query_execution_id: int | None = None
    node: RuntimeNodeRead | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DbSessionSnapshotRead(BaseModel):
    id: int
    run_id: int | None = None
    sampled_at: datetime
    inst_id: int | None = None
    instance_name: str | None = None
    db_host_name: str | None = None
    sid: int | None = None
    serial_number: str | None = None
    session_status: str | None = None
    username: str | None = None
    service_name: str | None = None
    module: str | None = None
    action: str | None = None
    client_identifier: str | None = None
    ecid: str | None = None
    machine: str | None = None
    program: str | None = None
    process: str | None = None
    sql_id: str | None = None
    sql_child_number: int | None = None
    sql_exec_start: datetime | None = None
    last_call_et_seconds: int | None = None
    event: str | None = None
    wait_class: str | None = None
    state: str | None = None
    blocking_instance: int | None = None
    blocking_session: int | None = None
    plan_hash_value: str | None = None
    row_wait_obj: str | None = None
    query_execution_id: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RuntimeTopologyNodeRead(BaseModel):
    node_key: str
    display_name: str
    node_type: str
    tier: str
    severity: str = "unknown"
    heat_score: float = 0
    confidence: str = "unknown"
    active_run_count: int = 0
    active_session_count: int = 0
    top_sql_id: str | None = None
    top_wait_class: str | None = None
    top_event: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    last_refreshed_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RuntimeTopologyEdgeRead(BaseModel):
    from_node_key: str
    to_node_key: str
    label: str
    confidence: str = "unknown"
    run_id: int | None = None
    evidence: str | None = None


class RuntimeTopologyMapRead(BaseModel):
    generated_at: datetime
    selected_run_id: int | None = None
    nodes: list[RuntimeTopologyNodeRead] = Field(default_factory=list)
    edges: list[RuntimeTopologyEdgeRead] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)


class ServerHeatmapCellRead(BaseModel):
    node_id: int
    bucket_start: datetime
    bucket_end: datetime
    heat_score: float
    severity: str
    contributing_run_ids: list[int] = Field(default_factory=list)
    contributing_sql_ids: list[str] = Field(default_factory=list)
    top_wait_class: str | None = None
    top_event: str | None = None
    metric_breakdown: dict[str, Any] = Field(default_factory=dict)
    explanation: str


class ServerHeatmapRowRead(BaseModel):
    node: RuntimeNodeRead
    tier: str
    cells: list[ServerHeatmapCellRead] = Field(default_factory=list)


class ServerHeatmapResponse(BaseModel):
    generated_at: datetime
    bucket_minutes: int
    rows: list[ServerHeatmapRowRead] = Field(default_factory=list)


class TopologyCorrelationRead(BaseModel):
    run_id: int
    selected_at: datetime
    job_identity: dict[str, Any]
    ess_request_id: str | None = None
    process_id: str | None = None
    ecid: str | None = None
    client_identifier: str | None = None
    active_sql_id: str | None = None
    plan_hash_value: str | None = None
    db_instance_node: RuntimeNodeRead | None = None
    db_host_node: RuntimeNodeRead | None = None
    app_server_node: RuntimeNodeRead | None = None
    app_server_confidence: str = "unknown"
    active_sessions: list[DbSessionSnapshotRead] = Field(default_factory=list)
    bindings: list[JobRunNodeBindingRead] = Field(default_factory=list)
    heat_summary: dict[str, Any] = Field(default_factory=dict)
    problem_classification: str = "unknown"
    evidence: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    recommended_next_query: str | None = None
    explanation: str | None = None


class RunCreate(BaseModel):
    customer_key: str
    environment: str
    job_family: str | None = None
    job_type: str
    job_name: str
    region: str | None = None
    workstream: str | None = None
    period: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    status: str = "RUNNING"
    ess_request_id: str | None = None
    job_id: str | None = None
    process_id: str | None = None
    api_operation: str | None = None
    sql_id: str | None = None
    plan_hash_value: str | None = None
    udq_name: str | None = None
    udq_hash: str | None = None
    expected_minutes_at_start: float | None = None
    current_progress_pct: float | None = None
    notes: str | None = None


class RunListItem(BaseModel):
    id: int
    run_key: str
    customer_key: str
    customer_name: str
    environment: str
    job_type: str
    job_name: str
    region: str | None = None
    workstream: str | None = None
    status: str
    process_id: str | None = None
    ess_request_id: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    elapsed_minutes: float
    runtime_state: RuntimeState
    severity: AlertSeverity
    variance_pct: float | None = None
    reason_codes: list[str] = Field(default_factory=list)


class VolumeSnapshotRead(BaseModel):
    id: int
    metric_name: str
    metric_value: float
    baseline_value: float | None = None
    unit: str | None = None
    data_window_start: datetime | None = None
    data_window_end: datetime | None = None
    shape_tags: list[str] | None = None

    model_config = ConfigDict(from_attributes=True)


class SqlObservationRead(BaseModel):
    id: int
    sql_id: str | None = None
    plan_hash_value: str | None = None
    child_number: int | None = None
    sql_profile: str | None = None
    module: str | None = None
    action: str | None = None
    elapsed_time_delta: float | None = None
    buffer_gets_delta: float | None = None
    rows_processed_delta: float | None = None
    top_wait_event: str | None = None
    udq_name: str | None = None
    udq_hash: str | None = None
    query_text_available: bool = False
    query_shape_tags: list[str] | None = None
    index_profile_notes: str | None = None
    recommendation_text: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AlertRead(BaseModel):
    id: int
    run_id: int | None = None
    severity: str
    state: str
    runtime_state: str | None = None
    reason_codes: list[str] | None = None
    payload: dict[str, Any] | None = None
    top_suspected_cause: str | None = None
    expected_minutes: float | None = None
    elapsed_minutes: float | None = None
    variance_pct: float | None = None
    eta_at: datetime | None = None
    acked_by: str | None = None
    acked_at: datetime | None = None
    ack_reason: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RunDetail(BaseModel):
    id: int
    run_key: str
    customer: CustomerRead
    environment: EnvironmentRead
    job_definition: JobDefinitionRead | None = None
    job_family: str | None = None
    job_type: str
    job_name: str
    region: str | None = None
    workstream: str | None = None
    period: str | None = None
    data_window_start: datetime | None = None
    data_window_end: datetime | None = None
    started_at: datetime
    ended_at: datetime | None = None
    status: str
    ess_request_id: str | None = None
    job_id: str | None = None
    process_id: str | None = None
    api_operation: str | None = None
    sql_id: str | None = None
    plan_hash_value: str | None = None
    udq_name: str | None = None
    udq_hash: str | None = None
    current_progress_pct: float | None = None
    last_progress_at: datetime | None = None
    source_type: str | None = None
    source_connector: str | None = None
    source_template_id: str | None = None
    source_query_execution_id: int | None = None
    ingested_at: datetime | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    evaluation: EvaluationResult
    volumes: list[VolumeSnapshotRead] = Field(default_factory=list)
    sql_observations: list[SqlObservationRead] = Field(default_factory=list)
    alerts: list[AlertRead] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    latest_diagnostic: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class ExpectationBase(BaseModel):
    customer_key: str
    environment: str
    job_family: str | None = None
    job_type: str | None = None
    job_name: str | None = None
    region: str | None = None
    workstream: str | None = None
    period: str | None = None
    data_window_start: datetime | None = None
    data_window_end: datetime | None = None
    ess_request_name: str | None = None
    process_name: str | None = None
    api_operation: str | None = None
    sql_id: str | None = None
    sql_plan_hash: str | None = None
    udq_name: str | None = None
    udq_hash: str | None = None
    baseline_method: str = "manual_goal"
    expected_minutes: float | None = None
    warning_threshold_pct: float = 25
    critical_threshold_pct: float = 75
    customer_goal_minutes: float | None = None
    minimum_history_count: int = 5
    confidence_score: float = 0.6
    owner: str | None = None
    alert_channel: str | None = None
    active_from: datetime | None = None
    active_until: datetime | None = None
    notes: str | None = None
    risk_assumptions: str | None = None
    last_reviewed_by: str | None = None
    last_reviewed_at: datetime | None = None


class ExpectationCreate(ExpectationBase):
    pass


class ExpectationUpdate(ExpectationBase):
    pass


class ExpectationRead(ExpectationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AckRequest(BaseModel):
    actor: str = "operator"
    reason: str


class ResolveRequest(BaseModel):
    actor: str = "operator"
    note: str


class AlertCreate(BaseModel):
    run_id: int
    send_mock_slack: bool = True


class AdHocMonitorCreate(BaseModel):
    customer_key: str
    environment: str
    job_id: str | None = None
    process_id: str | None = None
    ess_request_id: str | None = None
    sql_id: str | None = None
    api_operation: str | None = None
    manual_job_name: str
    expected_minutes: float | None = None
    baseline_selection: str = "ad_hoc"
    warning_threshold_pct: float = 25
    critical_threshold_pct: float = 75
    expiration_time: datetime | None = None
    destination: str | None = None
    notes: str | None = None


class AdHocMonitorRead(BaseModel):
    id: int
    name: str
    rule_type: str
    selector: dict[str, Any] | None = None
    expected_minutes: float | None = None
    warning_threshold_pct: float
    critical_threshold_pct: float
    expires_at: datetime | None = None
    destination: str | None = None
    active: bool
    notes: str | None = None
    run_id: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueryTemplateBase(BaseModel):
    template_id: str
    name: str
    description: str | None = None
    source_url: str | None = None
    source_reference: str | None = None
    database_type: str = "oracle"
    connector_type: str = "oracle_db"
    template_category: str = "diagnostic"
    sql_text: str
    required_parameters: dict[str, Any] = Field(default_factory=dict)
    default_parameters: dict[str, Any] = Field(default_factory=dict)
    output_mapping: dict[str, Any] = Field(default_factory=dict)
    owning_team: str | None = None
    active: bool = True
    tags: list[str] = Field(default_factory=list)
    customer_key: str | None = None
    environment: str | None = None
    job_family: str | None = None

    @field_validator("required_parameters", "default_parameters", "output_mapping", mode="before")
    @classmethod
    def _none_to_dict(cls, value: Any) -> dict[str, Any]:
        return {} if value is None else value

    @field_validator("tags", mode="before")
    @classmethod
    def _none_to_list(cls, value: Any) -> list[str]:
        return [] if value is None else value


class QueryTemplateCreate(QueryTemplateBase):
    pass


class QueryTemplateRead(QueryTemplateBase):
    id: int
    is_read_only_validated: bool = False
    last_validated_at: datetime | None = None
    last_executed_at: datetime | None = None
    validation_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueryExecuteRequest(BaseModel):
    customer_key: str | None = None
    environment: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    connector_config_key: str | None = None
    validate_only: bool = False
    initiated_by: str = "user"
    executed_by: str = "operator"


class QueryExecutionRead(BaseModel):
    id: int
    query_execution_id: str | None = None
    template_id: int
    connector_config_key: str | None = None
    status: str
    row_count: int
    elapsed_ms: int | None = None
    sample_result: list[Any] | dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    sanitized_error_message: str | None = None
    parameters: dict[str, Any] | None = None
    parameter_hash: str | None = None
    validation_result: dict[str, Any] | None = None
    initiated_by: str | None = None
    ingested_entity_counts: dict[str, Any] | None = None
    raw_sql_hash: str | None = None
    raw_sql_storage_enabled: bool = False
    correlation_id: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DiagnosticRunRequest(BaseModel):
    run_id: int | None = None
    ess_request_id: str | None = None
    process_id: str | None = None
    ecid: str | None = None
    lookback_minutes: int = 720
    collector_mode: str = "mock"


class DiagnosticMetricRead(BaseModel):
    id: int
    metric_key: str
    label: str
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None
    display_order: int
    comparison_baseline: str | None = None
    variance_pct: float | None = None

    model_config = ConfigDict(from_attributes=True)


class DiagnosticEvidenceRead(BaseModel):
    id: int
    evidence_type: str
    title: str
    query_template_id: int | None = None
    query_execution_id: int | None = None
    evidence_summary: str | None = None
    raw_sample: list[Any] | dict[str, Any] | None = None
    confidence_contribution: str | None = None
    observed_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiagnosticRunbookStepRead(BaseModel):
    id: int
    step_number: int
    step_type: str
    title: str
    body: str | None = None
    command_text: str | None = None
    executable_by_app: bool = False
    requires_approval: bool = True
    approval_role: str | None = None
    safety_note: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RuledOutAlternativeRead(BaseModel):
    id: int
    finding_id: int | None = None
    alternative_type: str
    reason: str
    supporting_evidence: str | None = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiagnosticDataQualityCheckRead(BaseModel):
    id: int
    check_key: str
    description: str
    status: str
    evidence_count: int
    message: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiagnosticFindingRead(BaseModel):
    id: int
    finding_number: int
    finding_key: str
    finding_type: str
    title: str
    severity: str
    confidence: str
    actionability: str
    lifecycle: str
    problem_statement: str | None = None
    business_impact: str | None = None
    technical_detail: str | None = None
    recommended_action: str | None = None
    expected_result: str | None = None
    approval_gate: str | None = None
    owner_team: str | None = None
    risk_if_done_wrong: str | None = None
    rollback_plan: str | None = None
    stop_recheck_condition: str | None = None
    source_sql_id: str | None = None
    source_plan_hash_value: str | None = None
    historical_plan_hash_value: str | None = None
    package_name: str | None = None
    object_name: str | None = None
    value_set_code: str | None = None
    scope_count: int | None = None
    confirmed_count: int | None = None
    unverified_count: int | None = None
    metrics: dict[str, Any] | None = None
    evidence: list[DiagnosticEvidenceRead] = Field(default_factory=list)
    metric_rows: list[DiagnosticMetricRead] = Field(default_factory=list)
    runbook_steps: list[DiagnosticRunbookStepRead] = Field(default_factory=list)
    ruled_out_alternatives: list[RuledOutAlternativeRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiagnosticReportSummaryRead(BaseModel):
    id: int
    run_id: int | None = None
    customer_key: str
    environment: str
    report_title: str
    diagnostic_type: str
    ess_request_id: str | None = None
    job_name: str | None = None
    process_id: str | None = None
    ecid: str | None = None
    incident_state: str
    freshness_status: str
    overall_confidence: str
    overall_status: str
    if_you_do_one_thing_today: str | None = None
    executive_summary: dict[str, Any] | None = None
    top_finding: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiagnosticReportRead(DiagnosticReportSummaryRead):
    job_definition: str | None = None
    client_identifier: str | None = None
    rac_cluster_size: int | None = None
    snapshot_start_at: datetime | None = None
    snapshot_end_at: datetime | None = None
    lookback_minutes: int | None = None
    collector_name: str | None = None
    collector_version: str | None = None
    source_package: str | None = None
    findings: list[DiagnosticFindingRead] = Field(default_factory=list)
    metrics: list[DiagnosticMetricRead] = Field(default_factory=list)
    ruled_out_alternatives: list[RuledOutAlternativeRead] = Field(default_factory=list)
    data_quality_checks: list[DiagnosticDataQualityCheckRead] = Field(default_factory=list)


class DiagnosticRunResponse(BaseModel):
    diagnostic_report_id: int
    summary: dict[str, Any] = Field(default_factory=dict)
    finding_count: int


class DiagnosticRenderRead(BaseModel):
    report_id: int
    markdown: str
    structured: DiagnosticReportRead


class GlossaryTermRead(BaseModel):
    id: int
    term: str
    definition: str
    domain: str | None = None
    active: bool

    model_config = ConfigDict(from_attributes=True)


class QueryTemplateValidationRead(BaseModel):
    is_valid: bool
    error: str | None = None
    bind_names: list[str] = Field(default_factory=list)
    referenced_objects: list[str] = Field(default_factory=list)


class QueryCatalogImportRead(BaseModel):
    imported: int
    updated: int
    skipped_remote: bool = True
    source: str


class CustomerPodOnboardRequest(BaseModel):
    customer_key: str
    display_name: str | None = None
    environment: str = "PROD"
    region: str | None = None
    lifecycle: str = "prod"
    connector_type: str = "OracleDbConnector"
    config_key: str | None = None
    env_var_prefix: str | None = None
    apply_stock_templates: bool = True
    run_initial_fetch: bool = False
    minimum_elapsed_minutes: int = Field(default=120, ge=0, le=10080)
    notes: str | None = None


class CustomerPodOnboardResponse(BaseModel):
    customer: CustomerRead
    environment: EnvironmentRead
    connector_config_id: int
    connector_config_key: str | None = None
    env_var_prefix: str | None = None
    stock_catalog: dict[str, Any] = Field(default_factory=dict)
    stock_template_ids: list[str] = Field(default_factory=list)
    validation_results: list[dict[str, Any]] = Field(default_factory=list)
    initial_fetch: dict[str, Any] | None = None
    next_steps: list[str] = Field(default_factory=list)
    custom_metrics_import_path: str = "/imports"


class QueryIngestResponse(BaseModel):
    query_execution_id: str | None
    status: str
    ingested_entity_counts: dict[str, int] = Field(default_factory=dict)
    affected_run_ids: list[int] = Field(default_factory=list)
    evaluations: list[dict[str, Any]] = Field(default_factory=list)


class SyncRunResponse(BaseModel):
    started_at: datetime
    finished_at: datetime
    templates_considered: int
    executions: list[QueryIngestResponse] = Field(default_factory=list)


class ImportPlanResponse(BaseModel):
    batch_id: int
    filename: str
    row_count: int
    created_runs: int
    created_expectations: int
    notes: str


class ConnectorHealth(BaseModel):
    id: int
    connector_type: str
    config_key: str | None = None
    name: str
    display_name: str | None = None
    status: str
    enabled: bool
    access_mode: Literal["read_only"] = "read_only"
    destructive_operations_allowed: bool = False
    guardrails: list[str] = Field(default_factory=list)
    last_checked_at: datetime | None = None
    last_successful_sync_at: datetime | None = None
    last_failed_sync_at: datetime | None = None
    scheduler_heartbeat_at: datetime | None = None
    health_message: str | None = None
    config: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class ConnectorTestRequest(BaseModel):
    connector_type: str
    customer_key: str | None = None
    environment: str | None = None


class ConnectorTestResponse(BaseModel):
    connector_type: str
    status: str
    message: str
    access_mode: Literal["read_only"] = "read_only"
    destructive_operations_allowed: bool = False
    sample: dict[str, Any] = Field(default_factory=dict)
