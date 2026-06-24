import { ChevronDown, ExternalLink, FileSearch, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { Metric } from "../components/Metric";
import { ReasonTags } from "../components/ReasonTags";
import { StatusPill } from "../components/StatusPill";
import { RuntimeTopologyMapView, ServerTimeHeatmapView } from "../components/topology/DashboardRuntimeMaps";
import { customerPodParam, useRole } from "../context/RoleContext";
import type {
  CustomerExecutiveSummaryResponse,
  DashboardItem,
  RuntimeState,
  ServerHeatmapCell,
} from "../types";
import { minutes, pct, shortDate } from "../utils/format";

const stateColors: Record<string, string> = {
  normal: "#2f9e44",
  complete: "#2f9e44",
  watch: "#d49a17",
  warning: "#f08c00",
  critical: "#d9480f",
  unknown_baseline: "#7b8494"
};

const LIVE_REFRESH_MS = 15000;

export function DashboardPage() {
  const { role, customerPod, customerPods } = useRole();
  const isExecutive = role === "executive";
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];
  const dashboardLimit = customerPod === "all" ? "300" : "100";
  const [refreshToken, setRefreshToken] = useState(0);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const { data, error, loading, refreshing: dashboardRefreshing } = useAsync(
    (signal) =>
      api.dashboard(
        { ...customerPodParam(customerPod), limit: dashboardLimit, status: "RUNNING" },
        { signal }
      ),
    [refreshToken, customerPod]
  );
  const { data: topologyData, refreshing: topologyRefreshing } = useAsync(
    (signal) => api.topology(customerPodParam(customerPod), { signal }),
    [refreshToken, customerPod]
  );
  const { data: heatmapData, refreshing: heatmapRefreshing } = useAsync(
    (signal) => api.topologyHeatmap({ ...customerPodParam(customerPod), bucket_minutes: "10" }, { signal }),
    [refreshToken, customerPod]
  );
  const {
    data: customerSummary,
    error: customerSummaryError,
    loading: customerSummaryLoading,
    refreshing: customerSummaryRefreshing
  } = useAsync<CustomerExecutiveSummaryResponse | null>(
    (signal) =>
      customerPod === "all"
        ? Promise.resolve(null)
        : api.customerExecutiveSummary(customerPod, { limit: "100" }, { signal }),
    [refreshToken, customerPod]
  );
  const [state, setState] = useState("all");
  const [expandedRunIds, setExpandedRunIds] = useState<Set<number>>(new Set());
  const [focusedRunIds, setFocusedRunIds] = useState<number[] | null>(null);
  const [selectedHeatCell, setSelectedHeatCell] = useState<ServerHeatmapCell | null>(null);
  const [showHotOnly, setShowHotOnly] = useState(false);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      setRefreshToken((value) => value + 1);
    }, LIVE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [autoRefresh, customerPod]);

  const allItems = data?.items ?? [];
  const items = useMemo(() => {
    const source = allItems;
    return source.filter((item) => {
      if (state !== "all" && item.runtime_state !== state) return false;
      if (focusedRunIds && !focusedRunIds.includes(item.run_id)) return false;
      return true;
    });
  }, [allItems, focusedRunIds, state]);

  const states = Array.from(new Set(allItems.map((item) => item.runtime_state)));
  const stateCounts = useMemo(() => {
    return allItems.reduce<Record<string, number>>((counts, item) => {
      counts[item.runtime_state] = (counts[item.runtime_state] ?? 0) + 1;
      return counts;
    }, {});
  }, [allItems]);
  const activeItems = items.filter((item) => item.status === "RUNNING");
  const allActiveItems = allItems.filter((item) => item.status === "RUNNING");
  const sortByRisk = (source: DashboardItem[]) =>
    [...source].sort((a, b) => {
      const aSeverity = severityRank[a.runtime_state] ?? 0;
      const bSeverity = severityRank[b.runtime_state] ?? 0;
      if (aSeverity !== bSeverity) return bSeverity - aSeverity;
      return Math.abs(b.variance_pct ?? 0) - Math.abs(a.variance_pct ?? 0);
    });
  const comparisonItems = sortByRisk(activeItems).slice(0, 10);
  const executiveWatchItems = sortByRisk(focusedRunIds ? activeItems : allActiveItems).slice(0, 6);
  const runtimeItems = isExecutive ? executiveWatchItems : items;
  const isRefreshing = dashboardRefreshing || topologyRefreshing || heatmapRefreshing || customerSummaryRefreshing;
  const selectedTopologyRunId = selectedHeatCell?.contributing_run_ids[0] ?? topologyData?.selected_run_id ?? null;

  function toggleExpanded(runId: number) {
    setExpandedRunIds((current) => {
      const next = new Set(current);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
    });
  }

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2 className="heading-with-help">
            Operations Summary
            <HelpTip
              label="Operations summary help"
              text="This page starts with status counts and job cards, then maps the selected job to ESS/API, middleware, DB instance, active SQL, and server-time heat."
            />
          </h2>
          <p>{selectedPod.label}: live monitored jobs, workstreams, and ad hoc monitors in the selected scope.</p>
          <p className="muted">
            Last refreshed {shortDate(data?.generated_at ?? null)}
            {isRefreshing ? <span className="live-refresh-pill">Updating data in place</span> : null}
          </p>
        </div>
        <button className="icon-button" onClick={() => setRefreshToken((value) => value + 1)} title="Refresh">
          <RefreshCw size={17} />
        </button>
      </div>

      <LoadingState loading={loading && !data} error={error} empty={!loading && allItems.length === 0} />

      {data ? (
        <>
          {customerPod !== "all" ? (
            <CustomerCriticalSummaryPanel
              summary={customerSummary ?? null}
              loading={customerSummaryLoading && !customerSummary}
              error={customerSummaryError}
            />
          ) : null}

          {isExecutive ? <ExecutiveSummary items={focusedRunIds ? activeItems : allActiveItems} /> : null}

          <div className="summary-grid">
            {(["critical", "warning", "watch", "normal", "unknown_baseline"] as RuntimeState[]).map((key) => (
              <Metric
                key={key}
                label={key.replace("_", " ")}
                value={stateCounts[key] ?? 0}
                help={stateHelp[key]}
              />
            ))}
          </div>

          {!isExecutive ? (
            <div className="filter-row">
              <label>
                State
                <select value={state} onChange={(event) => setState(event.target.value)}>
                  <option value="all">All states</option>
                  {states.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              {focusedRunIds ? (
                <button className="small-button" type="button" onClick={() => { setFocusedRunIds(null); setSelectedHeatCell(null); }}>
                  Clear heat-map focus
                </button>
              ) : null}
            </div>
          ) : focusedRunIds ? (
            <div className="filter-row executive-focus-row">
              <span className="muted">Executive view is focused on the selected heat-map cell.</span>
              <button className="small-button" type="button" onClick={() => { setFocusedRunIds(null); setSelectedHeatCell(null); }}>
                Clear heat-map focus
              </button>
            </div>
          ) : null}

          <div className="panel">
            <div className="compact-header section-header">
              <div>
                <h3 className="heading-with-help">
                  Server-time heat map
                  <HelpTip
                    label="Server-time heat map help"
                    text="Rows are servers or DB instances, columns are time buckets, and cell intensity represents slow-job count, waits, SQL concentration, CPU, GC, and node metrics when available."
                  />
                </h3>
                <p className="muted live-refresh-copy">
                  Live refresh {autoRefresh ? `on, every ${LIVE_REFRESH_MS / 1000}s` : "paused"}.
                  Last heat-map update {shortDate(heatmapData?.generated_at ?? null)}.
                  {heatmapRefreshing ? <span className="live-refresh-pill">Streaming updates</span> : null}
                </p>
              </div>
              <div className="heatmap-controls">
                <label className="toggle-row">
                  <input type="checkbox" checked={showHotOnly} onChange={(event) => setShowHotOnly(event.target.checked)} />
                  Show only hot nodes
                </label>
                <label className="toggle-row">
                  <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
                  Auto refresh
                </label>
                <button className="small-button" type="button" onClick={() => setRefreshToken((value) => value + 1)}>
                  <RefreshCw size={14} aria-hidden />
                  Refresh now
                </button>
              </div>
            </div>
            <ServerTimeHeatmapView
              heatmap={heatmapData}
              selectedCell={selectedHeatCell}
              showHotOnly={showHotOnly}
              items={allItems}
              topology={topologyData}
              onCellClick={(cell) => {
                setSelectedHeatCell(cell);
                setFocusedRunIds(cell.contributing_run_ids.length ? cell.contributing_run_ids : null);
              }}
            />
          </div>

          <div className="panel">
            <h3 className="heading-with-help">
              Execution topology
              <HelpTip
                label="Execution topology help"
                text="This map connects the selected job to ESS/API, inferred app or WLS server, confirmed DB instance/host, and active SQL_ID. Confirmed means direct session evidence; inferred means session metadata points there but telemetry has not confirmed it."
              />
            </h3>
            <RuntimeTopologyMapView topology={topologyData} selectedRunId={selectedTopologyRunId} />
          </div>

          <div>
            <div className="section-header compact-header">
              <h3 className="heading-with-help">
                {isExecutive ? "Executive watchlist" : "Runtime summary"}
                <HelpTip
                  label="Runtime summary help"
                  text={isExecutive ? "A concise customer-impact list of the highest-risk active jobs in the selected scope." : "These are job status cards, not the heat map. Use them to drill into a specific run after the topology and server-time heat map show where the pressure is."}
                />
              </h3>
            </div>
            <div className={`dashboard-grid ${isExecutive ? "dashboard-grid-executive" : ""}`}>
              <div className="heat-grid">
                {runtimeItems.length === 0 ? (
                  <div className="state-panel">No jobs need attention in the current scope.</div>
                ) : runtimeItems.map((item) => (
                  <JobHeatCard
                    key={item.run_id}
                    item={item}
                    role={role}
                    expanded={expandedRunIds.has(item.run_id)}
                    onToggle={() => toggleExpanded(item.run_id)}
                  />
                ))}
              </div>
              {!isExecutive ? (
                <div className="panel chart-panel">
                  <h3 className="heading-with-help">
                    Elapsed vs Expected
                    <HelpTip
                      label="Elapsed versus expected help"
                      text="Elapsed is how long the run has taken so far. Expected is the selected baseline after any volume adjustment. A long elapsed bar compared with expected is a runtime risk."
                    />
                  </h3>
                  <RuntimeComparisonPanel items={comparisonItems} />
                </div>
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}

function CustomerCriticalSummaryPanel({
  summary,
  loading,
  error
}: {
  summary: CustomerExecutiveSummaryResponse | null;
  loading: boolean;
  error: string | null;
}) {
  // Customer pages use a deliberately compact executive summary. The deeper
  // evidence trail belongs behind Explore run, where diagnostics, topology,
  // SQL/UDQ observations, alerts, and notes can be reviewed without cluttering
  // the two-minute customer status update.
  if (loading) {
    return (
      <div className="panel customer-critical-summary">
        <span className="eyebrow">AI-supported executive summary</span>
        <h3>Generating critical-event summary...</h3>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel customer-critical-summary">
        <span className="eyebrow">AI-supported executive summary</span>
        <h3>Critical-event summary unavailable</h3>
        <p className="muted">{error}</p>
      </div>
    );
  }

  if (!summary) return null;

  return (
    <div className="panel customer-critical-summary">
      <div className="critical-summary-header">
        <div>
          <span className="eyebrow">AI-supported executive summary</span>
          <h3>{summary.customer_name} critical events</h3>
          <p>{summary.headline}</p>
        </div>
        <div className="summary-source-chip">
          <strong>{summary.critical_event_count}</strong>
          <span>critical</span>
        </div>
      </div>

      {summary.bullets.length === 0 ? (
        <p className="muted">No active critical events are in this customer scope.</p>
      ) : (
        <ul className="critical-summary-list">
          {summary.bullets.map((item) => {
            // Executives need the runtime breach expressed as a quick multiple
            // of expectation, not as raw minutes only.
            const ratio = elapsedExpectedRatio(item.elapsed_minutes, item.expected_minutes);
            return (
              <li key={item.run_id}>
                <div className="critical-summary-compact-row">
                  <div className="critical-summary-main">
                    <div className="critical-summary-line">
                      <StatusPill state="critical" />
                      <div>
                        <strong>{item.job_name}</strong>
                        <span>
                          Started {shortDate(item.started_at)} · {item.environment}
                          {item.region ? ` / ${item.region}` : ""}
                          {item.workstream ? ` / ${item.workstream}` : ""}
                        </span>
                      </div>
                    </div>
                    <p>
                      <strong>Likely issue:</strong> {item.top_suspected_cause ?? item.diagnostic_top_finding ?? "running longer than expected"}.
                      {" "}
                      <strong>Fix:</strong> {item.proposed_solution}
                    </p>
                  </div>
                  <div className="elapsed-expected-badge" aria-label={`Elapsed ${minutes(item.elapsed_minutes)} versus expected ${minutes(item.expected_minutes)}`}>
                    <span>elapsed vs expected</span>
                    <strong>{minutes(item.elapsed_minutes)} / {minutes(item.expected_minutes)}</strong>
                    <small>{ratio}</small>
                  </div>
                  <div className="button-row critical-summary-actions">
                    <Link className="primary-button explore-link" to={`/runs/${item.run_id}`}>
                      <ExternalLink size={14} aria-hidden />
                      Explore run
                    </Link>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="muted summary-disclaimer">
        AI-supported summary. Use Explore run for diagnostics, SQL/UDQ evidence, topology, alert history, and full recommendations.
      </p>
    </div>
  );
}

function elapsedExpectedRatio(elapsed: number, expected: number | null) {
  if (!expected || expected <= 0) return "no baseline";
  return `${(elapsed / expected).toFixed(1)}x expected`;
}

function ExecutiveSummary({ items }: { items: DashboardItem[] }) {
  const critical = items.filter((item) => item.runtime_state === "critical");
  const warning = items.filter((item) => item.runtime_state === "warning");
  const customersAtRisk = new Set([...critical, ...warning].map((item) => item.customer_key)).size;
  const topRisks = [...critical, ...warning].slice(0, 5);

  return (
    <div className="executive-strip">
      <Metric
        label="Customers at risk"
        value={customersAtRisk}
        help="Number of customers with at least one critical or warning job in the current dashboard scope."
      />
      <Metric
        label="Critical jobs"
        value={critical.length}
        help="Jobs that are already beyond the critical runtime threshold or have a severe ETA/progress problem."
      />
      <Metric
        label="Warning jobs"
        value={warning.length}
        help="Jobs that are beyond the warning threshold but have not reached critical severity."
      />
      <div className="panel executive-risks">
        <h3 className="heading-with-help">
          Top risks
          <HelpTip
            label="Top risks help"
            text="This list is ordered from the current dashboard data and is meant for a quick customer-impact readout."
          />
        </h3>
        {topRisks.length === 0 ? (
          <p className="muted">No critical or warning jobs in scope.</p>
        ) : (
          topRisks.map((item) => (
            <Link to={`/runs/${item.run_id}`} key={item.run_id} className="risk-row">
              <StatusPill state={item.runtime_state} />
              <span>{item.customer}</span>
              <strong>{item.job_name}</strong>
              <small>{item.top_suspected_cause ?? "runtime variance"}</small>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}

function RuntimeComparisonPanel({ items }: { items: DashboardItem[] }) {
  if (items.length === 0) {
    return <div className="state-panel">No active runs match the current filters.</div>;
  }
  const maxMinutes = Math.max(
    ...items.map((item) => Math.max(item.elapsed_minutes, item.expected_minutes ?? 0)),
    1
  );

  return (
    <div className="runtime-comparison" aria-label="Elapsed versus expected runtime comparison">
      <div className="comparison-legend">
        <span><i className="legend-expected" /> expected</span>
        <span><i className="legend-elapsed" /> elapsed</span>
      </div>
      {items.map((item) => {
        const expectedWidth = `${Math.max(((item.expected_minutes ?? 0) / maxMinutes) * 100, item.expected_minutes ? 2 : 0)}%`;
        const elapsedWidth = `${Math.max((item.elapsed_minutes / maxMinutes) * 100, 2)}%`;
        return (
          <Link to={`/runs/${item.run_id}`} className="comparison-row" key={item.run_id}>
            <div className="comparison-label">
              <strong>{item.job_name}</strong>
              <span>{item.customer} / {item.environment} / {item.region ?? "global"}</span>
            </div>
            <div className="comparison-bars">
              <div className="comparison-bar-line">
                <span className="comparison-bar comparison-expected" style={{ width: expectedWidth }} />
                <small>{minutes(item.expected_minutes)}</small>
              </div>
              <div className="comparison-bar-line">
                <span
                  className="comparison-bar comparison-elapsed"
                  style={{ width: elapsedWidth, background: stateColors[item.runtime_state] ?? "#7b8494" }}
                />
                <small>{minutes(item.elapsed_minutes)} / {pct(item.variance_pct)}</small>
              </div>
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function JobHeatCard({
  item,
  role,
  expanded,
  onToggle
}: {
  item: DashboardItem;
  role: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const metricHelp = {
    elapsed: "Time since this job started, or total runtime if it already completed.",
    expected: "The app's selected baseline for this job and scope. It can come from a manual goal or historical runtime.",
    variance: "How far elapsed runtime is above or below expected runtime. Positive values mean slower than expected.",
    eta: "Estimated completion time. For active runs, progress can adjust this estimate.",
    confidence: "How much the app trusts the comparison. Low confidence usually means limited history or changed inputs.",
    alert: "Latest alert workflow state for this run."
  };

  return (
    <article className={`heat-card heat-${item.runtime_state}`}>
      <div className="heat-card-top">
        <div>
          <span className="eyebrow">
            {item.customer} / {item.environment}
          </span>
          <h3>{item.job_name}</h3>
        </div>
        <StatusPill state={item.runtime_state} />
      </div>
      <div className="card-meta">
        <span>{item.region ?? "global"}</span>
        <span>{item.workstream ?? "n/a"}</span>
        <span>{item.is_ad_hoc ? "ad hoc" : item.job_type}</span>
        <span>{item.source_type ?? "seed"}</span>
      </div>
      <div className="metric-grid compact">
        <Metric label="Elapsed" value={minutes(item.elapsed_minutes)} help={metricHelp.elapsed} />
        <Metric label="Expected" value={minutes(item.expected_minutes)} help={metricHelp.expected} />
        <Metric label="Variance" value={pct(item.variance_pct)} help={metricHelp.variance} />
        {role !== "executive" ? <Metric label="ETA" value={shortDate(item.eta_at)} help={metricHelp.eta} /> : null}
        {role !== "executive" ? (
          <Metric label="Confidence" value={`${Math.round(item.confidence_score * 100)}%`} help={metricHelp.confidence} />
        ) : null}
        {role === "operator" ? <Metric label="Alert" value={item.latest_alert_state ?? "none"} help={metricHelp.alert} /> : null}
      </div>
      <ReasonTags tags={role === "dba" ? item.reason_codes : item.cause_tags} limit={role === "executive" ? 3 : 6} />
      {item.top_suspected_cause ? <p className="cause-line">{item.top_suspected_cause}</p> : null}
      {item.latest_diagnostic_id ? (
        <Link className="diagnostic-inline-link" to={`/diagnostics/${item.latest_diagnostic_id}`}>
          <FileSearch size={14} aria-hidden />
          {item.latest_diagnostic_top_finding ?? item.latest_diagnostic_title}
        </Link>
      ) : null}
      {expanded ? (
        <div className="heat-card-details">
          <dl>
            <dt>Run</dt>
            <dd>{item.run_key}</dd>
            <dt>Started</dt>
            <dd>{shortDate(item.started_at)}</dd>
            <dt>ETA</dt>
            <dd>{shortDate(item.eta_at)}</dd>
            <dt>Confidence</dt>
            <dd>{Math.round(item.confidence_score * 100)}%</dd>
            <dt>Reason codes</dt>
            <dd><ReasonTags tags={item.reason_codes} limit={8} /></dd>
          </dl>
        </div>
      ) : null}
      <div className="heat-card-actions">
        {role !== "executive" ? (
          <button className="small-button" type="button" onClick={onToggle} aria-expanded={expanded}>
            <ChevronDown className={expanded ? "rotate-icon" : ""} size={14} aria-hidden />
            {expanded ? "Collapse" : "Expand"}
          </button>
        ) : null}
        <Link to={`/runs/${item.run_id}`} className="primary-button explore-link">
          <ExternalLink size={14} aria-hidden />
          Explore
        </Link>
      </div>
    </article>
  );
}

const stateHelp: Record<RuntimeState, string> = {
  normal: "The run is within its selected expected runtime and has no strong risk signal.",
  complete: "The run finished. Completed rows are useful for comparison but usually need no action.",
  watch: "The run is approaching its warning threshold or has a mild ETA risk.",
  warning: "The run exceeded the warning threshold. Support should review the recommended next action.",
  critical: "The run exceeded the critical threshold or has severe progress/ETA evidence. This is the highest urgency state.",
  unknown_baseline: "The app does not have enough comparable history or expectation data, so it is learning rather than paging critically."
};

const severityRank: Record<string, number> = {
  critical: 5,
  warning: 4,
  watch: 3,
  unknown_baseline: 2,
  normal: 1,
  complete: 0
};
