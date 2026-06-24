# Diagnostic Workbench

The Diagnostic Workbench turns a slow-job alert into an evidence-backed RCA report.

Alerts answer: "Is this run slower than expected?"

Diagnostics answer: "Why is it slow, how confident are we, what evidence supports that, what was ruled out, who owns next action, and what approval/rollback gates apply?"

## Local Demo

The local seed includes an ECID-style diagnostic for:

- ESS request `13729027`
- job `CN Calculate_pvt`
- ECID `0598914d69b56a3ce534410a606b4a9b`
- SQL_ID `dp9u1803k8k7f`

Open:

```text
/diagnostics
```

or open the seeded run and use the `Diagnostics` tab:

```text
/runs/:id
```

## Generating a Report

From the UI, open a run and select `Diagnostics`, then choose `Generate diagnostic`.

API:

```bash
curl -X POST http://localhost:8000/api/diagnostics/run \
  -H "Content-Type: application/json" \
  -d '{"ess_request_id":"13729027","lookback_minutes":720,"collector_mode":"mock"}'
```

The service resolves run/request/ECID context, builds evidence, creates findings, scores confidence, runs data-quality checks, and stores the report.

## Report Contents

Each report includes:

- incident header: ESS request, ECID, client identifier, RAC scope, snapshot window, collector version
- active/completed incident banner
- executive summary metrics
- "If you do only one thing today" guidance
- root-cause findings
- evidence rows linked to query templates and execution logs
- ruled-out/no-action alternatives
- data-quality gate
- glossary terms
- text-only runbook steps with approval and rollback gates

## Safety

The app never executes remediation. Runbook steps may display DBA-owned text such as `DBMS_STATS` or `DBMS_SPM`, but `executable_by_app=false` and data-quality checks fail if destructive commands are marked executable.

The SQL template execution engine remains `SELECT`/`WITH` only.

Raw customer SQL/source text is disabled by default. Evidence stores sanitized samples and shape metadata.

## Confirmed vs Potential Exposure

The seeded formula/cache finding separates:

- confirmed affected packages: `2`
- potential references: `1,157`
- unverified potential references: `1,155`

Potential reference count is not treated as confirmed customer impact.
