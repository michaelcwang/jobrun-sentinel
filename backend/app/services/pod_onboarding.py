from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConnectorConfig, Customer, Environment, QueryTemplate
from app.models.base import utcnow
from app.services.ingestion import QueryTemplateIngestionService
from app.services.query_catalog import QueryCatalogImporter
from app.services.query_execution import QueryTemplateExecutionService


STOCK_DISCOVERY_TEMPLATE_ID = "icm_active_long_running_jobs"


@dataclass
class PodOnboardingSummary:
    customer: Customer
    environment: Environment
    connector_config: ConnectorConfig
    stock_catalog: dict[str, Any] = field(default_factory=dict)
    stock_template_ids: list[str] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    initial_fetch: dict[str, Any] | None = None
    next_steps: list[str] = field(default_factory=list)


class CustomerPodOnboardingService:
    """Creates the local Sentinel control-plane records for a target customer pod.

    The service only writes to Sentinel's own database. Target customer pods are
    accessed later through read-only query-template execution, which keeps
    onboarding safe for production and useful in local mock mode.
    """

    def __init__(self, db: Session):
        self.db = db

    def onboard(
        self,
        *,
        customer_key: str,
        display_name: str | None = None,
        environment_name: str = "PROD",
        region: str | None = None,
        lifecycle: str = "prod",
        connector_type: str = "OracleDbConnector",
        config_key: str | None = None,
        env_var_prefix: str | None = None,
        apply_stock_templates: bool = True,
        run_initial_fetch: bool = False,
        minimum_elapsed_minutes: int = 120,
        notes: str | None = None,
        created_by: str = "operator",
    ) -> PodOnboardingSummary:
        normalized_key = _normalize_customer_key(customer_key)
        environment_name = environment_name.strip().upper() or "PROD"
        customer = self._upsert_customer(normalized_key, display_name, created_by)
        environment = self._upsert_environment(customer, environment_name, region, lifecycle, created_by)
        connector_config = self._upsert_connector_config(
            customer=customer,
            environment=environment,
            connector_type=connector_type,
            config_key=config_key or _default_config_key(normalized_key, environment_name),
            env_var_prefix=env_var_prefix or _default_env_prefix(normalized_key, environment_name),
            notes=notes,
            created_by=created_by,
        )

        stock_catalog: dict[str, Any] = {}
        if apply_stock_templates:
            stock_catalog = QueryCatalogImporter(self.db).import_bundled(initiated_by="pod_onboarding")

        stock_templates = self._stock_templates()
        validation_results = [
            {
                "template_id": template.template_id,
                "name": template.name,
                "category": template.template_category,
                **QueryTemplateExecutionService(self.db).validate_template(template),
            }
            for template in stock_templates
        ]

        initial_fetch = None
        if run_initial_fetch:
            initial_fetch = self._run_initial_fetch(
                customer_key=customer.customer_key,
                environment_name=environment.name,
                connector_config_key=connector_config.config_key,
                minimum_elapsed_minutes=minimum_elapsed_minutes,
            )

        connector_config.config = {
            **(connector_config.config or {}),
            "customer_key": customer.customer_key,
            "environment": environment.name,
            "onboarding": {
                "status": "ready_for_read_only_discovery",
                "stock_templates_applied": apply_stock_templates,
                "stock_template_ids": [template.template_id for template in stock_templates],
                "custom_metrics_import_path": "/imports",
                "last_onboarded_at": utcnow().isoformat(),
            },
        }
        self.db.flush()
        return PodOnboardingSummary(
            customer=customer,
            environment=environment,
            connector_config=connector_config,
            stock_catalog=stock_catalog,
            stock_template_ids=[template.template_id for template in stock_templates],
            validation_results=validation_results,
            initial_fetch=initial_fetch,
            next_steps=[
                "Confirm connector health in Sources.",
                "Review stock query templates and keep only approved templates active for the pod.",
                "Run one read-only discovery sync before enabling scheduler polling.",
                "Upload customer-specific plan rows or custom volume metrics from Imports.",
            ],
        )

    def _upsert_customer(self, customer_key: str, display_name: str | None, actor: str) -> Customer:
        customer = self.db.scalar(select(Customer).where(Customer.customer_key == customer_key))
        if customer is None:
            customer = Customer(customer_key=customer_key, display_name=display_name or customer_key.replace("_", " "), tier="onboarded")
            customer.created_by = actor
            self.db.add(customer)
        else:
            customer.display_name = display_name or customer.display_name
            customer.active = True
        customer.updated_by = actor
        self.db.flush()
        return customer

    def _upsert_environment(
        self, customer: Customer, environment_name: str, region: str | None, lifecycle: str, actor: str
    ) -> Environment:
        environment = self.db.scalar(
            select(Environment).where(Environment.customer_id == customer.id, Environment.name == environment_name)
        )
        if environment is None:
            environment = Environment(
                customer_id=customer.id,
                name=environment_name,
                region=region or "global",
                lifecycle=lifecycle or "prod",
            )
            environment.created_by = actor
            self.db.add(environment)
        else:
            environment.region = region or environment.region
            environment.lifecycle = lifecycle or environment.lifecycle
        environment.updated_by = actor
        self.db.flush()
        return environment

    def _upsert_connector_config(
        self,
        *,
        customer: Customer,
        environment: Environment,
        connector_type: str,
        config_key: str,
        env_var_prefix: str,
        notes: str | None,
        created_by: str,
    ) -> ConnectorConfig:
        config = self.db.scalar(select(ConnectorConfig).where(ConnectorConfig.config_key == config_key))
        if config is None:
            config = ConnectorConfig(
                connector_type=connector_type,
                config_key=config_key,
                name=f"{customer.display_name} {environment.name} read-only connector",
                display_name=f"{customer.display_name} {environment.name}",
                env_var_prefix=env_var_prefix,
                customer_id=customer.id,
                environment_id=environment.id,
                timeout_seconds=60,
                fetch_limit=500,
                status="configured",
                health_message="Configured for read-only pod discovery. Run health check before scheduler use.",
                enabled=True,
                config={},
            )
            config.created_by = created_by
            self.db.add(config)
        config.connector_type = connector_type
        config.customer_id = customer.id
        config.environment_id = environment.id
        config.display_name = f"{customer.display_name} {environment.name}"
        config.env_var_prefix = env_var_prefix
        config.last_checked_at = utcnow()
        config.health_message = "Configured for read-only pod discovery. Run health check before scheduler use."
        config.config = {
            **(config.config or {}),
            "customer_key": customer.customer_key,
            "environment": environment.name,
            "notes": notes,
            "secrets_location": "environment_or_secret_manager",
            "secrets_are_persisted": False,
        }
        config.updated_by = created_by
        self.db.flush()
        return config

    def _stock_templates(self) -> list[QueryTemplate]:
        templates = list(
            self.db.scalars(
                select(QueryTemplate)
                .where(
                    QueryTemplate.connector_type == "oracle_db",
                    QueryTemplate.template_category.in_(
                        [
                            "job_status",
                            "job_history",
                            "baseline_candidate",
                            "volume_snapshot",
                            "sql_observation",
                            "diagnostic",
                        ]
                    ),
                )
                .order_by(QueryTemplate.template_category.asc(), QueryTemplate.template_id.asc())
            )
        )
        return templates

    def _run_initial_fetch(
        self,
        *,
        customer_key: str,
        environment_name: str,
        connector_config_key: str | None,
        minimum_elapsed_minutes: int,
    ) -> dict[str, Any]:
        template = self.db.scalar(select(QueryTemplate).where(QueryTemplate.template_id == STOCK_DISCOVERY_TEMPLATE_ID))
        if template is None:
            return {
                "status": "skipped",
                "message": f"Stock discovery template {STOCK_DISCOVERY_TEMPLATE_ID} was not found.",
            }
        summary = QueryTemplateIngestionService(self.db).ingest(
            template,
            customer_key=customer_key,
            environment_name=environment_name,
            connector_config_key=connector_config_key,
            parameters={
                "minimum_elapsed_minutes": minimum_elapsed_minutes,
                "customer_key": customer_key,
            },
            initiated_by="pod_onboarding",
            executed_by="operator",
        )
        return {
            "status": summary.execution.log.status,
            "query_execution_id": summary.execution.log.query_execution_id,
            "ingested_entity_counts": summary.ingested_entity_counts,
            "affected_run_ids": summary.affected_run_ids,
            "evaluations": summary.evaluations,
        }


def _normalize_customer_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_").upper()
    if not normalized:
        raise ValueError("customer_key is required")
    return normalized[:80]


def _default_config_key(customer_key: str, environment_name: str) -> str:
    return f"{customer_key.lower()}_{environment_name.lower()}"


def _default_env_prefix(customer_key: str, environment_name: str) -> str:
    return f"JOBRUN_ORACLE_{customer_key}_{environment_name}"
