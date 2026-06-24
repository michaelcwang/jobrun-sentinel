# Oracle Connector

JobRun Sentinel Phase 2 adds a real Oracle DB connector behind feature flags while preserving local mock mode.

## Local Mock Mode

Default `.env` values keep the app fully functional without Oracle credentials:

```env
JOBRUN_CONNECTOR_MODE=mock
JOBRUN_ALLOW_ORACLE_CONNECTOR=false
```

In this mode, SQL templates still pass through the read-only validator and audit log path, but rows come from the mock connector.

## Enabling Oracle Mode

Set connector mode and provide secrets through environment variables only:

```env
JOBRUN_CONNECTOR_MODE=oracle
JOBRUN_ALLOW_ORACLE_CONNECTOR=true
JOBRUN_ORACLE_DEFAULT_CONFIG_KEY=demo

JOBRUN_ORACLE_DEMO_USER=readonly_user
JOBRUN_ORACLE_DEMO_PASSWORD=...
JOBRUN_ORACLE_DEMO_DSN=host.example.com/service
JOBRUN_ORACLE_DEMO_CLIENT_MODE=thin
```

Optional settings:

```env
JOBRUN_ORACLE_DEMO_TNS_ADMIN=/path/to/network/admin
JOBRUN_ORACLE_DEMO_WALLET_LOCATION=/path/to/wallet
JOBRUN_ORACLE_DEMO_WALLET_PASSWORD=...
JOBRUN_ORACLE_DEMO_QUERY_TIMEOUT_SECONDS=60
JOBRUN_ORACLE_DEMO_FETCH_LIMIT=500
JOBRUN_ORACLE_DEMO_CONNECT_TIMEOUT_SECONDS=15
```

`python-oracledb` thin mode is the default. Thick mode is supported by setting `JOBRUN_ORACLE_DEMO_CLIENT_MODE=thick` and configuring Oracle client libraries outside the app.

## Connector Config Routing

`ConnectorConfig` database rows store non-secret routing only:

- `config_key`, for example `demo`
- `display_name`
- customer/environment routing fields
- `env_var_prefix`, for example `JOBRUN_ORACLE_DEMO`
- `enabled`
- timeout/fetch settings

The connector resolves credentials from `${env_var_prefix}_USER`, `${env_var_prefix}_PASSWORD`, `${env_var_prefix}_DSN`, wallet, and TNS env vars. Passwords, wallet passwords, DSNs, and tokens are never persisted by the app.

## Production Setup Checklist

Use this sequence when establishing a new production connector:

1. Provision a database account with read-only grants for the approved runtime, ESS, SQL observation, ASH/AWR, and volume views.
2. Create or approve the query templates that this connector is allowed to run.
3. Store Oracle secrets in the production secret manager or environment using a dedicated prefix, for example `JOBRUN_ORACLE_PROD1`.
4. Add a `ConnectorConfig` row with customer/environment routing, `connector_type=oracle_db`, `config_key`, `display_name`, `env_var_prefix`, timeout, fetch limit, and `enabled=false` while testing.
5. Run connector health and template validation.
6. Execute one template in preview mode and review `QueryExecutionLog` for row count, sanitized sample, elapsed time, validation result, and correlation ID.
7. Run one ingestion cycle and verify the affected runs, topology bindings, diagnostics, and alerts.
8. Enable the connector and scheduler only after health, validation, and audit logs look correct.

The production split is intentional:

- `ConnectorConfig` controls routing and safe non-secret settings.
- Environment variables or the secret manager provide credentials, wallet settings, DSN, and client mode.
- Query templates define what read-only evidence can be collected.
- Query execution logs prove what ran, when it ran, and what it ingested.

## Updating Connectors in Production

Common updates should not require storing or exposing secrets in Sentinel:

- Credential rotation: update the secret manager or environment values for the existing `env_var_prefix`, restart or reload the backend, then run connector health.
- DSN, wallet, or `TNS_ADMIN` change: update environment values, validate health, run one preview query, then resume scheduled sync.
- Add a customer or pod: create a new `ConnectorConfig` route with a dedicated `config_key` and `env_var_prefix`; do not reuse credentials across tenants unless production policy explicitly allows it.
- Change polling behavior: update scheduler interval and template active flags, then check `/sources` and `QueryExecutionLog`.
- Disable a connector: set the connector config inactive, set `JOBRUN_ALLOW_ORACLE_CONNECTOR=false`, or switch `JOBRUN_CONNECTOR_MODE=mock` during a rollback.
- Remove a template: mark it inactive first, verify no scheduler run depends on it, then remove it in a controlled deployment.

After any update, use this verification path:

```bash
cd backend
.venv/bin/python -m app.cli connector-health
.venv/bin/python -m app.cli validate-templates
.venv/bin/python -m app.cli sync-once
```

Then confirm `/sources`, `/query-templates`, `/query-executions`, and a known run detail page all show the expected connector, template, and provenance metadata.

## Customer Pod Onboarding From The UI

The Sources page includes **Add customer pod** for production-friendly onboarding.

What the form does:

1. Creates or updates the local `Customer` and `Environment` scope.
2. Creates or updates a non-secret `ConnectorConfig` route for that customer/environment.
3. Stores the env var prefix, timeout, fetch limit, and routing metadata only.
4. Imports the bundled stock ICM query templates.
5. Validates stock templates through the read-only SQL guardrail.
6. Optionally runs one read-only discovery fetch and stores query execution provenance.

What the form does not do:

- It does not collect or persist passwords, DSNs, wallet passwords, or tokens.
- It does not run remediation commands.
- It does not modify the target customer pod.
- It does not assume stock templates cover every customer-defined UDQ or metric.

After onboarding, use Imports for customer-specific manual plan rows, volume metrics, or other custom metric columns. This lets the stock query catalog establish the baseline discovery path while customer-specific data shape can be layered in without changing connector secrets.

## Read-Only Contract

The connector validates every template before execution:

- allowed: single `SELECT` or `WITH` statements
- required: named bind parameters such as `:request_id`
- blocked: DML, DDL, PL/SQL blocks, procedure calls, `DBMS_*`, multiple statements, and interpolation patterns
- enforced: row limit and query timeout

Use read-only database grants in production. The app is intentionally observational: it may write to its own Sentinel database, but it must not mutate the target pod.

## Health Checks

Use:

```bash
cd backend
.venv/bin/python -m app.cli connector-health
```

The health result reports only safe flags such as `dsn_configured` and `password_configured`; it does not expose values.
