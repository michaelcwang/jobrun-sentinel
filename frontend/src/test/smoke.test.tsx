import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Layout } from "../components/Layout";
import { StatusPill } from "../components/StatusPill";
import { RoleProvider } from "../context/RoleContext";
import { ThemeProvider } from "../context/ThemeContext";
import { DiagnosticDetailPage } from "../pages/DiagnosticDetailPage";
import { DiagnosticsPage } from "../pages/DiagnosticsPage";
import { DashboardPage } from "../pages/DashboardPage";
import { RunDetailPage } from "../pages/RunDetailPage";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("frontend smoke", () => {
  it("renders the application shell", () => {
    render(
      <ThemeProvider>
        <RoleProvider>
          <MemoryRouter>
            <Layout>
              <div>Dashboard content</div>
            </Layout>
          </MemoryRouter>
        </RoleProvider>
      </ThemeProvider>
    );

    expect(screen.getByText("JobRun Sentinel")).toBeInTheDocument();
    expect(screen.getByText("Dashboard content")).toBeInTheDocument();
  });

  it("renders status pills", () => {
    render(<StatusPill state="critical" />);
    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("renders diagnostics list", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([diagnosticSummary])));
    render(
      <RoleProvider>
        <MemoryRouter>
          <DiagnosticsPage />
        </MemoryRouter>
      </RoleProvider>
    );

    expect(await screen.findByText("ECID Slow Job Diagnostic - CN Calculate_pvt ESS 13729027")).toBeInTheDocument();
    expect(screen.getAllByText("Plan regression on HZ_REF_ENTITIES lookup").length).toBeGreaterThan(0);
  });

  it("renders diagnostic detail report", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/glossary")) {
          return jsonResponse([{ id: 1, term: "ECID", definition: "Correlation key", domain: "oracle", active: true }]);
        }
        return jsonResponse(diagnosticDetail);
      })
    );
    render(
      <MemoryRouter initialEntries={["/diagnostics/1"]}>
        <Routes>
          <Route path="/diagnostics/:id" element={<DiagnosticDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("If you do only one thing today")).toBeInTheDocument();
    expect(screen.getAllByText("Plan regression on HZ_REF_ENTITIES lookup").length).toBeGreaterThan(0);
    expect(screen.getByText("Data-quality gate")).toBeInTheDocument();
  });

  it("renders dashboard runtime topology and server-time heat map", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/topology/heatmap")) return jsonResponse(heatmapResponse);
        if (url.includes("/topology/current")) return jsonResponse(topologyResponse);
        return jsonResponse(dashboardResponse);
      })
    );
    render(
      <RoleProvider>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </RoleProvider>
    );

    expect(await screen.findByText("Execution topology")).toBeInTheDocument();
    expect(screen.getAllByText("Server-time heat map").length).toBeGreaterThan(0);
    expect(screen.getByText("Runtime summary")).toBeInTheDocument();
    expect(screen.getAllByText("DBRAC_inst1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SQL_ID dp9u1803k8k7f").length).toBeGreaterThan(0);
    expect(screen.getByText("Auto refresh")).toBeInTheDocument();
    const pageText = document.body.textContent ?? "";
    expect(pageText.indexOf("Server-time heat map")).toBeLessThan(pageText.indexOf("Execution topology"));

    fireEvent.click(screen.getByRole("button", { name: /Investigate DBRAC_inst1.*critical heat 82/i }));
    expect(screen.getByText("Heat-map investigation")).toBeInTheDocument();
    expect(screen.getByText("Two-click investigation path")).toBeInTheDocument();
    expect(screen.getByText("Recommended fix path")).toBeInTheDocument();
    expect(screen.getByText("Open diagnostic")).toBeInTheDocument();
    expect(screen.getByText("Explore run")).toBeInTheDocument();
    expect(screen.getByText("Execution path for the selected heat tile")).toBeInTheDocument();
  });

  it("renders customer executive critical-event summary for selected customer pods", async () => {
    window.localStorage.setItem("jobrun-sentinel-customer-pod", "CUST_A");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/customers/CUST_A/executive-summary")) return jsonResponse(customerExecutiveSummary);
        if (url.includes("/topology/heatmap")) return jsonResponse(heatmapResponse);
        if (url.includes("/topology/current")) return jsonResponse(topologyResponse);
        return jsonResponse(dashboardResponse);
      })
    );
    render(
      <RoleProvider>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </RoleProvider>
    );

    expect(await screen.findByText("Customer A critical events")).toBeInTheDocument();
    expect(screen.getByText(/Started/)).toBeInTheDocument();
    expect(screen.getAllByText(/elapsed vs expected/i).length).toBeGreaterThan(0);
    expect(screen.getByLabelText(/Elapsed 13h versus expected 5h 50m/i)).toBeInTheDocument();
    expect(screen.getByText(/Fix:/)).toBeInTheDocument();
    expect(screen.getByText(/Remove the OR predicate/)).toBeInTheDocument();
  });

  it("auto-refreshes dashboard heat-map data for live traffic", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/topology/heatmap")) return jsonResponse(heatmapResponse);
      if (url.includes("/topology/current")) return jsonResponse(topologyResponse);
      return jsonResponse(dashboardResponse);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <RoleProvider>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </RoleProvider>
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getAllByText("Server-time heat map").length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(4);

    await act(async () => {
      vi.advanceTimersByTime(15000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetchMock).toHaveBeenCalledTimes(7);
  });

  it("renders run detail topology tab", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/topology")) return jsonResponse(topologyCorrelation);
        return jsonResponse(runDetail);
      })
    );
    render(
      <RoleProvider>
        <MemoryRouter initialEntries={["/runs/10"]}>
          <Routes>
            <Route path="/runs/:id" element={<RunDetailPage />} />
          </Routes>
        </MemoryRouter>
      </RoleProvider>
    );

    fireEvent.click(await screen.findByRole("button", { name: "Topology" }));
    expect(await screen.findByText("Runtime location")).toBeInTheDocument();
    expect(screen.getAllByText("DBRAC_inst1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SQL_ID dp9u1803k8k7f").length).toBeGreaterThan(0);
  });
});

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

const diagnosticSummary = {
  id: 1,
  run_id: 10,
  customer_key: "CUST_A",
  environment: "PROD",
  report_title: "ECID Slow Job Diagnostic - CN Calculate_pvt ESS 13729027",
  diagnostic_type: "slow_job",
  ess_request_id: "13729027",
  job_name: "CN Calculate_pvt",
  process_id: "1434435",
  ecid: "0598914d69b56a3ce534410a606b4a9b",
  incident_state: "active",
  freshness_status: "fresh",
  overall_confidence: "high",
  overall_status: "warning",
  if_you_do_one_thing_today: "Get DBA sign-off to address the plan regression first.",
  executive_summary: {},
  top_finding: {
    title: "Plan regression on HZ_REF_ENTITIES lookup",
    severity: "critical",
    finding_type: "PLAN_REGRESSION",
    actionability: "READY_TO_ACT_WITH_SIGNOFF"
  },
  created_at: "2026-06-20T10:00:00",
  updated_at: "2026-06-20T10:00:00"
};

const diagnosticDetail = {
  ...diagnosticSummary,
  job_definition: "JobDefinition://oracle/apps/ess/incentiveCompensation/cn/processes/transactionProcess/Calculate_pvt",
  client_identifier: "ess13729027-1434435",
  rac_cluster_size: 8,
  snapshot_start_at: "2026-06-20T00:00:00",
  snapshot_end_at: "2026-06-20T12:00:00",
  lookback_minutes: 720,
  collector_name: "JobRun Sentinel Diagnostic Collector",
  collector_version: "2B.1",
  source_package: "CN_TP_CALCULATIONS_PVT.CALCULATE",
  executive_summary: {
    root_cause_count: 2,
    plan_regression_factor: 28,
    live_runtime_hours: 13.2,
    bottleneck_executions: 12150000,
    confirmed_formula_packages: 2,
    potential_formula_references: 1157
  },
  metrics: [],
  findings: [
    {
      id: 11,
      finding_number: 1,
      finding_key: "dp9u1803k8k7f",
      finding_type: "PLAN_REGRESSION",
      title: "Plan regression on HZ_REF_ENTITIES lookup",
      severity: "critical",
      confidence: "high",
      actionability: "READY_TO_ACT_WITH_SIGNOFF",
      lifecycle: "active",
      problem_statement: "Current plan uses a less selective path.",
      business_impact: "The job is still active after 13 hours.",
      technical_detail: "Current plan 51543091 vs historical 3256752871.",
      recommended_action: "Refresh stats/histograms or load a SQL Plan Baseline with DBA sign-off.",
      expected_result: "Return to selective index path.",
      approval_gate: "DBA sign-off.",
      owner_team: "DBA",
      risk_if_done_wrong: "Wrong plan for other workloads.",
      rollback_plan: "Restore stats or drop baseline.",
      stop_recheck_condition: "Stop if SQL_ID changes.",
      source_sql_id: "dp9u1803k8k7f",
      source_plan_hash_value: "51543091",
      historical_plan_hash_value: "3256752871",
      package_name: null,
      object_name: "HZ_REF_ENTITIES",
      value_set_code: null,
      scope_count: null,
      confirmed_count: null,
      unverified_count: null,
      metrics: {},
      evidence: [],
      metric_rows: [],
      runbook_steps: [],
      ruled_out_alternatives: [],
      created_at: "2026-06-20T10:00:00",
      updated_at: "2026-06-20T10:00:00"
    }
  ],
  ruled_out_alternatives: [],
  data_quality_checks: [
    {
      id: 21,
      check_key: "remediation_non_executable",
      description: "Recommended actions do not include executable destructive operations",
      status: "passed",
      evidence_count: 3,
      message: "Remediation commands are text-only.",
      created_at: "2026-06-20T10:00:00"
    }
  ]
};

const dashboardItem = {
  run_id: 10,
  run_key: "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT",
  customer: "Customer A",
  customer_key: "CUST_A",
  environment: "PROD",
  job_family: "ICM Calculation",
  job_type: "CalculatePVT",
  job_name: "APJ Direct CalculatePVT",
  region: "APJ",
  workstream: "Direct",
  status: "RUNNING",
  started_at: "2026-06-20T00:00:00",
  ended_at: null,
  elapsed_minutes: 780,
  expected_minutes: 350,
  variance_pct: 122.8,
  eta_at: "2026-06-20T08:00:00",
  confidence_score: 0.6,
  runtime_state: "critical",
  latest_alert_state: "new",
  latest_alert_severity: "critical",
  cause_tags: ["new UDQ", "plan change"],
  reason_codes: ["ELAPSED_GT_CRITICAL_THRESHOLD", "NEW_UDQ_HASH", "SQL_PLAN_CHANGED"],
  top_suspected_cause: "Customer-authored UDQ changed",
  is_ad_hoc: false,
  source_type: "seed",
  source_connector: null,
  last_refreshed_at: "2026-06-20T10:00:00",
  latest_diagnostic_id: 1,
  latest_diagnostic_title: "APJ diagnostic",
  latest_diagnostic_top_finding: "Plan regression on HZ_REF_ENTITIES lookup"
};

const dashboardResponse = {
  generated_at: "2026-06-20T10:00:00",
  items: [dashboardItem],
  counts_by_state: { critical: 1 }
};

const customerExecutiveSummary = {
  generated_at: "2026-06-20T10:00:00",
  customer_key: "CUST_A",
  customer_name: "Customer A",
  environment: null,
  generation_mode: "local_ai_synthesis",
  headline: "1 critical event needs executive attention.",
  data_points_used: ["runtime evaluation", "diagnostic findings", "SQL/UDQ observations"],
  critical_event_count: 1,
  bullets: [
    {
      run_id: 10,
      job_name: "APJ Direct CalculatePVT",
      job_type: "CalculatePVT",
      environment: "PROD",
      region: "APJ",
      workstream: "Direct",
      status: "RUNNING",
      started_at: "2026-06-20T00:00:00",
      elapsed_minutes: 780,
      expected_minutes: 350,
      variance_pct: 122.8,
      top_suspected_cause: "Customer-authored UDQ changed",
      proposed_solution: "Remove the OR predicate on the lookup column or split into UNION ALL / separate statements.",
      supporting_analysis: [
        "Elapsed 780m vs expected 350m.",
        "Diagnostic finding: Plan regression on HZ_REF_ENTITIES lookup."
      ],
      reason_codes: ["ELAPSED_GT_CRITICAL_THRESHOLD", "NEW_UDQ_HASH"],
      diagnostic_id: 1,
      diagnostic_title: "APJ diagnostic",
      diagnostic_top_finding: "Plan regression on HZ_REF_ENTITIES lookup",
      topology_summary: "Active on DBRAC_inst1 with SQL_ID dp9u1803k8k7f and wait User I/O."
    }
  ]
};

const topologyNodeBase = {
  heat_score: 80,
  confidence: "confirmed",
  active_run_count: 1,
  active_session_count: 1,
  top_sql_id: "dp9u1803k8k7f",
  top_wait_class: "User I/O",
  top_event: "cell single block physical read",
  metrics: {},
  last_refreshed_at: "2026-06-20T10:00:00",
  details: {}
};

const topologyResponse = {
  generated_at: "2026-06-20T10:00:00",
  selected_run_id: 10,
  nodes: [
    { ...topologyNodeBase, node_key: "job-10", display_name: "APJ Direct CalculatePVT", node_type: "job_run", tier: "Job", severity: "critical" },
    { ...topologyNodeBase, node_key: "db-instance-1", display_name: "DBRAC_inst1", node_type: "db_instance", tier: "DB", severity: "critical" },
    { ...topologyNodeBase, node_key: "sql-dp9u1803k8k7f", display_name: "SQL_ID dp9u1803k8k7f", node_type: "sql_id", tier: "SQL", severity: "critical" }
  ],
  edges: [{ from_node_key: "job-10", to_node_key: "db-instance-1", label: "active DB session", confidence: "confirmed", run_id: 10, evidence: "confirmed" }],
  explanations: ["This is not a cluster-wide outage. Heat is concentrated on DB instance 1 and SQL_ID dp9u1803k8k7f."]
};

const heatmapResponse = {
  generated_at: "2026-06-20T10:00:00",
  bucket_minutes: 10,
  rows: [
    {
      node: {
        id: 1,
        customer_key: "CUST_A",
        environment: "PROD",
        node_type: "db_instance",
        node_key: "db-instance-1",
        display_name: "DBRAC_inst1",
        host_name: "dbhost-a",
        instance_name: "DBRAC_inst1",
        server_name: null,
        cluster_name: "DBRAC",
        service_name: "ICM_PRD",
        availability_domain: null,
        region: "global",
        tags: {},
        active: true,
        created_at: "2026-06-20T10:00:00",
        updated_at: "2026-06-20T10:00:00"
      },
      tier: "DB",
      cells: [
        {
          node_id: 1,
          bucket_start: "2026-06-20T09:50:00",
          bucket_end: "2026-06-20T10:00:00",
          heat_score: 82,
          severity: "critical",
          contributing_run_ids: [10],
          contributing_sql_ids: ["dp9u1803k8k7f"],
          top_wait_class: "User I/O",
          top_event: "cell single block physical read",
          metric_breakdown: {},
          explanation: "DBRAC_inst1: heat 82 from APJ SQL."
        }
      ]
    }
  ]
};

const runDetail = {
  id: 10,
  run_key: "CUST_A-PROD-APJ-DIRECT-CALC-CURRENT",
  customer: { id: 1, customer_key: "CUST_A", display_name: "Customer A" },
  environment: { id: 1, name: "PROD", region: "global", lifecycle: "prod" },
  job_definition: null,
  job_family: "ICM Calculation",
  job_type: "CalculatePVT",
  job_name: "APJ Direct CalculatePVT",
  region: "APJ",
  workstream: "Direct",
  period: "FY26-Q4",
  data_window_start: null,
  data_window_end: null,
  started_at: "2026-06-20T00:00:00",
  ended_at: null,
  status: "RUNNING",
  ess_request_id: "ESS-APJ-90045",
  job_id: "JOB-ICM-APJ-20260620",
  process_id: "PROC-APJ-DIRECT-8841",
  api_operation: "CalculatePVT",
  sql_id: "dp9u1803k8k7f",
  plan_hash_value: "51543091",
  udq_name: "MTQ_ICM_OBA_BY_BADGE_VS",
  udq_hash: "sha256:udq-apj-direct-v2",
  current_progress_pct: 64,
  last_progress_at: "2026-06-20T08:00:00",
  source_type: "seed",
  source_connector: null,
  source_template_id: null,
  source_query_execution_id: null,
  ingested_at: null,
  provenance: {},
  notes: "Synthetic APJ topology test.",
  evaluation: {
    run_id: 10,
    runtime_state: "critical",
    severity: "critical",
    expected_minutes: 350,
    expected_source: "manual_goal",
    elapsed_minutes: 780,
    variance_pct: 122.8,
    eta_at: null,
    confidence_score: 0.6,
    reason_codes: ["ELAPSED_GT_CRITICAL_THRESHOLD"],
    cause_tags: ["runtime critical"],
    recommended_actions: ["Review topology."],
    top_suspected_cause: "Customer-authored UDQ changed",
    historical_comparison: {}
  },
  volumes: [],
  sql_observations: [],
  alerts: [],
  timeline: [],
  latest_diagnostic: null
};

const topologyCorrelation = {
  run_id: 10,
  selected_at: "2026-06-20T10:00:00",
  job_identity: {},
  ess_request_id: "ESS-APJ-90045",
  process_id: "PROC-APJ-DIRECT-8841",
  ecid: "apj-direct-calculatepvt-ecid",
  client_identifier: "ess-apj-90045-8841",
  active_sql_id: "dp9u1803k8k7f",
  plan_hash_value: "51543091",
  db_instance_node: heatmapResponse.rows[0].node,
  db_host_node: { ...heatmapResponse.rows[0].node, id: 2, node_type: "db_host", node_key: "db-host-dbhost-a", display_name: "dbhost-a" },
  app_server_node: { ...heatmapResponse.rows[0].node, id: 3, node_type: "ess_server", node_key: "app-ess_soaserver_as24_01", display_name: "ESS_SOAServer_as24_01" },
  app_server_confidence: "inferred",
  active_sessions: [
    {
      id: 1,
      run_id: 10,
      sampled_at: "2026-06-20T10:00:00",
      inst_id: 1,
      instance_name: "DBRAC_inst1",
      db_host_name: "dbhost-a",
      sid: 7716,
      serial_number: "4435",
      session_status: "ACTIVE",
      username: "FUSION_RUNTIME",
      service_name: "ICM_PRD",
      module: "CN_TP_CALCULATIONS_PVT.CALCULATE",
      action: "CalculatePVT APJ Direct",
      client_identifier: "ess-apj-90045-8841",
      ecid: "apj-direct-calculatepvt-ecid",
      machine: "ESS_SOAServer_as24_01",
      program: "JDBC Thin Client",
      process: "PROC-APJ-DIRECT-8841",
      sql_id: "dp9u1803k8k7f",
      sql_child_number: 0,
      sql_exec_start: "2026-06-20T00:40:00",
      last_call_et_seconds: 49320,
      event: "cell single block physical read",
      wait_class: "User I/O",
      state: "WAITING",
      blocking_instance: null,
      blocking_session: null,
      plan_hash_value: "51543091",
      row_wait_obj: "HZ_REF_ENTITIES",
      query_execution_id: null,
      created_at: "2026-06-20T10:00:00"
    }
  ],
  bindings: [],
  heat_summary: { server_heat_score: 82, hottest_node: "DBRAC_inst1" },
  problem_classification: "customer_query_udq_problem",
  evidence: ["Confirmed: APJ Direct CalculatePVT is active on DBRAC_inst1."],
  missing_inputs: [],
  recommended_next_query: "ash_samples_by_ecid_or_sql_id",
  explanation: "Confirmed active DB session with plan regression / UDQ risk."
};
