# Phase 2 Summary

## Summary of Changes

- Added a feature-flagged Oracle DB connector using env-only credentials and lazy `python-oracledb` import.
- Added conservative read-only SQL validation for `SELECT`/`WITH` templates, named binds, row limits, timeouts, and unsafe SQL rejection.
- Expanded query templates into executable ingestion definitions with categories, default parameters, output mappings, validation state, and provenance.
- Added `QueryExecutionLog` audit records with sanitized parameters, small sample results, raw SQL hash, correlation ID, and status metadata.
- Added a bundled synthetic ICM query catalog, including the APJ Direct CalculatePVT regression story.
- Added mock-backed query execution and ingestion into `JobRun`, `VolumeSnapshot`, and `SqlObservation` with idempotent upsert behavior.
- Added scheduler services for one-shot sync and optional APScheduler polling.
- Updated `/sources`, `/query-templates`, `/runs/:id`, and `/dashboard` to show source health, template execution, ingestion, provenance, and last-refreshed context.
- Added CLI commands for catalog import, template validation, one-shot sync, and connector health.
- Added an idempotent Alembic Phase 2 migration plus a SQLite-only local compatibility helper for existing demo databases.
- Updated `.env.example`, README, and docs for the Oracle connector, query template registry, and scheduler.

## Commands Run

```bash
cd backend
.venv/bin/python -m pytest
.venv/bin/python -c "from app.main import app; print(app.title)"
.venv/bin/python -c "from app.core.config import Settings; from app.services.scheduler import start_scheduler_if_enabled; s=start_scheduler_if_enabled(Settings(scheduler_enabled=True, scheduler_interval_seconds=3600)); print(type(s).__name__ if s else 'none'); s.shutdown(wait=False) if s else None"
env DATABASE_URL=sqlite:////private/tmp/jobrun_cli_phase2.db .venv/bin/python -m app.cli import-query-catalog
env DATABASE_URL=sqlite:////private/tmp/jobrun_cli_phase2.db .venv/bin/python -m app.cli validate-templates
env DATABASE_URL=sqlite:////private/tmp/jobrun_cli_phase2.db .venv/bin/python -m app.cli sync-once
env DATABASE_URL=sqlite:////private/tmp/jobrun_cli_phase2.db .venv/bin/python -m app.cli connector-health
```

```bash
cd frontend
npm test
npm run build
```

## Test Results

- Backend pytest: `26 passed`
- Frontend Vitest: `2 passed`
- Frontend production build: passed
- FastAPI app import: passed
- Scheduler enabled construction smoke check: passed
- CLI catalog import on temp DB: imported 8 templates
- CLI template validation on temp DB: 8 valid templates
- CLI one-shot sync on temp DB: considered 8 templates and executed mock-backed ingestion
- API smoke: `/api/query-catalog/import`, `/api/query-templates`, `/api/sources/health`, and `/api/query-executions` returned 200

## Assumptions

- Local development should remain mock-first and must not require Oracle credentials.
- Real Oracle credentials are provided by environment variables or a production secrets manager, never by persisted app records.
- `ConnectorConfig` rows are routing metadata only and may store `env_var_prefix`, timeouts, fetch limits, and display names.
- The bundled catalog uses synthetic `mock_icm_*` view names and is intended to validate the ingestion pipeline, not expose internal SQL.
- The Phase 2 remote Confluence importer is an interface placeholder; bundled local import is fully functional.
- Raw Oracle query text remains disabled by default. The app stores SQL hashes and template metadata for provenance.

## Local Mock Mode

```bash
docker compose up --build
```

or:

```bash
cd backend
.venv/bin/pip install -r requirements.txt
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

Then use `/query-templates` to import the bundled catalog, validate templates, preview rows, ingest rows, and run one sync cycle.

## Oracle Connector Mode

Set:

```env
JOBRUN_CONNECTOR_MODE=oracle
JOBRUN_ALLOW_ORACLE_CONNECTOR=true
JOBRUN_ORACLE_DEFAULT_CONFIG_KEY=demo
JOBRUN_ORACLE_DEMO_USER=readonly_user
JOBRUN_ORACLE_DEMO_PASSWORD=...
JOBRUN_ORACLE_DEMO_DSN=host.example.com/service
```

Optional wallet/TNS/thick-mode variables are documented in `docs/oracle_connector.md`.

## Limitations and Phase 3 Recommendations

- Phase 2B addendum is documented separately in `PHASE2B_SUMMARY.md` and adds the Diagnostic Workbench for evidence-backed RCA reports.
- Add real Confluence catalog import once the approved source and auth pattern are confirmed.
- Add ESS/API and OCI telemetry connectors and correlate their identifiers with direct DB query results.
- Add production Alembic migrations for the Phase 2 columns.
- Add authentication, RBAC enforcement, tenant isolation, and a production secrets manager integration.
- Expand SQL/UDQ analysis from rule-based reason codes into richer plan-regression and advisory AI workflows over sanitized metadata.
