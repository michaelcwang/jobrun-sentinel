# Hardening Summary

## Current Status

This pass finishes the production-hardening work needed to make the existing phases reliable and CI-verifiable.

Latest inspected GitHub Actions run before this patch:

- Run: `28104211291`
- Commit: `d90918a`
- Result: failed
- Backend pytest: passed
- Frontend job: failed during dependency install
- Docker Compose build: failed
- Log download was blocked by GitHub API permissions, but job metadata was available.

Fixes in this patch:

- Normalized `frontend/package-lock.json` away from an internal Oracle npm registry so GitHub-hosted runners can run `npm ci`.
- Updated `frontend/Dockerfile` to use `npm ci --no-audit --no-fund`.
- Improved GitHub Actions with concurrency, pip/npm cache, pipefail command logging, failure artifact uploads, Docker build logs, and a CI-safe review-bundle artifact.
- Completed the review-bundle zip structure: metadata, test results, API snapshots, screenshots, page inventory, diagnostic review, design review notes, and README.
- Added `TopologyIngestionService` so topology collection runs through query-template execution, creates `QueryExecutionLog` provenance, and maps rows into `DbSessionSnapshot`, `RuntimeNode`, and `JobRunNodeBinding`.
- Updated `RuntimeTopologyService` to prefer ingested snapshots, invoke topology ingestion when needed, and use seed fallback only in mock/demo/local mode.
- Kept heat scoring in the dedicated `TopologyHeatScoreScorer` module and added isolated tests.

## Commands Run

Backend:

```bash
cd backend
.venv/bin/python -m pytest
```

Result: `68 passed, 2 warnings`.

Frontend:

```bash
cd frontend
npm ci --no-audit --no-fund
npm run build
npm test
```

Result: install passed, build passed, `8 passed`.

Review bundle:

```bash
cd backend
.venv/bin/python -m app.cli review-bundle --skip-screenshots --skip-commands --output-dir backend/review_bundles
```

Result: zip bundle created with 21 artifacts, including required top-level files and directories.

Docker:

```bash
docker compose build
```

Result: not locally executable in this environment because Docker is not installed. The GitHub Actions workflow runs Docker Compose build as a required job.

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
python -m app.cli review-bundle
```

CI-safe command:

```bash
cd backend
python -m app.cli review-bundle --skip-screenshots --skip-commands --output-dir backend/review_bundles
```

The generated zip contains:

- `app_metadata.json`
- `test_results/`
- `api_snapshots/`
- `screenshots/`
- `page_inventory.json`
- `diagnostics_review.json`
- `design_review_notes.md`
- `README.md`
- `manifest.json`

The bundle redacts password/token/secret/DSN/wallet fields, internal registry URLs, and long raw SQL-like text.

## Connector-Driven vs Synthetic

Connector-driven now:

- Active DB session/topology rows are collected by `TopologyIngestionService`.
- Rows are executed through `QueryTemplateExecutionService`.
- `QueryExecutionLog` stores audit/provenance.
- `DbSessionSnapshot`, `RuntimeNode`, and `JobRunNodeBinding` are created from query-template results.
- `RuntimeTopologyService` reads ingested snapshots first and only uses seed rows in mock/demo/local mode.

Synthetic remains:

- Seed data for local demo and scale testing.
- Mock Oracle connector rows for local development without credentials.
- Server metrics such as WLS GC and some DB node pressure samples.
- Diagnostic and APJ evidence examples when no real connector data exists.

## Remaining Production Gaps

- Docker Compose build still needs GitHub Actions confirmation because Docker is unavailable locally.
- Real Oracle connectivity remains feature-flagged and requires production read-only credentials, network routing, and wallet/TNS configuration.
- Playwright screenshots require a running frontend; CI uploads the bundle in no-browser mode.
- Deeper decomposition of evaluation and diagnostic generators remains future hardening work, but the topology heat scorer and runtime-map UI split are in place.

## Safety Posture

- Query templates are validated as single `SELECT` or `WITH` statements.
- DBMS remediation, DML, DDL, PL/SQL, and multi-statement execution are blocked by tests.
- Oracle credentials, DSNs, wallets, and tokens are not stored in Sentinel connector records.
- Raw UDQ/customer SQL text remains disabled by default.
- Errors and review-bundle output are sanitized before external sharing.
