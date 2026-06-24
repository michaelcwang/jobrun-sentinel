# Query Template Registry

The registry stores approved SQL templates that can be validated, previewed, and ingested into canonical JobRun Sentinel entities.

## Template Fields

Important fields:

- `template_id`: stable key used by import and provenance.
- `template_category`: `job_status`, `job_history`, `volume_snapshot`, `sql_observation`, `expectation_candidate`, or `diagnostic`.
- `sql_text`: read-only SQL with named bind parameters.
- `required_parameters`: JSON schema-like metadata for expected parameters.
- `default_parameters`: demo or scheduler parameters.
- `output_mapping`: maps result columns to canonical entities.
- `is_read_only_validated`, `last_validated_at`, `last_executed_at`, `validation_error`.

## Bundled ICM Catalog

The local catalog lives at:

```text
backend/app/templates/icm_monitoring_templates.json
```

Import it from the UI at `/query-templates`, through the API:

```bash
curl -X POST http://localhost:8000/api/query-catalog/import
```

or with the CLI:

```bash
cd backend
.venv/bin/python -m app.cli import-query-catalog
```

The bundled templates are synthetic and non-sensitive. They exercise ICM job status, job history, CalculatePVT history, volume snapshots, SQL observations, UDQ metadata, active long-running jobs, and the APJ Direct regression story.

## Output Mapping

Example:

```json
{
  "entity": "job_run",
  "fields": {
    "external_run_id": "REQUEST_ID",
    "process_id": "PROCESS_ID",
    "ess_request_id": "ESS_REQUEST_ID",
    "job_name": "JOB_NAME",
    "api_operation": "API_OPERATION",
    "status": "STATUS",
    "started_at": "STARTED_AT",
    "ended_at": "ENDED_AT",
    "elapsed_minutes": "ELAPSED_MINUTES",
    "region": "REGION",
    "workstream": "WORKSTREAM",
    "business_period": "BUSINESS_PERIOD"
  }
}
```

Supported Phase 2 entities are `job_run`, `volume_snapshot`, and `sql_observation`.

## Execution Logs

Every validate, preview, execute, and ingest path writes a `QueryExecutionLog` with:

- template and connector identifiers
- sanitized parameters and parameter hash
- status, row count, elapsed time, and validation result
- small sanitized sample result
- raw SQL hash, not raw SQL text by default
- correlation ID and initiated-by metadata

Recent logs appear on `/query-templates` and source status appears on `/sources`.

## Remote Catalog Placeholder

The `QueryCatalogImporter` has a remote Confluence/source URL extension point controlled by:

```env
JOBRUN_QUERY_CATALOG_SOURCE_URL=
JOBRUN_CONFLUENCE_PAT=
JOBRUN_CONFLUENCE_USERNAME=
JOBRUN_CONFLUENCE_BASE_URL=
```

When these are absent, remote import is skipped and the bundled catalog remains the source of truth for local/demo mode.
