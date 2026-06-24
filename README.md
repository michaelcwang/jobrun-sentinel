# JobRun Sentinel

JobRun Sentinel is a production-oriented MVP for detecting, explaining, and alerting on slow-running Oracle enterprise jobs. It ships with synthetic data modeled on an ICM CalculatePVT incident: an APJ Direct job exceeds its expected runtime while SQL_ID, plan hash, UDQ hash, and data-window/volume signals differ from the baseline.

## Read-Only Operating Model

JobRun Sentinel is designed to be non-destructive against target customer pods. External connectors may inspect runtime history, ESS/API status, SQL/plan metadata, volume snapshots, telemetry, and published query-template results. They must not perform customer-side DML, DDL, job control, deployment, configuration changes, or corrective actions.

The app can still write to its own Sentinel database for local artifacts such as discovered jobs, baselines, expectations, alerts, acknowledgements, imports, notes, and AI analysis results. Those writes are internal to the tool and do not mutate the target pod.

AI logic, when added, should operate on sanitized metrics and metadata only. It should produce explanations, suspected-cause ranking, and next-action recommendations, while deterministic services remain responsible for status, severity, thresholds, and alert creation.

## Quick Start

Run the full stack with Docker Compose:

```bash
docker compose up --build
```

Then open:

- Frontend: http://localhost:5173/dashboard
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

Local development without Docker:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/python -m app.seed --init
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

If your environment blocks the public npm registry or has certificate-chain issues, use the internal registry pattern:

```bash
npm --strict-ssl=false install --registry=https://artifacthub-iad.oci.oraclecorp.com/api/npm/npmjs-registry --no-audit --no-fund
```

## Architecture

- `backend/app/models`: SQLAlchemy domain model for customers, environments, jobs, runs, baselines, SQL observations, alerts, connectors, query templates, imports, and playbook notes.
- `backend/app/services/baseline.py`: historical runtime statistics: p50, p75, p90, p95, average, MAD, last successful duration, volume throughput, confidence.
- `backend/app/services/evaluation.py`: slow-run evaluator, reason codes, ETA, variance, cause tags, recommendations, alert payloads.
- `backend/app/connectors`: abstract connector interfaces, mocked implementations for local development, and a feature-flagged read-only Oracle DB connector.
- `backend/app/services/query_execution.py`: SQL template validation, mock/Oracle execution, audit logging, and sanitized samples.
- `backend/app/services/ingestion.py`: maps query rows into canonical JobRun, VolumeSnapshot, and SQL observation records, then evaluates affected runs.
- `backend/app/services/scheduler.py`: optional APScheduler polling and one-shot sync.
- `backend/app/services/diagnostics.py`: evidence-backed slow-job diagnostics, findings, confidence scoring, data-quality checks, and text-only runbooks.
- `backend/app/services/topology.py`: runtime topology correlation, DB session snapshots, job-to-node bindings, and server-time heat-map scoring.
- `backend/app/api/router.py`: REST API required by the MVP.
- `frontend/src/pages`: dashboard, runtime topology map, runs, run detail, expectation manager, alerts, ad hoc monitor builder, sources, query templates, imports, diagnostics, and playbook.

The app defaults to SQLite for local development and uses PostgreSQL in Docker Compose. Alembic is wired in `backend/alembic`; the MVP also creates tables on startup to keep local onboarding simple.

Phase 2 docs:

- `docs/oracle_connector.md`
- `docs/review_bundle.md`
- `docs/query_template_registry.md`
- `docs/scheduler.md`
- `PHASE2_SUMMARY.md`

Phase 2B docs:

- `docs/diagnostic_workbench.md`
- `docs/diagnostic_report_schema.md`
- `docs/slow_job_rca_methodology.md`
- `PHASE2B_SUMMARY.md`

Phase 2C docs:

- `docs/runtime_topology_map.md`
- `docs/server_time_heatmap.md`
- `docs/oracle_session_correlation_queries.md`
- `PHASE2C_SUMMARY.md`

## Seed Data

Synthetic seed data includes:

- Customer A with APJ, EMEA, and AMER/LATAM jobs.
- APJ Direct CalculatePVT historical runs around 350 minutes.
- Current APJ Direct run over 12 hours, marked critical.
- CalculatePVT API operation, ESS request ID, job ID, process ID.
- Customer-authored UDQ `MTQ_ICM_OBA_BY_BADGE_VS` with changed hash.
- New SQL_ID, plan hash, SQL profile/index intervention metadata.
- Volume/data-window drift.
- Customer B Run Revert regression and a learning-mode first run.
- Manual plan rows and a CSV fixture in `fixtures/maverick_manual_plan_seed.csv`.
- Runtime topology data for APJ, EMEA, AMER/LATAM, and CN runs.
- ESS/WLS nodes, DB RAC instances, DB hosts, active DB session snapshots, wait classes, SQL_ID placement, and node metric samples.

For larger runtime-summary, server-time heat-map, and alert testing, generate deterministic scale data:

```bash
cd backend
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/python -m app.seed --scale --scale-customers 10 --scale-jobs-per-customer 25
```

This adds `DEMO_CUST_01` through `DEMO_CUST_10`. Each customer has 25 active key jobs, six successful historical runs for comparable jobs, volume snapshots, SQL observations, expectation records where appropriate, alert rules, seeded alerts, runtime nodes, DB session snapshots, job-to-node bindings, and server-time metric samples across normal, watch, warning, critical, and learning-mode states.

The command is safe to rerun. If the demo customers already exist, it backfills or refreshes topology evidence and alert payloads instead of duplicating the customer/job records.

## Customer Pod Scope

Use the customer pod selector in the left panel to focus the app on one customer at a time. Select `Demo Customer 1`, `Demo Customer 2`, and so on to validate runtime summary cards, the execution topology, server-time heat map, and alerting without overwhelming a viewer with the full scale dataset.

The Dashboard, Runs, Expectations, Alerts, Ad Hoc, Imports, and Playbook pages pass the selected customer key to the API. Source health and SQL template registration remain shared admin views, while template execution and imports default to the selected pod when one is active.

## Live Incident Traffic Simulator

To watch the dashboard update with fresh Customer A and Customer B incidents, run:

```bash
cd backend
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/python -m app.cli live-traffic --cycles 5 --interval-seconds 10 --reset-live
```

The simulator creates or refreshes stable `LIVE-*` runs, injects synthetic SQL/UDQ/volume/topology observations, runs evaluation, correlates runtime topology, and generates diagnostics where useful. It prints run IDs and sample API calls for dashboard, run detail, topology, heat-map, and diagnostic endpoints.

See `docs/live_traffic_simulator.md` for scenario names and demo guidance.

## Role-Aware UI

Use the theme and role selectors in the top-right of the app. Theme defaults to `System`, follows the user's OS light/dark preference, and can be overridden to `Light` or `Dark`.

- Executive: high-level customer and business risk, top risks, limited technical noise.
- Operator: full support workflow with reason codes, alerts, acknowledgements, imports, and ad hoc monitors.
- DBA: SQL_ID, plan hash, UDQ hash, source connector, and query-template investigation views.

Hover the help icons next to section titles and metrics to explain status colors, variance, ETA, confidence, reason codes, topology confidence, connector results, and SQL-template behavior.

## Runtime Topology and Server-Time Heat Map

The dashboard no longer treats status cards as the heat map. It now has:

- Operations Summary: counts for critical, warning, watch, normal, and unknown-baseline runs.
- Execution topology: a map-like path from job run to ESS/API, inferred app or WLS server, confirmed DB instance and host, active DB session, SQL_ID, plan hash, wait class, and event.
- Server-time heat map: rows are runtime nodes and columns are time buckets. Cells score node heat from active slow-job count, wait samples, SQL concentration, CPU/load, WLS GC, and DB wait metrics when available.
- Runtime summary: job status cards with elapsed-vs-expected metrics and Explore links.

Confirmed topology evidence comes from read-only DB session placement such as `GV$SESSION` joined to `GV$INSTANCE`. App/WLS server placement is marked inferred when it comes only from `MACHINE`, `PROGRAM`, `MODULE`, `ACTION`, `CLIENT_IDENTIFIER`, or ECID. Future WLS/OCI/Grafana/Prometheus telemetry can upgrade those signals.

The seeded APJ Direct CalculatePVT run maps to `DBRAC_inst1` / `dbhost-a`, inferred app server `ESS_SOAServer_as24_01`, SQL_ID `dp9u1803k8k7f`, plan `51543091`, wait class `User I/O`, and event `cell single block physical read`.

## Alert Logic

The evaluator:

1. Finds the best matching active expectation record.
2. Computes historical baseline statistics for comparable successful runs.
3. Uses manual expectation first; otherwise uses historical p75 when history is sufficient.
4. Adjusts expected runtime when current volume materially exceeds baseline.
5. Computes elapsed time, variance, ETA, runtime state, severity, reason codes, and recommended actions.
6. Flags non-comparable runs when SQL_ID, plan hash, UDQ hash, or data window changed.

Example APJ reason codes include:

- `ELAPSED_GT_CRITICAL_THRESHOLD`
- `CURRENT_VOLUME_GT_BASELINE`
- `DATA_WINDOW_MISMATCH`
- `NEW_UDQ_HASH`
- `NEW_SQL_ID`
- `SQL_PLAN_CHANGED`
- `SQL_PROFILE_OR_INDEX_CHANGE`
- `STUCK_NO_PROGRESS`

## Manual Plan Import

Use `/imports` in the UI or:

```bash
curl -F "file=@fixtures/maverick_manual_plan_seed.csv" \
  "http://localhost:8000/api/imports/plans?customer_key=CUST_A&environment=PROD"
```

Supported CSV columns include `Step`, `Status`, `Process ID`, `Actual Execution Time (Minutes)`, `Estimated Run Time`, start/end timestamps, owner, comments, and volume. XLSX support is documented as an extension point; `openpyxl` is already included.

## Connector Extension Points

Interfaces live in `backend/app/connectors/base.py`:

- `JobHistoryConnector`
- `OracleDbConnector`
- `EssApiConnector`
- `OciTelemetryConnector`
- `SqlObservationConnector`
- `VolumeSnapshotConnector`
- `SlackConnector`
- `ConfluenceQueryCatalogConnector`

Real Oracle DB connector:

- Uses `python-oracledb` thin mode by default, with thick mode enabled by env configuration.
- Reads DSN, wallet, `TNS_ADMIN`, usernames, and passwords only from environment variables or a production secrets manager.
- Enforces read-only SQL, named parameters, query timeout, row limit, and audit logging.
- Connect with database grants that cannot write, execute procedures, alter sessions beyond approved read settings, or change customer-side state.
- Route connections per customer/environment.
- Never store raw customer SQL text unless `JOBRUN_ALLOW_RAW_QUERY_TEXT=true` and a secure storage policy is in place.

Example local-safe env values are in `.env.example`.

Production connector setup is a three-part model:

- `ConnectorConfig` rows store non-secret routing, display names, customer/environment scope, env var prefix, timeout, fetch limit, and enabled state.
- Environment variables or the production secret manager store credentials, DSN, wallet, wallet password, `TNS_ADMIN`, and client mode.
- Query templates define the approved read-only evidence collection path and every execution is validated and audit logged.

To establish or update a production connector:

1. Provision a read-only source account and approved views.
2. Add secrets under a dedicated prefix such as `JOBRUN_ORACLE_PROD1`.
3. Create or update the `ConnectorConfig` route for the target customer/environment.
4. Import and validate query templates.
5. Run connector health, preview execution, and one ingestion cycle.
6. Enable scheduled sync after `/sources` and `/query-executions` show healthy, sanitized results.

For credential rotation or pod changes, update the secret manager/env values or the routing row, then rerun health checks. Sentinel never needs the raw password or wallet secret stored in its database.

Customer pod onboarding:

- Use Sources -> Add customer pod to create the local `Customer`, `Environment`, and non-secret `ConnectorConfig` route.
- Apply the bundled stock ICM templates for job status, job history, volume snapshots, SQL/UDQ observations, topology, and diagnostics.
- Optionally run one read-only discovery fetch. In local mode this uses mock data; in production it uses the configured Oracle connector and creates query execution logs.
- The left customer-pod selector reads backend pods and merges them with the seeded demo pods.
- Use Imports after stock discovery to upload customer-specific plan rows, volume metrics, or custom metric columns that stock queries do not cover.

Slack integration:

- Implement `SlackConnector.send_alert`.
- Read webhook/token from environment variables only.
- Keep payloads free of PII and raw SQL text.
- Preserve `AlertEvent` audit entries for sent, acknowledged, escalated, and resolved states.

## Query Templates

The registry only accepts parameterized `SELECT`/`WITH` SQL and blocks write/DDL keywords, PL/SQL, procedure calls, `DBMS_*`, multiple statements, and interpolation patterns. Executions store audit metadata and a small sanitized sample result, not large result sets.

## CI And Review Bundle

GitHub Actions runs backend install/tests, frontend `npm ci`/build/tests, and Docker Compose build on push and pull request.

Create an external review bundle from a running local app:

```bash
cd backend
.venv/bin/python -m app.cli review-bundle
```

The command captures redacted API snapshots, test/build output, optional Playwright screenshots, and a zip under `backend/review_bundles`. See `HARDENING_SUMMARY.md` for verification details and known gaps.

Import the bundled synthetic ICM catalog:

```bash
cd backend
.venv/bin/python -m app.cli import-query-catalog
```

Validate all active templates:

```bash
cd backend
.venv/bin/python -m app.cli validate-templates
```

Run one sync cycle:

```bash
cd backend
.venv/bin/python -m app.cli sync-once
```

The bundled catalog also includes Phase 2C topology templates:

- `active_db_session_by_ecid_or_client_identifier`
- `active_db_session_by_ess_request`
- `ash_samples_by_ecid_or_sql_id`
- `node_wait_heat_by_time_bucket`
- `instance_health_snapshot`
- `blocking_session_check_by_ecid_or_sql_id`
- `app_server_inference_from_session`

## Diagnostic Workbench

Use `/diagnostics` to review evidence-backed slow-job RCA reports. Use the `Diagnostics` tab on `/runs/:id` to generate or refresh a report for a run.

The local seed includes a diagnostic for ESS `13729027` / `CN Calculate_pvt` with:

- high-confidence `PLAN_REGRESSION` on SQL_ID `dp9u1803k8k7f`
- current plan `51543091` using `HZ_REF_ENTITIES_X26`
- historical plan `3256752871` using `HZ_REF_ENTITIES_N1`
- high-confidence generated formula/cache defect for `ADXX_CN_FORMULA_111141_PKG`
- confirmed affected packages `2`, potential references `1,157`, and unverified references `1,155`
- ruled-out RAC/ESS queue/locking/secondary SQL alternatives
- data-quality gate and glossary

Diagnostic runbooks are text-only. The app never executes DBMS_STATS, DBMS_SPM, DBMS_SQLTUNE, DDL, DML, PL/SQL, package recompiles, or other remediation commands against customer pods.

## Security and Governance

- Source DB access must be read-only.
- Source pod access must be observational only; no DML, DDL, job control, deployment, or pod-side configuration changes.
- SQL templates must be parameterized.
- Secrets must come from environment variables or a secrets manager.
- Slack alerts should not include customer PII or raw query text.
- Raw query text storage is disabled by default.
- AI analysis should use sanitized metadata and return recommendations only.
- Alert acknowledgement and query execution are audit logged.
- RBAC placeholder roles are documented in UI as `viewer`, `operator`, and `admin`.

## Tests

Backend:

```bash
cd backend
.venv/bin/python -m pytest
```

Frontend:

```bash
cd frontend
npm test
npm run build
```

Current verification performed:

- Backend pytest: `45 passed`
- Frontend Vitest: `6 passed`
- Frontend production build: passed
- CLI smoke: bundled catalog import, template validation, one-shot sync, and connector health passed against a temp SQLite DB.
- API smoke: `/api/query-catalog/import`, `/api/query-templates`, `/api/sources/health`, and `/api/query-executions` returned 200.
- API smoke: `DEMO_CUST_01` dashboard and runs returned 25 running jobs scoped to that customer; playbook digest returned 25 active monitored runs.
