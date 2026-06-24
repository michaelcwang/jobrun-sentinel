"""phase 2 connector schema

Revision ID: 0002_phase2_connector_schema
Revises: 0001_initial_schema
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_phase2_connector_schema"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _add_missing_columns(
        "job_runs",
        [
            sa.Column("source_type", sa.String(length=80), nullable=True, server_default="seed"),
            sa.Column("source_connector", sa.String(length=120), nullable=True),
            sa.Column("source_template_id", sa.String(length=120), nullable=True),
            sa.Column("source_query_execution_id", sa.Integer(), nullable=True),
            sa.Column("ingested_at", sa.DateTime(), nullable=True),
        ],
    )
    _add_missing_columns(
        "query_templates",
        [
            sa.Column("connector_type", sa.String(length=80), nullable=True, server_default="oracle_db"),
            sa.Column("template_category", sa.String(length=80), nullable=True, server_default="diagnostic"),
            sa.Column("default_parameters", sa.JSON(), nullable=True),
            sa.Column("is_read_only_validated", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("last_executed_at", sa.DateTime(), nullable=True),
            sa.Column("validation_error", sa.Text(), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column("customer_key", sa.String(length=80), nullable=True),
            sa.Column("environment", sa.String(length=80), nullable=True),
            sa.Column("job_family", sa.String(length=120), nullable=True),
        ],
    )
    _add_missing_columns(
        "query_execution_logs",
        [
            sa.Column("query_execution_id", sa.String(length=80), nullable=True),
            sa.Column("connector_config_key", sa.String(length=120), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("elapsed_ms", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(length=80), nullable=True),
            sa.Column("sanitized_error_message", sa.Text(), nullable=True),
            sa.Column("parameter_hash", sa.String(length=128), nullable=True),
            sa.Column("validation_result", sa.JSON(), nullable=True),
            sa.Column("initiated_by", sa.String(length=80), nullable=True, server_default="user"),
            sa.Column("ingested_entity_counts", sa.JSON(), nullable=True),
            sa.Column("raw_sql_hash", sa.String(length=128), nullable=True),
            sa.Column("raw_sql_storage_enabled", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("correlation_id", sa.String(length=120), nullable=True),
        ],
    )
    _add_missing_columns(
        "connector_configs",
        [
            sa.Column("config_key", sa.String(length=120), nullable=True),
            sa.Column("display_name", sa.String(length=200), nullable=True),
            sa.Column("env_var_prefix", sa.String(length=160), nullable=True),
            sa.Column("timeout_seconds", sa.Integer(), nullable=True),
            sa.Column("fetch_limit", sa.Integer(), nullable=True),
            sa.Column("last_successful_sync_at", sa.DateTime(), nullable=True),
            sa.Column("last_failed_sync_at", sa.DateTime(), nullable=True),
            sa.Column("scheduler_heartbeat_at", sa.DateTime(), nullable=True),
        ],
    )
    _create_missing_indexes()


def downgrade() -> None:
    # The first migration creates tables from current metadata in this MVP, so a
    # destructive downgrade here can break fresh databases. Leave Phase 2 columns
    # in place and let full environment rebuilds use 0001 downgrade when needed.
    pass


def _add_missing_columns(table_name: str, columns: list[sa.Column]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def _create_missing_indexes() -> None:
    indexes = {
        "job_runs": [
            ("ix_job_runs_source_template_id", ["source_template_id"]),
            ("ix_job_runs_source_query_execution_id", ["source_query_execution_id"]),
        ],
        "query_templates": [
            ("ix_query_templates_connector_type", ["connector_type"]),
            ("ix_query_templates_template_category", ["template_category"]),
            ("ix_query_templates_is_read_only_validated", ["is_read_only_validated"]),
            ("ix_query_templates_customer_key", ["customer_key"]),
            ("ix_query_templates_environment", ["environment"]),
            ("ix_query_templates_job_family", ["job_family"]),
        ],
        "query_execution_logs": [
            ("ix_query_execution_logs_query_execution_id", ["query_execution_id"], True),
            ("ix_query_execution_logs_connector_config_key", ["connector_config_key"]),
            ("ix_query_execution_logs_correlation_id", ["correlation_id"]),
        ],
        "connector_configs": [
            ("ix_connector_configs_config_key", ["config_key"]),
        ],
    }
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    for table_name, table_indexes in indexes.items():
        if table_name not in table_names:
            continue
        existing = {index["name"] for index in inspector.get_indexes(table_name)}
        for item in table_indexes:
            name, columns, *unique = item
            if name not in existing:
                op.create_index(name, table_name, columns, unique=bool(unique and unique[0]))
