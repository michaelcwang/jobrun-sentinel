from datetime import UTC, datetime
from typing import Any

from app.connectors.base import (
    ConfluenceQueryCatalogConnector,
    EssApiConnector,
    JobHistoryConnector,
    OciTelemetryConnector,
    OracleDbConnector,
    SlackConnector,
    SqlObservationConnector,
    VolumeSnapshotConnector,
)
from app.services.query_guard import validate_read_only_template


class MockJobHistoryConnector(JobHistoryConnector):
    def fetch_runs(self, customer_key: str, environment: str) -> list[dict[str, Any]]:
        return [
            {
                "customer_key": customer_key,
                "environment": environment,
                "run_key": f"{customer_key}-{environment}-mock-current",
                "job_name": "Mock CalculatePVT",
                "status": "RUNNING",
                "started_at": _utcnow().isoformat(),
            }
        ]


class MockOracleDbConnector(OracleDbConnector):
    def execute_template(
        self,
        sql_text: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
        row_limit: int,
        validate_only: bool = False,
    ) -> list[dict[str, Any]]:
        validate_read_only_template(sql_text)
        if validate_only:
            return []
        sql_lower = sql_text.lower()
        if "mock_raise_ora_error" in sql_lower or parameters.get("simulate_ora_error"):
            raise RuntimeError(
                "ORA-00942: table or view does not exist; password=mock-secret dsn=mock-host.example/service"
            )
        if "mock_icm_job_history" in sql_lower or "run_history" in sql_lower:
            return [
                {
                    "REQUEST_ID": "ESS-APJ-HIST-001",
                    "PROCESS_ID": "PROC-APJ-HIST-001",
                    "ESS_REQUEST_ID": "ESS-APJ-HIST-001",
                    "JOB_NAME": "APJ Direct CalculatePVT",
                    "API_OPERATION": "CalculatePVT",
                    "STATUS": "SUCCESS",
                    "STARTED_AT": "2026-06-18T00:00:00",
                    "ENDED_AT": "2026-06-18T05:50:00",
                    "ELAPSED_MINUTES": 350,
                    "REGION": "APJ",
                    "WORKSTREAM": "Direct",
                    "BUSINESS_PERIOD": "2026-Q2",
                }
            ][:row_limit]
        if "mock_icm_volume_snapshot" in sql_lower:
            return [
                {
                    "RUN_KEY": parameters.get("run_key", "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT"),
                    "METRIC_NAME": "transactions",
                    "METRIC_VALUE": 1820000,
                    "BASELINE_VALUE": 875000,
                    "UNIT": "rows",
                    "SHAPE_TAGS": "volume drift,data window mismatch",
                }
            ][:row_limit]
        if "mock_icm_sql_observation" in sql_lower or "mock_icm_udq_metadata" in sql_lower:
            return [
                {
                    "RUN_KEY": parameters.get("run_key", "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT"),
                    "SQL_ID": parameters.get("sql_id", "9x3m1apjnew"),
                    "PLAN_HASH_VALUE": "992384711",
                    "CHILD_NUMBER": 0,
                    "SQL_PROFILE": "ICM_APJ_PROFILE_V2",
                    "MODULE": "ICM",
                    "ACTION": "CalculatePVT",
                    "ELAPSED_TIME_DELTA": 43100,
                    "BUFFER_GETS_DELTA": 92000000,
                    "ROWS_PROCESSED_DELTA": 1820000,
                    "TOP_WAIT_EVENT": "db file sequential read",
                    "UDQ_NAME": "MTQ_ICM_OBA_BY_BADGE_VS",
                    "UDQ_HASH": "sha256:udq-apj-direct-v2",
                    "QUERY_SHAPE_TAGS": "OR predicate,full scan,unstable plan,HZ_REF_ENTITIES,EXTN_ATTRIBUTE_NUMBER007",
                    "INDEX_PROFILE_NOTES": "SQL profile/index intervention observed",
                    "RECOMMENDATION_TEXT": "Remove OR predicate or split into UNION ALL / separate SQL branches, then validate execution statistics.",
                }
            ][:row_limit]
        if "mock_icm_active_long_running" in sql_lower or "mock_icm_job_status" in sql_lower:
            customer_prefix = str(parameters.get("customer_key") or "").strip()
            id_prefix = f"{customer_prefix}-" if customer_prefix else ""
            return [
                {
                    "REQUEST_ID": parameters.get("request_id", f"{id_prefix}ESS-APJ-90045"),
                    "PROCESS_ID": parameters.get("process_id", f"{id_prefix}PROC-APJ-CURRENT"),
                    "ESS_REQUEST_ID": parameters.get("request_id", f"{id_prefix}ESS-APJ-90045"),
                    "JOB_NAME": "APJ Direct CalculatePVT",
                    "API_OPERATION": "CalculatePVT",
                    "STATUS": "RUNNING",
                    "STARTED_AT": "2026-06-20T00:00:00",
                    "ENDED_AT": None,
                    "ELAPSED_MINUTES": 742,
                    "REGION": "APJ",
                    "WORKSTREAM": "Direct",
                    "BUSINESS_PERIOD": "2026-Q2",
                    "SQL_ID": parameters.get("sql_id", "9x3m1apjnew"),
                    "PLAN_HASH_VALUE": "992384711",
                    "UDQ_NAME": "MTQ_ICM_OBA_BY_BADGE_VS",
                    "UDQ_HASH": "sha256:udq-apj-direct-v2",
                }
            ][:row_limit]
        if "mock_topology_active_db_session" in sql_lower:
            sql_id = parameters.get("sql_id") or "dp9u1803k8k7f"
            if parameters.get("process_id") == "PROC-COLLECT-6621" or "collect" in str(parameters.get("ess_request_token", "")).lower():
                return [
                    {
                        "INST_ID": 3,
                        "INSTANCE_NAME": "DBRAC_inst3",
                        "DB_HOST_NAME": "dbhost-c",
                        "SID": 1842,
                        "SERIAL_NUMBER": "5512",
                        "SESSION_STATUS": "ACTIVE",
                        "SERVICE_NAME": "ICM_PRD",
                        "MODULE": "ICM_COLLECT",
                        "ACTION": "Collect Credits",
                        "CLIENT_IDENTIFIER": "ess-collect-55431-6621",
                        "ECID": None,
                        "MACHINE": "ESS_SOAServer_as27_01",
                        "PROGRAM": "ESS Java Worker",
                        "PROCESS": "PROC-COLLECT-6621",
                        "SQL_ID": "2collectbase",
                        "SQL_CHILD_NUMBER": 0,
                        "SQL_EXEC_START": "2026-06-20T09:40:00",
                        "LAST_CALL_ET_SECONDS": 9040,
                        "EVENT": "scheduler wait",
                        "WAIT_CLASS": "Scheduler",
                        "STATE": "WAITING",
                        "BLOCKING_INSTANCE": None,
                        "BLOCKING_SESSION": None,
                        "PLAN_HASH_VALUE": "77192011",
                        "ASH_AVAILABLE": False,
                    }
                ][:row_limit]
            return [
                {
                    "INST_ID": 1,
                    "INSTANCE_NAME": "DBRAC_inst1",
                    "DB_HOST_NAME": "dbhost-a",
                    "SID": 7716,
                    "SERIAL_NUMBER": "4435",
                    "SESSION_STATUS": "ACTIVE",
                    "USERNAME": "FUSION_RUNTIME",
                    "SERVICE_NAME": "ICM_PRD",
                    "MODULE": "CN_TP_CALCULATIONS_PVT.CALCULATE",
                    "ACTION": "CalculatePVT APJ Direct",
                    "CLIENT_IDENTIFIER": parameters.get("client_identifier") or "ess-apj-90045-8841",
                    "ECID": parameters.get("ecid") or "apj-direct-calculatepvt-ecid",
                    "MACHINE": "ESS_SOAServer_as24_01",
                    "PROGRAM": "JDBC Thin Client",
                    "PROCESS": parameters.get("process_id") or "PROC-APJ-DIRECT-8841",
                    "SQL_ID": sql_id,
                    "SQL_CHILD_NUMBER": 0,
                    "SQL_EXEC_START": "2026-06-20T00:40:00",
                    "LAST_CALL_ET_SECONDS": 49320,
                    "EVENT": "cell single block physical read",
                    "WAIT_CLASS": "User I/O",
                    "STATE": "WAITING",
                    "BLOCKING_INSTANCE": None,
                    "BLOCKING_SESSION": None,
                    "PLAN_HASH_VALUE": "51543091",
                }
            ][:row_limit]
        if "mock_topology_ash_samples" in sql_lower:
            return [
                {
                    "SAMPLE_TIME": "2026-06-20T10:00:00",
                    "INST_ID": 1,
                    "INSTANCE_NAME": "DBRAC_inst1",
                    "DB_HOST_NAME": "dbhost-a",
                    "SQL_ID": parameters.get("sql_id") or "dp9u1803k8k7f",
                    "WAIT_CLASS": "User I/O",
                    "EVENT": "cell single block physical read",
                    "SESSION_STATE": "WAITING",
                    "ASH_SAMPLES": 42,
                }
            ][:row_limit]
        if "mock_topology_node_wait_heat" in sql_lower:
            return [
                {
                    "BUCKET_START": parameters.get("from_at", "2026-06-20T10:00:00"),
                    "BUCKET_END": parameters.get("to_at", "2026-06-20T10:10:00"),
                    "INST_ID": 1,
                    "INSTANCE_NAME": "DBRAC_inst1",
                    "DB_HOST_NAME": "dbhost-a",
                    "WAIT_CLASS": "User I/O",
                    "EVENT": "cell single block physical read",
                    "ASH_SAMPLES": 47,
                    "ACTIVE_SLOW_JOB_COUNT": 1,
                    "TOP_SQL_ID": "dp9u1803k8k7f",
                }
            ][:row_limit]
        if "mock_topology_instance_health" in sql_lower:
            return [
                {
                    "INST_ID": parameters.get("inst_id", 1),
                    "INSTANCE_NAME": f"DBRAC_inst{parameters.get('inst_id', 1)}",
                    "DB_HOST_NAME": "dbhost-a",
                    "ACTIVE_SESSIONS": 34,
                    "CPU_WAIT_SAMPLES": 8,
                    "IO_WAIT_SAMPLES": 38,
                    "CONCURRENCY_WAIT_SAMPLES": 3,
                    "APPLICATION_WAIT_SAMPLES": 2,
                    "CLUSTER_WAIT_SAMPLES": 4,
                    "ACTIVE_SQL_COUNT": 7,
                    "TOP_SQL_ID": "dp9u1803k8k7f",
                    "TOP_EVENT": "cell single block physical read",
                }
            ][:row_limit]
        if "mock_topology_blocking_session" in sql_lower:
            return [
                {
                    "ECID": parameters.get("ecid"),
                    "SQL_ID": parameters.get("sql_id") or "dp9u1803k8k7f",
                    "BLOCKING_INSTANCE": None,
                    "BLOCKING_SESSION": None,
                    "BLOCKING_STATUS": "none",
                    "EVIDENCE_SUMMARY": "No blocking session observed in mock topology data.",
                }
            ][:row_limit]
        if "mock_topology_app_server_inference" in sql_lower:
            return [
                {
                    "MACHINE": "ESS_SOAServer_as24_01",
                    "PROGRAM": "JDBC Thin Client",
                    "MODULE": "CN_TP_CALCULATIONS_PVT.CALCULATE",
                    "ACTION": "CalculatePVT APJ Direct",
                    "CLIENT_IDENTIFIER": parameters.get("client_identifier") or "ess-apj-90045-8841",
                    "ECID": parameters.get("ecid") or "apj-direct-calculatepvt-ecid",
                    "INFERRED_SERVER_NAME": "ESS_SOAServer_as24_01",
                    "INFERENCE_CONFIDENCE": "inferred",
                    "EVIDENCE_SUMMARY": "Inferred from GV$SESSION.MACHINE/PROGRAM; WLS telemetry not yet connected.",
                }
            ][:row_limit]
        if "mock_diagnostic_active_session" in sql_lower:
            return [
                {
                    "ECID": parameters.get("ecid", "0598914d69b56a3ce534410a606b4a9b"),
                    "INST_ID": 1,
                    "SID": 7716,
                    "STATUS": "ACTIVE",
                    "LAST_CALL_ET": 47537,
                    "SQL_ID": "dp9u1803k8k7f",
                    "MODULE": "CN_TP_CALCULATIONS_PVT.CALCULATE",
                    "ACTION": "Calculate_pvt",
                }
            ][:row_limit]
        if "mock_diagnostic_sqlstats" in sql_lower or "mock_diagnostic_sql_hotspots" in sql_lower:
            return [
                {
                    "SQL_ID": parameters.get("sql_id", "dp9u1803k8k7f"),
                    "PLAN_HASH_VALUE": "51543091",
                    "EXECUTIONS": 12150000,
                    "ELAPSED_SECONDS": 192901,
                    "CPU_SECONDS": 191153,
                    "BUFFER_GETS": 415000000,
                    "TOP_WAIT_EVENT": "cell single block physical read",
                }
            ][:row_limit]
        if "mock_diagnostic_awr_plan_history" in sql_lower or "mock_diagnostic_plan_comparison" in sql_lower:
            return [
                {
                    "SQL_ID": parameters.get("sql_id", "dp9u1803k8k7f"),
                    "CURRENT_PLAN_HASH": "51543091",
                    "HISTORICAL_PLAN_HASH": "3256752871",
                    "CURRENT_INDEX": "HZ_REF_ENTITIES_X26",
                    "HISTORICAL_INDEX": "HZ_REF_ENTITIES_N1",
                    "COST_RATIO": 27.8,
                    "COST": 6,
                    "CARDINALITY_ROWS": 1,
                }
            ][:row_limit]
        if "mock_diagnostic_source_search" in sql_lower or "mock_diagnostic_formula_metadata" in sql_lower:
            return [
                {
                    "PACKAGE_NAME": "ADXX_CN_FORMULA_111141_PKG",
                    "VALUE_SET_CODE": parameters.get("value_set_code", "MTQ_ICM_OBA_BY_BADGE_VS"),
                    "SANITIZED_PATTERN": "get_commission -> clean_queries_results",
                    "SQL_ID": "cxk88uqjzpud8",
                    "CONFIRMED_AFFECTED": True,
                },
                {
                    "PACKAGE_NAME": "ADXX_CN_FORMULA_24005_PKG",
                    "VALUE_SET_CODE": parameters.get("value_set_code", "MTQ_ICM_OBA_BY_BADGE_VS"),
                    "SANITIZED_PATTERN": "get_commission -> clean_queries_results",
                    "SQL_ID": "cxk88uqjzpud8",
                    "CONFIRMED_AFFECTED": True,
                },
            ][:row_limit]
        if "mock_diagnostic_formula_duplication" in sql_lower:
            return [
                {
                    "ESS_REQUEST_ID": parameters.get("ess_request_id", "13729027"),
                    "TOTAL_LINES": 253391,
                    "DISTINCT_KEYS": 105267,
                    "REDUNDANT_CALL_PCT": 58.5,
                }
            ][:row_limit]
        if "mock_diagnostic_blocking_session" in sql_lower:
            return [{"ECID": parameters.get("ecid"), "BLOCKING_SESSION": None, "BLOCKING_INSTANCE": None, "STATUS": "none"}][
                :row_limit
            ]
        if "mock_diagnostic_rac_gc_waits" in sql_lower:
            return [
                {"ECID": parameters.get("ecid"), "SQL_ID": "gwxtms3bcc9hs", "GC_WAIT_SAMPLES": 4, "TOTAL_SAMPLES": 1200}
            ][:row_limit]
        return [
            {
                "request_id": parameters.get("request_id", "ESS-APJ-90045"),
                "status": "RUNNING",
                "elapsed_minutes": 742,
                "sql_id": parameters.get("sql_id", "9x3m1apjnew"),
                "plan_hash_value": "992384711",
                "sampled_at": _utcnow().isoformat(),
                "guardrail": f"mocked read-only execution, row_limit={row_limit}, timeout={timeout_seconds}s",
            }
        ]


class MockEssApiConnector(EssApiConnector):
    def fetch_request_status(
        self, request_id: str | None = None, process_name: str | None = None
    ) -> dict[str, Any]:
        return {
            "request_id": request_id or "ESS-APJ-90045",
            "process_name": process_name or "CalculatePVT",
            "status": "RUNNING",
            "phase": "CALCULATING",
            "last_update": _utcnow().isoformat(),
        }


class MockOciTelemetryConnector(OciTelemetryConnector):
    def fetch_metrics(self, selector: dict[str, Any]) -> dict[str, Any]:
        return {
            "selector": selector,
            "cpu_pct": 71.4,
            "db_time_seconds": 48239,
            "wait_class": "User I/O",
            "mocked": True,
        }


class MockSqlObservationConnector(SqlObservationConnector):
    def fetch_observations(self, run_selector: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "sql_id": run_selector.get("sql_id", "9x3m1apjnew"),
                "plan_hash_value": "992384711",
                "sql_profile": "ICM_APJ_PROFILE_V2",
                "udq_name": "MTQ_ICM_OBA_BY_BADGE_VS",
                "udq_hash": "sha256:udq-apj-direct-v2",
                "query_shape_tags": ["OR predicate", "full scan", "unstable plan"],
            }
        ]


class MockVolumeSnapshotConnector(VolumeSnapshotConnector):
    def fetch_volume(self, run_selector: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "metric_name": "transactions",
                "metric_value": 1820000,
                "baseline_value": 875000,
                "unit": "rows",
                "shape_tags": ["volume drift", "data window mismatch"],
            }
        ]


class MockSlackConnector(SlackConnector):
    def send_alert(self, payload: dict[str, Any], destination: str | None = None) -> dict[str, Any]:
        return {
            "status": "mock_sent",
            "destination": destination or payload.get("alert_channel") or "#jobrun-sentinel",
            "payload": payload,
            "sent_at": _utcnow().isoformat(),
        }


class MockConfluenceQueryCatalogConnector(ConfluenceQueryCatalogConnector):
    def fetch_templates(self, source_reference: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "template_id": "icm_ess_request_status",
                "name": "ICM ESS Request Status",
                "source_reference": source_reference or "Support Playbook: ICM Job Inspection",
                "database_type": "oracle",
                "sql_text": "SELECT request_id, phase_code, status_code FROM ess_request_history WHERE request_id = :request_id",
                "required_parameters": {"request_id": {"type": "string"}},
            }
        ]


class MockConnectorRegistry:
    def __init__(self) -> None:
        self.job_history = MockJobHistoryConnector()
        self.oracle_db = MockOracleDbConnector()
        self.ess_api = MockEssApiConnector()
        self.oci_telemetry = MockOciTelemetryConnector()
        self.sql_observation = MockSqlObservationConnector()
        self.volume_snapshot = MockVolumeSnapshotConnector()
        self.slack = MockSlackConnector()
        self.confluence_catalog = MockConfluenceQueryCatalogConnector()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
