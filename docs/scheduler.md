# Scheduler

Phase 2 includes an APScheduler-backed polling path for active query templates.

## Defaults

The scheduler is disabled locally:

```env
JOBRUN_SCHEDULER_ENABLED=false
JOBRUN_SCHEDULER_INTERVAL_SECONDS=300
JOBRUN_SCHEDULER_MAX_CONCURRENCY=2
```

Missing Oracle credentials never block app startup. In mock mode, scheduled templates execute against synthetic connector rows.

## One-Shot Sync

Run a single cycle without enabling the background scheduler:

```bash
curl -X POST http://localhost:8000/api/sync/run-once
```

or:

```bash
cd backend
.venv/bin/python -m app.cli sync-once
```

The sync service:

1. finds active `oracle_db` templates with default parameters and output mappings,
2. validates SQL,
3. executes through mock or Oracle connector,
4. ingests mapped rows idempotently,
5. evaluates affected runs,
6. generates alerts when thresholds are breached,
7. records execution logs and connector heartbeat timestamps.

## Background Mode

Enable:

```env
JOBRUN_SCHEDULER_ENABLED=true
```

The scheduler avoids overlapping work for the same template/config key and continues after individual template failures. Sanitized errors are stored in `QueryExecutionLog`.

## Health

The `/sources` page and `/api/sources/health` expose:

- connector status
- config key and display name
- last successful sync
- last failed sync
- scheduler heartbeat
- safe non-secret connector config flags
