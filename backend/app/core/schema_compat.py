from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.models import Base


def ensure_sqlite_phase2_columns(engine: Engine) -> None:
    """Add newly introduced nullable/defaulted columns for existing local SQLite DBs.

    Production deployments should apply Alembic migrations. This helper is intentionally
    scoped to SQLite so the local demo database can survive incremental MVP changes.
    """
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns or column.primary_key:
                    continue
                column_type = column.type.compile(dialect=engine.dialect)
                default_sql = _sqlite_default(column.name)
                connection.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}{default_sql}')
                )


def _sqlite_default(column_name: str) -> str:
    if column_name in {
        "connector_type",
        "template_category",
        "status",
        "initiated_by",
        "executed_by",
        "source_type",
    }:
        defaults = {
            "connector_type": "oracle_db",
            "template_category": "diagnostic",
            "status": "success",
            "initiated_by": "user",
            "executed_by": "operator",
            "source_type": "seed",
        }
        return f" DEFAULT '{defaults[column_name]}'"
    if column_name in {
        "is_read_only_validated",
        "raw_sql_storage_enabled",
    }:
        return " DEFAULT 0"
    if column_name in {"active", "enabled"}:
        return " DEFAULT 1"
    return ""
