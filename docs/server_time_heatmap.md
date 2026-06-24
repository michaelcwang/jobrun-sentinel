# Server-Time Heat Map

The server-time heat map is the actual heat map in JobRun Sentinel. It is not a board of job status cards.

## Layout

- Rows: runtime nodes such as ESS/WLS servers, DB instances, DB hosts, and inferred/unknown nodes.
- Columns: time buckets, usually 5 or 10 minutes.
- Cells: severity and pressure for that node during that time bucket.

Clicking a cell filters the dashboard to the contributing jobs and SQL_IDs.

## Heat Score

The MVP computes `heat_score` on a 0-100 scale from available evidence:

- active slow-job count
- current DB session wait samples
- SQL_ID concentration
- runtime variance severity via open alerts
- DB active sessions
- DB I/O, cluster, application, and concurrency waits
- CPU utilization when available
- WLS full GC percentage when available

Severity thresholds:

- `critical`: score >= 75
- `warning`: score >= 50
- `watch`: score >= 25
- `normal`: score > 0
- `unknown`: no contributing data

The calculation intentionally favors explainability over precision. The cell payload includes `metric_breakdown` and `explanation` so operators can see why a node is hot.

## Interpretation

Use the heat map to answer:

- Which node was hot when the job was slow?
- Were other jobs slow on the same node?
- Is pressure concentrated on one SQL_ID or spread across the cluster?
- Does middleware GC coincide with multiple slow jobs?
- Are DB waits concentrated on one RAC instance?

For the APJ Direct CalculatePVT seed, heat is concentrated on `DBRAC_inst1` and SQL_ID `dp9u1803k8k7f`, while other DB instances remain normal. That supports a SQL/plan/UDQ investigation more than a cluster-wide outage hypothesis.

## Limitations

In local mode, node metrics are synthetic. In production, heat quality depends on approved read-only access to DB dynamic performance views and telemetry. Missing ASH privileges should not fail the app; the service falls back to current sessions and node metrics and documents missing inputs.
