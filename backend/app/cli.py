import argparse
import json
from typing import Any

from sqlalchemy import select

from app.connectors.oracle import OracleConnectorConfigResolver, RealOracleDbConnector
from app.core.database import SessionLocal, engine
from app.core.schema_compat import ensure_sqlite_phase2_columns
from app.models import Base, ConnectorConfig, QueryTemplate
from app.live_traffic import run_live_traffic
from app.services.query_catalog import QueryCatalogImporter
from app.services.query_execution import QueryTemplateExecutionService
from app.services.scheduler import run_sync_once


def main() -> None:
    parser = argparse.ArgumentParser(description="JobRun Sentinel Phase 2 management commands")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("import-query-catalog", help="Import the bundled read-only ICM query catalog")
    subcommands.add_parser("validate-templates", help="Validate all active SQL templates")
    subcommands.add_parser("sync-once", help="Run one mock/Oracle ingestion cycle for active templates")
    subcommands.add_parser("connector-health", help="Show mock and Oracle connector health without secrets")
    live = subcommands.add_parser("live-traffic", help="Generate live synthetic Customer A/B incidents")
    live.add_argument(
        "--scenario",
        action="append",
        help="Scenario or group: all, customer-a, customer-b, customer-a-apj-udq, customer-a-middleware-gc, customer-b-revert-regression, customer-b-learning-mode.",
    )
    live.add_argument("--cycles", type=int, default=1)
    live.add_argument("--interval-seconds", type=float, default=0)
    live.add_argument("--no-diagnostics", action="store_true")
    live.add_argument("--reset-live", action="store_true")
    live.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    ensure_sqlite_phase2_columns(engine)

    db = SessionLocal()
    try:
        if args.command == "import-query-catalog":
            _print(QueryCatalogImporter(db).import_bundled(initiated_by="cli"))
            db.commit()
        elif args.command == "validate-templates":
            _print(_validate_templates(db))
            db.commit()
        elif args.command == "sync-once":
            _print(run_sync_once(db, initiated_by="cli"))
            db.commit()
        elif args.command == "connector-health":
            _print(_connector_health(db))
        elif args.command == "live-traffic":
            _print(
                run_live_traffic(
                    db,
                    scenario_names=args.scenario or ["all"],
                    cycles=args.cycles,
                    interval_seconds=args.interval_seconds,
                    generate_diagnostics=not args.no_diagnostics,
                    reset_live=args.reset_live,
                    base_url=args.base_url,
                )
            )
            db.commit()
    finally:
        db.close()


def _validate_templates(db) -> dict[str, Any]:
    service = QueryTemplateExecutionService(db)
    results = []
    for template in db.scalars(select(QueryTemplate).where(QueryTemplate.active.is_(True)).order_by(QueryTemplate.template_id.asc())):
        result = service.validate_template(template)
        results.append(
            {
                "template_id": template.template_id,
                "is_valid": result["is_valid"],
                "error": result.get("error"),
                "bind_names": result.get("bind_names", []),
                "referenced_objects": result.get("referenced_objects", []),
            }
        )
    return {"template_count": len(results), "results": results}


def _connector_health(db) -> dict[str, Any]:
    configs = list(db.scalars(select(ConnectorConfig).order_by(ConnectorConfig.config_key.asc())))
    oracle_status = []
    for config in configs:
        if config.connector_type != "OracleDbConnector":
            continue
        connector_settings = OracleConnectorConfigResolver().resolve(
            config_key=config.config_key,
            env_var_prefix=config.env_var_prefix,
        )
        oracle_status.append(
            {
                "config_key": config.config_key,
                "display_name": config.display_name,
                "health": RealOracleDbConnector(connector_settings).health_check(),
            }
        )
    return {
        "mock": {"status": "healthy", "message": "Mock connector is always available for local/demo mode."},
        "oracle": oracle_status,
    }


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, default=str, indent=2))


if __name__ == "__main__":
    main()
