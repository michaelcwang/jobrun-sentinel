from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import os
import re
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.mock import MockConnectorRegistry
from app.connectors.oracle import OracleConnectorConfigResolver, RealOracleDbConnector
from app.core.config import Settings, get_settings
from app.models import ConnectorConfig, Customer, Environment, QueryExecutionLog, QueryTemplate
from app.models.base import utcnow
from app.services.query_guard import QueryValidationError, validate_read_only_template


@dataclass
class QueryExecutionSummary:
    log: QueryExecutionLog
    rows: list[dict[str, Any]] = field(default_factory=list)
    validation_error: str | None = None


class QueryTemplateExecutionService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    def validate_template(self, template: QueryTemplate) -> dict[str, Any]:
        try:
            result = validate_read_only_template(
                template.sql_text,
                allowed_objects=self.settings.sql_allowlist or None,
            )
        except QueryValidationError as exc:
            template.is_read_only_validated = False
            template.validation_error = str(exc)
            template.last_validated_at = utcnow()
            self.db.flush()
            return {"is_valid": False, "error": str(exc), "bind_names": [], "referenced_objects": []}

        template.is_read_only_validated = True
        template.validation_error = None
        template.last_validated_at = utcnow()
        self.db.flush()
        return {
            "is_valid": True,
            "error": None,
            "bind_names": result.bind_names,
            "referenced_objects": result.referenced_objects,
        }

    def execute(
        self,
        template: QueryTemplate,
        *,
        customer_key: str | None,
        environment_name: str | None,
        parameters: dict[str, Any] | None = None,
        connector_config_key: str | None = None,
        initiated_by: str = "user",
        executed_by: str = "operator",
        validate_only: bool = False,
    ) -> QueryExecutionSummary:
        started_at = utcnow()
        started = perf_counter()
        parameters = {**(template.default_parameters or {}), **(parameters or {})}
        connector_config = self._resolve_connector_config(connector_config_key, customer_key, environment_name)
        customer = self._customer(customer_key)
        environment = self._environment(customer, environment_name)
        validation_payload: dict[str, Any]
        rows: list[dict[str, Any]] = []
        status = "success"
        error_code = None
        sanitized_error_message = None

        try:
            validation_payload = self.validate_template(template)
            if not validation_payload["is_valid"]:
                raise QueryValidationError(validation_payload["error"] or "SQL template validation failed.")
            missing = self._missing_parameters(template, parameters)
            if missing:
                raise QueryValidationError(f"Missing required parameters: {', '.join(missing)}")
            if validate_only:
                status = "validated"
            else:
                connector = self._connector(connector_config)
                rows = connector.execute_template(
                    template.sql_text,
                    parameters,
                    timeout_seconds=self._timeout(connector_config),
                    row_limit=self._fetch_limit(connector_config),
                )
                rows = rows[: self._fetch_limit(connector_config)]
        except QueryValidationError as exc:
            status = "blocked"
            error_code = "VALIDATION_BLOCKED"
            sanitized_error_message = str(exc)
            validation_payload = {"is_valid": False, "error": str(exc)}
        except TimeoutError as exc:
            status = "timeout"
            error_code = "QUERY_TIMEOUT"
            sanitized_error_message = _sanitize_error(exc)
            validation_payload = {"is_valid": True}
        except Exception as exc:
            status = "failed"
            error_code = "QUERY_FAILED"
            sanitized_error_message = _sanitize_error(exc)
            validation_payload = {"is_valid": True}

        finished_at = utcnow()
        elapsed_ms = int((perf_counter() - started) * 1000)
        template.last_executed_at = finished_at if status in {"success", "validated"} else template.last_executed_at
        log = QueryExecutionLog(
            query_execution_id=f"qe-{uuid4().hex[:12]}",
            template_id=template.id,
            connector_config_key=connector_config.config_key if connector_config else (connector_config_key or self.settings.oracle_default_config_key),
            customer_id=customer.id if customer else None,
            environment_id=environment.id if environment else None,
            status=status,
            started_at=started_at,
            ended_at=finished_at,
            finished_at=finished_at,
            row_count=len(rows),
            elapsed_ms=elapsed_ms,
            sample_result=_sample(rows),
            error=sanitized_error_message,
            error_code=error_code,
            sanitized_error_message=sanitized_error_message,
            parameters=_sanitize_parameters(parameters),
            parameter_hash=_hash_json(parameters),
            validation_result=validation_payload,
            initiated_by=initiated_by,
            raw_sql_hash=_hash_text(template.sql_text),
            raw_sql_storage_enabled=self.settings.allow_raw_query_text_storage,
            correlation_id=f"corr-{uuid4().hex[:10]}",
            executed_by=executed_by,
        )
        self.db.add(log)
        self.db.flush()
        return QueryExecutionSummary(log=log, rows=rows, validation_error=sanitized_error_message)

    def _resolve_connector_config(
        self, connector_config_key: str | None, customer_key: str | None, environment_name: str | None
    ) -> ConnectorConfig | None:
        stmt = select(ConnectorConfig).where(ConnectorConfig.connector_type.in_(["OracleDbConnector", "oracle_db"]))
        if connector_config_key:
            stmt = stmt.where(ConnectorConfig.config_key == connector_config_key)
        configs = list(self.db.scalars(stmt.order_by(ConnectorConfig.id.asc())))
        if not configs:
            return None
        if customer_key:
            for config in configs:
                if (config.config or {}).get("customer_key") == customer_key:
                    return config
        return configs[0]

    def _connector(self, connector_config: ConnectorConfig | None):
        if self.settings.connector_mode == "oracle" and self.settings.allow_oracle_connector:
            config_key = connector_config.config_key if connector_config and connector_config.config_key else None
            env_var_prefix = connector_config.env_var_prefix if connector_config else None
            oracle_settings = OracleConnectorConfigResolver(self.settings).resolve(config_key, env_var_prefix)
            return RealOracleDbConnector(oracle_settings)
        return MockConnectorRegistry().oracle_db

    def _timeout(self, connector_config: ConnectorConfig | None) -> int:
        return connector_config.timeout_seconds if connector_config and connector_config.timeout_seconds else self.settings.oracle_query_timeout_seconds

    def _fetch_limit(self, connector_config: ConnectorConfig | None) -> int:
        return connector_config.fetch_limit if connector_config and connector_config.fetch_limit else self.settings.oracle_fetch_limit

    def _customer(self, customer_key: str | None) -> Customer | None:
        if not customer_key:
            return None
        return self.db.scalar(select(Customer).where(Customer.customer_key == customer_key))

    def _environment(self, customer: Customer | None, environment_name: str | None) -> Environment | None:
        if not customer or not environment_name:
            return None
        return self.db.scalar(
            select(Environment).where(Environment.customer_id == customer.id, Environment.name == environment_name)
        )

    @staticmethod
    def _missing_parameters(template: QueryTemplate, parameters: dict[str, Any]) -> list[str]:
        schema = template.required_parameters or {}
        return [name for name in schema.keys() if name not in parameters]


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: dict[str, Any]) -> str:
    return _hash_text(json.dumps(_sanitize_parameters(value), sort_keys=True, default=str))


def _sanitize_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in parameters.items():
        if any(token in key.lower() for token in ["password", "secret", "token", "wallet"]):
            sanitized[key] = "[redacted]"
        else:
            sanitized[key] = value
    return sanitized


def _sanitize_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ")
    for key, value in os.environ.items():
        if value and any(token in key.lower() for token in ["password", "secret", "token", "wallet", "dsn"]):
            message = message.replace(value, "[redacted]")
    message = re.sub(r"(?i)(password|token|secret|wallet|dsn)\s*[:=]\s*[^,\s;]+", r"\1=[redacted]", message)
    return message[:500]


def _sample(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_sanitize_parameters(row) for row in rows[:10]]
