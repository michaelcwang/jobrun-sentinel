from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, TimestampMixin, utcnow


class Customer(TimestampMixin, AuditMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    tier: Mapped[str | None] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    environments: Mapped[list["Environment"]] = relationship(back_populates="customer")
    job_definitions: Mapped[list["JobDefinition"]] = relationship(back_populates="customer")


class Environment(TimestampMixin, AuditMixin, Base):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("customer_id", "name", name="uq_environment_customer_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    region: Mapped[str | None] = mapped_column(String(80))
    lifecycle: Mapped[str] = mapped_column(String(40), default="prod")
    base_url: Mapped[str | None] = mapped_column(String(255))

    customer: Mapped[Customer] = relationship(back_populates="environments")


class JobDefinition(TimestampMixin, AuditMixin, Base):
    __tablename__ = "job_definitions"
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "job_family",
            "job_type",
            "job_name",
            name="uq_job_definition_customer_signature",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    job_family: Mapped[str] = mapped_column(String(120), index=True)
    job_type: Mapped[str] = mapped_column(String(120), index=True)
    job_name: Mapped[str] = mapped_column(String(200), index=True)
    default_region: Mapped[str | None] = mapped_column(String(80), index=True)
    default_workstream: Mapped[str | None] = mapped_column(String(120), index=True)
    ess_request_name: Mapped[str | None] = mapped_column(String(160))
    process_name: Mapped[str | None] = mapped_column(String(160))
    api_operation: Mapped[str | None] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    customer: Mapped[Customer] = relationship(back_populates="job_definitions")
    runs: Mapped[list["JobRun"]] = relationship(back_populates="job_definition")


class JobRun(TimestampMixin, AuditMixin, Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        Index("ix_job_runs_active_lookup", "customer_id", "environment_id", "status"),
        Index("ix_job_runs_signature", "job_definition_id", "region", "workstream", "period"),
        UniqueConstraint("run_key", name="uq_job_runs_run_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_key: Mapped[str] = mapped_column(String(120), nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environments.id"), index=True)
    job_definition_id: Mapped[int | None] = mapped_column(ForeignKey("job_definitions.id"), index=True)
    job_family: Mapped[str | None] = mapped_column(String(120))
    job_type: Mapped[str] = mapped_column(String(120), index=True)
    job_name: Mapped[str] = mapped_column(String(200), index=True)
    region: Mapped[str | None] = mapped_column(String(80), index=True)
    workstream: Mapped[str | None] = mapped_column(String(120), index=True)
    period: Mapped[str | None] = mapped_column(String(40), index=True)
    business_scope: Mapped[dict | None] = mapped_column(JSON, default=dict)
    data_window_start: Mapped[datetime | None] = mapped_column(DateTime)
    data_window_end: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(40), default="RUNNING", index=True)
    ess_request_id: Mapped[str | None] = mapped_column(String(120), index=True)
    job_id: Mapped[str | None] = mapped_column(String(120), index=True)
    process_id: Mapped[str | None] = mapped_column(String(120), index=True)
    api_operation: Mapped[str | None] = mapped_column(String(160), index=True)
    sql_id: Mapped[str | None] = mapped_column(String(80), index=True)
    plan_hash_value: Mapped[str | None] = mapped_column(String(80), index=True)
    udq_name: Mapped[str | None] = mapped_column(String(200), index=True)
    udq_hash: Mapped[str | None] = mapped_column(String(160), index=True)
    expected_minutes_at_start: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    current_progress_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(80), default="seed")
    source_connector: Mapped[str | None] = mapped_column(String(120))
    source_template_id: Mapped[str | None] = mapped_column(String(120), index=True)
    source_query_execution_id: Mapped[int | None] = mapped_column(Integer, index=True)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime)

    customer: Mapped[Customer] = relationship()
    environment: Mapped[Environment] = relationship()
    job_definition: Mapped[JobDefinition | None] = relationship(back_populates="runs")
    parameters: Mapped[list["JobRunParameter"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    volume_snapshots: Mapped[list["VolumeSnapshot"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    sql_observations: Mapped[list["SqlObservation"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(back_populates="run")
    diagnostic_reports: Mapped[list["DiagnosticReport"]] = relationship(back_populates="run")
    node_bindings: Mapped[list["JobRunNodeBinding"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    db_session_snapshots: Mapped[list["DbSessionSnapshot"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class JobRunParameter(TimestampMixin, Base):
    __tablename__ = "job_run_parameters"
    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_job_run_parameters_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("job_runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    value: Mapped[str | None] = mapped_column(Text)
    value_hash: Mapped[str | None] = mapped_column(String(160))
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)

    run: Mapped[JobRun] = relationship(back_populates="parameters")


class ExpectationRecord(TimestampMixin, AuditMixin, Base):
    __tablename__ = "expectation_records"
    __table_args__ = (
        Index(
            "ix_expectations_matching",
            "customer_key",
            "environment",
            "job_family",
            "job_type",
            "job_name",
            "active_from",
            "active_until",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_key: Mapped[str] = mapped_column(String(80), index=True)
    environment: Mapped[str] = mapped_column(String(80), index=True)
    job_family: Mapped[str | None] = mapped_column(String(120), index=True)
    job_type: Mapped[str | None] = mapped_column(String(120), index=True)
    job_name: Mapped[str | None] = mapped_column(String(200), index=True)
    region: Mapped[str | None] = mapped_column(String(80), index=True)
    workstream: Mapped[str | None] = mapped_column(String(120), index=True)
    period: Mapped[str | None] = mapped_column(String(40), index=True)
    data_window_start: Mapped[datetime | None] = mapped_column(DateTime)
    data_window_end: Mapped[datetime | None] = mapped_column(DateTime)
    ess_request_name: Mapped[str | None] = mapped_column(String(160))
    process_name: Mapped[str | None] = mapped_column(String(160))
    api_operation: Mapped[str | None] = mapped_column(String(160))
    sql_id: Mapped[str | None] = mapped_column(String(80), index=True)
    sql_plan_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    udq_name: Mapped[str | None] = mapped_column(String(200), index=True)
    udq_hash: Mapped[str | None] = mapped_column(String(160), index=True)
    baseline_method: Mapped[str] = mapped_column(String(60), default="historical_p50_p90")
    expected_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    warning_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=25)
    critical_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=75)
    customer_goal_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    minimum_history_count: Mapped[int] = mapped_column(Integer, default=5)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0.6)
    owner: Mapped[str | None] = mapped_column(String(160))
    alert_channel: Mapped[str | None] = mapped_column(String(160))
    active_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    active_until: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    risk_assumptions: Mapped[str | None] = mapped_column(Text)
    last_reviewed_by: Mapped[str | None] = mapped_column(String(160))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)


class BaselineSnapshot(TimestampMixin, Base):
    __tablename__ = "baseline_snapshots"
    __table_args__ = (
        Index("ix_baseline_snapshots_signature", "customer_key", "environment", "job_signature"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_key: Mapped[str] = mapped_column(String(80), index=True)
    environment: Mapped[str] = mapped_column(String(80), index=True)
    job_signature: Mapped[str] = mapped_column(String(400), index=True)
    baseline_method: Mapped[str] = mapped_column(String(60), default="historical_p75")
    p50_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    p75_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    p90_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    p95_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    average_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    median_abs_deviation: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    last_successful_duration: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    baseline_volume_metric: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    throughput_per_minute: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    comparable_signature: Mapped[dict | None] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VolumeSnapshot(TimestampMixin, Base):
    __tablename__ = "volume_snapshots"
    __table_args__ = (Index("ix_volume_snapshots_run_metric", "run_id", "metric_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("job_runs.id"), index=True)
    metric_name: Mapped[str] = mapped_column(String(120), index=True)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    baseline_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    unit: Mapped[str | None] = mapped_column(String(40))
    data_window_start: Mapped[datetime | None] = mapped_column(DateTime)
    data_window_end: Mapped[datetime | None] = mapped_column(DateTime)
    shape_tags: Mapped[list | None] = mapped_column(JSON, default=list)

    run: Mapped[JobRun] = relationship(back_populates="volume_snapshots")


class SqlObservation(TimestampMixin, Base):
    __tablename__ = "sql_observations"
    __table_args__ = (Index("ix_sql_observations_run_sql", "run_id", "sql_id", "plan_hash_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("job_runs.id"), index=True)
    sql_id: Mapped[str | None] = mapped_column(String(80), index=True)
    plan_hash_value: Mapped[str | None] = mapped_column(String(80), index=True)
    child_number: Mapped[int | None] = mapped_column(Integer)
    sql_profile: Mapped[str | None] = mapped_column(String(200))
    module: Mapped[str | None] = mapped_column(String(160))
    action: Mapped[str | None] = mapped_column(String(160))
    elapsed_time_delta: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    buffer_gets_delta: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    rows_processed_delta: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    top_wait_event: Mapped[str | None] = mapped_column(String(200))
    udq_name: Mapped[str | None] = mapped_column(String(200), index=True)
    udq_hash: Mapped[str | None] = mapped_column(String(160), index=True)
    query_text_available: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_query_text: Mapped[str | None] = mapped_column(Text)
    query_shape_tags: Mapped[list | None] = mapped_column(JSON, default=list)
    index_profile_notes: Mapped[str | None] = mapped_column(Text)
    recommendation_text: Mapped[str | None] = mapped_column(Text)

    run: Mapped[JobRun] = relationship(back_populates="sql_observations")


class AlertRule(TimestampMixin, AuditMixin, Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    rule_type: Mapped[str] = mapped_column(String(40), default="standard", index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("environments.id"), index=True)
    job_definition_id: Mapped[int | None] = mapped_column(ForeignKey("job_definitions.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("job_runs.id"), index=True)
    selector: Mapped[dict | None] = mapped_column(JSON, default=dict)
    expected_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    warning_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=25)
    critical_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=75)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    destination: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_state_severity", "state", "severity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("job_runs.id"), index=True)
    alert_rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id"), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="info", index=True)
    state: Mapped[str] = mapped_column(String(40), default="new", index=True)
    runtime_state: Mapped[str | None] = mapped_column(String(40), index=True)
    reason_codes: Mapped[list | None] = mapped_column(JSON, default=list)
    payload: Mapped[dict | None] = mapped_column(JSON, default=dict)
    top_suspected_cause: Mapped[str | None] = mapped_column(String(240))
    expected_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    elapsed_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    variance_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    eta_at: Mapped[datetime | None] = mapped_column(DateTime)
    acked_by: Mapped[str | None] = mapped_column(String(160))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime)
    ack_reason: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(160))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution_note: Mapped[str | None] = mapped_column(Text)

    run: Mapped[JobRun | None] = relationship(back_populates="alerts")
    events: Mapped[list["AlertEvent"]] = relationship(back_populates="alert", cascade="all, delete-orphan")


class AlertEvent(TimestampMixin, Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, default=dict)
    actor: Mapped[str | None] = mapped_column(String(160), default="system")

    alert: Mapped[Alert] = relationship(back_populates="events")


class QueryTemplate(TimestampMixin, AuditMixin, Base):
    __tablename__ = "query_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_reference: Mapped[str | None] = mapped_column(String(300))
    database_type: Mapped[str] = mapped_column(String(80), default="oracle")
    connector_type: Mapped[str] = mapped_column(String(80), default="oracle_db", index=True)
    template_category: Mapped[str] = mapped_column(String(80), default="diagnostic", index=True)
    sql_text: Mapped[str] = mapped_column(Text)
    required_parameters: Mapped[dict | None] = mapped_column(JSON, default=dict)
    default_parameters: Mapped[dict | None] = mapped_column(JSON, default=dict)
    output_mapping: Mapped[dict | None] = mapped_column(JSON, default=dict)
    owning_team: Mapped[str | None] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_read_only_validated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime)
    validation_error: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON, default=list)
    customer_key: Mapped[str | None] = mapped_column(String(80), index=True)
    environment: Mapped[str | None] = mapped_column(String(80), index=True)
    job_family: Mapped[str | None] = mapped_column(String(120), index=True)


class QueryExecutionLog(TimestampMixin, Base):
    __tablename__ = "query_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("query_templates.id"), index=True)
    query_execution_id: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    connector_config_key: Mapped[str | None] = mapped_column(String(120), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("environments.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="success", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    sample_result: Mapped[list | dict | None] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    sanitized_error_message: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict | None] = mapped_column(JSON, default=dict)
    parameter_hash: Mapped[str | None] = mapped_column(String(128))
    validation_result: Mapped[dict | None] = mapped_column(JSON, default=dict)
    initiated_by: Mapped[str | None] = mapped_column(String(80), default="user")
    ingested_entity_counts: Mapped[dict | None] = mapped_column(JSON, default=dict)
    raw_sql_hash: Mapped[str | None] = mapped_column(String(128))
    raw_sql_storage_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    correlation_id: Mapped[str | None] = mapped_column(String(120), index=True)
    executed_by: Mapped[str | None] = mapped_column(String(160), default="operator")


class RuntimeNode(TimestampMixin, Base):
    __tablename__ = "runtime_nodes"
    __table_args__ = (
        UniqueConstraint("customer_key", "environment", "node_key", name="uq_runtime_node_key"),
        Index("ix_runtime_nodes_scope_type", "customer_key", "environment", "node_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_key: Mapped[str] = mapped_column(String(80), index=True)
    environment: Mapped[str] = mapped_column(String(80), index=True)
    node_type: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    node_key: Mapped[str] = mapped_column(String(160), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    host_name: Mapped[str | None] = mapped_column(String(200), index=True)
    instance_name: Mapped[str | None] = mapped_column(String(160), index=True)
    server_name: Mapped[str | None] = mapped_column(String(200), index=True)
    cluster_name: Mapped[str | None] = mapped_column(String(200), index=True)
    service_name: Mapped[str | None] = mapped_column(String(200))
    availability_domain: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(80), index=True)
    ip_address_hash: Mapped[str | None] = mapped_column(String(160))
    tags: Mapped[dict | None] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    metrics: Mapped[list["RuntimeNodeMetricSample"]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )
    bindings: Mapped[list["JobRunNodeBinding"]] = relationship(back_populates="node")


class RuntimeNodeMetricSample(TimestampMixin, Base):
    __tablename__ = "runtime_node_metric_samples"
    __table_args__ = (
        Index("ix_runtime_node_metrics_lookup", "node_id", "sampled_at", "metric_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("runtime_nodes.id"), index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    metric_name: Mapped[str] = mapped_column(String(120), index=True)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    unit: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(80), default="mock", index=True)
    source_ref: Mapped[str | None] = mapped_column(String(240))

    node: Mapped[RuntimeNode] = relationship(back_populates="metrics")


class JobRunNodeBinding(TimestampMixin, Base):
    __tablename__ = "job_run_node_bindings"
    __table_args__ = (
        UniqueConstraint("run_id", "node_id", "binding_type", name="uq_job_run_node_binding"),
        Index("ix_job_run_node_binding_lookup", "run_id", "binding_type", "confidence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("job_runs.id"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("runtime_nodes.id"), index=True)
    binding_type: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    confidence: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, default=dict)
    query_execution_id: Mapped[int | None] = mapped_column(ForeignKey("query_execution_logs.id"), index=True)

    run: Mapped[JobRun] = relationship(back_populates="node_bindings")
    node: Mapped[RuntimeNode] = relationship(back_populates="bindings")


class DbSessionSnapshot(TimestampMixin, Base):
    __tablename__ = "db_session_snapshots"
    __table_args__ = (
        Index("ix_db_session_snapshot_run_time", "run_id", "sampled_at"),
        Index("ix_db_session_snapshot_sql", "sql_id", "plan_hash_value"),
        Index("ix_db_session_snapshot_identity", "ecid", "client_identifier"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("job_runs.id"), index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    inst_id: Mapped[int | None] = mapped_column(Integer, index=True)
    instance_name: Mapped[str | None] = mapped_column(String(160), index=True)
    db_host_name: Mapped[str | None] = mapped_column(String(200), index=True)
    sid: Mapped[int | None] = mapped_column(Integer, index=True)
    serial_number: Mapped[str | None] = mapped_column(String(80))
    session_status: Mapped[str | None] = mapped_column(String(80), index=True)
    username: Mapped[str | None] = mapped_column(String(160))
    service_name: Mapped[str | None] = mapped_column(String(200))
    module: Mapped[str | None] = mapped_column(String(240), index=True)
    action: Mapped[str | None] = mapped_column(String(240), index=True)
    client_identifier: Mapped[str | None] = mapped_column(String(200), index=True)
    ecid: Mapped[str | None] = mapped_column(String(200), index=True)
    machine: Mapped[str | None] = mapped_column(String(200), index=True)
    program: Mapped[str | None] = mapped_column(String(240))
    process: Mapped[str | None] = mapped_column(String(120))
    sql_id: Mapped[str | None] = mapped_column(String(80), index=True)
    sql_child_number: Mapped[int | None] = mapped_column(Integer)
    sql_exec_start: Mapped[datetime | None] = mapped_column(DateTime)
    last_call_et_seconds: Mapped[int | None] = mapped_column(Integer)
    event: Mapped[str | None] = mapped_column(String(240), index=True)
    wait_class: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str | None] = mapped_column(String(120))
    blocking_instance: Mapped[int | None] = mapped_column(Integer)
    blocking_session: Mapped[int | None] = mapped_column(Integer)
    plan_hash_value: Mapped[str | None] = mapped_column(String(80), index=True)
    row_wait_obj: Mapped[str | None] = mapped_column(String(120))
    query_execution_id: Mapped[int | None] = mapped_column(ForeignKey("query_execution_logs.id"), index=True)

    run: Mapped[JobRun | None] = relationship(back_populates="db_session_snapshots")


class DiagnosticReport(TimestampMixin, Base):
    __tablename__ = "diagnostic_reports"
    __table_args__ = (
        Index("ix_diagnostic_reports_lookup", "customer_key", "environment", "ess_request_id"),
        Index("ix_diagnostic_reports_status", "overall_status", "incident_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("job_runs.id"), index=True)
    customer_key: Mapped[str] = mapped_column(String(80), index=True)
    environment: Mapped[str] = mapped_column(String(80), index=True)
    report_title: Mapped[str] = mapped_column(String(300))
    diagnostic_type: Mapped[str] = mapped_column(String(80), default="slow_job", index=True)
    ess_request_id: Mapped[str | None] = mapped_column(String(120), index=True)
    job_definition: Mapped[str | None] = mapped_column(String(500))
    job_name: Mapped[str | None] = mapped_column(String(200), index=True)
    process_id: Mapped[str | None] = mapped_column(String(120), index=True)
    ecid: Mapped[str | None] = mapped_column(String(160), index=True)
    client_identifier: Mapped[str | None] = mapped_column(String(200), index=True)
    rac_cluster_size: Mapped[int | None] = mapped_column(Integer)
    snapshot_start_at: Mapped[datetime | None] = mapped_column(DateTime)
    snapshot_end_at: Mapped[datetime | None] = mapped_column(DateTime)
    lookback_minutes: Mapped[int | None] = mapped_column(Integer)
    collector_name: Mapped[str | None] = mapped_column(String(200))
    collector_version: Mapped[str | None] = mapped_column(String(80))
    source_package: Mapped[str | None] = mapped_column(String(200))
    freshness_status: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    incident_state: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    executive_summary: Mapped[dict | None] = mapped_column(JSON, default=dict)
    if_you_do_one_thing_today: Mapped[str | None] = mapped_column(Text)
    overall_confidence: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    overall_status: Mapped[str] = mapped_column(String(40), default="warning", index=True)

    run: Mapped[JobRun | None] = relationship(back_populates="diagnostic_reports")
    findings: Mapped[list["DiagnosticFinding"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="DiagnosticFinding.finding_number"
    )
    metrics: Mapped[list["DiagnosticMetric"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="DiagnosticMetric.display_order"
    )
    ruled_out_alternatives: Mapped[list["RuledOutAlternative"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    data_quality_checks: Mapped[list["DiagnosticDataQualityCheck"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class DiagnosticFinding(TimestampMixin, Base):
    __tablename__ = "diagnostic_findings"
    __table_args__ = (
        Index("ix_diagnostic_findings_report_type", "diagnostic_report_id", "finding_type"),
        UniqueConstraint("diagnostic_report_id", "finding_key", name="uq_diagnostic_finding_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    diagnostic_report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_reports.id"), index=True)
    finding_number: Mapped[int] = mapped_column(Integer, default=1)
    finding_key: Mapped[str] = mapped_column(String(200), index=True)
    finding_type: Mapped[str] = mapped_column(String(80), default="UNKNOWN", index=True)
    title: Mapped[str] = mapped_column(String(260))
    severity: Mapped[str] = mapped_column(String(40), default="warning", index=True)
    confidence: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    actionability: Mapped[str] = mapped_column(String(80), default="OBSERVE_ONLY", index=True)
    lifecycle: Mapped[str] = mapped_column(String(40), default="active", index=True)
    problem_statement: Mapped[str | None] = mapped_column(Text)
    business_impact: Mapped[str | None] = mapped_column(Text)
    technical_detail: Mapped[str | None] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    expected_result: Mapped[str | None] = mapped_column(Text)
    approval_gate: Mapped[str | None] = mapped_column(Text)
    owner_team: Mapped[str | None] = mapped_column(String(160), index=True)
    risk_if_done_wrong: Mapped[str | None] = mapped_column(Text)
    rollback_plan: Mapped[str | None] = mapped_column(Text)
    stop_recheck_condition: Mapped[str | None] = mapped_column(Text)
    source_sql_id: Mapped[str | None] = mapped_column(String(80), index=True)
    source_plan_hash_value: Mapped[str | None] = mapped_column(String(80), index=True)
    historical_plan_hash_value: Mapped[str | None] = mapped_column(String(80), index=True)
    package_name: Mapped[str | None] = mapped_column(String(200), index=True)
    object_name: Mapped[str | None] = mapped_column(String(200), index=True)
    value_set_code: Mapped[str | None] = mapped_column(String(200), index=True)
    scope_count: Mapped[int | None] = mapped_column(Integer)
    confirmed_count: Mapped[int | None] = mapped_column(Integer)
    unverified_count: Mapped[int | None] = mapped_column(Integer)
    metrics: Mapped[dict | None] = mapped_column(JSON, default=dict)

    report: Mapped[DiagnosticReport] = relationship(back_populates="findings")
    evidence: Mapped[list["DiagnosticEvidence"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )
    metric_rows: Mapped[list["DiagnosticMetric"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", order_by="DiagnosticMetric.display_order"
    )
    runbook_steps: Mapped[list["DiagnosticRunbookStep"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", order_by="DiagnosticRunbookStep.step_number"
    )
    ruled_out_alternatives: Mapped[list["RuledOutAlternative"]] = relationship(back_populates="finding")


class DiagnosticEvidence(TimestampMixin, Base):
    __tablename__ = "diagnostic_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_findings.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(240))
    query_template_id: Mapped[int | None] = mapped_column(ForeignKey("query_templates.id"), index=True)
    query_execution_id: Mapped[int | None] = mapped_column(ForeignKey("query_execution_logs.id"), index=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text)
    raw_sample: Mapped[list | dict | None] = mapped_column(JSON, default=dict)
    confidence_contribution: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)

    finding: Mapped[DiagnosticFinding] = relationship(back_populates="evidence")


class DiagnosticMetric(TimestampMixin, Base):
    __tablename__ = "diagnostic_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("diagnostic_reports.id"), index=True)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("diagnostic_findings.id"), index=True)
    metric_key: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(200))
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    value_text: Mapped[str | None] = mapped_column(String(300))
    unit: Mapped[str | None] = mapped_column(String(40))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    comparison_baseline: Mapped[str | None] = mapped_column(String(300))
    variance_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    report: Mapped[DiagnosticReport | None] = relationship(back_populates="metrics")
    finding: Mapped[DiagnosticFinding | None] = relationship(back_populates="metric_rows")


class RuledOutAlternative(TimestampMixin, Base):
    __tablename__ = "ruled_out_alternatives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_reports.id"), index=True)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("diagnostic_findings.id"), index=True)
    alternative_type: Mapped[str] = mapped_column(String(80), index=True)
    reason: Mapped[str] = mapped_column(Text)
    supporting_evidence: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="ruled_out", index=True)

    report: Mapped[DiagnosticReport] = relationship(back_populates="ruled_out_alternatives")
    finding: Mapped[DiagnosticFinding | None] = relationship(back_populates="ruled_out_alternatives")


class DiagnosticDataQualityCheck(TimestampMixin, Base):
    __tablename__ = "diagnostic_data_quality_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_reports.id"), index=True)
    check_key: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="passed", index=True)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)

    report: Mapped[DiagnosticReport] = relationship(back_populates="data_quality_checks")


class DiagnosticRunbookStep(TimestampMixin, Base):
    __tablename__ = "diagnostic_runbook_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_findings.id"), index=True)
    step_number: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(60), default="analysis", index=True)
    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str | None] = mapped_column(Text)
    command_text: Mapped[str | None] = mapped_column(Text)
    executable_by_app: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_role: Mapped[str | None] = mapped_column(String(120))
    safety_note: Mapped[str | None] = mapped_column(Text)

    finding: Mapped[DiagnosticFinding] = relationship(back_populates="runbook_steps")


class GlossaryTerm(TimestampMixin, Base):
    __tablename__ = "glossary_terms"
    __table_args__ = (UniqueConstraint("term", "domain", name="uq_glossary_term_domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(160), index=True)
    definition: Mapped[str] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(80), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ReportTemplate(TimestampMixin, Base):
    __tablename__ = "report_templates"
    __table_args__ = (UniqueConstraint("template_key", name="uq_report_template_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    diagnostic_type: Mapped[str] = mapped_column(String(80), default="slow_job", index=True)
    markdown_template: Mapped[str | None] = mapped_column(Text)
    structured_template: Mapped[dict | None] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ConnectorConfig(TimestampMixin, AuditMixin, Base):
    __tablename__ = "connector_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connector_type: Mapped[str] = mapped_column(String(120), index=True)
    config_key: Mapped[str | None] = mapped_column(String(120), index=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    env_var_prefix: Mapped[str | None] = mapped_column(String(160))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("environments.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer)
    fetch_limit: Mapped[int | None] = mapped_column(Integer)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_failed_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    scheduler_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    config: Mapped[dict | None] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="mocked", index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    health_message: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ImportBatch(TimestampMixin, AuditMixin, Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(80), default="manual_plan_csv")
    status: Mapped[str] = mapped_column(String(40), default="imported")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    rows: Mapped[list["ImportedPlanRow"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class ImportedPlanRow(TimestampMixin, Base):
    __tablename__ = "imported_plan_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    step: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str | None] = mapped_column(String(80))
    process_id: Mapped[str | None] = mapped_column(String(120), index=True)
    actual_execution_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    estimated_run_minutes: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    owner: Mapped[str | None] = mapped_column(String(160))
    comment: Mapped[str | None] = mapped_column(Text)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    mapped_run_id: Mapped[int | None] = mapped_column(ForeignKey("job_runs.id"), index=True)
    raw: Mapped[dict | None] = mapped_column(JSON, default=dict)

    batch: Mapped[ImportBatch] = relationship(back_populates="rows")


class PlaybookNote(TimestampMixin, AuditMixin, Base):
    __tablename__ = "playbook_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("environments.id"), index=True)
    job_definition_id: Mapped[int | None] = mapped_column(ForeignKey("job_definitions.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("job_runs.id"), index=True)
    note_date: Mapped[date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), default="watch")
    owner: Mapped[str | None] = mapped_column(String(160))
