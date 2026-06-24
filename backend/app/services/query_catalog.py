import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import QueryTemplate
from app.models.base import utcnow
from app.services.query_guard import QueryValidationError, validate_read_only_template


CATALOG_PATH = Path(__file__).resolve().parents[1] / "templates" / "icm_monitoring_templates.json"


class QueryCatalogImporter:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()

    def import_bundled(self, path: Path | None = None, *, initiated_by: str = "catalog_import") -> dict[str, Any]:
        catalog_path = path or CATALOG_PATH
        payload = json.loads(catalog_path.read_text())
        imported = 0
        updated = 0
        for item in payload:
            template = self.db.scalar(select(QueryTemplate).where(QueryTemplate.template_id == item["template_id"]))
            was_new = template is None
            if template is None:
                template = QueryTemplate(template_id=item["template_id"], name=item["name"], sql_text=item["sql_text"])
                self.db.add(template)
            _apply_template_payload(template, item, updated_by=initiated_by)
            try:
                validate_read_only_template(template.sql_text, allowed_objects=self.settings.sql_allowlist or None)
                template.is_read_only_validated = True
                template.validation_error = None
            except QueryValidationError as exc:
                template.is_read_only_validated = False
                template.validation_error = str(exc)
            template.last_validated_at = utcnow()
            if was_new:
                imported += 1
            else:
                updated += 1
        self.db.flush()
        processed = imported + updated
        return {
            "imported": processed,
            "created": imported,
            "updated": updated,
            "skipped_remote": True,
            "source": str(catalog_path),
        }

    def import_remote_if_configured(self) -> dict[str, Any]:
        if not self.settings.query_catalog_source_url:
            return {"imported": 0, "updated": 0, "skipped_remote": True, "source": "remote:not-configured"}
        return {
            "imported": 0,
            "updated": 0,
            "skipped_remote": True,
            "source": self.settings.query_catalog_source_url,
            "message": "Remote catalog interface is configured as a Phase 2 extension point; bundled import remains active.",
        }


def _apply_template_payload(template: QueryTemplate, item: dict[str, Any], *, updated_by: str) -> None:
    for key in [
        "name",
        "description",
        "source_url",
        "source_reference",
        "database_type",
        "connector_type",
        "template_category",
        "sql_text",
        "required_parameters",
        "default_parameters",
        "output_mapping",
        "owning_team",
        "tags",
    ]:
        if key in item:
            setattr(template, key, item[key])
    template.active = item.get("active", True)
    template.updated_by = updated_by
