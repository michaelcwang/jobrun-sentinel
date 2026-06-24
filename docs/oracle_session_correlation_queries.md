# Oracle Session Correlation Queries

Phase 2C adds read-only query templates for mapping slow jobs to active DB sessions, RAC instances, DB hosts, SQL_IDs, waits, and inferred middleware nodes.

## Bundled Templates

- `active_db_session_by_ecid_or_client_identifier`
- `active_db_session_by_ess_request`
- `ash_samples_by_ecid_or_sql_id`
- `node_wait_heat_by_time_bucket`
- `instance_health_snapshot`
- `blocking_session_check_by_ecid_or_sql_id`
- `app_server_inference_from_session`

Import them with:

```bash
cd backend
.venv/bin/python -m app.cli import-query-catalog
```

or through:

```http
POST /api/query-catalog/import-topology-templates
```

## Correlation Method

1. Resolve job identifiers: run ID, ESS request, process ID, ECID, client identifier, SQL_ID, module/action, API operation.
2. Find active DB sessions using ECID or client identifier first.
3. Fall back to ESS request, process ID, module/action, or SQL_ID when ECID is unavailable.
4. Join session placement to DB instance and host metadata.
5. Infer middleware/app server from `MACHINE`, `PROGRAM`, `MODULE`, `ACTION`, `CLIENT_IDENTIFIER`, and ECID.
6. Use ASH-style buckets when available to build server-time heat.
7. If ASH is unavailable, record the missing input and fall back to current sessions plus node metrics.

## Confirmed vs Inferred

Confirmed DB placement requires session/instance evidence such as `INST_ID`, `INSTANCE_NAME`, and `HOST_NAME`.

App server placement is inferred when it comes only from session metadata. It becomes confirmed only after a telemetry source, such as WLS, OCI, Grafana, or Prometheus, corroborates it.

## Safety

Templates must remain `SELECT` or `WITH` only and use named bind parameters. The SQL guard rejects DML, DDL, PL/SQL, `DBMS_*`, `EXEC`, `CALL`, multiple statements, and interpolation patterns.

The app must never execute:

- `DBMS_STATS`
- `DBMS_SPM`
- `DBMS_SQLTUNE`
- `ALTER`, `CREATE`, `DROP`, `TRUNCATE`
- `INSERT`, `UPDATE`, `DELETE`, `MERGE`
- anonymous PL/SQL blocks
- package recompiles or remediation commands

Recommended remediation may appear only as text in diagnostic runbooks.

## Troubleshooting Missing Inputs

- Missing ECID: use `active_db_session_by_ess_request` or module/action fallback.
- Missing ASH privileges: use `instance_health_snapshot` and current session placement.
- Missing WLS telemetry: treat app server as inferred.
- Multiple SQL_IDs on one node: inspect concentration before declaring node-wide pressure.
- No active session: use ESS/API status and prior query execution logs to determine whether the job completed or stalled before sampling.
