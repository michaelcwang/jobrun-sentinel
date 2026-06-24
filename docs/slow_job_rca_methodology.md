# Slow Job RCA Methodology

The Diagnostic Workbench follows an evidence-first workflow.

## 1. Build Context

Resolve run, ESS request, process ID, ECID, client identifier, snapshot window, and collector metadata. Use mock data locally and read-only query templates in production.

## 2. Determine Incident State

If active session evidence exists and `last_call_et` exceeds threshold, mark the report `active`. If the job completed, report final elapsed time. If inputs are missing, mark `unknown`.

## 3. Rank SQL Hotspots

Rank SQL_IDs by ASH samples, elapsed time, CPU time, executions, and wait time. Concentrated hotspots drive findings. Scattered background waits become no-action or secondary items.

## 4. Detect Plan Regression

Compare current and historical:

- plan hash
- cost
- estimated rows
- index/access path
- execution count
- elapsed and CPU seconds
- wait events

High confidence requires at least two independent sources, for example live session plus SQL stats plus AWR/plan history.

## 5. Detect UDQ and Query-Shape Risk

Flag changed UDQ hash/name, OR predicate, full scan, unstable plan, non-sargable lookup, high candidate-row lookup, volume drift, or data-window mismatch. Store shape tags and hashes, not raw query text unless explicitly enabled.

## 6. Detect Formula/Codegen Cache Defects

Use sanitized source inspection and formula metadata. Confirm direct source evidence before claiming confirmed exposure. Treat source-search counts as potential exposure only.

## 7. Rule Out Alternatives

RAC gc waits, ESS queueing, locking/blocking, network, downstream dependencies, and lower-volume secondary SQL must be documented when considered. They are root causes only when evidence is concentrated and directly tied to the slow run.

## 8. Recommend Safe Actions

Recommendations are owner-specific:

- DBA: same-day stats/histogram or SQL Plan Baseline review with sign-off.
- SR/formula owner: generated formula/cache behavior.
- Query/customer owner: UDQ rewrite or query-shape fix.
- Observe only: inconclusive evidence.

Every action includes approval, risk, rollback, validation, and stop/re-check criteria.

## 9. Never Execute Remediation

JobRun Sentinel may display remediation text, but it does not run `DBMS_STATS`, `DBMS_SPM`, `DBMS_SQLTUNE`, package recompiles, DDL, DML, PL/SQL, or any other mutating command against customer pods.
