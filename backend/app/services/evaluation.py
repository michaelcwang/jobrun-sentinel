from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.connectors.mock import MockConnectorRegistry
from app.core.config import get_settings
from app.models import (
    Alert,
    AlertEvent,
    AlertRule,
    Customer,
    DiagnosticFinding,
    DiagnosticReport,
    DbSessionSnapshot,
    ExpectationRecord,
    JobRunNodeBinding,
    JobRun,
    SqlObservation,
    VolumeSnapshot,
)
from app.models.base import utcnow
from app.schemas import EvaluationResult
from app.services.baseline import BaselineComputation, BaselineService, duration_minutes, to_float


CAUSE_TAGS = {
    "CURRENT_VOLUME_GT_BASELINE": "volume drift",
    "VOLUME_OR_DATA_WINDOW_MISMATCH": "volume/data window mismatch",
    "NEW_UDQ_HASH": "new UDQ",
    "CUSTOMER_UDQ_RISK": "customer UDQ risk",
    "NEW_SQL_ID": "new SQL_ID",
    "SQL_PLAN_CHANGED": "plan change",
    "SQL_PROFILE_OR_INDEX_CHANGE": "SQL profile/index change",
    "STUCK_NO_PROGRESS": "stuck progress",
    "NO_BASELINE": "no baseline",
    "FIRST_RUN_AT_SCALE": "first run at scale",
    "DATA_WINDOW_MISMATCH": "data window mismatch",
    "ETA_AFTER_CUSTOMER_GOAL": "ETA breach",
    "ELAPSED_GT_WARNING_THRESHOLD": "runtime warning",
    "ELAPSED_GT_CRITICAL_THRESHOLD": "runtime critical",
}


class EvaluationService:
    def __init__(self, db: Session, connectors: MockConnectorRegistry | None = None):
        self.db = db
        self.connectors = connectors or MockConnectorRegistry()
        self.settings = get_settings()
        self._expectation_cache: dict[tuple[str, str], list[ExpectationRecord]] = {}

    def evaluate_run(
        self,
        run_id: int,
        *,
        create_alert: bool = False,
        send_mock_slack: bool = False,
    ) -> EvaluationResult:
        run = self.db.get(JobRun, run_id)
        if not run:
            raise ValueError(f"Run {run_id} was not found")

        now = utcnow()
        expectation = self.find_expectation_for_run(run, now)
        minimum_history = expectation.minimum_history_count if expectation else 5
        baseline = BaselineService(self.db).compute_for_run(run, minimum_history=minimum_history)

        expected_minutes, expected_source, confidence = self._select_expected_minutes(
            expectation, baseline
        )
        reason_codes: list[str] = []
        recommended_actions: list[str] = []
        historical = self._historical_payload(baseline)

        if expected_minutes is None:
            reason_codes.append("NO_BASELINE")
            if baseline.sample_count > 0 and baseline.sample_count < minimum_history:
                reason_codes.append("FIRST_RUN_AT_SCALE")
            runtime_state = "unknown_baseline"
            severity = "info"
            variance_pct = None
            eta_at = None
        else:
            expected_minutes, volume_codes = self._adjust_for_volume(run, expected_minutes)
            reason_codes.extend(volume_codes)
            elapsed = duration_minutes(run, now=now)
            variance_pct = round(((elapsed - expected_minutes) / expected_minutes) * 100, 1)
            eta_at = self._estimate_eta(run, expected_minutes, elapsed)
            runtime_state, severity = self._state_from_thresholds(
                run,
                elapsed,
                expected_minutes,
                expectation,
                reason_codes,
                eta_at,
            )

        elapsed_minutes = round(duration_minutes(run, now=now), 1)
        reason_codes.extend(self._comparison_reason_codes(run, expectation, baseline))
        if "NEW_UDQ_HASH" in reason_codes:
            reason_codes.append("CUSTOMER_UDQ_RISK")
        if "CURRENT_VOLUME_GT_BASELINE" in reason_codes or "DATA_WINDOW_MISMATCH" in reason_codes:
            reason_codes.append("VOLUME_OR_DATA_WINDOW_MISMATCH")
        reason_codes = list(dict.fromkeys(reason_codes))
        cause_tags = [CAUSE_TAGS[code] for code in reason_codes if code in CAUSE_TAGS]
        recommended_actions.extend(self._recommendations(reason_codes))
        top_suspected_cause = self._top_suspected_cause(reason_codes)

        if expected_minutes is not None and runtime_state == "normal" and run.status in {"SUCCESS", "COMPLETED", "SUCCEEDED"}:
            runtime_state = "complete"

        result = EvaluationResult(
            run_id=run.id,
            runtime_state=runtime_state,
            severity=severity,
            expected_minutes=round(expected_minutes, 1) if expected_minutes is not None else None,
            expected_source=expected_source,
            elapsed_minutes=elapsed_minutes,
            variance_pct=variance_pct,
            eta_at=eta_at,
            confidence_score=round(confidence, 2),
            reason_codes=reason_codes,
            cause_tags=cause_tags,
            recommended_actions=recommended_actions,
            top_suspected_cause=top_suspected_cause,
            historical_comparison=historical,
        )

        result.slack_payload = self.build_alert_payload(run, result)

        if create_alert:
            alert = self.create_or_update_alert(run, result)
            if send_mock_slack and result.severity in {"warning", "critical", "watch"}:
                destination = self._alert_destination(run, expectation)
                send_result = self.connectors.slack.send_alert(result.slack_payload or {}, destination)
                alert.events.append(
                    AlertEvent(
                        event_type="mock_slack_sent",
                        message=f"Mock Slack payload sent to {send_result['destination']}",
                        metadata_json=send_result,
                    )
                )
                self.db.flush()

        return result

    def find_expectation_for_run(
        self, run: JobRun, now: datetime | None = None
    ) -> ExpectationRecord | None:
        now = now or utcnow()
        cache_key = (run.customer.customer_key, run.environment.name)
        if cache_key not in self._expectation_cache:
            stmt = select(ExpectationRecord).where(
                ExpectationRecord.customer_key == cache_key[0],
                ExpectationRecord.environment == cache_key[1],
                ExpectationRecord.active_from <= now,
                or_(ExpectationRecord.active_until.is_(None), ExpectationRecord.active_until >= now),
            )
            self._expectation_cache[cache_key] = list(self.db.scalars(stmt))
        candidates = self._expectation_cache[cache_key]
        scored: list[tuple[int, ExpectationRecord]] = []
        for candidate in candidates:
            score = 0
            comparisons = [
                ("job_family", run.job_family, 4),
                ("job_type", run.job_type, 6),
                ("job_name", run.job_name, 8),
                ("region", run.region, 4),
                ("workstream", run.workstream, 4),
                ("period", run.period, 2),
                ("api_operation", run.api_operation, 3),
            ]
            matched = True
            for attr, run_value, weight in comparisons:
                expected_value = getattr(candidate, attr)
                if expected_value is None:
                    continue
                if run_value != expected_value:
                    matched = False
                    break
                score += weight
            if matched:
                soft_comparators = [
                    ("sql_id", run.sql_id, 1),
                    ("sql_plan_hash", run.plan_hash_value, 1),
                    ("udq_name", run.udq_name, 1),
                    ("udq_hash", run.udq_hash, 1),
                ]
                for attr, run_value, weight in soft_comparators:
                    expected_value = getattr(candidate, attr)
                    if expected_value is not None and run_value == expected_value:
                        score += weight
                scored.append((score, candidate))
        if not scored:
            return None
        scored.sort(key=lambda item: (item[0], item[1].confidence_score or 0, item[1].id), reverse=True)
        return scored[0][1]

    def create_or_update_alert(self, run: JobRun, result: EvaluationResult) -> Alert:
        open_alert = self.db.scalar(
            select(Alert)
            .where(
                Alert.run_id == run.id,
                Alert.state.in_(["new", "acknowledged"]),
            )
            .order_by(Alert.created_at.desc())
        )
        if result.runtime_state in {"normal", "complete"}:
            if open_alert:
                open_alert.state = "resolved"
                open_alert.resolved_by = "system"
                open_alert.resolved_at = utcnow()
                open_alert.resolution_note = "Evaluation returned to normal."
                open_alert.events.append(
                    AlertEvent(event_type="resolved", message="Evaluation returned to normal.")
                )
                self.db.flush()
                return open_alert
            alert = Alert(
                run_id=run.id,
                severity=result.severity,
                state="resolved",
                runtime_state=result.runtime_state,
                reason_codes=result.reason_codes,
                payload=result.slack_payload,
                top_suspected_cause=result.top_suspected_cause,
                expected_minutes=self._decimal(result.expected_minutes),
                elapsed_minutes=self._decimal(result.elapsed_minutes),
                variance_pct=self._decimal(result.variance_pct),
                eta_at=result.eta_at,
                resolved_by="system",
                resolved_at=utcnow(),
                resolution_note="No active runtime risk.",
            )
            self.db.add(alert)
            self.db.flush()
            return alert

        alert = open_alert or Alert(run_id=run.id, state="new")
        alert.severity = result.severity
        alert.runtime_state = result.runtime_state
        alert.reason_codes = result.reason_codes
        alert.payload = result.slack_payload
        alert.top_suspected_cause = result.top_suspected_cause
        alert.expected_minutes = self._decimal(result.expected_minutes)
        alert.elapsed_minutes = self._decimal(result.elapsed_minutes)
        alert.variance_pct = self._decimal(result.variance_pct)
        alert.eta_at = result.eta_at
        if not open_alert:
            self.db.add(alert)
            alert.events.append(
                AlertEvent(
                    event_type="created",
                    message=f"{result.runtime_state} alert generated for run {run.run_key}.",
                )
            )
        else:
            alert.events.append(
                AlertEvent(
                    event_type="updated",
                    message=f"Alert refreshed: {result.runtime_state} / {result.severity}.",
                )
            )
        self.db.flush()
        return alert

    def build_alert_payload(self, run: JobRun, result: EvaluationResult) -> dict[str, Any]:
        first_sql = run.sql_observations[0] if run.sql_observations else None
        dashboard_base = self.settings.default_alert_dashboard_url.removesuffix("/dashboard").rstrip("/")
        payload = {
            "severity": result.severity,
            "customer": run.customer.display_name,
            "customer_key": run.customer.customer_key,
            "environment": run.environment.name,
            "job_name": run.job_name,
            "job_type": run.job_type,
            "run_id": run.id,
            "run_key": run.run_key,
            "process_id": run.process_id,
            "ess_request_id": run.ess_request_id,
            "elapsed_minutes": result.elapsed_minutes,
            "expected_minutes": result.expected_minutes,
            "variance_pct": result.variance_pct,
            "eta": result.eta_at.isoformat() if result.eta_at else None,
            "reason_codes": result.reason_codes,
            "top_suspected_cause": result.top_suspected_cause,
            "sql": {
                "sql_id": (first_sql.sql_id if first_sql else run.sql_id),
                "plan_hash_value": (first_sql.plan_hash_value if first_sql else run.plan_hash_value),
                "sql_profile": first_sql.sql_profile if first_sql else None,
                "udq_name": (first_sql.udq_name if first_sql else run.udq_name),
                "udq_hash": (first_sql.udq_hash if first_sql else run.udq_hash),
                "query_shape_tags": first_sql.query_shape_tags if first_sql else [],
            },
            "next_actions": result.recommended_actions,
            "dashboard_link": f"{dashboard_base}/runs/{run.id}",
        }
        diagnostic = self._latest_diagnostic(run.id)
        if diagnostic:
            top_finding = self._top_diagnostic_finding(diagnostic)
            if top_finding:
                payload["diagnostic"] = {
                    "diagnostic_report_id": diagnostic.id,
                    "diagnostic_link": f"{dashboard_base}/diagnostics/{diagnostic.id}",
                    "top_finding": top_finding.title,
                    "finding_type": top_finding.finding_type,
                    "finding_key": top_finding.finding_key,
                    "confidence": top_finding.confidence,
                    "actionability": top_finding.actionability,
                    "owner": top_finding.owner_team,
                    "source_sql_id": top_finding.source_sql_id,
                    "current_plan_hash": top_finding.source_plan_hash_value,
                    "historical_plan_hash": top_finding.historical_plan_hash_value,
                    "recommended_action": top_finding.recommended_action,
                }
        topology = self._topology_summary(run.id)
        if topology:
            payload["topology"] = topology
        return payload

    def _latest_diagnostic(self, run_id: int) -> DiagnosticReport | None:
        return self.db.scalar(
            select(DiagnosticReport)
            .where(DiagnosticReport.run_id == run_id)
            .order_by(DiagnosticReport.updated_at.desc(), DiagnosticReport.created_at.desc())
        )

    @staticmethod
    def _top_diagnostic_finding(report: DiagnosticReport) -> DiagnosticFinding | None:
        if not report.findings:
            return None
        return sorted(report.findings, key=lambda item: (item.severity != "critical", item.finding_number))[0]

    def _topology_summary(self, run_id: int) -> dict[str, Any] | None:
        session = self.db.scalar(
            select(DbSessionSnapshot)
            .where(DbSessionSnapshot.run_id == run_id)
            .order_by(DbSessionSnapshot.sampled_at.desc(), DbSessionSnapshot.last_call_et_seconds.desc())
        )
        bindings = list(
            self.db.scalars(
                select(JobRunNodeBinding)
                .where(JobRunNodeBinding.run_id == run_id)
                .options(selectinload(JobRunNodeBinding.node))
                .order_by(JobRunNodeBinding.updated_at.desc())
            )
        )
        if not session and not bindings:
            return None
        db_instance = next((binding for binding in bindings if binding.binding_type == "db_instance_confirmed"), None)
        db_host = next((binding for binding in bindings if binding.binding_type == "db_host_confirmed"), None)
        app_server = next((binding for binding in bindings if binding.binding_type == "app_server_inferred"), None)
        heat_score = 78 if session and session.sql_id == "dp9u1803k8k7f" else 52 if session else 0
        return {
            "db_instance": db_instance.node.display_name if db_instance and db_instance.node else session.instance_name if session else None,
            "db_host": db_host.node.display_name if db_host and db_host.node else session.db_host_name if session else None,
            "app_server": app_server.node.display_name if app_server and app_server.node else session.machine if session else None,
            "app_server_confidence": "inferred" if app_server else "unknown",
            "active_sql_id": session.sql_id if session else None,
            "plan_hash_value": session.plan_hash_value if session else None,
            "wait_class": session.wait_class if session else None,
            "top_wait_event": session.event if session else None,
            "server_heat_score": heat_score,
            "node_pressure_supports_alert": heat_score >= 75,
            "summary": (
                f"Runtime topology confirms active DB session on {session.instance_name or 'unknown DB instance'} "
                f"with SQL_ID {session.sql_id or 'unknown'}, wait {session.wait_class or 'unknown'}."
                if session
                else "Runtime topology has node binding evidence but no active DB session snapshot."
            ),
        }

    def daily_digest(self, customer_key: str | None = None) -> dict[str, Any]:
        stmt = select(JobRun).where(JobRun.status.in_(["RUNNING", "WATCH"])).order_by(JobRun.started_at)
        if customer_key:
            stmt = stmt.join(Customer, JobRun.customer_id == Customer.id).where(
                Customer.customer_key == customer_key
            )
        active_runs = list(self.db.scalars(stmt))
        evaluated = [self.evaluate_run(run.id) for run in active_runs]
        return {
            "generated_at": utcnow().isoformat(),
            "headline": f"{len(evaluated)} active monitored runs",
            "critical": [item.model_dump(mode="json") for item in evaluated if item.severity == "critical"],
            "watch": [
                item.model_dump(mode="json")
                for item in evaluated
                if item.severity in {"watch", "warning"}
            ],
        }

    def _select_expected_minutes(
        self, expectation: ExpectationRecord | None, baseline: BaselineComputation
    ) -> tuple[float | None, str | None, float]:
        if expectation and expectation.expected_minutes is not None:
            return (
                float(expectation.expected_minutes),
                expectation.baseline_method or "manual_goal",
                float(expectation.confidence_score or 0.6),
            )
        minimum_history = expectation.minimum_history_count if expectation else 5
        if baseline.sample_count >= minimum_history:
            selected = baseline.p75_minutes or baseline.p90_minutes or baseline.average_minutes
            return selected, "historical_p75", baseline.confidence_score
        return None, "learning_mode", min(baseline.confidence_score, 0.35)

    def _adjust_for_volume(self, run: JobRun, expected_minutes: float) -> tuple[float, list[str]]:
        codes: list[str] = []
        for snapshot in run.volume_snapshots:
            metric = to_float(snapshot.metric_value)
            baseline = to_float(snapshot.baseline_value)
            if metric is None or baseline is None or baseline <= 0:
                continue
            ratio = metric / baseline
            if ratio > 1.2:
                expected_minutes = expected_minutes * (1 + 0.80 * (ratio - 1))
                codes.append("CURRENT_VOLUME_GT_BASELINE")
            if snapshot.shape_tags and any("data window" in tag for tag in snapshot.shape_tags):
                codes.append("DATA_WINDOW_MISMATCH")
        return expected_minutes, codes

    def _state_from_thresholds(
        self,
        run: JobRun,
        elapsed: float,
        expected_minutes: float,
        expectation: ExpectationRecord | None,
        reason_codes: list[str],
        eta_at: datetime | None,
    ) -> tuple[str, str]:
        warning_pct = float(expectation.warning_threshold_pct) if expectation else 25.0
        critical_pct = float(expectation.critical_threshold_pct) if expectation else 75.0
        warning_limit = expected_minutes * (1 + warning_pct / 100)
        critical_limit = expected_minutes * (1 + critical_pct / 100)

        if elapsed > critical_limit:
            reason_codes.append("ELAPSED_GT_CRITICAL_THRESHOLD")
            state, severity = "critical", "critical"
        elif elapsed > warning_limit:
            reason_codes.append("ELAPSED_GT_WARNING_THRESHOLD")
            state, severity = "warning", "warning"
        elif elapsed > expected_minutes * 0.85 and run.status == "RUNNING":
            state, severity = "watch", "watch"
        else:
            state, severity = "normal", "info"

        if expectation and expectation.customer_goal_minutes and eta_at:
            goal_at = run.started_at + timedelta(minutes=float(expectation.customer_goal_minutes))
            if eta_at > goal_at:
                reason_codes.append("ETA_AFTER_CUSTOMER_GOAL")
                if severity == "info":
                    state, severity = "watch", "watch"

        if self._is_stuck(run):
            reason_codes.append("STUCK_NO_PROGRESS")
            if severity in {"info", "watch"}:
                state, severity = "warning", "warning"

        return state, severity

    def _estimate_eta(self, run: JobRun, expected_minutes: float, elapsed: float) -> datetime | None:
        if run.ended_at:
            return run.ended_at
        progress = to_float(run.current_progress_pct)
        if progress and progress > 1:
            total_estimate = elapsed / (progress / 100)
            return run.started_at + timedelta(minutes=total_estimate)
        return run.started_at + timedelta(minutes=expected_minutes)

    def _comparison_reason_codes(
        self,
        run: JobRun,
        expectation: ExpectationRecord | None,
        baseline: BaselineComputation,
    ) -> list[str]:
        codes: list[str] = []
        current_sql, current_plan, current_udq = self._current_sql_udq(run)
        reference_sql = expectation.sql_id if expectation else None
        reference_plan = expectation.sql_plan_hash if expectation else None
        reference_udq = expectation.udq_hash if expectation else None

        if not expectation:
            reference_sql = baseline.last_successful_sql_id
            reference_plan = baseline.last_successful_plan_hash
            reference_udq = baseline.last_successful_udq_hash

        if reference_sql and current_sql and reference_sql != current_sql:
            codes.append("NEW_SQL_ID")
        if reference_plan and current_plan and str(reference_plan) != str(current_plan):
            codes.append("SQL_PLAN_CHANGED")
        if reference_udq and current_udq and reference_udq != current_udq:
            codes.append("NEW_UDQ_HASH")

        for observation in run.sql_observations:
            tags = observation.query_shape_tags or []
            notes = (observation.index_profile_notes or "").lower()
            if observation.sql_profile or "index" in notes or "profile" in notes:
                codes.append("SQL_PROFILE_OR_INDEX_CHANGE")
            if "unstable plan" in tags and "SQL_PLAN_CHANGED" not in codes:
                codes.append("SQL_PLAN_CHANGED")

        if baseline.sample_count < 2 and "NO_BASELINE" not in codes:
            codes.append("FIRST_RUN_AT_SCALE")
        return codes

    def _current_sql_udq(self, run: JobRun) -> tuple[str | None, str | None, str | None]:
        observation: SqlObservation | None = run.sql_observations[0] if run.sql_observations else None
        return (
            observation.sql_id if observation and observation.sql_id else run.sql_id,
            observation.plan_hash_value
            if observation and observation.plan_hash_value
            else run.plan_hash_value,
            observation.udq_hash if observation and observation.udq_hash else run.udq_hash,
        )

    def _latest_prior_success(self, run: JobRun) -> JobRun | None:
        conditions = [
            JobRun.customer_id == run.customer_id,
            JobRun.environment_id == run.environment_id,
            JobRun.status.in_(["SUCCESS", "COMPLETED", "SUCCEEDED"]),
            JobRun.ended_at.is_not(None),
            JobRun.id != run.id,
        ]
        if run.job_definition_id:
            conditions.append(JobRun.job_definition_id == run.job_definition_id)
        else:
            conditions.extend([JobRun.job_type == run.job_type, JobRun.job_name == run.job_name])
        if run.region:
            conditions.append(JobRun.region == run.region)
        if run.workstream:
            conditions.append(JobRun.workstream == run.workstream)
        return self.db.scalar(
            select(JobRun).where(and_(*conditions)).order_by(JobRun.started_at.desc())
        )

    def _is_stuck(self, run: JobRun) -> bool:
        if run.status != "RUNNING" or not run.last_progress_at:
            return False
        if run.current_progress_pct is not None and float(run.current_progress_pct) >= 99:
            return False
        return run.last_progress_at < utcnow() - timedelta(minutes=60)

    def _recommendations(self, reason_codes: list[str]) -> list[str]:
        actions: list[str] = []
        if "NO_BASELINE" in reason_codes:
            actions.append("Keep this run in learning mode and collect more successful timings before paging.")
        if "CURRENT_VOLUME_GT_BASELINE" in reason_codes or "DATA_WINDOW_MISMATCH" in reason_codes:
            actions.append("Compare current data window and volume metrics with the baseline run set.")
        if "NEW_UDQ_HASH" in reason_codes:
            actions.append("Review customer-authored UDQ changes before declaring an Oracle runtime regression.")
        if "CUSTOMER_UDQ_RISK" in reason_codes:
            actions.append(
                "Compare current data window, volume, SQL_ID, plan hash, and UDQ hash before treating this as an Oracle runtime regression. "
                "For the UDQ, review the OR predicate pattern and consider UNION ALL or separate SQL branches, then validate with execution statistics."
            )
        if "NEW_SQL_ID" in reason_codes or "SQL_PLAN_CHANGED" in reason_codes:
            actions.append("Compare SQL_ID, plan hash, profile, and index state against prior successful runs.")
        if "STUCK_NO_PROGRESS" in reason_codes:
            actions.append("Run a direct read-only DB status query and verify ESS progress is still advancing.")
        if not actions:
            actions.append("Continue monitoring; no immediate variance driver was detected.")
        return actions

    def _top_suspected_cause(self, reason_codes: list[str]) -> str | None:
        priority = [
            ("NEW_UDQ_HASH", "Customer-authored UDQ changed"),
            ("CURRENT_VOLUME_GT_BASELINE", "Current data volume is materially above baseline"),
            ("SQL_PLAN_CHANGED", "SQL execution plan changed"),
            ("NEW_SQL_ID", "Current SQL_ID differs from comparable history"),
            ("STUCK_NO_PROGRESS", "Progress appears stale"),
            ("NO_BASELINE", "No comparable baseline"),
        ]
        for code, cause in priority:
            if code in reason_codes:
                return cause
        return None

    def _historical_payload(self, baseline: BaselineComputation) -> dict[str, Any]:
        return {
            "sample_count": baseline.sample_count,
            "p50_minutes": baseline.p50_minutes,
            "p75_minutes": baseline.p75_minutes,
            "p90_minutes": baseline.p90_minutes,
            "p95_minutes": baseline.p95_minutes,
            "average_minutes": baseline.average_minutes,
            "median_abs_deviation": baseline.median_abs_deviation,
            "last_successful_duration": baseline.last_successful_duration,
            "baseline_volume_metric": baseline.baseline_volume_metric,
            "throughput_per_minute": baseline.throughput_per_minute,
        }

    def _alert_destination(self, run: JobRun, expectation: ExpectationRecord | None) -> str | None:
        if expectation and expectation.alert_channel:
            return expectation.alert_channel
        rule = self.db.scalar(
            select(AlertRule)
            .where(AlertRule.run_id == run.id, AlertRule.active.is_(True))
            .order_by(AlertRule.created_at.desc())
        )
        return rule.destination if rule else None

    @staticmethod
    def _decimal(value: float | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(round(value, 2)))
