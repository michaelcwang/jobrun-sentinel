from __future__ import annotations

from typing import Any

from app.models import DbSessionSnapshot, JobRunNodeBinding, RuntimeNodeMetricSample


class TopologyHeatScoreScorer:
    """Scores server-time heat from sessions, slow-job bindings, and node metrics."""

    def score(
        self,
        sessions: list[DbSessionSnapshot],
        bindings: list[JobRunNodeBinding],
        metrics: list[RuntimeNodeMetricSample],
        slow_run_ids: set[int] | None = None,
    ) -> tuple[float, dict[str, Any]]:
        slow_run_ids = slow_run_ids or set()
        active_slow_jobs = len(
            {
                binding.run_id
                for binding in bindings
                if binding.run and binding.run.status == "RUNNING" and binding.run_id in slow_run_ids
            }
        )
        wait_samples = len([session for session in sessions if session.wait_class and session.wait_class.lower() not in {"cpu", "idle"}])
        sql_concentration = max(
            [
                len([session for session in sessions if session.sql_id == sql_id])
                for sql_id in {session.sql_id for session in sessions if session.sql_id}
            ]
            or [0]
        )
        metric_values = {metric.metric_name: float(metric.metric_value) for metric in metrics}
        cpu = metric_values.get("cpu_utilization_pct", 0)
        gc = metric_values.get("wls_full_gc_pct", 0)
        cluster_waits = metric_values.get("db_cluster_wait_samples", 0)
        io_waits = metric_values.get("db_io_wait_samples", 0)
        app_waits = metric_values.get("db_application_wait_samples", 0)
        active_sessions = metric_values.get("db_active_sessions", 0)
        score = (
            active_slow_jobs * 22
            + wait_samples * 8
            + sql_concentration * 5
            + max(cpu - 60, 0) * 0.7
            + gc * 1.6
            + min(cluster_waits, 30) * 0.7
            + min(io_waits, 45) * 1.0
            + min(app_waits, 30) * 0.8
            + min(active_sessions, 50) * 0.45
        )
        return round(min(score, 100), 1), {
            "active_slow_jobs": active_slow_jobs,
            "wait_samples": wait_samples,
            "sql_concentration": sql_concentration,
            "cpu_utilization_pct": cpu,
            "wls_full_gc_pct": gc,
            "db_cluster_wait_samples": cluster_waits,
            "db_io_wait_samples": io_waits,
            "db_application_wait_samples": app_waits,
            "db_active_sessions": active_sessions,
        }
