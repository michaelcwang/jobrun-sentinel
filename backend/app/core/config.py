from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "JobRun Sentinel"
    environment: str = "local"
    database_url: str = "sqlite:///./jobrun_sentinel.db"
    auto_seed: bool = True
    auto_seed_scale: bool = False
    scale_seed_customer_count: int = 10
    scale_seed_jobs_per_customer: int = 25
    connector_mode: Literal["mock", "oracle"] = Field(default="mock", validation_alias="JOBRUN_CONNECTOR_MODE")
    allow_oracle_connector: bool = Field(default=False, validation_alias="JOBRUN_ALLOW_ORACLE_CONNECTOR")
    allow_raw_query_text_storage: bool = Field(
        default=False,
        validation_alias=AliasChoices("ALLOW_RAW_QUERY_TEXT_STORAGE", "JOBRUN_ALLOW_RAW_QUERY_TEXT"),
    )
    source_access_mode: Literal["read_only"] = "read_only"
    destructive_source_operations_allowed: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
        ]
    )
    scheduler_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("SCHEDULER_ENABLED", "JOBRUN_SCHEDULER_ENABLED"),
    )
    scheduler_interval_seconds: int = Field(default=300, validation_alias="JOBRUN_SCHEDULER_INTERVAL_SECONDS")
    scheduler_max_concurrency: int = Field(default=2, validation_alias="JOBRUN_SCHEDULER_MAX_CONCURRENCY")
    default_alert_dashboard_url: str = "http://localhost:5173/dashboard"
    oracle_default_config_key: str = Field(default="demo", validation_alias="JOBRUN_ORACLE_DEFAULT_CONFIG_KEY")
    oracle_driver_mode: Literal["thin", "thick"] = "thin"
    oracle_tns_admin: str | None = None
    oracle_wallet_location: str | None = None
    oracle_query_timeout_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices("ORACLE_QUERY_TIMEOUT_SECONDS", "JOBRUN_ORACLE_QUERY_TIMEOUT_SECONDS"),
    )
    oracle_fetch_limit: int = Field(default=500, validation_alias="JOBRUN_ORACLE_FETCH_LIMIT")
    oracle_connect_timeout_seconds: int = Field(default=15, validation_alias="JOBRUN_ORACLE_CONNECT_TIMEOUT_SECONDS")
    query_template_row_limit: int = Field(default=250, validation_alias="QUERY_TEMPLATE_ROW_LIMIT")
    query_catalog_source_url: str | None = Field(default=None, validation_alias="JOBRUN_QUERY_CATALOG_SOURCE_URL")
    confluence_pat: str | None = Field(default=None, validation_alias="JOBRUN_CONFLUENCE_PAT")
    confluence_username: str | None = Field(default=None, validation_alias="JOBRUN_CONFLUENCE_USERNAME")
    confluence_base_url: str | None = Field(default=None, validation_alias="JOBRUN_CONFLUENCE_BASE_URL")
    sql_allowlist: list[str] = Field(default_factory=list, validation_alias="JOBRUN_SQL_ALLOWLIST")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
