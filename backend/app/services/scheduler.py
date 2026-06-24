from datetime import datetime
from threading import Lock
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models import ConnectorConfig, QueryTemplate
from app.models.base import utcnow
from app.services.ingestion import QueryTemplateIngestionService

_active_keys: set[str] = set()
_lock = Lock()
_scheduler: BackgroundScheduler | None = None


def scheduler_enabled(settings: Settings | None = None) -> bool:
    return (settings or get_settings()).scheduler_enabled


def run_sync_once(db: Session, *, initiated_by: str = "scheduler") -> dict[str, Any]:
    started_at = utcnow()
    templates = list(
        db.scalars(
            select(QueryTemplate)
            .where(QueryTemplate.active.is_(True), QueryTemplate.connector_type == "oracle_db")
            .order_by(QueryTemplate.template_id.asc())
        )
    )
    executions = []
    for template in templates:
        if not template.output_mapping or not template.default_parameters:
            continue
        key = f"{template.template_id}:default"
        if not _acquire(key):
            continue
        try:
            customer_key = template.customer_key or "CUST_A"
            environment = template.environment or "PROD"
            summary = QueryTemplateIngestionService(db).ingest(
                template,
                customer_key=customer_key,
                environment_name=environment,
                parameters=template.default_parameters or {},
                initiated_by=initiated_by,
                executed_by="scheduler",
            )
            executions.append(
                {
                    "query_execution_id": summary.execution.log.query_execution_id,
                    "status": summary.execution.log.status,
                    "ingested_entity_counts": summary.ingested_entity_counts,
                    "affected_run_ids": summary.affected_run_ids,
                    "evaluations": summary.evaluations,
                }
            )
        except Exception as exc:
            executions.append(
                {
                    "query_execution_id": None,
                    "status": "failed",
                    "ingested_entity_counts": {},
                    "affected_run_ids": [],
                    "evaluations": [],
                    "error": str(exc)[:300],
                }
            )
        finally:
            _release(key)
    _record_heartbeat(db, success=all(item["status"] in {"success", "validated"} for item in executions))
    finished_at = utcnow()
    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "templates_considered": len(templates),
        "executions": executions,
    }


def start_scheduler_if_enabled(settings: Settings | None = None) -> BackgroundScheduler | None:
    global _scheduler
    settings = settings or get_settings()
    if not settings.scheduler_enabled:
        return None
    if _scheduler and _scheduler.running:
        return _scheduler
    scheduler = BackgroundScheduler(max_instances=settings.scheduler_max_concurrency)
    scheduler.add_job(
        _scheduled_sync,
        "interval",
        seconds=settings.scheduler_interval_seconds,
        id="jobrun-sentinel-sync",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def _scheduled_sync() -> None:
    db = SessionLocal()
    try:
        run_sync_once(db, initiated_by="scheduler")
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _record_heartbeat(db: Session, *, success: bool) -> None:
    configs = list(db.scalars(select(ConnectorConfig).where(ConnectorConfig.connector_type == "OracleDbConnector")))
    now = utcnow()
    for config in configs:
        config.scheduler_heartbeat_at = now
        if success:
            config.last_successful_sync_at = now
        else:
            config.last_failed_sync_at = now
    db.flush()


def _acquire(key: str) -> bool:
    with _lock:
        if key in _active_keys:
            return False
        _active_keys.add(key)
        return True


def _release(key: str) -> None:
    with _lock:
        _active_keys.discard(key)
