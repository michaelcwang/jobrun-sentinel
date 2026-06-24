import argparse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.models import (
    AlertRule,
    Base,
    ConnectorConfig,
    Customer,
    Environment,
    ExpectationRecord,
    ImportBatch,
    ImportedPlanRow,
    JobDefinition,
    JobRun,
    PlaybookNote,
    QueryTemplate,
    SqlObservation,
    VolumeSnapshot,
)
from app.services.evaluation import EvaluationService
from app.services.diagnostics import (
    CALCULATE_PVT_JOB_DEFINITION,
    EXAMPLE_ECID,
    EXAMPLE_ESS_REQUEST_ID,
    DiagnosticAnalysisService,
)
from app.services.topology import RuntimeTopologyService


SCALE_REGIONS = ["APJ", "EMEA", "AMER", "LATAM", "GLOBAL"]
SCALE_WORKSTREAMS = ["Direct", "Partner", "Payroll", "Collections", "Reconciliation"]
SCALE_JOB_PATTERNS = [
    ("ICM Calculation", "CalculatePVT", "CalculatePVT", "Calculate Incentive Compensation"),
    ("ICM Collection", "Collect", "Collect Transactions", "Collect Credits"),
    ("ICM Crediting", "Credit", "Credit Allocation", "Allocate Credits"),
    ("ICM Payment", "Payment", "Payment Validation", "Validate Payments"),
    ("Payroll", "Payroll Calculation", "Payroll Close", "Run Payroll Close"),
    ("Order Management", "Import", "Order Import", "Import Orders"),
    ("Revenue", "Revenue Recognition", "Revenue Recognition", "Recognize Revenue"),
    ("Billing", "Invoice", "Invoice Generation", "Generate Invoices"),
    ("Territory", "Assignment", "Territory Assignment", "Assign Territories"),
    ("Quota", "Load", "Quota Load", "Load Quotas"),
]
SCALE_STATES = ["normal", "watch", "warning", "critical", "unknown_baseline"]


def seed_database(db: Session, *, force: bool = False) -> None:
    if force:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    elif db.scalar(select(Customer.id).limit(1)) is not None:
        return

    now = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
    cust_a = Customer(customer_key="CUST_A", display_name="Customer A", tier="strategic")
    cust_b = Customer(customer_key="CUST_B", display_name="Customer B", tier="standard")
    db.add_all([cust_a, cust_b])
    db.flush()

    env_a = Environment(customer_id=cust_a.id, name="PROD", region="global", lifecycle="prod")
    env_b = Environment(customer_id=cust_b.id, name="PROD", region="global", lifecycle="prod")
    db.add_all([env_a, env_b])
    db.flush()

    apj_calc = JobDefinition(
        customer_id=cust_a.id,
        job_family="ICM Calculation",
        job_type="CalculatePVT",
        job_name="APJ Direct CalculatePVT",
        default_region="APJ",
        default_workstream="Direct",
        ess_request_name="Calculate Incentive Compensation",
        process_name="APJ Direct Calculation",
        api_operation="CalculatePVT",
    )
    emea_calc = JobDefinition(
        customer_id=cust_a.id,
        job_family="ICM Calculation",
        job_type="CalculatePVT",
        job_name="EMEA Direct CalculatePVT",
        default_region="EMEA",
        default_workstream="Direct",
        ess_request_name="Calculate Incentive Compensation",
        process_name="EMEA Direct Calculation",
        api_operation="CalculatePVT",
    )
    collect = JobDefinition(
        customer_id=cust_a.id,
        job_family="ICM Collection",
        job_type="Collect",
        job_name="AMER/LATAM Collect Credits",
        default_region="AMER/LATAM",
        default_workstream="Collect",
        ess_request_name="Collect Credits",
        process_name="Collect Credit Transactions",
    )
    revert = JobDefinition(
        customer_id=cust_b.id,
        job_family="ICM Maintenance",
        job_type="Run Revert",
        job_name="Run Revert",
        default_region="Global",
        default_workstream="Revert",
        ess_request_name="Revert Calculation",
        process_name="Run Revert",
    )
    new_model = JobDefinition(
        customer_id=cust_b.id,
        job_family="ICM Calculation",
        job_type="CalculatePVT",
        job_name="New Territory Model CalculatePVT",
        default_region="APJ",
        default_workstream="Pilot",
        ess_request_name="Calculate Incentive Compensation",
        process_name="New Territory Pilot",
        api_operation="CalculatePVT",
    )
    db.add_all([apj_calc, emea_calc, collect, revert, new_model])
    db.flush()

    _seed_history(
        db,
        cust_a,
        env_a,
        apj_calc,
        now,
        durations=[340, 355, 348, 362, 351, 347, 359, 346],
        volumes=[1080000, 1105000, 1074000, 1110000, 1092000, 1101000, 1088000, 1096000],
        sql_id="5gk9apjbase",
        plan_hash="184029177",
        udq_hash="sha256:udq-apj-direct-v1",
    )
    _seed_history(
        db,
        cust_a,
        env_a,
        emea_calc,
        now,
        durations=[230, 241, 236, 244, 238, 239],
        volumes=[820000, 835000, 816000, 840000, 828000, 830000],
        sql_id="6em2calcbase",
        plan_hash="61372844",
        udq_hash="sha256:udq-emea-v1",
    )
    _seed_history(
        db,
        cust_a,
        env_a,
        collect,
        now,
        durations=[132, 139, 141, 136, 144],
        volumes=[410000, 420000, 415000, 430000, 425000],
        sql_id="2collectbase",
        plan_hash="77192011",
        udq_hash=None,
    )
    _seed_history(
        db,
        cust_b,
        env_b,
        revert,
        now,
        durations=[58, 66, 61, 63, 67, 62],
        volumes=[90000, 88000, 91000, 93000, 89500, 90500],
        sql_id="7revertbase",
        plan_hash="1149012",
        udq_hash=None,
    )

    apj_current = JobRun(
        run_key="CUST_A-PROD-APJ-DIRECT-CALC-CURRENT",
        customer_id=cust_a.id,
        environment_id=env_a.id,
        job_definition_id=apj_calc.id,
        job_family=apj_calc.job_family,
        job_type=apj_calc.job_type,
        job_name=apj_calc.job_name,
        region="APJ",
        workstream="Direct",
        period="FY26-Q4",
        data_window_start=now - timedelta(days=68),
        data_window_end=now,
        started_at=now - timedelta(minutes=780),
        status="RUNNING",
        ess_request_id="ESS-APJ-90045",
        job_id="JOB-ICM-APJ-20260620",
        process_id="PROC-APJ-DIRECT-8841",
        api_operation="CalculatePVT",
        sql_id="9x3m1apjnew",
        plan_hash_value="992384711",
        udq_name="MTQ_ICM_OBA_BY_BADGE_VS",
        udq_hash="sha256:udq-apj-direct-v2",
        current_progress_pct=Decimal("64.00"),
        last_progress_at=now - timedelta(minutes=135),
        notes="Synthetic incident: customer-authored UDQ changed and data window is larger than prior timing.",
    )
    db.add(apj_current)
    db.flush()
    db.add_all(
        [
            VolumeSnapshot(
                run_id=apj_current.id,
                metric_name="transactions",
                metric_value=Decimal("1425000"),
                baseline_value=Decimal("1100000"),
                unit="rows",
                data_window_start=apj_current.data_window_start,
                data_window_end=apj_current.data_window_end,
                shape_tags=["volume drift", "data window mismatch"],
            ),
            SqlObservation(
                run_id=apj_current.id,
                sql_id="9x3m1apjnew",
                plan_hash_value="992384711",
                child_number=1,
                sql_profile="ICM_APJ_PROFILE_V2",
                module="ICM CalculatePVT",
                action="APJ Direct calculation",
                elapsed_time_delta=Decimal("44220"),
                buffer_gets_delta=Decimal("982334911"),
                rows_processed_delta=Decimal("1425000"),
                top_wait_event="db file scattered read",
                udq_name="MTQ_ICM_OBA_BY_BADGE_VS",
                udq_hash="sha256:udq-apj-direct-v2",
                query_text_available=False,
                query_shape_tags=["OR predicate", "full scan", "unstable plan"],
                index_profile_notes="New SQL profile observed after index intervention; compare against baseline plan.",
                recommendation_text="Remove the OR predicate on the lookup column or split into UNION ALL / separate statements.",
            ),
        ]
    )

    emea_current = JobRun(
        run_key="CUST_A-PROD-EMEA-DIRECT-CALC-CURRENT",
        customer_id=cust_a.id,
        environment_id=env_a.id,
        job_definition_id=emea_calc.id,
        job_family=emea_calc.job_family,
        job_type=emea_calc.job_type,
        job_name=emea_calc.job_name,
        region="EMEA",
        workstream="Direct",
        period="FY26-Q4",
        data_window_start=now - timedelta(days=31),
        data_window_end=now,
        started_at=now - timedelta(minutes=112),
        status="RUNNING",
        ess_request_id="ESS-EMEA-77421",
        process_id="PROC-EMEA-DIRECT-1120",
        api_operation="CalculatePVT",
        sql_id="6em2calcbase",
        plan_hash_value="61372844",
        udq_name="EMEA_DIRECT_STANDARD",
        udq_hash="sha256:udq-emea-v1",
        current_progress_pct=Decimal("52.00"),
        last_progress_at=now - timedelta(minutes=8),
    )
    db.add(emea_current)
    db.flush()
    db.add(
        VolumeSnapshot(
            run_id=emea_current.id,
            metric_name="transactions",
            metric_value=Decimal("836000"),
            baseline_value=Decimal("830000"),
            unit="rows",
            shape_tags=[],
        )
    )

    collect_current = JobRun(
        run_key="CUST_A-PROD-AMER-LATAM-COLLECT-CURRENT",
        customer_id=cust_a.id,
        environment_id=env_a.id,
        job_definition_id=collect.id,
        job_family=collect.job_family,
        job_type=collect.job_type,
        job_name=collect.job_name,
        region="AMER/LATAM",
        workstream="Collect",
        period="FY26-Q4",
        started_at=now - timedelta(minutes=182),
        status="RUNNING",
        ess_request_id="ESS-COLLECT-55431",
        process_id="PROC-COLLECT-6621",
        sql_id="2collectbase",
        plan_hash_value="77192011",
        current_progress_pct=Decimal("84.00"),
        last_progress_at=now - timedelta(minutes=14),
    )
    db.add(collect_current)
    db.flush()
    db.add(
        VolumeSnapshot(
            run_id=collect_current.id,
            metric_name="transactions",
            metric_value=Decimal("485000"),
            baseline_value=Decimal("420000"),
            unit="rows",
            shape_tags=["volume drift"],
        )
    )

    revert_current = JobRun(
        run_key="CUST_B-PROD-RUN-REVERT-CURRENT",
        customer_id=cust_b.id,
        environment_id=env_b.id,
        job_definition_id=revert.id,
        job_family=revert.job_family,
        job_type=revert.job_type,
        job_name=revert.job_name,
        region="Global",
        workstream="Revert",
        period="FY26-Q4",
        started_at=now - timedelta(minutes=392),
        status="RUNNING",
        ess_request_id="ESS-REVERT-90821",
        process_id="PROC-REVERT-4001",
        current_progress_pct=Decimal("38.00"),
        last_progress_at=now - timedelta(minutes=77),
        notes="No SQL observation available yet. Direct DB status query is recommended.",
    )
    db.add(revert_current)

    learning_run = JobRun(
        run_key="CUST_B-PROD-NEW-TERRITORY-FIRST-RUN",
        customer_id=cust_b.id,
        environment_id=env_b.id,
        job_definition_id=new_model.id,
        job_family=new_model.job_family,
        job_type=new_model.job_type,
        job_name=new_model.job_name,
        region="APJ",
        workstream="Pilot",
        period="FY26-Q4",
        started_at=now - timedelta(minutes=42),
        status="RUNNING",
        ess_request_id="ESS-PILOT-11001",
        process_id="PROC-PILOT-NEW-TERRITORY",
        api_operation="CalculatePVT",
        current_progress_pct=Decimal("12.00"),
        last_progress_at=now - timedelta(minutes=5),
        notes="First observed run at this scope; learning mode until more history is available.",
    )
    db.add(learning_run)
    db.flush()

    db.add_all(
        [
            ExpectationRecord(
                customer_key="CUST_A",
                environment="PROD",
                job_family="ICM Calculation",
                job_type="CalculatePVT",
                job_name="APJ Direct CalculatePVT",
                region="APJ",
                workstream="Direct",
                period="FY26-Q4",
                ess_request_name="Calculate Incentive Compensation",
                process_name="APJ Direct Calculation",
                api_operation="CalculatePVT",
                sql_id="5gk9apjbase",
                sql_plan_hash="184029177",
                udq_name="MTQ_ICM_OBA_BY_BADGE_VS",
                udq_hash="sha256:udq-apj-direct-v1",
                baseline_method="manual_goal",
                expected_minutes=Decimal("350.00"),
                warning_threshold_pct=Decimal("20.00"),
                critical_threshold_pct=Decimal("75.00"),
                customer_goal_minutes=Decimal("420.00"),
                minimum_history_count=5,
                confidence_score=Decimal("0.82"),
                owner="ICM Support",
                alert_channel="#jobrun-sentinel",
                notes="Manual expectation from prior successful APJ Direct timing.",
                risk_assumptions="Comparable only when UDQ hash, data window, and plan hash remain stable.",
                last_reviewed_by="support-lead",
                last_reviewed_at=now - timedelta(days=2),
            ),
            ExpectationRecord(
                customer_key="CUST_A",
                environment="PROD",
                job_family="ICM Calculation",
                job_type="CalculatePVT",
                job_name="EMEA Direct CalculatePVT",
                region="EMEA",
                workstream="Direct",
                baseline_method="historical_p50_p90",
                expected_minutes=Decimal("245.00"),
                warning_threshold_pct=Decimal("25.00"),
                critical_threshold_pct=Decimal("75.00"),
                customer_goal_minutes=Decimal("330.00"),
                confidence_score=Decimal("0.76"),
                owner="ICM Support",
                alert_channel="#jobrun-sentinel",
            ),
            ExpectationRecord(
                customer_key="CUST_A",
                environment="PROD",
                job_family="ICM Collection",
                job_type="Collect",
                job_name="AMER/LATAM Collect Credits",
                region="AMER/LATAM",
                workstream="Collect",
                baseline_method="historical_p50_p90",
                expected_minutes=Decimal("145.00"),
                warning_threshold_pct=Decimal("15.00"),
                critical_threshold_pct=Decimal("60.00"),
                customer_goal_minutes=Decimal("210.00"),
                confidence_score=Decimal("0.70"),
                owner="ICM Support",
            ),
        ]
    )

    db.add_all(
        [
            QueryTemplate(
                template_id="icm_ess_request_status",
                name="ICM ESS request status by request id",
                description="Read-only support query for ESS request phase and status.",
                source_reference="Published ICM job inspection catalog",
                database_type="oracle",
                connector_type="oracle_db",
                template_category="job_status",
                sql_text="SELECT request_id, phase_code, status_code, elapsed_minutes FROM ess_request_history WHERE request_id = :request_id",
                required_parameters={"request_id": {"type": "string"}},
                default_parameters={"request_id": "ESS-APJ-90045"},
                output_mapping={"request_id": "request_id", "status": "status_code"},
                owning_team="ICM Support",
                active=True,
                is_read_only_validated=True,
                last_validated_at=now - timedelta(days=3),
                tags=["icm", "ess", "status"],
            ),
            QueryTemplate(
                template_id="icm_sql_observation_by_sql_id",
                name="SQL observation by SQL_ID",
                description="ASH/AWR-like SQL metadata used by support to compare SQL_ID, plan hash, and profile.",
                source_reference="Published ICM job inspection catalog",
                database_type="oracle",
                connector_type="oracle_db",
                template_category="sql_observation",
                sql_text="SELECT sql_id, plan_hash_value, child_number, elapsed_time_delta FROM v$sql WHERE sql_id = :sql_id",
                required_parameters={"sql_id": {"type": "string"}},
                default_parameters={"sql_id": "9x3m1apjnew"},
                output_mapping={"sql_id": "sql_id", "plan": "plan_hash_value"},
                owning_team="Database Performance",
                active=True,
                is_read_only_validated=True,
                last_validated_at=now - timedelta(days=1),
                tags=["icm", "sql", "plan"],
            ),
        ]
    )

    for connector_type, name, message in [
        ("JobHistoryConnector", "Mock job history connector", "Returns synthetic current and historical runs."),
        ("OracleDbConnector", "Mock Oracle read-only connector", "python-oracledb DSN/wallet/TNS_ADMIN placeholders documented."),
        ("EssApiConnector", "Mock ESS API connector", "Fetches synthetic ESS status."),
        ("OciTelemetryConnector", "Mock OCI telemetry connector", "Telemetry is mocked until OCI integration is enabled."),
        ("SqlObservationConnector", "Mock SQL observation connector", "Returns synthetic SQL_ID/plan/UDQ observations."),
        ("VolumeSnapshotConnector", "Mock volume connector", "Returns synthetic business volume metrics."),
        ("SlackConnector", "Mock Slack notifier", "Generates payloads without sending external messages."),
        ("ConfluenceQueryCatalogConnector", "Mock Confluence query catalog", "Imports published query template metadata."),
    ]:
        db.add(
            ConnectorConfig(
                connector_type=connector_type,
                config_key="demo" if connector_type == "OracleDbConnector" else connector_type.lower(),
                display_name=name,
                env_var_prefix="JOBRUN_ORACLE_DEMO" if connector_type == "OracleDbConnector" else None,
                name=name,
                timeout_seconds=60,
                fetch_limit=500,
                status="healthy",
                last_checked_at=now,
                health_message=message,
                enabled=True,
                config={
                    "mode": "mock",
                    "access_mode": "read_only",
                    "destructive_operations_allowed": False,
                    "secrets": "environment only",
                },
            )
        )

    batch = ImportBatch(
        filename="maverick_manual_plan_seed.csv",
        source_type="manual_plan_csv",
        status="imported",
        row_count=3,
        notes="Seeded example of estimates, actuals, process IDs, owner, comments, and volume.",
    )
    db.add(batch)
    db.flush()
    db.add_all(
        [
            ImportedPlanRow(
                import_batch_id=batch.id,
                row_number=1,
                step="APJ Direct CalculatePVT",
                status="Running",
                process_id="PROC-APJ-DIRECT-8841",
                actual_execution_minutes=Decimal("780"),
                estimated_run_minutes=Decimal("350"),
                started_at=apj_current.started_at,
                owner="ICM Support",
                comment="Actual exceeds estimate; changed UDQ hash.",
                volume=Decimal("1425000"),
                mapped_run_id=apj_current.id,
            ),
            ImportedPlanRow(
                import_batch_id=batch.id,
                row_number=2,
                step="Run Revert",
                status="Running",
                process_id="PROC-REVERT-4001",
                actual_execution_minutes=Decimal("392"),
                estimated_run_minutes=Decimal("67"),
                started_at=revert_current.started_at,
                owner="ICM Support",
                comment="Run Revert exceeded p90 baseline by 5.8x.",
                volume=Decimal("90500"),
                mapped_run_id=revert_current.id,
            ),
            ImportedPlanRow(
                import_batch_id=batch.id,
                row_number=3,
                step="AMER/LATAM Collect Credits",
                status="Running",
                process_id="PROC-COLLECT-6621",
                actual_execution_minutes=Decimal("182"),
                estimated_run_minutes=Decimal("145"),
                started_at=collect_current.started_at,
                owner="ICM Support",
                comment="Collect job is above estimate; watch volume drift.",
                volume=Decimal("485000"),
                mapped_run_id=collect_current.id,
            ),
        ]
    )

    db.add_all(
        [
            AlertRule(
                name="APJ Direct critical monitor",
                rule_type="standard",
                customer_id=cust_a.id,
                environment_id=env_a.id,
                job_definition_id=apj_calc.id,
                run_id=apj_current.id,
                selector={"ess_request_id": "ESS-APJ-90045", "api_operation": "CalculatePVT"},
                expected_minutes=Decimal("350"),
                warning_threshold_pct=Decimal("20"),
                critical_threshold_pct=Decimal("75"),
                destination="#jobrun-sentinel",
                notes="Seeded standard monitor for the APJ Direct scenario.",
            ),
            AlertRule(
                name="Ad hoc Run Revert watch",
                rule_type="ad_hoc",
                customer_id=cust_b.id,
                environment_id=env_b.id,
                job_definition_id=revert.id,
                run_id=revert_current.id,
                selector={"process_id": "PROC-REVERT-4001", "manual_job_name": "Run Revert"},
                expected_minutes=Decimal("67"),
                warning_threshold_pct=Decimal("25"),
                critical_threshold_pct=Decimal("75"),
                expires_at=now + timedelta(days=1),
                destination="#jobrun-sentinel",
                notes="Ad hoc monitor created for support escalation coverage.",
            ),
        ]
    )
    db.add(
        PlaybookNote(
            customer_id=cust_a.id,
            environment_id=env_a.id,
            job_definition_id=apj_calc.id,
            run_id=apj_current.id,
            note_date=date.today(),
            title="APJ Direct CalculatePVT at breach risk",
            body="Check data window, UDQ hash, SQL_ID, and plan hash before treating the incident as an Oracle runtime regression.",
            risk_level="critical",
            owner="ICM Support",
        )
    )
    db.flush()

    for run in [apj_current, collect_current, revert_current, learning_run]:
        EvaluationService(db).evaluate_run(run.id, create_alert=True, send_mock_slack=False)
    ensure_phase2b_seed_data(db, now=now)
    ensure_phase2c_seed_data(db, now=now)


def ensure_phase2c_seed_data(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Ensure runtime topology seed data exists for local map/heat-map demos."""
    return RuntimeTopologyService(db).ensure_seed_topology(now=now)


def _seed_history(
    db: Session,
    customer: Customer,
    environment: Environment,
    job: JobDefinition,
    now: datetime,
    *,
    durations: list[int],
    volumes: list[int],
    sql_id: str,
    plan_hash: str,
    udq_hash: str | None,
) -> None:
    for index, duration in enumerate(durations):
        start = now - timedelta(days=21 - index * 2, minutes=duration)
        end = start + timedelta(minutes=duration)
        run = JobRun(
            run_key=f"{customer.customer_key}-{job.job_name.replace(' ', '-').upper()}-HIST-{index + 1}",
            customer_id=customer.id,
            environment_id=environment.id,
            job_definition_id=job.id,
            job_family=job.job_family,
            job_type=job.job_type,
            job_name=job.job_name,
            region=job.default_region,
            workstream=job.default_workstream,
            period="FY26-Q3",
            data_window_start=start - timedelta(days=31),
            data_window_end=start,
            started_at=start,
            ended_at=end,
            status="SUCCESS",
            ess_request_id=f"ESS-HIST-{job.id}-{index + 1}",
            process_id=f"PROC-HIST-{job.id}-{index + 1}",
            api_operation=job.api_operation,
            sql_id=sql_id,
            plan_hash_value=plan_hash,
            udq_name="MTQ_ICM_OBA_BY_BADGE_VS" if udq_hash else None,
            udq_hash=udq_hash,
            expected_minutes_at_start=Decimal(str(duration)),
            current_progress_pct=Decimal("100"),
            last_progress_at=end,
        )
        db.add(run)
        db.flush()
        db.add(
            VolumeSnapshot(
                run_id=run.id,
                metric_name="transactions",
                metric_value=Decimal(str(volumes[index])),
                baseline_value=Decimal(str(volumes[index])),
                unit="rows",
                data_window_start=run.data_window_start,
                data_window_end=run.data_window_end,
                shape_tags=[],
            )
        )
        db.add(
            SqlObservation(
                run_id=run.id,
                sql_id=sql_id,
                plan_hash_value=plan_hash,
                child_number=0,
                sql_profile=None,
                module=job.job_family,
                action=job.job_name,
                elapsed_time_delta=Decimal(str(duration * 60)),
                buffer_gets_delta=Decimal(str(volumes[index] * 210)),
                rows_processed_delta=Decimal(str(volumes[index])),
                top_wait_event="CPU",
                udq_name="MTQ_ICM_OBA_BY_BADGE_VS" if udq_hash else None,
                udq_hash=udq_hash,
                query_text_available=False,
                query_shape_tags=[],
                recommendation_text="Comparable successful baseline run.",
            )
        )


def ensure_phase2b_seed_data(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Ensure the evidence-backed diagnostic workbench has its canonical seed report.

    Existing local databases from Phase 1/2 already have customers, so startup calls
    this helper independently of the base seed path.
    """
    now = now or datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
    customer = db.scalar(select(Customer).where(Customer.customer_key == "CUST_A"))
    if customer is None:
        customer = Customer(customer_key="CUST_A", display_name="Customer A", tier="strategic")
        db.add(customer)
        db.flush()
    environment = db.scalar(select(Environment).where(Environment.customer_id == customer.id, Environment.name == "PROD"))
    if environment is None:
        environment = Environment(customer_id=customer.id, name="PROD", region="global", lifecycle="prod")
        db.add(environment)
        db.flush()
    job = db.scalar(
        select(JobDefinition).where(
            JobDefinition.customer_id == customer.id,
            JobDefinition.job_family == "ICM Calculation",
            JobDefinition.job_type == "Calculate_pvt",
            JobDefinition.job_name == "CN Calculate_pvt",
        )
    )
    if job is None:
        job = JobDefinition(
            customer_id=customer.id,
            job_family="ICM Calculation",
            job_type="Calculate_pvt",
            job_name="CN Calculate_pvt",
            default_region="GLOBAL",
            default_workstream="Transaction Processing",
            ess_request_name="Calculate Incentive Compensation",
            process_name="CN Calculate_pvt",
            api_operation="Calculate_pvt",
        )
        db.add(job)
        db.flush()

    run = db.scalar(select(JobRun).where(JobRun.ess_request_id == EXAMPLE_ESS_REQUEST_ID))
    created_runs = 0
    if run is None:
        run = JobRun(
            run_key="CUST_A-PROD-ESS-13729027-CN-CALCULATE-PVT",
            customer_id=customer.id,
            environment_id=environment.id,
            job_definition_id=job.id,
            job_family=job.job_family,
            job_type=job.job_type,
            job_name=job.job_name,
            region="GLOBAL",
            workstream="Transaction Processing",
            period="FY26-Q4",
            business_scope={
                "ecid": EXAMPLE_ECID,
                "client_identifier": "ess13729027-1434435",
                "rac_cluster_size": 8,
                "active_session": {"inst_id": 1, "sid": 7716, "last_call_et_seconds": 47537},
            },
            data_window_start=now - timedelta(days=31),
            data_window_end=now,
            started_at=now - timedelta(seconds=47537),
            status="RUNNING",
            ess_request_id=EXAMPLE_ESS_REQUEST_ID,
            job_id="JOB-CN-CALCULATE-PVT-13729027",
            process_id="1434435",
            api_operation="Calculate_pvt",
            sql_id="dp9u1803k8k7f",
            plan_hash_value="51543091",
            udq_name="MTQ_ICM_OBA_BY_BADGE_VS",
            udq_hash="sha256:mtq-icm-oba-by-badge-vs",
            current_progress_pct=Decimal("48.00"),
            last_progress_at=now - timedelta(minutes=45),
            notes="Seed diagnostic workbench scenario based on ECID-style slow job evidence.",
        )
        db.add(run)
        db.flush()
        created_runs = 1

    if not db.scalar(select(SqlObservation.id).where(SqlObservation.run_id == run.id, SqlObservation.sql_id == "dp9u1803k8k7f")):
        db.add(
            SqlObservation(
                run_id=run.id,
                sql_id="dp9u1803k8k7f",
                plan_hash_value="51543091",
                child_number=0,
                sql_profile=None,
                module="CN_TP_CALCULATIONS_PVT",
                action="CALCULATE",
                elapsed_time_delta=Decimal("192901"),
                buffer_gets_delta=Decimal("415000000"),
                rows_processed_delta=Decimal("12150000"),
                top_wait_event="cell single block physical read",
                udq_name="MTQ_ICM_OBA_BY_BADGE_VS",
                udq_hash="sha256:mtq-icm-oba-by-badge-vs",
                query_text_available=False,
                query_shape_tags=["plan regression", "HZ_REF_ENTITIES", "EXTN_ATTRIBUTE_NUMBER007"],
                index_profile_notes="Current plan uses HZ_REF_ENTITIES_X26; historical good plan used HZ_REF_ENTITIES_N1.",
                recommendation_text="Use DBA-approved stats/histogram refresh or SQL Plan Baseline; do not execute remediation from this app.",
            )
        )
    if not db.scalar(select(VolumeSnapshot.id).where(VolumeSnapshot.run_id == run.id, VolumeSnapshot.metric_name == "formula_lookup_lines")):
        db.add(
            VolumeSnapshot(
                run_id=run.id,
                metric_name="formula_lookup_lines",
                metric_value=Decimal("253391"),
                baseline_value=Decimal("105267"),
                unit="lines",
                shape_tags=["duplicate keys", "cache ineffective"],
            )
        )

    service = DiagnosticAnalysisService(db)
    existing_report = service.latest_for_run(run.id)
    if existing_report is None:
        result = service.generate_report(run_id=run.id, lookback_minutes=720, collector_mode="seed")
        return {"created_runs": created_runs, "created_reports": 1, "report_id": result.report.id}
    return {"created_runs": created_runs, "created_reports": 0, "report_id": existing_report.id}


def seed_scale_test_data(
    db: Session,
    *,
    customer_count: int = 10,
    jobs_per_customer: int = 25,
    prefix: str = "DEMO_CUST",
) -> dict[str, int]:
    """Create deterministic high-cardinality demo data for heat-map and alert testing.

    The function is intentionally idempotent at the customer-key level. If
    DEMO_CUST_01 already exists, it is skipped instead of duplicated.
    """

    now = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
    counts = {
        "customers": 0,
        "job_definitions": 0,
        "current_runs": 0,
        "history_runs": 0,
        "expectations": 0,
        "alert_rules": 0,
        "alerts": 0,
        "topology_nodes": 0,
        "topology_metrics": 0,
        "topology_sessions": 0,
        "topology_bindings": 0,
    }

    for customer_index in range(1, customer_count + 1):
        customer_key = f"{prefix}_{customer_index:02d}"
        if db.scalar(select(Customer.id).where(Customer.customer_key == customer_key)):
            _merge_topology_counts(
                counts,
                RuntimeTopologyService(db).ensure_seed_topology(
                    customer_key=customer_key,
                    environment="PROD",
                    now=now,
                ),
            )
            _refresh_scale_alert_payloads(db, customer_key)
            continue

        customer = Customer(
            customer_key=customer_key,
            display_name=f"Demo Customer {customer_index:02d}",
            tier="scale-test",
        )
        db.add(customer)
        db.flush()
        counts["customers"] += 1

        environment = Environment(
            customer_id=customer.id,
            name="PROD",
            region="global",
            lifecycle="prod",
            base_url=f"https://demo-{customer_index:02d}.example.invalid",
        )
        db.add(environment)
        db.flush()

        for job_index in range(1, jobs_per_customer + 1):
            blueprint = SCALE_JOB_PATTERNS[(job_index - 1) % len(SCALE_JOB_PATTERNS)]
            job_family, job_type, job_label, ess_request_name = blueprint
            region = SCALE_REGIONS[(customer_index + job_index) % len(SCALE_REGIONS)]
            workstream = SCALE_WORKSTREAMS[(customer_index * 2 + job_index) % len(SCALE_WORKSTREAMS)]
            state = SCALE_STATES[(customer_index + job_index) % len(SCALE_STATES)]
            base_minutes = 55 + (job_index % 8) * 18 + customer_index * 3
            baseline_volume = 75000 + customer_index * 9000 + job_index * 13500
            baseline_participants = 1200 + customer_index * 80 + job_index * 35
            job_name = f"{region} {workstream} {job_label} {job_index:02d}"
            api_operation = "CalculatePVT" if job_type == "CalculatePVT" else None
            base_sql_id = f"s{customer_index:02d}{job_index:02d}base"
            base_plan_hash = str(41000000 + customer_index * 1000 + job_index * 17)
            base_udq_hash = (
                f"sha256:{customer_key.lower()}-udq-{job_index:02d}-v1"
                if job_family.startswith("ICM")
                else None
            )
            current_sql_id = base_sql_id
            current_plan_hash = base_plan_hash
            current_udq_hash = base_udq_hash
            query_tags: list[str] = []
            sql_profile = None
            index_notes = None
            recommendation = "Comparable current SQL observation."

            if state == "critical":
                current_sql_id = f"s{customer_index:02d}{job_index:02d}slow"
                current_plan_hash = str(int(base_plan_hash) + 9187)
                if base_udq_hash:
                    current_udq_hash = base_udq_hash.replace("-v1", "-v2")
                query_tags = ["OR predicate", "full scan", "unstable plan"]
                sql_profile = f"SENTINEL_PROFILE_{customer_index:02d}_{job_index:02d}"
                index_notes = "Plan hash changed after profile/index intervention; compare against prior successful runs."
                recommendation = "Review customer-authored query shape and compare SQL plan before escalating as platform regression."
            elif state == "warning" and job_index % 3 == 0:
                current_sql_id = f"s{customer_index:02d}{job_index:02d}warn"
                query_tags = ["new SQL_ID"]
                recommendation = "Check whether this warning is tied to a new SQL_ID or normal volume variance."

            job_definition = JobDefinition(
                customer_id=customer.id,
                job_family=job_family,
                job_type=job_type,
                job_name=job_name,
                default_region=region,
                default_workstream=workstream,
                ess_request_name=ess_request_name,
                process_name=job_name,
                api_operation=api_operation,
            )
            db.add(job_definition)
            db.flush()
            counts["job_definitions"] += 1

            if state != "unknown_baseline":
                history_created = _seed_scale_history(
                    db,
                    customer,
                    environment,
                    job_definition,
                    now,
                    base_minutes=base_minutes,
                    baseline_volume=baseline_volume,
                    baseline_participants=baseline_participants,
                    sql_id=base_sql_id,
                    plan_hash=base_plan_hash,
                    udq_hash=base_udq_hash,
                )
                counts["history_runs"] += history_created

                db.add(
                    ExpectationRecord(
                        customer_key=customer.customer_key,
                        environment=environment.name,
                        job_family=job_family,
                        job_type=job_type,
                        job_name=job_name,
                        region=region,
                        workstream=workstream,
                        period="FY26-Q4",
                        ess_request_name=ess_request_name,
                        process_name=job_name,
                        api_operation=api_operation,
                        sql_id=base_sql_id,
                        sql_plan_hash=base_plan_hash,
                        udq_name=_scale_udq_name(customer_key, job_index) if base_udq_hash else None,
                        udq_hash=base_udq_hash,
                        baseline_method="manual_goal" if job_index % 3 == 0 else "historical_p50_p90",
                        expected_minutes=Decimal(str(base_minutes)),
                        warning_threshold_pct=Decimal("20.00"),
                        critical_threshold_pct=Decimal("60.00"),
                        customer_goal_minutes=Decimal(str(round(base_minutes * 1.45, 2))),
                        minimum_history_count=5,
                        confidence_score=Decimal("0.74") if state == "watch" else Decimal("0.82"),
                        owner="Scale Test Support",
                        alert_channel="#jobrun-sentinel-scale",
                        notes="Scale-test expectation generated for heat-map and alert validation.",
                        risk_assumptions="Comparable only when SQL_ID, plan hash, UDQ hash, and volume stay near baseline.",
                        last_reviewed_by="seed-generator",
                        last_reviewed_at=now - timedelta(days=1),
                    )
                )
                counts["expectations"] += 1

            current_run = _seed_scale_current_run(
                db,
                customer,
                environment,
                job_definition,
                now,
                job_index=job_index,
                state=state,
                base_minutes=base_minutes,
                baseline_volume=baseline_volume,
                baseline_participants=baseline_participants,
                sql_id=current_sql_id,
                plan_hash=current_plan_hash,
                udq_hash=current_udq_hash,
                sql_profile=sql_profile,
                query_tags=query_tags,
                index_notes=index_notes,
                recommendation=recommendation,
            )
            counts["current_runs"] += 1

            db.add(
                AlertRule(
                    name=f"{customer_key} {job_name} monitor",
                    rule_type="standard",
                    customer_id=customer.id,
                    environment_id=environment.id,
                    job_definition_id=job_definition.id,
                    run_id=current_run.id,
                    selector={
                        "run_key": current_run.run_key,
                        "process_id": current_run.process_id,
                        "ess_request_id": current_run.ess_request_id,
                        "target_state": state,
                    },
                    expected_minutes=Decimal(str(base_minutes)) if state != "unknown_baseline" else None,
                    warning_threshold_pct=Decimal("20.00"),
                    critical_threshold_pct=Decimal("60.00"),
                    destination="#jobrun-sentinel-scale",
                    active=True,
                    notes=f"Scale-test monitor expected to evaluate as {state}.",
                )
            )
            counts["alert_rules"] += 1

            if state != "normal":
                EvaluationService(db).evaluate_run(
                    current_run.id,
                    create_alert=True,
                    send_mock_slack=False,
                )
                counts["alerts"] += 1

        db.add(
            PlaybookNote(
                customer_id=customer.id,
                environment_id=environment.id,
                note_date=date.today(),
                title=f"Scale-test watch list for {customer.display_name}",
                body=(
                    f"{jobs_per_customer} active key jobs generated across normal, watch, warning, "
                    "critical, and learning-mode states."
                ),
                risk_level="watch",
                owner="Scale Test Support",
            )
        )
        _merge_topology_counts(
            counts,
            RuntimeTopologyService(db).ensure_seed_topology(
                customer_key=customer_key,
                environment=environment.name,
                now=now,
            ),
        )
        _refresh_scale_alert_payloads(db, customer_key)

    return counts


def _merge_topology_counts(target: dict[str, int], topology_counts: dict[str, int]) -> None:
    target["topology_nodes"] += topology_counts.get("nodes", 0)
    target["topology_metrics"] += topology_counts.get("metrics", 0)
    target["topology_sessions"] += topology_counts.get("sessions", 0)
    target["topology_bindings"] += topology_counts.get("bindings", 0)


def _refresh_scale_alert_payloads(db: Session, customer_key: str) -> None:
    runs = list(
        db.scalars(
            select(JobRun)
            .join(Customer, JobRun.customer_id == Customer.id)
            .where(
                Customer.customer_key == customer_key,
                JobRun.run_key.like(f"{customer_key}-PROD-%-CURRENT"),
                JobRun.status == "RUNNING",
            )
        )
    )
    evaluator = EvaluationService(db)
    for run in runs:
        if (run.business_scope or {}).get("scale_seed_state") == "normal":
            continue
        evaluator.evaluate_run(run.id, create_alert=True, send_mock_slack=False)


def _seed_scale_history(
    db: Session,
    customer: Customer,
    environment: Environment,
    job: JobDefinition,
    now: datetime,
    *,
    base_minutes: int,
    baseline_volume: int,
    baseline_participants: int,
    sql_id: str,
    plan_hash: str,
    udq_hash: str | None,
) -> int:
    duration_offsets = [-7, 3, -2, 5, 9, 1]
    for index, offset in enumerate(duration_offsets, start=1):
        duration = max(base_minutes + offset, 20)
        start = now - timedelta(days=21 - index * 2, minutes=duration, hours=index % 3)
        end = start + timedelta(minutes=duration)
        volume = baseline_volume + offset * 180
        participants = baseline_participants + offset * 6
        run = JobRun(
            run_key=f"{customer.customer_key}-{job.id:04d}-HIST-{index}",
            customer_id=customer.id,
            environment_id=environment.id,
            job_definition_id=job.id,
            job_family=job.job_family,
            job_type=job.job_type,
            job_name=job.job_name,
            region=job.default_region,
            workstream=job.default_workstream,
            period="FY26-Q3",
            data_window_start=start - timedelta(days=31),
            data_window_end=start,
            started_at=start,
            ended_at=end,
            status="SUCCESS",
            ess_request_id=f"ESS-{customer.customer_key}-{job.id:04d}-H{index}",
            job_id=f"JOB-{customer.customer_key}-{job.id:04d}-H{index}",
            process_id=f"PROC-{customer.customer_key}-{job.id:04d}-H{index}",
            api_operation=job.api_operation,
            sql_id=sql_id,
            plan_hash_value=plan_hash,
            udq_name=_scale_udq_name(customer.customer_key, job.id) if udq_hash else None,
            udq_hash=udq_hash,
            expected_minutes_at_start=Decimal(str(base_minutes)),
            current_progress_pct=Decimal("100.00"),
            last_progress_at=end,
        )
        db.add(run)
        db.flush()
        _add_scale_metrics(
            db,
            run,
            metric_value=volume,
            baseline_value=baseline_volume,
            participants=participants,
            baseline_participants=baseline_participants,
            tags=[],
        )
        _add_scale_sql_observation(
            db,
            run,
            sql_id=sql_id,
            plan_hash=plan_hash,
            udq_hash=udq_hash,
            sql_profile=None,
            query_tags=[],
            index_notes=None,
            recommendation="Comparable successful scale-test baseline run.",
        )
    return len(duration_offsets)


def _seed_scale_current_run(
    db: Session,
    customer: Customer,
    environment: Environment,
    job: JobDefinition,
    now: datetime,
    *,
    job_index: int,
    state: str,
    base_minutes: int,
    baseline_volume: int,
    baseline_participants: int,
    sql_id: str,
    plan_hash: str,
    udq_hash: str | None,
    sql_profile: str | None,
    query_tags: list[str],
    index_notes: str | None,
    recommendation: str,
) -> JobRun:
    profile = {
        "normal": {"elapsed": 0.55, "progress": 62, "stale": 8, "volume_ratio": 1.02, "tags": []},
        "watch": {"elapsed": 0.92, "progress": 71, "stale": 12, "volume_ratio": 1.05, "tags": []},
        "warning": {"elapsed": 1.35, "progress": 78, "stale": 20, "volume_ratio": 1.10, "tags": []},
        "critical": {
            "elapsed": 2.25,
            "progress": 41,
            "stale": 95,
            "volume_ratio": 1.45,
            "tags": ["volume drift", "data window mismatch"],
        },
        "unknown_baseline": {
            "elapsed": 0.70,
            "progress": 25,
            "stale": 15,
            "volume_ratio": 1.25,
            "tags": ["learning mode"],
        },
    }[state]
    elapsed_minutes = round(base_minutes * profile["elapsed"])
    current_volume = round(baseline_volume * profile["volume_ratio"])
    current_participants = round(baseline_participants * (1 + (profile["volume_ratio"] - 1) * 0.35))
    start = now - timedelta(minutes=elapsed_minutes, seconds=job_index * 7)
    data_window_days = 46 if state == "critical" else 31
    run = JobRun(
        run_key=f"{customer.customer_key}-PROD-{job.id:04d}-CURRENT",
        customer_id=customer.id,
        environment_id=environment.id,
        job_definition_id=job.id,
        job_family=job.job_family,
        job_type=job.job_type,
        job_name=job.job_name,
        region=job.default_region,
        workstream=job.default_workstream,
        period="FY26-Q4",
        business_scope={
            "scale_seed_state": state,
            "customer_index": customer.customer_key,
            "job_index": job_index,
        },
        data_window_start=now - timedelta(days=data_window_days),
        data_window_end=now,
        started_at=start,
        status="RUNNING",
        ess_request_id=f"ESS-{customer.customer_key}-{job.id:04d}-CURRENT",
        job_id=f"JOB-{customer.customer_key}-{job.id:04d}-CURRENT",
        process_id=f"PROC-{customer.customer_key}-{job.id:04d}-CURRENT",
        api_operation=job.api_operation,
        sql_id=sql_id,
        plan_hash_value=plan_hash,
        udq_name=_scale_udq_name(customer.customer_key, job.id) if udq_hash else None,
        udq_hash=udq_hash,
        expected_minutes_at_start=Decimal(str(base_minutes)) if state != "unknown_baseline" else None,
        current_progress_pct=Decimal(str(profile["progress"])),
        last_progress_at=now - timedelta(minutes=profile["stale"]),
        notes=f"Scale-test current run expected to evaluate as {state}.",
    )
    db.add(run)
    db.flush()
    _add_scale_metrics(
        db,
        run,
        metric_value=current_volume,
        baseline_value=baseline_volume,
        participants=current_participants,
        baseline_participants=baseline_participants,
        tags=profile["tags"],
    )
    _add_scale_sql_observation(
        db,
        run,
        sql_id=sql_id,
        plan_hash=plan_hash,
        udq_hash=udq_hash,
        sql_profile=sql_profile,
        query_tags=query_tags,
        index_notes=index_notes,
        recommendation=recommendation,
    )
    return run


def _add_scale_metrics(
    db: Session,
    run: JobRun,
    *,
    metric_value: int,
    baseline_value: int,
    participants: int,
    baseline_participants: int,
    tags: list[str],
) -> None:
    db.add_all(
        [
            VolumeSnapshot(
                run_id=run.id,
                metric_name="transactions",
                metric_value=Decimal(str(metric_value)),
                baseline_value=Decimal(str(baseline_value)),
                unit="rows",
                data_window_start=run.data_window_start,
                data_window_end=run.data_window_end,
                shape_tags=tags,
            ),
            VolumeSnapshot(
                run_id=run.id,
                metric_name="participants",
                metric_value=Decimal(str(participants)),
                baseline_value=Decimal(str(baseline_participants)),
                unit="people",
                data_window_start=run.data_window_start,
                data_window_end=run.data_window_end,
                shape_tags=[],
            ),
        ]
    )


def _add_scale_sql_observation(
    db: Session,
    run: JobRun,
    *,
    sql_id: str,
    plan_hash: str,
    udq_hash: str | None,
    sql_profile: str | None,
    query_tags: list[str],
    index_notes: str | None,
    recommendation: str,
) -> None:
    db.add(
        SqlObservation(
            run_id=run.id,
            sql_id=sql_id,
            plan_hash_value=plan_hash,
            child_number=0,
            sql_profile=sql_profile,
            module=run.job_family,
            action=run.job_name,
            elapsed_time_delta=Decimal(str(round((run.expected_minutes_at_start or Decimal("60")) * 60))),
            buffer_gets_delta=Decimal(str((run.id + 1000) * 8800)),
            rows_processed_delta=run.volume_snapshots[0].metric_value
            if run.volume_snapshots
            else Decimal("0"),
            top_wait_event="db file sequential read" if query_tags else "CPU",
            udq_name=run.udq_name,
            udq_hash=udq_hash,
            query_text_available=False,
            query_shape_tags=query_tags,
            index_profile_notes=index_notes,
            recommendation_text=recommendation,
        )
    )


def _scale_udq_name(customer_key: str, job_index: int) -> str:
    return f"UDQ_{customer_key}_KEY_JOB_{job_index:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed JobRun Sentinel synthetic data.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables before seeding.")
    parser.add_argument("--init", action="store_true", help="Create tables and seed only if empty.")
    parser.add_argument(
        "--scale",
        action="store_true",
        help="Add deterministic 10-customer scale-test seed data for heat-map and alert validation.",
    )
    parser.add_argument("--scale-customers", type=int, default=10)
    parser.add_argument("--scale-jobs-per-customer", type=int, default=25)
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        has_seed = db.scalar(select(Customer.id).limit(1)) is not None
        if args.reset or args.init or not has_seed:
            seed_database(db, force=args.reset)
        ensure_phase2b_seed_data(db)
        if args.scale:
            counts = seed_scale_test_data(
                db,
                customer_count=args.scale_customers,
                jobs_per_customer=args.scale_jobs_per_customer,
            )
            print(f"Scale seed counts: {counts}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
