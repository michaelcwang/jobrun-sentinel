from dataclasses import dataclass
import os
from typing import Any

from app.connectors.base import OracleDbConnector
from app.core.config import Settings, get_settings
from app.services.query_guard import apply_oracle_row_limit, validate_read_only_template


@dataclass(frozen=True)
class OracleConnectorSettings:
    config_key: str
    env_var_prefix: str
    user: str | None
    password: str | None
    dsn: str | None
    tns_admin: str | None
    wallet_location: str | None
    wallet_password: str | None
    client_mode: str
    query_timeout_seconds: int
    fetch_limit: int
    connect_timeout_seconds: int
    enabled: bool

    @property
    def has_required_credentials(self) -> bool:
        return bool(self.enabled and self.user and self.password and self.dsn)

    def safe_summary(self) -> dict[str, Any]:
        return {
            "config_key": self.config_key,
            "env_var_prefix": self.env_var_prefix,
            "client_mode": self.client_mode,
            "dsn_configured": bool(self.dsn),
            "user_configured": bool(self.user),
            "password_configured": bool(self.password),
            "tns_admin_configured": bool(self.tns_admin),
            "wallet_location_configured": bool(self.wallet_location),
            "wallet_password_configured": bool(self.wallet_password),
            "query_timeout_seconds": self.query_timeout_seconds,
            "fetch_limit": self.fetch_limit,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "enabled": self.enabled,
        }


class OracleConnectorConfigResolver:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def resolve(self, config_key: str | None = None, env_var_prefix: str | None = None) -> OracleConnectorSettings:
        key = (config_key or self.settings.oracle_default_config_key or "demo").upper()
        prefix = env_var_prefix or f"JOBRUN_ORACLE_{key}"
        return OracleConnectorSettings(
            config_key=key.lower(),
            env_var_prefix=prefix,
            user=os.getenv(f"{prefix}_USER"),
            password=os.getenv(f"{prefix}_PASSWORD"),
            dsn=os.getenv(f"{prefix}_DSN"),
            tns_admin=os.getenv(f"{prefix}_TNS_ADMIN") or self.settings.oracle_tns_admin,
            wallet_location=os.getenv(f"{prefix}_WALLET_LOCATION") or self.settings.oracle_wallet_location,
            wallet_password=os.getenv(f"{prefix}_WALLET_PASSWORD"),
            client_mode=(os.getenv(f"{prefix}_CLIENT_MODE") or self.settings.oracle_driver_mode).lower(),
            query_timeout_seconds=int(
                os.getenv(f"{prefix}_QUERY_TIMEOUT_SECONDS") or self.settings.oracle_query_timeout_seconds
            ),
            fetch_limit=int(os.getenv(f"{prefix}_FETCH_LIMIT") or self.settings.oracle_fetch_limit),
            connect_timeout_seconds=int(
                os.getenv(f"{prefix}_CONNECT_TIMEOUT_SECONDS") or self.settings.oracle_connect_timeout_seconds
            ),
            enabled=self.settings.allow_oracle_connector and self.settings.connector_mode == "oracle",
        )


class OracleConnectorUnavailable(RuntimeError):
    pass


class RealOracleDbConnector(OracleDbConnector):
    def __init__(self, connector_settings: OracleConnectorSettings | None = None):
        self.connector_settings = connector_settings or OracleConnectorConfigResolver().resolve()

    def health_check(self) -> dict[str, Any]:
        summary = self.connector_settings.safe_summary()
        if not self.connector_settings.enabled:
            return {
                "status": "disabled",
                "message": "Oracle connector is disabled. Local mock mode remains active.",
                "config": summary,
            }
        if not self.connector_settings.has_required_credentials:
            return {
                "status": "missing_credentials",
                "message": "Oracle connector is enabled but required env vars are missing.",
                "config": summary,
            }
        try:
            self.execute_template(
                "SELECT 1 AS HEALTH_VALUE FROM dual WHERE 1 = :health_check",
                {"health_check": 1},
                timeout_seconds=min(self.connector_settings.query_timeout_seconds, 10),
                row_limit=1,
            )
        except Exception as exc:
            return {"status": "error", "message": _sanitize_error(exc), "config": summary}
        return {"status": "healthy", "message": "Read-only Oracle health check succeeded.", "config": summary}

    def execute_template(
        self,
        sql_text: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
        row_limit: int,
        validate_only: bool = False,
    ) -> list[dict[str, Any]]:
        allowed_objects = get_settings().sql_allowlist or None
        if allowed_objects is not None:
            allowed_objects = [*allowed_objects, "dual"]
        validate_read_only_template(sql_text, allowed_objects=allowed_objects)
        if validate_only:
            return []
        if not self.connector_settings.has_required_credentials:
            raise OracleConnectorUnavailable("Oracle connector is not configured with required read-only credentials.")

        try:
            import oracledb  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise OracleConnectorUnavailable("python-oracledb is not installed in this environment.") from exc

        settings = self.connector_settings
        if settings.client_mode == "thick":  # pragma: no cover - needs Oracle client
            init_kwargs = {}
            if settings.tns_admin:
                init_kwargs["config_dir"] = settings.tns_admin
            oracledb.init_oracle_client(**init_kwargs)

        connect_kwargs: dict[str, Any] = {
            "user": settings.user,
            "password": settings.password,
            "dsn": settings.dsn,
            "tcp_connect_timeout": settings.connect_timeout_seconds,
        }
        if settings.tns_admin:
            connect_kwargs["config_dir"] = settings.tns_admin
        if settings.wallet_location:
            connect_kwargs["wallet_location"] = settings.wallet_location
        if settings.wallet_password:
            connect_kwargs["wallet_password"] = settings.wallet_password

        limited_sql = apply_oracle_row_limit(sql_text, min(row_limit, settings.fetch_limit))
        bind_parameters = dict(parameters)
        bind_parameters["__jobrun_row_limit"] = min(row_limit, settings.fetch_limit)

        try:
            with oracledb.connect(**connect_kwargs) as connection:
                with connection.cursor() as cursor:
                    cursor.call_timeout = int(timeout_seconds * 1000)
                    cursor.execute(limited_sql, bind_parameters)
                    columns = [column[0] for column in cursor.description or []]
                    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchmany(bind_parameters["__jobrun_row_limit"])]
        except Exception as exc:
            raise OracleConnectorUnavailable(_sanitize_error(exc)) from exc


def _sanitize_error(exc: Exception) -> str:
    message = str(exc)
    for key, value in os.environ.items():
        if "PASSWORD" in key or "TOKEN" in key or "SECRET" in key or key.endswith("_DSN"):
            if value:
                message = message.replace(value, "[redacted]")
    return message[:500]
