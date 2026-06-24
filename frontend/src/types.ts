export type RuntimeState = "normal" | "watch" | "warning" | "critical" | "complete" | "unknown_baseline";
export type Severity = "info" | "watch" | "warning" | "critical";

export interface EvaluationResult {
  run_id: number;
  runtime_state: RuntimeState;
  severity: Severity;
  expected_minutes: number | null;
  expected_source: string | null;
  elapsed_minutes: number;
  variance_pct: number | null;
  eta_at: string | null;
  confidence_score: number;
  reason_codes: string[];
  cause_tags: string[];
  recommended_actions: string[];
  top_suspected_cause: string | null;
  historical_comparison: Record<string, unknown>;
  slack_payload?: Record<string, unknown>;
}

export interface DashboardItem {
  run_id: number;
  run_key: string;
  customer: string;
  customer_key: string;
  environment: string;
  job_family: string | null;
  job_type: string;
  job_name: string;
  region: string | null;
  workstream: string | null;
  status: string;
  started_at: string;
  ended_at: string | null;
  elapsed_minutes: number;
  expected_minutes: number | null;
  variance_pct: number | null;
  eta_at: string | null;
  confidence_score: number;
  runtime_state: RuntimeState;
  latest_alert_state: string | null;
  latest_alert_severity: string | null;
  cause_tags: string[];
  reason_codes: string[];
  top_suspected_cause: string | null;
  is_ad_hoc: boolean;
  source_type: string | null;
  source_connector: string | null;
  last_refreshed_at: string | null;
  latest_diagnostic_id: number | null;
  latest_diagnostic_title: string | null;
  latest_diagnostic_top_finding: string | null;
}

export interface DashboardResponse {
  generated_at: string;
  items: DashboardItem[];
  counts_by_state: Record<string, number>;
}

export interface CustomerCriticalEventSummary {
  run_id: number;
  job_name: string;
  job_type: string;
  environment: string;
  region: string | null;
  workstream: string | null;
  status: string;
  started_at: string;
  elapsed_minutes: number;
  expected_minutes: number | null;
  variance_pct: number | null;
  top_suspected_cause: string | null;
  proposed_solution: string;
  supporting_analysis: string[];
  reason_codes: string[];
  diagnostic_id: number | null;
  diagnostic_title: string | null;
  diagnostic_top_finding: string | null;
  topology_summary: string | null;
}

export interface CustomerExecutiveSummaryResponse {
  generated_at: string;
  customer_key: string;
  customer_name: string;
  environment: string | null;
  generation_mode: string;
  headline: string;
  data_points_used: string[];
  critical_event_count: number;
  bullets: CustomerCriticalEventSummary[];
}

export interface CustomerPodRead {
  id: number;
  customer_key: string;
  display_name: string;
  tier: string | null;
  active: boolean;
}

export interface CustomerPodOnboardResponse {
  customer: CustomerPodRead;
  environment: {
    id: number;
    name: string;
    region: string | null;
    lifecycle: string;
  };
  connector_config_id: number;
  connector_config_key: string | null;
  env_var_prefix: string | null;
  stock_catalog: Record<string, unknown>;
  stock_template_ids: string[];
  validation_results: Array<Record<string, unknown>>;
  initial_fetch: Record<string, unknown> | null;
  next_steps: string[];
  custom_metrics_import_path: string;
}

export interface RuntimeNode {
  id: number;
  customer_key: string;
  environment: string;
  node_type: string;
  node_key: string;
  display_name: string;
  host_name: string | null;
  instance_name: string | null;
  server_name: string | null;
  cluster_name: string | null;
  service_name: string | null;
  availability_domain: string | null;
  region: string | null;
  tags: Record<string, unknown> | null;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RuntimeTopologyNode {
  node_key: string;
  display_name: string;
  node_type: string;
  tier: string;
  severity: string;
  heat_score: number;
  confidence: string;
  active_run_count: number;
  active_session_count: number;
  top_sql_id: string | null;
  top_wait_class: string | null;
  top_event: string | null;
  metrics: Record<string, unknown>;
  last_refreshed_at: string | null;
  details: Record<string, unknown>;
}

export interface RuntimeTopologyEdge {
  from_node_key: string;
  to_node_key: string;
  label: string;
  confidence: string;
  run_id: number | null;
  evidence: string | null;
}

export interface RuntimeTopologyMap {
  generated_at: string;
  selected_run_id: number | null;
  nodes: RuntimeTopologyNode[];
  edges: RuntimeTopologyEdge[];
  explanations: string[];
}

export interface DbSessionSnapshot {
  id: number;
  run_id: number | null;
  sampled_at: string;
  inst_id: number | null;
  instance_name: string | null;
  db_host_name: string | null;
  sid: number | null;
  serial_number: string | null;
  session_status: string | null;
  username: string | null;
  service_name: string | null;
  module: string | null;
  action: string | null;
  client_identifier: string | null;
  ecid: string | null;
  machine: string | null;
  program: string | null;
  process: string | null;
  sql_id: string | null;
  sql_child_number: number | null;
  sql_exec_start: string | null;
  last_call_et_seconds: number | null;
  event: string | null;
  wait_class: string | null;
  state: string | null;
  blocking_instance: number | null;
  blocking_session: number | null;
  plan_hash_value: string | null;
  row_wait_obj: string | null;
  query_execution_id: number | null;
  created_at: string;
}

export interface JobRunNodeBinding {
  id: number;
  run_id: number;
  node_id: number;
  binding_type: string;
  confidence: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  evidence_summary: string | null;
  evidence_json: Record<string, unknown> | null;
  query_execution_id: number | null;
  node: RuntimeNode | null;
  created_at: string;
  updated_at: string;
}

export interface TopologyCorrelation {
  run_id: number;
  selected_at: string;
  job_identity: Record<string, unknown>;
  ess_request_id: string | null;
  process_id: string | null;
  ecid: string | null;
  client_identifier: string | null;
  active_sql_id: string | null;
  plan_hash_value: string | null;
  db_instance_node: RuntimeNode | null;
  db_host_node: RuntimeNode | null;
  app_server_node: RuntimeNode | null;
  app_server_confidence: string;
  active_sessions: DbSessionSnapshot[];
  bindings: JobRunNodeBinding[];
  heat_summary: Record<string, unknown>;
  problem_classification: string;
  evidence: string[];
  missing_inputs: string[];
  recommended_next_query: string | null;
  explanation: string | null;
}

export interface ServerHeatmapCell {
  node_id: number;
  bucket_start: string;
  bucket_end: string;
  heat_score: number;
  severity: string;
  contributing_run_ids: number[];
  contributing_sql_ids: string[];
  top_wait_class: string | null;
  top_event: string | null;
  metric_breakdown: Record<string, unknown>;
  explanation: string;
}

export interface ServerHeatmapRow {
  node: RuntimeNode;
  tier: string;
  cells: ServerHeatmapCell[];
}

export interface ServerHeatmapResponse {
  generated_at: string;
  bucket_minutes: number;
  rows: ServerHeatmapRow[];
}

export interface RunListItem {
  id: number;
  run_key: string;
  customer_key: string;
  customer_name: string;
  environment: string;
  job_type: string;
  job_name: string;
  region: string | null;
  workstream: string | null;
  status: string;
  process_id: string | null;
  ess_request_id: string | null;
  started_at: string;
  ended_at: string | null;
  elapsed_minutes: number;
  runtime_state: RuntimeState;
  severity: Severity;
  variance_pct: number | null;
  reason_codes: string[];
}

export interface VolumeSnapshot {
  id: number;
  metric_name: string;
  metric_value: number;
  baseline_value: number | null;
  unit: string | null;
  data_window_start: string | null;
  data_window_end: string | null;
  shape_tags: string[] | null;
}

export interface SqlObservation {
  id: number;
  sql_id: string | null;
  plan_hash_value: string | null;
  child_number: number | null;
  sql_profile: string | null;
  module: string | null;
  action: string | null;
  elapsed_time_delta: number | null;
  buffer_gets_delta: number | null;
  rows_processed_delta: number | null;
  top_wait_event: string | null;
  udq_name: string | null;
  udq_hash: string | null;
  query_text_available: boolean;
  query_shape_tags: string[] | null;
  index_profile_notes: string | null;
  recommendation_text: string | null;
}

export interface Alert {
  id: number;
  run_id: number | null;
  severity: string;
  state: string;
  runtime_state: string | null;
  reason_codes: string[] | null;
  payload: Record<string, unknown> | null;
  top_suspected_cause: string | null;
  expected_minutes: number | null;
  elapsed_minutes: number | null;
  variance_pct: number | null;
  eta_at: string | null;
  acked_by: string | null;
  acked_at: string | null;
  ack_reason: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
  created_at: string;
}

export interface RunDetail {
  id: number;
  run_key: string;
  customer: { id: number; customer_key: string; display_name: string };
  environment: { id: number; name: string; region: string | null; lifecycle: string };
  job_definition: {
    id: number;
    job_family: string;
    job_type: string;
    job_name: string;
    default_region: string | null;
    default_workstream: string | null;
    ess_request_name: string | null;
    process_name: string | null;
    api_operation: string | null;
  } | null;
  job_family: string | null;
  job_type: string;
  job_name: string;
  region: string | null;
  workstream: string | null;
  period: string | null;
  data_window_start: string | null;
  data_window_end: string | null;
  started_at: string;
  ended_at: string | null;
  status: string;
  ess_request_id: string | null;
  job_id: string | null;
  process_id: string | null;
  api_operation: string | null;
  sql_id: string | null;
  plan_hash_value: string | null;
  udq_name: string | null;
  udq_hash: string | null;
  current_progress_pct: number | null;
  last_progress_at: string | null;
  source_type: string | null;
  source_connector: string | null;
  source_template_id: string | null;
  source_query_execution_id: number | null;
  ingested_at: string | null;
  provenance: Record<string, unknown>;
  notes: string | null;
  evaluation: EvaluationResult;
  volumes: VolumeSnapshot[];
  sql_observations: SqlObservation[];
  alerts: Alert[];
  timeline: Array<{ ts: string; label: string; state: string }>;
  latest_diagnostic: DiagnosticReportSummary | null;
}

export interface ExpectationRecord {
  id: number;
  customer_key: string;
  environment: string;
  job_family: string | null;
  job_type: string | null;
  job_name: string | null;
  region: string | null;
  workstream: string | null;
  period: string | null;
  baseline_method: string;
  expected_minutes: number | null;
  warning_threshold_pct: number;
  critical_threshold_pct: number;
  customer_goal_minutes: number | null;
  minimum_history_count: number;
  confidence_score: number;
  owner: string | null;
  alert_channel: string | null;
  notes: string | null;
  risk_assumptions: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectorHealth {
  id: number;
  connector_type: string;
  config_key: string | null;
  name: string;
  display_name: string | null;
  status: string;
  enabled: boolean;
  access_mode: "read_only";
  destructive_operations_allowed: boolean;
  guardrails: string[];
  last_checked_at: string | null;
  last_successful_sync_at: string | null;
  last_failed_sync_at: string | null;
  scheduler_heartbeat_at: string | null;
  health_message: string | null;
  config: Record<string, unknown> | null;
}

export interface QueryTemplate {
  id: number;
  template_id: string;
  name: string;
  description: string | null;
  source_url: string | null;
  source_reference: string | null;
  database_type: string;
  connector_type: string;
  template_category: string;
  sql_text: string;
  required_parameters: Record<string, unknown>;
  default_parameters: Record<string, unknown>;
  output_mapping: Record<string, unknown>;
  owning_team: string | null;
  active: boolean;
  is_read_only_validated: boolean;
  last_validated_at: string | null;
  last_executed_at: string | null;
  validation_error: string | null;
  tags: string[];
  customer_key: string | null;
  environment: string | null;
  job_family: string | null;
  created_at: string;
  updated_at: string;
}

export interface QueryExecutionLog {
  id: number;
  query_execution_id: string | null;
  template_id: number;
  connector_config_key: string | null;
  status: string;
  row_count: number;
  elapsed_ms: number | null;
  sample_result: unknown;
  error: string | null;
  error_code: string | null;
  sanitized_error_message: string | null;
  parameters: Record<string, unknown> | null;
  parameter_hash: string | null;
  validation_result: Record<string, unknown> | null;
  initiated_by: string | null;
  ingested_entity_counts: Record<string, unknown> | null;
  raw_sql_hash: string | null;
  raw_sql_storage_enabled: boolean;
  correlation_id: string | null;
  started_at: string;
  ended_at: string | null;
  finished_at: string | null;
}

export interface DiagnosticMetric {
  id: number;
  metric_key: string;
  label: string;
  value_numeric: number | null;
  value_text: string | null;
  unit: string | null;
  display_order: number;
  comparison_baseline: string | null;
  variance_pct: number | null;
}

export interface DiagnosticEvidence {
  id: number;
  evidence_type: string;
  title: string;
  query_template_id: number | null;
  query_execution_id: number | null;
  evidence_summary: string | null;
  raw_sample: unknown;
  confidence_contribution: string | null;
  observed_at: string | null;
  created_at: string;
}

export interface DiagnosticRunbookStep {
  id: number;
  step_number: number;
  step_type: string;
  title: string;
  body: string | null;
  command_text: string | null;
  executable_by_app: boolean;
  requires_approval: boolean;
  approval_role: string | null;
  safety_note: string | null;
}

export interface RuledOutAlternative {
  id: number;
  finding_id: number | null;
  alternative_type: string;
  reason: string;
  supporting_evidence: string | null;
  status: string;
  created_at: string;
}

export interface DiagnosticDataQualityCheck {
  id: number;
  check_key: string;
  description: string;
  status: string;
  evidence_count: number;
  message: string | null;
  created_at: string;
}

export interface DiagnosticFinding {
  id: number;
  finding_number: number;
  finding_key: string;
  finding_type: string;
  title: string;
  severity: string;
  confidence: string;
  actionability: string;
  lifecycle: string;
  problem_statement: string | null;
  business_impact: string | null;
  technical_detail: string | null;
  recommended_action: string | null;
  expected_result: string | null;
  approval_gate: string | null;
  owner_team: string | null;
  risk_if_done_wrong: string | null;
  rollback_plan: string | null;
  stop_recheck_condition: string | null;
  source_sql_id: string | null;
  source_plan_hash_value: string | null;
  historical_plan_hash_value: string | null;
  package_name: string | null;
  object_name: string | null;
  value_set_code: string | null;
  scope_count: number | null;
  confirmed_count: number | null;
  unverified_count: number | null;
  metrics: Record<string, unknown> | null;
  evidence: DiagnosticEvidence[];
  metric_rows: DiagnosticMetric[];
  runbook_steps: DiagnosticRunbookStep[];
  ruled_out_alternatives: RuledOutAlternative[];
  created_at: string;
  updated_at: string;
}

export interface DiagnosticReportSummary {
  id: number;
  run_id: number | null;
  customer_key: string;
  environment: string;
  report_title: string;
  diagnostic_type: string;
  ess_request_id: string | null;
  job_name: string | null;
  process_id: string | null;
  ecid: string | null;
  incident_state: string;
  freshness_status: string;
  overall_confidence: string;
  overall_status: string;
  if_you_do_one_thing_today: string | null;
  executive_summary: Record<string, unknown> | null;
  top_finding: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface DiagnosticReport extends DiagnosticReportSummary {
  job_definition: string | null;
  client_identifier: string | null;
  rac_cluster_size: number | null;
  snapshot_start_at: string | null;
  snapshot_end_at: string | null;
  lookback_minutes: number | null;
  collector_name: string | null;
  collector_version: string | null;
  source_package: string | null;
  findings: DiagnosticFinding[];
  metrics: DiagnosticMetric[];
  ruled_out_alternatives: RuledOutAlternative[];
  data_quality_checks: DiagnosticDataQualityCheck[];
}

export interface GlossaryTerm {
  id: number;
  term: string;
  definition: string;
  domain: string | null;
  active: boolean;
}

export interface AdHocMonitor {
  id: number;
  name: string;
  rule_type: string;
  selector: Record<string, unknown> | null;
  expected_minutes: number | null;
  warning_threshold_pct: number;
  critical_threshold_pct: number;
  expires_at: string | null;
  destination: string | null;
  active: boolean;
  notes: string | null;
  run_id: number | null;
  created_at: string;
}
