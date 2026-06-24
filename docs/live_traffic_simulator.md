# Live Traffic Simulator

The live traffic simulator creates synthetic Customer A and Customer B incident traffic in the local JobRun Sentinel database. It is intended for demos where the dashboard, topology map, server-time heat map, alerts, run detail, and diagnostics should update while the app is open.

The simulator is local-only and non-destructive. It writes synthetic `LIVE-*` observations into the app database, then runs the same evaluation, topology correlation, and diagnostic services used by the API. It does not connect to Oracle and it does not execute remediation commands.

## Run Once

```bash
cd backend
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/python -m app.cli live-traffic
```

This creates or refreshes four stable live runs:

- `customer-a-apj-udq`: Customer A APJ Direct CalculatePVT with volume drift, changed UDQ hash, changed SQL_ID, plan change, DB instance 1, and User I/O waits.
- `customer-a-middleware-gc`: Customer A Collect Credits with scheduler/WLS pressure and ASH unavailable.
- `customer-b-revert-regression`: Customer B Run Revert with elapsed-time regression, SQL_ID/plan change, and DB I/O waits.
- `customer-b-learning-mode`: Customer B first-run-at-scale CalculatePVT with no formal baseline.

## Run as a Live Demo Loop

```bash
cd backend
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/python -m app.cli live-traffic --cycles 5 --interval-seconds 10 --reset-live
```

Keep the frontend open at `http://localhost:5173/dashboard`, select Customer A or Customer B, and refresh the dashboard or drill into a run after each cycle. The script advances elapsed minutes, progress, volume pressure, topology heat, alerts, and recommendations.

## Scope to One Customer

```bash
cd backend
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/python -m app.cli live-traffic --scenario customer-a --cycles 3 --interval-seconds 5
```

```bash
cd backend
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/python -m app.cli live-traffic --scenario customer-b --cycles 3 --interval-seconds 5
```

## Run One Incident Pattern

```bash
cd backend
DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/python -m app.cli live-traffic --scenario customer-a-apj-udq --cycles 4 --interval-seconds 5
```

Valid scenario names:

- `all`
- `customer-a`
- `customer-b`
- `customer-a-apj-udq`
- `customer-a-middleware-gc`
- `customer-b-revert-regression`
- `customer-b-learning-mode`

## Output

The command prints JSON containing created run IDs, runtime states, reason codes, topology placement, diagnostic report IDs where generated, and sample API calls such as:

- `GET /api/dashboard?customer_key=CUST_A&environment=PROD`
- `POST /api/evaluate/{run_id}`
- `POST /api/runs/{run_id}/correlate-topology`
- `GET /api/runs/{run_id}/topology`
- `GET /api/topology/heatmap?customer_key=CUST_A&environment=PROD&bucket_minutes=10`
- `GET /api/diagnostics/{diagnostic_id}`

## What to Look For

Customer A APJ UDQ scenario should show:

- critical or warning runtime state as cycles advance
- `NEW_SQL_ID`, `SQL_PLAN_CHANGED`, `NEW_UDQ_HASH`, `CUSTOMER_UDQ_RISK`, and volume/data-window reason codes
- SQL_ID `dp9u1803k8k7f`
- DB instance `DBRAC_inst1`
- inferred app server `ESS_SOAServer_as24_01`
- recommendation to compare SQL_ID, plan hash, UDQ hash, volume, and data window before declaring an Oracle runtime regression

Customer B scenarios should show contrast:

- Run Revert regression with SQL/plan comparison and DB I/O evidence
- learning-mode CalculatePVT with no baseline and lower-severity guidance

## Safety

The simulator only creates synthetic observations inside the JobRun Sentinel app database. It does not:

- connect to Oracle
- run DBMS packages
- execute DDL/DML
- store secrets
- store raw customer SQL text
- execute remediation commands
