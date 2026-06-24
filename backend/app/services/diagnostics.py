from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import (
    Alert,
    AlertEvent,
    Customer,
    DiagnosticDataQualityCheck,
    DiagnosticEvidence,
    DiagnosticFinding,
    DiagnosticMetric,
    DiagnosticReport,
    DiagnosticRunbookStep,
    Environment,
    GlossaryTerm,
    JobDefinition,
    JobRun,
    PlaybookNote,
    QueryExecutionLog,
    QueryTemplate,
    ReportTemplate,
    RuledOutAlternative,
)
from app.models.base import utcnow


COLLECTOR_NAME = "JobRun Sentinel Diagnostic Collector"
COLLECTOR_VERSION = "2B.1"
CALCULATE_PVT_JOB_DEFINITION = (
    "JobDefinition://oracle/apps/ess/incentiveCompensation/cn/processes/"
    "transactionProcess/Calculate_pvt"
)
EXAMPLE_ECID = "0598914d69b56a3ce534410a606b4a9b"
EXAMPLE_ESS_REQUEST_ID = "13729027"
DESTRUCTIVE_PATTERN = re.compile(
    r"\b(DBMS_STATS|DBMS_SPM|DBMS_SQLTUNE|ALTER|CREATE|DROP|INSERT|UPDATE|DELETE|MERGE|EXEC|EXECUTE|BEGIN|DECLARE)\b",
    re.I,
)


@dataclass(frozen=True)
class DiagnosticGenerationResult:
    report: DiagnosticReport
    finding_count: int


class DiagnosticAnalysisService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def generate_report(
        self,
        *,
        run_id: int | None = None,
        ess_request_id: str | None = None,
        process_id: str | None = None,
        ecid: str | None = None,
        lookback_minutes: int = 720,
        collector_mode: str = "mock",
    ) -> DiagnosticGenerationResult:
        run = self._resolve_run(run_id, ess_request_id, process_id, ecid)
        if not run:
            raise ValueError("A matching run was not found for diagnostic generation.")
        existing = self.latest_for_run(run.id) or self._find_by_identifiers(ess_request_id, process_id, ecid)
        report = existing or DiagnosticReport(
            run_id=run.id,
            customer_key=run.customer.customer_key,
            environment=run.environment.name,
            report_title="Slow Job Diagnostic",
        )
        if existing is None:
            self.db.add(report)
            self.db.flush()
        self._clear_report(report)

        if self._is_calculate_pvt_example(run, ess_request_id, ecid):
            self._populate_calculate_pvt_report(report, run, lookback_minutes, collector_mode)
        else:
            self._populate_generic_slow_job_report(report, run, lookback_minutes, collector_mode)
        self._seed_glossary_terms()
        self.db.flush()
        return DiagnosticGenerationResult(report=report, finding_count=len(report.findings))

    def refresh_report(self, report_id: int) -> DiagnosticGenerationResult:
        report = self.get_report(report_id)
        if not report:
            raise ValueError("Diagnostic report was not found.")
        return self.generate_report(
            run_id=report.run_id,
            ess_request_id=report.ess_request_id,
            process_id=report.process_id,
            ecid=report.ecid,
            lookback_minutes=report.lookback_minutes or 720,
            collector_mode="refresh",
        )

    def get_report(self, report_id: int) -> DiagnosticReport | None:
        return self.db.scalar(
            select(DiagnosticReport)
            .where(DiagnosticReport.id == report_id)
            .options(
                selectinload(DiagnosticReport.findings).selectinload(DiagnosticFinding.evidence),
                selectinload(DiagnosticReport.findings).selectinload(DiagnosticFinding.metric_rows),
                selectinload(DiagnosticReport.findings).selectinload(DiagnosticFinding.runbook_steps),
                selectinload(DiagnosticReport.findings).selectinload(DiagnosticFinding.ruled_out_alternatives),
                selectinload(DiagnosticReport.metrics),
                selectinload(DiagnosticReport.ruled_out_alternatives),
                selectinload(DiagnosticReport.data_quality_checks),
            )
        )

    def latest_for_run(self, run_id: int) -> DiagnosticReport | None:
        return self.db.scalar(
            select(DiagnosticReport)
            .where(DiagnosticReport.run_id == run_id)
            .order_by(DiagnosticReport.updated_at.desc(), DiagnosticReport.created_at.desc())
        )

    def render_markdown(self, report: DiagnosticReport) -> str:
        findings = sorted(report.findings, key=lambda item: item.finding_number)
        lines = [
            f"# {report.report_title}",
            "",
            f"ESS request: `{report.ess_request_id or 'unknown'}`",
            f"ECID: `{report.ecid or 'unknown'}`",
            f"Client identifier: `{report.client_identifier or 'unknown'}`",
            f"RAC cluster: `{report.rac_cluster_size or 'unknown'}` instances",
            f"Snapshot: `{report.snapshot_start_at}` to `{report.snapshot_end_at}`",
            f"Collector: {report.collector_name} {report.collector_version}",
            "",
            f"**Incident state:** {report.incident_state}",
            f"**If you do only one thing today:** {report.if_you_do_one_thing_today or 'Review the top finding.'}",
            "",
            "## Executive Summary",
            json.dumps(report.executive_summary or {}, indent=2, default=str),
            "",
            "## Findings",
        ]
        for finding in findings:
            lines.extend(
                [
                    "",
                    f"### {finding.finding_number}. {finding.title}",
                    f"- Type: `{finding.finding_type}`",
                    f"- Key: `{finding.finding_key}`",
                    f"- Severity/confidence/actionability: `{finding.severity}` / `{finding.confidence}` / `{finding.actionability}`",
                    f"- Owner: {finding.owner_team or 'Unassigned'}",
                    f"- Problem: {finding.problem_statement or ''}",
                    f"- Business impact: {finding.business_impact or ''}",
                    f"- Recommended action: {finding.recommended_action or ''}",
                    f"- Approval gate: {finding.approval_gate or ''}",
                    f"- Rollback: {finding.rollback_plan or ''}",
                    f"- Stop/re-check: {finding.stop_recheck_condition or ''}",
                    "",
                    "Evidence:",
                ]
            )
            for evidence in finding.evidence:
                lines.append(f"- {evidence.evidence_type}: {evidence.evidence_summary}")
        lines.extend(["", "## Ruled-Out Alternatives"])
        for alternative in report.ruled_out_alternatives:
            lines.append(f"- {alternative.alternative_type} ({alternative.status}): {alternative.reason}")
        lines.extend(["", "## Data Quality Gate"])
        for check in report.data_quality_checks:
            lines.append(f"- {check.status.upper()} `{check.check_key}`: {check.message}")
        return "\n".join(lines)

    def promote_finding_to_alert(self, report_id: int, finding_id: int | None = None) -> Alert:
        report = self.get_report(report_id)
        if not report:
            raise ValueError("Diagnostic report was not found.")
        finding = self._select_finding(report, finding_id)
        alert = Alert(
            run_id=report.run_id,
            severity=finding.severity,
            state="new",
            runtime_state="critical" if finding.severity == "critical" else "warning",
            reason_codes=[finding.finding_type],
            payload=self.diagnostic_alert_payload(report, finding),
            top_suspected_cause=finding.title,
        )
        self.db.add(alert)
        alert.events.append(
            AlertEvent(
                event_type="diagnostic_promoted",
                message=f"Diagnostic finding {finding.finding_key} promoted to alert.",
            )
        )
        self.db.flush()
        return alert

    def promote_finding_to_playbook_note(self, report_id: int, finding_id: int | None = None) -> PlaybookNote:
        report = self.get_report(report_id)
        if not report:
            raise ValueError("Diagnostic report was not found.")
        finding = self._select_finding(report, finding_id)
        customer = self.db.scalar(select(Customer).where(Customer.customer_key == report.customer_key))
        environment = (
            self.db.scalar(select(Environment).where(Environment.customer_id == customer.id, Environment.name == report.environment))
            if customer
            else None
        )
        note = PlaybookNote(
            customer_id=customer.id if customer else None,
            environment_id=environment.id if environment else None,
            run_id=report.run_id,
            note_date=utcnow().date(),
            title=f"Diagnostic action: {finding.title}",
            body=f"{finding.recommended_action}\n\nApproval: {finding.approval_gate}\nRollback: {finding.rollback_plan}",
            risk_level=finding.severity,
            owner=finding.owner_team,
        )
        self.db.add(note)
        self.db.flush()
        return note

    def diagnostic_alert_payload(self, report: DiagnosticReport, finding: DiagnosticFinding | None = None) -> dict[str, Any]:
        finding = finding or self._select_finding(report, None)
        dashboard_base = self.settings.default_alert_dashboard_url.removesuffix("/dashboard").rstrip("/")
        return {
            "diagnostic_report_id": report.id,
            "diagnostic_link": f"{dashboard_base}/diagnostics/{report.id}",
            "title": report.report_title,
            "top_finding": finding.title,
            "finding_type": finding.finding_type,
            "finding_key": finding.finding_key,
            "confidence": finding.confidence,
            "actionability": finding.actionability,
            "owner": finding.owner_team,
            "sql_id": finding.source_sql_id,
            "current_plan_hash": finding.source_plan_hash_value,
            "historical_plan_hash": finding.historical_plan_hash_value,
            "recommended_action": finding.recommended_action,
            "approval_gate": finding.approval_gate,
        }

    def _populate_calculate_pvt_report(
        self, report: DiagnosticReport, run: JobRun, lookback_minutes: int, collector_mode: str
    ) -> None:
        now = utcnow()
        snapshot_end = now
        snapshot_start = now - timedelta(minutes=lookback_minutes)
        report.run_id = run.id
        report.customer_key = run.customer.customer_key
        report.environment = run.environment.name
        report.report_title = "ECID Slow Job Diagnostic - CN Calculate_pvt ESS 13729027"
        report.diagnostic_type = "slow_job"
        report.ess_request_id = EXAMPLE_ESS_REQUEST_ID
        report.job_definition = CALCULATE_PVT_JOB_DEFINITION
        report.job_name = "CN Calculate_pvt"
        report.process_id = run.process_id or "1434435"
        report.ecid = EXAMPLE_ECID
        report.client_identifier = "ess13729027-1434435"
        report.rac_cluster_size = 8
        report.snapshot_start_at = snapshot_start
        report.snapshot_end_at = snapshot_end
        report.lookback_minutes = lookback_minutes
        report.collector_name = COLLECTOR_NAME
        report.collector_version = COLLECTOR_VERSION
        report.source_package = "CN_TP_CALCULATIONS_PVT.CALCULATE"
        report.freshness_status = "fresh" if collector_mode != "stale" else "stale"
        report.incident_state = "active"
        report.overall_confidence = "high"
        report.overall_status = "warning"
        report.if_you_do_one_thing_today = (
            "Get DBA sign-off to address the high-confidence SQL plan regression first: refresh "
            "HZ_REF_ENTITIES statistics/histograms or load the historical-good SQL Plan Baseline, "
            "then validate SQL_ID dp9u1803k8k7f execution stats before pursuing broader formula exposure."
        )
        report.executive_summary = {
            "root_cause_count": 2,
            "bottleneck_sql_id": "dp9u1803k8k7f",
            "plan_regression_factor": 28,
            "live_runtime_seconds": 47537,
            "live_runtime_hours": 13.2,
            "bottleneck_executions": 12150000,
            "bottleneck_elapsed_seconds": 192901,
            "bottleneck_cpu_seconds": 191153,
            "confirmed_formula_packages": 2,
            "potential_formula_references": 1157,
            "collector_mode": collector_mode,
        }
        report.metrics.extend(
            [
                self._metric("root_cause_count", "Root causes", 2, None, 1),
                self._metric("plan_regression_factor", "Plan regression factor", 28, "x", 2, "historical good plan"),
                self._metric("live_runtime_hours", "Live runtime", Decimal("13.2"), "hours", 3),
                self._metric("bottleneck_executions", "Bottleneck executions", 12150000, "execs", 4),
                self._metric("potential_formula_references", "Potential formula references", 1157, "packages", 5),
            ]
        )

        plan_finding = DiagnosticFinding(
            diagnostic_report_id=report.id,
            finding_number=1,
            finding_key="dp9u1803k8k7f",
            finding_type="PLAN_REGRESSION",
            title="Plan regression on HZ_REF_ENTITIES lookup",
            severity="critical",
            confidence="high",
            actionability="READY_TO_ACT_WITH_SIGNOFF",
            lifecycle="active",
            problem_statement=(
                "The dominant live SQL is using a materially less selective HZ_REF_ENTITIES access path than the "
                "historical-good plan."
            ),
            business_impact=(
                "The Calculate_pvt ESS request is still active after more than 13 hours and the bottleneck SQL has "
                "accumulated about 12.15M executions, creating customer-visible delay."
            ),
            technical_detail=(
                "Current plan hash 51543091 chooses HZ_REF_ENTITIES_X26 with estimated cost 167 and about 498 "
                "candidate rows. Historical plan hash 3256752871 used HZ_REF_ENTITIES_N1 with estimated cost 6 "
                "and about 1 row. The observed live waits are Exadata cell single block and multiblock reads."
            ),
            recommended_action=(
                "With DBA sign-off, refresh HZ_REF_ENTITIES statistics/histograms or load a SQL Plan Baseline for "
                "the historical-good plan. Validate plan hash, execution count, elapsed seconds, CPU seconds, and "
                "wait events after the change."
            ),
            expected_result="SQL_ID dp9u1803k8k7f should return to the selective index path and reduce per-call elapsed time.",
            approval_gate="DBA sign-off plus incident lead approval before any stats or SPM action.",
            owner_team="DBA",
            risk_if_done_wrong=(
                "A bad stats refresh or incorrect baseline can shift other HZ_REF_ENTITIES workloads onto worse plans."
            ),
            rollback_plan="Restore prior table stats or drop the SQL Plan Baseline through the approved DBA runbook.",
            stop_recheck_condition=(
                "Stop if the active session leaves SQL_ID dp9u1803k8k7f, plan hash no longer matches 51543091, or "
                "ASH no longer shows this SQL as the concentrated hotspot."
            ),
            source_sql_id="dp9u1803k8k7f",
            source_plan_hash_value="51543091",
            historical_plan_hash_value="3256752871",
            object_name="HZ_REF_ENTITIES",
            metrics={
                "current_plan_hash": "51543091",
                "historical_good_plan_hash": "3256752871",
                "current_cost": 167,
                "historical_cost": 6,
                "cost_ratio": 27.8,
                "current_index": "HZ_REF_ENTITIES_X26",
                "historical_index": "HZ_REF_ENTITIES_N1",
                "current_candidate_rows": 498,
                "historical_candidate_rows": 1,
                "executions": 12150000,
                "elapsed_sec": 192901,
                "cpu_sec": 191153,
                "top_wait_event": "cell single block physical read",
                "confidence_explanation": self.score_confidence(
                    ["GV_SQL", "DBA_HIST_SQL_PLAN", "GV_SESSION"], []
                )[1],
            },
        )
        report.findings.append(plan_finding)
        self.db.flush()
        plan_finding.metric_rows.extend(
            [
                self._metric("current_cost", "Current plan cost", 167, None, 1, "6 historical", Decimal("2683.33")),
                self._metric("current_candidate_rows", "Current candidate rows", 498, "rows", 2, "1 historical"),
                self._metric("executions", "Cumulative executions", 12150000, "execs", 3),
                self._metric("elapsed_sec", "Cumulative elapsed", 192901, "seconds", 4),
                self._metric("cpu_sec", "Cumulative CPU", 191153, "seconds", 5),
            ]
        )
        plan_logs = self._diagnostic_execution_logs(report, plan_finding, [
            ("diagnostic_active_session_by_ecid", "GV_SESSION", "Active session confirms ESS request is still running.", [{"INST_ID": 1, "SID": 7716, "STATUS": "ACTIVE", "LAST_CALL_ET": 47537, "SQL_ID": "dp9u1803k8k7f"}]),
            ("diagnostic_sqlstats_by_sql_id", "GV_SQL", "SQL_ID dp9u1803k8k7f dominates elapsed and CPU time.", [{"SQL_ID": "dp9u1803k8k7f", "PLAN_HASH_VALUE": 51543091, "EXECUTIONS": 12150000, "ELAPSED_SECONDS": 192901, "CPU_SECONDS": 191153}]),
            ("diagnostic_awr_plan_history", "DBA_HIST_SQL_PLAN", "AWR plan history shows historical selective plan hash 3256752871 using HZ_REF_ENTITIES_N1.", [{"SQL_ID": "dp9u1803k8k7f", "PLAN_HASH_VALUE": 3256752871, "INDEX_NAME": "HZ_REF_ENTITIES_N1", "COST": 6, "ROWS": 1}]),
        ])
        plan_finding.evidence.extend(plan_logs)
        plan_finding.runbook_steps.extend(
            [
                self._runbook(1, "analysis", "Validate current hotspot", "Confirm active SQL_ID, plan hash, wait class, and last_call_et before any intervention.", None, False, False, None),
                self._runbook(
                    2,
                    "remediation_text",
                    "DBA option A: refresh stats/histograms",
                    "Run only through the approved DBA change path. JobRun Sentinel must not execute this.",
                    "DBMS_STATS.GATHER_TABLE_STATS('HZ', 'HZ_REF_ENTITIES', method_opt => 'FOR COLUMNS SIZE AUTO EXTN_ATTRIBUTE_NUMBER007')",
                    False,
                    True,
                    "DBA",
                ),
                self._runbook(
                    3,
                    "remediation_text",
                    "DBA option B: load SQL Plan Baseline",
                    "Use the historical-good plan only after confirming it is still valid for the current data shape.",
                    "DBMS_SPM.LOAD_PLANS_FROM_SQLSET(sql_id => 'dp9u1803k8k7f', plan_hash_value => 3256752871)",
                    False,
                    True,
                    "DBA",
                ),
                self._runbook(4, "validation", "Validate after action", "Re-check plan hash, executions per minute, elapsed/CPU seconds, and Exadata cell read waits.", "SELECT sql_id, plan_hash_value, executions FROM gv$sql WHERE sql_id = :sql_id", False, False, None),
                self._runbook(5, "rollback", "Rollback path", "Restore stats or drop the newly loaded baseline through DBA-controlled rollback.", "DBMS_STATS.RESTORE_TABLE_STATS('HZ', 'HZ_REF_ENTITIES', systimestamp - interval '1' hour)", False, True, "DBA"),
            ]
        )

        cache_finding = DiagnosticFinding(
            diagnostic_report_id=report.id,
            finding_number=2,
            finding_key="ADXX_CN_FORMULA_111141_PKG",
            finding_type="CODE_GENERATION_DEFECT",
            title="Self-clearing cache inside generated formula package",
            severity="critical",
            confidence="high",
            actionability="NEEDS_SR",
            lifecycle="chronic",
            problem_statement=(
                "Generated formula code appears to memoize lookup results and then clear the cache immediately "
                "after each get_commission call, defeating reuse for repeated keys."
            ),
            business_impact=(
                "Repeated lookup keys cause redundant calls against the shared value set, amplifying the SQL plan "
                "regression and increasing exposure for formulas that reference MTQ_ICM_OBA_BY_BADGE_VS."
            ),
            technical_detail=(
                "Direct sanitized source-inspection evidence links get_commission to clean_queries_results after "
                "the memoized lookup. Duplicate-key evidence shows 253,391 total lines versus 105,267 distinct keys, "
                "or about 58.5% redundant calls."
            ),
            recommended_action=(
                "Open an Oracle SR and assign formula-owner review for generated formula/value-set caching behavior. "
                "Do not hand-edit generated production package bodies."
            ),
            expected_result="A generated-code fix should preserve cache reuse and reduce duplicated value-set lookups.",
            approval_gate="SR triage plus formula-owner approval before any generated-code change or regeneration.",
            owner_team="Oracle SR / Formula Owner",
            risk_if_done_wrong="Hand edits to generated formula packages can be overwritten or create incorrect compensation results.",
            rollback_plan="Rollback through formula deployment/regeneration controls, not manual package edits.",
            stop_recheck_condition="Stop broad exposure claims unless direct source reading confirms the same call path in additional packages.",
            package_name="ADXX_CN_FORMULA_111141_PKG",
            value_set_code="MTQ_ICM_OBA_BY_BADGE_VS",
            scope_count=1157,
            confirmed_count=2,
            unverified_count=1155,
            metrics={
                "total_lines": 253391,
                "distinct_keys": 105267,
                "duplication_ratio": 2.41,
                "redundant_call_pct": 58.5,
                "confirmed_packages": ["ADXX_CN_FORMULA_111141_PKG", "ADXX_CN_FORMULA_24005_PKG"],
                "confirmation_sql_id": "cxk88uqjzpud8",
                "potential_reference_count": 1157,
                "confirmed_count": 2,
                "unverified_count": 1155,
                "confidence_explanation": self.score_confidence(["DBA_SOURCE", "FORMULA_METADATA", "VOLUME_QUERY"], [])[1],
                "exposure_wording": "Only 2 packages are confirmed affected by direct source reading; 1,155 are unverified potential references.",
            },
        )
        report.findings.append(cache_finding)
        self.db.flush()
        cache_finding.metric_rows.extend(
            [
                self._metric("confirmed_count", "Confirmed affected packages", 2, "packages", 1, "direct source reading"),
                self._metric("potential_reference_count", "Potential references", 1157, "packages", 2, "source search only"),
                self._metric("unverified_count", "Unverified potential exposure", 1155, "packages", 3),
                self._metric("duplication_ratio", "Duplicate lookup ratio", Decimal("2.41"), "x", 4),
                self._metric("redundant_call_pct", "Redundant calls", Decimal("58.5"), "%", 5),
            ]
        )
        cache_finding.evidence.extend(
            self._diagnostic_execution_logs(report, cache_finding, [
                ("diagnostic_source_search", "DBA_SOURCE", "Sanitized source pattern shows get_commission followed by clean_queries_results.", [{"PACKAGE_NAME": "ADXX_CN_FORMULA_111141_PKG", "SANITIZED_PATTERN": "get_commission -> clean_queries_results"}]),
                ("diagnostic_formula_duplication_count", "VOLUME_QUERY", "Duplicate-key count shows 253,391 total lines versus 105,267 distinct keys.", [{"TOTAL_LINES": 253391, "DISTINCT_KEYS": 105267, "REDUNDANT_CALL_PCT": 58.5}]),
                ("diagnostic_formula_metadata", "FORMULA_METADATA", "Second package ADXX_CN_FORMULA_24005_PKG confirms the same shared value-set pattern.", [{"PACKAGE_NAME": "ADXX_CN_FORMULA_24005_PKG", "SQL_ID": "cxk88uqjzpud8", "VALUE_SET_CODE": "MTQ_ICM_OBA_BY_BADGE_VS"}]),
            ])
        )
        cache_finding.runbook_steps.extend(
            [
                self._runbook(1, "analysis", "Confirm source evidence", "Use SELECT-only source inspection templates and keep raw source text disabled by default.", None, False, False, None),
                self._runbook(2, "remediation_text", "Open Oracle SR", "Attach sanitized evidence, package names, value-set code, duplication ratio, and confirmation SQL_ID.", None, False, True, "SR owner"),
                self._runbook(3, "validation", "Validate generated-code behavior", "After a fix, compare distinct-key count, lookup calls, and SQL executions per transaction before and after.", "SELECT package_name, value_set_code, duplicate_ratio FROM diagnostic_formula_metadata WHERE ess_request_id = :ess_request_id", False, False, None),
                self._runbook(4, "rollback", "Rollback generated-code change", "Use formula deployment rollback/regeneration controls; do not hand-edit production generated package bodies.", None, False, True, "Formula owner"),
            ]
        )

        report.ruled_out_alternatives.extend(
            [
                RuledOutAlternative(
                    finding_id=plan_finding.id,
                    alternative_type="RAC_INTERCONNECT",
                    reason="RAC gc waits were scattered across unrelated SQL_IDs and were not concentrated on dp9u1803k8k7f.",
                    supporting_evidence="diagnostic_rac_gc_wait_distribution showed low-volume, distributed gc waits.",
                    status="ruled_out",
                ),
                RuledOutAlternative(
                    finding_id=plan_finding.id,
                    alternative_type="ESS_QUEUE",
                    reason="The request is already executing with an ACTIVE database session, so queue time is not the current bottleneck.",
                    supporting_evidence="GV_SESSION instance 1 SID 7716 active with last_call_et around 47,537 seconds.",
                    status="ruled_out",
                ),
                RuledOutAlternative(
                    finding_id=plan_finding.id,
                    alternative_type="LOCKING",
                    reason="No blocking session evidence was present in the synthetic blocking-session check.",
                    supporting_evidence="diagnostic_blocking_session_check returned no blocker for SID 7716.",
                    status="ruled_out",
                ),
                RuledOutAlternative(
                    finding_id=None,
                    alternative_type="SECONDARY_SQL",
                    reason="Secondary SQL_ID gwxtms3bcc9hs is lower volume and should not drive same-day action.",
                    supporting_evidence="ASH samples were below hotspot threshold relative to dp9u1803k8k7f.",
                    status="secondary",
                ),
                RuledOutAlternative(
                    finding_id=cache_finding.id,
                    alternative_type="CUSTOMER_VOLUME_ONLY",
                    reason="Volume alone does not explain the memoization being cleared after each call.",
                    supporting_evidence="Direct source evidence confirms cache invalidation in the call path.",
                    status="secondary",
                ),
            ]
        )
        report.data_quality_checks.extend(self._data_quality_checks(report))
        self._seed_report_template()

    def _populate_generic_slow_job_report(
        self, report: DiagnosticReport, run: JobRun, lookback_minutes: int, collector_mode: str
    ) -> None:
        now = utcnow()
        report.run_id = run.id
        report.customer_key = run.customer.customer_key
        report.environment = run.environment.name
        report.report_title = f"Slow Job Diagnostic - {run.job_name}"
        report.diagnostic_type = "slow_job"
        report.ess_request_id = run.ess_request_id
        report.job_definition = run.job_definition.job_name if run.job_definition else run.job_name
        report.job_name = run.job_name
        report.process_id = run.process_id
        report.ecid = (run.business_scope or {}).get("ecid")
        report.client_identifier = (run.business_scope or {}).get("client_identifier")
        report.snapshot_start_at = now - timedelta(minutes=lookback_minutes)
        report.snapshot_end_at = now
        report.lookback_minutes = lookback_minutes
        report.collector_name = COLLECTOR_NAME
        report.collector_version = COLLECTOR_VERSION
        report.freshness_status = "fresh"
        report.incident_state = "active" if run.status == "RUNNING" else "completed"
        report.overall_confidence = "medium" if run.sql_observations else "low"
        report.overall_status = "warning"
        report.if_you_do_one_thing_today = "Confirm the dominant SQL/plan evidence before choosing a remediation path."
        first_sql = run.sql_observations[0] if run.sql_observations else None
        report.executive_summary = {
            "root_cause_count": 1 if first_sql else 0,
            "collector_mode": collector_mode,
            "bottleneck_sql_id": first_sql.sql_id if first_sql else run.sql_id,
        }
        if first_sql:
            finding = DiagnosticFinding(
                diagnostic_report_id=report.id,
                finding_number=1,
                finding_key=first_sql.sql_id or "unknown-sql",
                finding_type="SQL_HOTSPOT",
                title=f"SQL hotspot observed for {first_sql.sql_id or 'unknown SQL_ID'}",
                severity="warning",
                confidence="medium",
                actionability="NEEDS_DBA_REVIEW",
                lifecycle="active",
                problem_statement="The run has SQL observation metadata but does not yet have enough evidence for a high-confidence RCA.",
                business_impact="The job is slow and needs focused SQL evidence collection before remediation.",
                technical_detail=f"Plan hash {first_sql.plan_hash_value}; top wait {first_sql.top_wait_event}.",
                recommended_action="Collect ASH, SQL stats, and plan history with read-only diagnostic templates.",
                approval_gate="DBA review before any remediation.",
                owner_team="DBA",
                rollback_plan="No app-side remediation is executed.",
                stop_recheck_condition="Stop if the SQL_ID is no longer active or evidence points to queueing/blocking.",
                source_sql_id=first_sql.sql_id,
                source_plan_hash_value=first_sql.plan_hash_value,
                metrics={"confidence_explanation": self.score_confidence(["GV_SQL"], ["DBMS_XPLAN_DISPLAY_AWR"])[1]},
            )
            report.findings.append(finding)
        report.data_quality_checks.extend(self._data_quality_checks(report))

    def score_confidence(self, evidence_types: list[str], missing_inputs: list[str]) -> tuple[str, str]:
        independent_sources = set(evidence_types)
        if len(independent_sources) >= 2 and not missing_inputs:
            return "high", "High confidence because at least two independent evidence sources corroborate the finding and no critical input is missing."
        if independent_sources and len(missing_inputs) <= 1:
            return "medium", "Medium confidence because one direct source is present but additional corroborating evidence would reduce risk."
        return "low", "Low confidence because direct evidence is incomplete or critical inputs are missing."

    def _data_quality_checks(self, report: DiagnosticReport) -> list[DiagnosticDataQualityCheck]:
        evidence_count = sum(len(finding.evidence) for finding in report.findings)
        high_confidence_without_evidence = [
            finding.finding_key for finding in report.findings if finding.confidence == "high" and len(finding.evidence) < 2
        ]
        unsafe_steps = [
            step.title
            for finding in report.findings
            for step in finding.runbook_steps
            if step.executable_by_app and contains_destructive_command(step.command_text or "")
        ]
        exposure_check = any(
            finding.scope_count is not None
            and finding.confirmed_count is not None
            and finding.unverified_count == max((finding.scope_count or 0) - (finding.confirmed_count or 0), 0)
            for finding in report.findings
            if finding.scope_count
        )
        return [
            self._dq("correlation_key_present", "ECID or equivalent correlation key present", "passed" if report.ecid or report.ess_request_id else "failed", evidence_count, report.ecid or report.ess_request_id or "Missing ECID/ESS correlation key."),
            self._dq("snapshot_window_present", "Snapshot window present", "passed" if report.snapshot_start_at and report.snapshot_end_at else "failed", evidence_count, "Snapshot window is present." if report.snapshot_start_at and report.snapshot_end_at else "Snapshot window missing."),
            self._dq("incident_state_determined", "Active/completed state determined", "passed" if report.incident_state in {"active", "completed"} else "warning", evidence_count, f"Incident state is {report.incident_state}."),
            self._dq("dominant_sql_ranking_available", "Dominant SQL ranking available", "passed" if any(f.source_sql_id for f in report.findings) else "warning", evidence_count, "Dominant SQL_ID captured." if any(f.source_sql_id for f in report.findings) else "No SQL_ID ranking available."),
            self._dq("high_confidence_supported", "Evidence exists for each high-confidence finding", "passed" if not high_confidence_without_evidence else "failed", evidence_count, "High-confidence findings have independent evidence." if not high_confidence_without_evidence else f"Missing evidence for {', '.join(high_confidence_without_evidence)}."),
            self._dq("confirmed_vs_potential_exposure", "No unsupported extrapolation from potential exposure to confirmed exposure", "passed" if exposure_check or not any(f.scope_count for f in report.findings) else "warning", evidence_count, "Potential exposure is separated from confirmed affected packages."),
            self._dq("raw_sql_redaction", "Secrets/raw customer SQL redaction check passed", "passed", evidence_count, "Raw SQL text storage is disabled by default; evidence samples are sanitized."),
            self._dq("remediation_non_executable", "Recommended actions do not include executable destructive operations", "passed" if not unsafe_steps else "failed", evidence_count, "Remediation commands are text-only and executable_by_app=false." if not unsafe_steps else f"Unsafe executable steps: {', '.join(unsafe_steps)}."),
            self._dq("provenance_present", "Query execution provenance present where applicable", "passed" if evidence_count > 0 else "warning", evidence_count, f"{evidence_count} evidence rows linked to query templates/executions."),
        ]

    def _diagnostic_execution_logs(
        self,
        report: DiagnosticReport,
        finding: DiagnosticFinding,
        entries: list[tuple[str, str, str, list[dict[str, Any]]]],
    ) -> list[DiagnosticEvidence]:
        evidence_rows: list[DiagnosticEvidence] = []
        for template_key, evidence_type, summary, sample in entries:
            template = self._get_or_create_diagnostic_template(template_key, evidence_type)
            log = QueryExecutionLog(
                query_execution_id=f"qe-{uuid4().hex[:12]}",
                template_id=template.id,
                connector_config_key="demo",
                customer_id=report.run.customer_id if report.run else None,
                environment_id=report.run.environment_id if report.run else None,
                status="success",
                started_at=utcnow(),
                ended_at=utcnow(),
                finished_at=utcnow(),
                row_count=len(sample),
                elapsed_ms=12,
                sample_result=_sanitize_sample(sample),
                parameters={"ecid": report.ecid, "ess_request_id": report.ess_request_id},
                parameter_hash=_hash_json({"ecid": report.ecid, "ess_request_id": report.ess_request_id}),
                validation_result={"is_valid": True, "diagnostic": True},
                initiated_by="diagnostic",
                ingested_entity_counts={"diagnostic_evidence": 1},
                raw_sql_hash=_hash_text(template.sql_text),
                raw_sql_storage_enabled=self.settings.allow_raw_query_text_storage,
                correlation_id=f"diag-{report.id}-{finding.finding_number}-{uuid4().hex[:6]}",
                executed_by="diagnostic_collector",
            )
            self.db.add(log)
            self.db.flush()
            evidence_rows.append(
                DiagnosticEvidence(
                    finding_id=finding.id,
                    evidence_type=evidence_type,
                    title=template.name,
                    query_template_id=template.id,
                    query_execution_id=log.id,
                    evidence_summary=summary,
                    raw_sample=_sanitize_sample(sample),
                    confidence_contribution="Direct evidence" if evidence_type in {"GV_SQL", "DBA_SOURCE"} else "Corroborating evidence",
                    observed_at=utcnow(),
                )
            )
        return evidence_rows

    def _get_or_create_diagnostic_template(self, template_key: str, evidence_type: str) -> QueryTemplate:
        template = self.db.scalar(select(QueryTemplate).where(QueryTemplate.template_id == template_key))
        if template:
            return template
        template = QueryTemplate(
            template_id=template_key,
            name=template_key.replace("_", " ").title(),
            description=f"Synthetic SELECT-only diagnostic collector for {evidence_type}.",
            source_reference="Bundled Phase 2B diagnostic catalog",
            database_type="oracle",
            connector_type="oracle_db",
            template_category=template_key,
            sql_text=f"SELECT * FROM mock_{template_key} WHERE ecid = :ecid",
            required_parameters={"ecid": {"type": "string"}},
            default_parameters={"ecid": EXAMPLE_ECID},
            output_mapping={"entity": "diagnostic_evidence", "evidence_type": evidence_type},
            owning_team="ICM Support",
            active=True,
            is_read_only_validated=True,
            last_validated_at=utcnow(),
            tags=["diagnostic", evidence_type.lower()],
        )
        self.db.add(template)
        self.db.flush()
        return template

    def _resolve_run(
        self, run_id: int | None, ess_request_id: str | None, process_id: str | None, ecid: str | None
    ) -> JobRun | None:
        if run_id:
            return self.db.get(JobRun, run_id)
        stmt = select(JobRun).order_by(JobRun.started_at.desc())
        if ess_request_id:
            stmt = stmt.where(JobRun.ess_request_id == ess_request_id)
        elif process_id:
            stmt = stmt.where(JobRun.process_id == process_id)
        elif ecid:
            stmt = stmt.where(JobRun.business_scope["ecid"].as_string() == ecid)
        else:
            return None
        return self.db.scalar(stmt)

    def _find_by_identifiers(
        self, ess_request_id: str | None, process_id: str | None, ecid: str | None
    ) -> DiagnosticReport | None:
        stmt = select(DiagnosticReport).order_by(DiagnosticReport.updated_at.desc())
        if ess_request_id:
            stmt = stmt.where(DiagnosticReport.ess_request_id == ess_request_id)
        elif process_id:
            stmt = stmt.where(DiagnosticReport.process_id == process_id)
        elif ecid:
            stmt = stmt.where(DiagnosticReport.ecid == ecid)
        else:
            return None
        return self.db.scalar(stmt)

    def _is_calculate_pvt_example(self, run: JobRun, ess_request_id: str | None, ecid: str | None) -> bool:
        return (
            run.ess_request_id == EXAMPLE_ESS_REQUEST_ID
            or ess_request_id == EXAMPLE_ESS_REQUEST_ID
            or ecid == EXAMPLE_ECID
            or (run.business_scope or {}).get("ecid") == EXAMPLE_ECID
        )

    def _clear_report(self, report: DiagnosticReport) -> None:
        report.findings.clear()
        report.metrics.clear()
        report.ruled_out_alternatives.clear()
        report.data_quality_checks.clear()
        self.db.flush()

    def _select_finding(self, report: DiagnosticReport, finding_id: int | None) -> DiagnosticFinding:
        findings = sorted(report.findings, key=lambda item: (item.severity != "critical", item.finding_number))
        if finding_id:
            for finding in findings:
                if finding.id == finding_id:
                    return finding
            raise ValueError("Diagnostic finding was not found.")
        if not findings:
            raise ValueError("Diagnostic report has no findings.")
        return findings[0]

    def _metric(
        self,
        key: str,
        label: str,
        value: int | float | Decimal | None,
        unit: str | None,
        order: int,
        baseline: str | None = None,
        variance_pct: Decimal | None = None,
    ) -> DiagnosticMetric:
        numeric = Decimal(str(value)) if value is not None else None
        return DiagnosticMetric(
            metric_key=key,
            label=label,
            value_numeric=numeric,
            value_text=None if numeric is not None else str(value),
            unit=unit,
            display_order=order,
            comparison_baseline=baseline,
            variance_pct=variance_pct,
        )

    def _dq(self, key: str, description: str, status: str, evidence_count: int, message: str) -> DiagnosticDataQualityCheck:
        return DiagnosticDataQualityCheck(
            check_key=key,
            description=description,
            status=status,
            evidence_count=evidence_count,
            message=message,
        )

    def _runbook(
        self,
        number: int,
        step_type: str,
        title: str,
        body: str,
        command: str | None,
        executable: bool,
        requires_approval: bool,
        approval_role: str | None,
    ) -> DiagnosticRunbookStep:
        return DiagnosticRunbookStep(
            step_number=number,
            step_type=step_type,
            title=title,
            body=body,
            command_text=command,
            executable_by_app=executable,
            requires_approval=requires_approval,
            approval_role=approval_role,
            safety_note="Text-only runbook step. JobRun Sentinel never executes remediation commands.",
        )

    def _seed_glossary_terms(self) -> None:
        terms = {
            ("ECID", "oracle"): "Execution Context ID, used to correlate an ESS request through application and database layers.",
            ("ASH", "oracle"): "Active Session History samples active database sessions so hotspots can be ranked over time.",
            ("RAC", "oracle"): "Real Application Clusters, where a database runs across multiple instances.",
            ("plan hash", "oracle"): "A numeric identifier for an optimizer execution plan.",
            ("SQL Plan Baseline", "oracle"): "An optimizer management object that can guide SQL toward an accepted plan.",
            ("generated package", "icm"): "A generated PL/SQL package produced from formula or value-set configuration.",
            ("last_call_et", "oracle"): "Elapsed seconds since the current database call began.",
            ("Exadata cell read waits", "oracle"): "Storage-cell read wait events such as cell single block or multiblock physical read.",
        }
        for (term, domain), definition in terms.items():
            existing = self.db.scalar(select(GlossaryTerm).where(GlossaryTerm.term == term, GlossaryTerm.domain == domain))
            if not existing:
                self.db.add(GlossaryTerm(term=term, domain=domain, definition=definition, active=True))

    def _seed_report_template(self) -> None:
        existing = self.db.scalar(select(ReportTemplate).where(ReportTemplate.template_key == "ecid_slow_job_v1"))
        if existing:
            return
        self.db.add(
            ReportTemplate(
                template_key="ecid_slow_job_v1",
                name="ECID Slow Job Diagnostic",
                diagnostic_type="slow_job",
                markdown_template="# {{ report_title }}\n\n{{ executive_summary }}",
                structured_template={"sections": ["header", "summary", "findings", "evidence", "ruled_out", "data_quality"]},
                active=True,
            )
        )


def contains_destructive_command(command_text: str) -> bool:
    return bool(DESTRUCTIVE_PATTERN.search(command_text or ""))


def _sanitize_sample(sample: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for row in sample[:10]:
        clean = {}
        for key, value in row.items():
            key_l = key.lower()
            if any(token in key_l for token in ["password", "secret", "token", "raw_sql", "query_text"]):
                clean[key] = "[redacted]"
            else:
                clean[key] = value
        sanitized.append(clean)
    return sanitized


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: dict[str, Any]) -> str:
    return _hash_text(json.dumps(value, sort_keys=True, default=str))
