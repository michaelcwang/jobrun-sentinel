# Diagnostic Report Schema

Phase 2B adds normalized diagnostic tables.

## Primary Tables

- `diagnostic_reports`: one report per diagnostic run, optionally linked to `job_runs`.
- `diagnostic_findings`: root-cause, secondary, or ruled-out findings.
- `diagnostic_evidence`: evidence rows linked to findings and query execution provenance.
- `diagnostic_metrics`: report/finding metrics for display and comparison.
- `ruled_out_alternatives`: alternatives considered and intentionally deprioritized.
- `diagnostic_data_quality_checks`: self-check gate results.
- `diagnostic_runbook_steps`: text-only analysis, validation, remediation, and rollback steps.
- `glossary_terms`: executive/support explanations.
- `report_templates`: report rendering templates.

## Finding Fields

Findings include:

- `finding_type`: `PLAN_REGRESSION`, `SQL_HOTSPOT`, `CODE_GENERATION_DEFECT`, `CACHE_INEFFECTIVE`, `RAC_CONTENTION`, `RULED_OUT`, and related values.
- `severity`: `info`, `warning`, `critical`.
- `confidence`: `high`, `medium`, `low`.
- `actionability`: `READY_TO_ACT_WITH_SIGNOFF`, `NEEDS_DBA_REVIEW`, `NEEDS_SR`, `NEEDS_FORMULA_OWNER`, `OBSERVE_ONLY`, `RULED_OUT`.
- owner, approval gate, risk, rollback, expected result, stop/re-check condition.

## Evidence Provenance

Evidence rows may link to:

- `query_template_id`
- `query_execution_id`
- sanitized raw sample
- evidence type such as `GV_SQL`, `GV_SESSION`, `DBA_HIST_SQL_PLAN`, `DBA_SOURCE`, `FORMULA_METADATA`

Execution logs keep query hashes and sanitized samples, not secrets or raw customer SQL by default.

## Data Quality Gate

Required checks include:

- correlation key present
- snapshot window present
- incident state determined
- dominant SQL ranking available
- high-confidence findings have independent evidence
- potential exposure is separated from confirmed exposure
- raw SQL redaction passed
- destructive remediation is not executable by the app
- query execution provenance exists where applicable
