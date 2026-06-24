# Hardening Summary

## Summary

This pass focused on production reliability and verification for the existing JobRun Sentinel phases.

Implemented:

- GitHub Actions CI for backend install/tests, frontend `npm ci`/build/tests, and Docker Compose build.
- `python -m app.cli review-bundle` command that captures redacted API snapshots, command output, optional Playwright screenshots, and a zipped review package.
- Connector-driven topology ingestion that runs stock topology templates through the existing query-template execution/audit path before falling back to local seed topology.
- High-fidelity mock Oracle coverage for active session lookup, missing ASH privileges, ORA-style errors, and sanitized errors.
- Production safety tests for read-only templates, DBMS remediation blocking, raw UDQ SQL default behavior, and secret leakage.
- Service/component splitting for topology heat scoring and dashboard runtime map/heatmap components.
- Docker context ignores to keep local DBs, virtualenvs, node modules, and build output out of image builds.

## Commands Run

```bash
cd backend
.venv/bin/python -m pytest
```

Result: `61 passed, 2 warnings`.

```bash
cd frontend
npm run build
npm test
```

Result: build passed, `8 passed`.

```bash
cd backend
.venv/bin/python -m app.cli review-bundle --skip-commands --skip-screenshots --output-dir backend/review_bundles
```

Result: zip bundle created with 8 API snapshot artifacts.

```bash
docker compose build
```

Result: attempted locally, but Docker is not installed in this environment (`docker: command not found`). The CI workflow includes this as a required job.

## CI Local Equivalent

Run these from the repository root:

```bash
cd backend
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest
```

```bash
cd frontend
npm ci
npm run build
npm test
```

```bash
docker compose build
```

## Review Bundle

Full command:

```bash
cd backend
.venv/bin/python -m app.cli review-bundle
```

Useful options:

- `--api-base-url http://127.0.0.1:8000`
- `--frontend-base-url http://127.0.0.1:5173`
- `--output-dir backend/review_bundles`
- `--skip-screenshots`
- `--skip-commands`

The bundle redacts password/token/secret/DSN/wallet fields and raw SQL-like text. Screenshots use Playwright through `npx playwright screenshot`; install browser support with `npx playwright install chromium` if the local machine has not used Playwright before.

## Connector-Driven vs Synthetic

Connector-driven now:

- Active DB session rows can be fetched from stock topology templates.
- Rows are executed through `QueryTemplateExecutionService`.
- `QueryExecutionLog` stores audit/provenance.
- `DbSessionSnapshot`, `RuntimeNode`, and `JobRunNodeBinding` are created from query results.
- Missing ASH privileges are handled as degraded topology evidence, not startup failure.

Synthetic remains:

- Seed data for local demo and scale testing.
- Mock Oracle connector rows for local development without credentials.
- Server metrics such as WLS GC and some DB node pressure samples.
- Diagnostic and APJ evidence examples when no real connector data exists.

## Known Gaps

- Docker Compose build was not locally verified because Docker is unavailable on this machine.
- Playwright screenshots require a running frontend and browser support; the review command degrades by recording warnings if screenshots fail.
- Large services still exist. This pass extracted heat scoring and dashboard runtime-map components, but deeper decomposition of evaluation and diagnostics should be done incrementally with broader regression coverage.
- Real Oracle connector behavior is feature-flagged and tested through resolver/guardrail/mock paths. Live Oracle connectivity requires production read-only credentials and network access.

## Safety Posture

- Query templates are validated as single `SELECT` or `WITH` statements.
- DBMS remediation, DML, DDL, PL/SQL, and multi-statement execution are blocked by tests.
- Oracle credentials, DSNs, wallets, and tokens are not stored in Sentinel connector records.
- Raw UDQ/customer SQL text remains disabled by default.
- Errors are sanitized before query execution logs or API payloads expose them.
