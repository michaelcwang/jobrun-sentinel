# Phase 2B Summary

## Summary of Changes

- Added Diagnostic Workbench data model and idempotent Alembic migration.
- Added `DiagnosticAnalysisService` for evidence-backed slow-job RCA generation.
- Seeded an ECID-style report for ESS `13729027` / `CN Calculate_pvt`.
- Added two high-confidence findings: SQL plan regression and generated-formula cache defect.
- Added evidence, metrics, runbook steps, ruled-out alternatives, data-quality checks, glossary terms, and report templates.
- Added diagnostic API endpoints and alert/playbook promotion endpoints.
- Enriched alert payloads with top diagnostic finding metadata when a diagnostic exists.
- Added `/diagnostics`, `/diagnostics/:id`, and a run-detail `Diagnostics` tab.
- Added bundled diagnostic query templates and mock connector responses.
- Added backend and frontend tests.

## Commands Run

```bash
cd backend
.venv/bin/python -m pytest
.venv/bin/python -m json.tool app/templates/icm_monitoring_templates.json >/tmp/icm_templates_valid.json
```

```bash
cd frontend
npm test
npm run build
```

## Test Results

- Backend pytest: `36 passed`
- Frontend Vitest: `4 passed`
- Frontend production build: passed
- Bundled template catalog JSON validation: passed
- API smoke: `/api/diagnostics`, `/api/diagnostics/1`, `/api/diagnostics/1/render`, `/api/glossary`, and seeded run detail returned 200

## Seed Report

The seeded diagnostic report demonstrates:

- ESS request `13729027`
- ECID `0598914d69b56a3ce534410a606b4a9b`
- RAC cluster size `8`
- active session instance `1` / SID `7716`
- SQL_ID `dp9u1803k8k7f`
- current plan `51543091`
- historical good plan `3256752871`
- current index `HZ_REF_ENTITIES_X26`
- historical index `HZ_REF_ENTITIES_N1`
- generated package `ADXX_CN_FORMULA_111141_PKG`
- value set `MTQ_ICM_OBA_BY_BADGE_VS`
- confirmed affected packages `2`
- potential references `1,157`, with `1,155` explicitly unverified

## Safety

Read-only constraints remain unchanged. Query template execution still allows only `SELECT`/`WITH`.

Diagnostic runbook steps may show DBA-owned remediation text, but every destructive remediation step is `executable_by_app=false` and requires approval. The app never executes DBMS_STATS, DBMS_SPM, DBMS_SQLTUNE, PL/SQL, DDL, DML, package recompiles, or other customer-pod mutations.

## Limitations

- The Phase 2B diagnostic collectors are synthetic in local mode.
- Real production evidence quality depends on approved read-only query templates for GV$, DBA_HIST, AWR/ASH-like sources, and sanitized source-inspection views.
- Report rendering is structured React plus markdown API output; PDF/export is future work.
