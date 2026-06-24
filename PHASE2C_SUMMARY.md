# Phase 2C Summary

## Summary of Changes

- Renamed the dashboard card board concept from Heat Map to Runtime summary / Jobs needing attention.
- Added runtime topology data model:
  - `RuntimeNode`
  - `RuntimeNodeMetricSample`
  - `JobRunNodeBinding`
  - `DbSessionSnapshot`
- Added `RuntimeTopologyService` for session placement, node upsert, binding confidence, topology explanation, and server-time heat scoring.
- Added Phase 2C Alembic migration `0004_phase2c_runtime_topology.py`.
- Added seed topology data for APJ, EMEA, AMER/LATAM, and CN examples.
- Extended deterministic scale seed data so `DEMO_CUST_01` through `DEMO_CUST_10` each get runtime nodes, DB session snapshots, job-to-node bindings, server metric samples, and topology-enriched alert payloads.
- Added bundled read-only topology query templates and mock connector responses.
- Added topology API endpoints:
  - `GET /api/topology/current`
  - `GET /api/topology/heatmap`
  - `GET /api/runs/{id}/topology`
  - `POST /api/runs/{id}/correlate-topology`
  - `GET /api/nodes`
  - `GET /api/nodes/{id}`
  - `GET /api/nodes/{id}/metrics`
  - `POST /api/query-catalog/import-topology-templates`
- Enriched alert payloads with topology summary when session/binding evidence exists.
- Updated dashboard with:
  - Operations Summary
  - Execution topology
  - Server-time heat map
  - Runtime summary job cards
- Added `/topology` route.
- Added run-detail `Topology` tab.
- Updated Sources and Help pages with topology collector and map/heat-map guidance.
- Added docs:
  - `docs/runtime_topology_map.md`
  - `docs/server_time_heatmap.md`
  - `docs/oracle_session_correlation_queries.md`

## Seed Story

The APJ Direct CalculatePVT run now has topology evidence:

- DB instance: `DBRAC_inst1` confirmed
- DB host: `dbhost-a` confirmed
- App server: `ESS_SOAServer_as24_01` inferred
- SQL_ID: `dp9u1803k8k7f`
- Plan hash: `51543091`
- Wait class: `User I/O`
- Event: `cell single block physical read`
- Explanation: heat is concentrated on SQL/plan/UDQ evidence, not a cluster-wide outage

The AMER/LATAM Collect example demonstrates missing ECID fallback and middleware/scheduler pressure. EMEA demonstrates node-normal job-specific variance. CN Calculate_pvt remains tied to the Phase 2B diagnostic report.

The scale-test generator now also validates the design beyond Customer A:

- 10 demo customers
- 25 current jobs per customer
- 4 DB instance nodes and shared ESS/WLS-style nodes per customer
- confirmed DB instance/host bindings
- inferred app-server bindings from session machine/program
- varied wait classes, ASH availability, middleware GC spikes, DB wait pressure, and hot-instance placement
- rerunnable topology backfill for existing demo customers

## Assumptions

- DB instance and host are confirmed only when session/instance metadata exists.
- App/WLS server is inferred from `MACHINE`, `PROGRAM`, `MODULE`, `ACTION`, `CLIENT_IDENTIFIER`, or ECID until telemetry confirms it.
- Local heat-map data is synthetic and meant to validate UX and scoring behavior.
- IP addresses are not stored or displayed; only display names or hashed/redacted metadata should be used.
- ASH may be unavailable in production. The service records that gap and falls back to current sessions and node metrics.

## Commands Run

```bash
backend/.venv/bin/python -m py_compile backend/app/services/topology.py backend/app/api/router.py backend/app/services/evaluation.py backend/app/seed.py backend/app/models/entities.py backend/app/schemas/api.py
backend/.venv/bin/python -m json.tool backend/app/templates/icm_monitoring_templates.json
backend/.venv/bin/python -m pytest backend/app/tests
```

```bash
cd frontend
npm test
npm run build
```

## Test Results

- Backend pytest after scale-topology update: `47 passed`
- Backend topology pytest after scale-topology update: `11 passed`
- Frontend Vitest: `6 passed`
- Frontend production build: passed
- Query template catalog JSON validation: passed

## Local Run

Local mock mode still requires no Oracle credentials:

```bash
cd backend
DATABASE_URL=sqlite:///./jobrun_sentinel.db AUTO_SEED=true .venv/bin/uvicorn app.main:app --reload
```

```bash
cd frontend
npm run dev
```

Open:

- `http://localhost:5173/dashboard`
- `http://localhost:5173/topology`
- `http://localhost:5173/runs/<run_id>`

## Production Notes

The topology connector path remains read-only. Production should route approved templates through the Phase 2 query execution service and keep all pod calls observational:

- no DML
- no DDL
- no PL/SQL
- no job control
- no remediation execution
- no raw customer SQL text unless explicitly enabled by policy

## Follow-Up Work

- Connect WLS/OCI/Grafana/Prometheus metrics to upgrade app-server inference to confirmed placement.
- Add React Flow or a richer SVG edge layer if operators need more complex multi-job maps.
- Add persisted server heat-map snapshots if production query volume makes on-demand calculation too expensive.
- Add per-customer topology template routing and privilege checks.
