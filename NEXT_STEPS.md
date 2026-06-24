# NEXT STEPS

## Phase 1: Manual Plan Import + Heat Map + Ad Hoc Alerts

- Harden CSV import validation and duplicate detection.
- Add XLSX parsing with explicit sheet/column mapping.
- Add editable mapping profiles per support team.
- Add dashboard filter persistence and saved views.
- Add ad hoc monitor expiration cleanup and notification history.

## Phase 2: Direct Oracle DB Connector and Published ICM Query Templates

- Implement `OracleDbConnector` with `python-oracledb`.
- Support thin/thick mode, DSN, wallet, `TNS_ADMIN`, and per-customer routing.
- Enforce read-only SQL guardrails, named parameters, timeout, row limit, and audit logs.
- Validate every real connector with read-only grants and block customer-side DML, DDL, job control, and configuration mutation.
- Import published ICM SQL templates from Confluence/catalog sources.
- Add connector-level health checks and execution diagnostics.

## Phase 3: ESS/API + OCI Telemetry Integration

- Implement ESS request status lookup by request ID and process name.
- Add API operation correlation for CalculatePVT and related invocations.
- Pull OCI telemetry where available and correlate DB/service metrics to job runs.
- Add scheduler-backed polling with backoff and stale-source detection.

## Phase 4: SQL/UDQ Plan Regression Analysis

- Add historical SQL_ID and plan-hash comparison windows.
- Detect unstable child cursors, SQL profile/index interventions, and plan flips.
- Add UDQ metadata ingestion with hash-only storage by default.
- Add richer recommendation rules for common UDQ shapes such as OR predicates and full scans.
- Add optional AI analysis over sanitized runtime, SQL/UDQ, volume, and alert metadata; keep AI output advisory and non-mutating.

## Phase 5: Multi-Customer Production Hardening

- Add authentication, RBAC, and tenant isolation.
- Move secrets to the approved production secrets manager.
- Replace mocked Slack/Jira/Confluence connectors with real implementations.
- Add alert deduplication, escalation policies, maintenance windows, and suppression rules.
- Add Postgres migrations managed exclusively through Alembic.
- Add observability for the Sentinel service itself: metrics, logs, traces, and SLOs.
