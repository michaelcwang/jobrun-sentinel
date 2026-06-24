import { ExternalLink, FileSearch } from "lucide-react";
import { Link } from "react-router-dom";

import { Metric } from "../Metric";
import { StatusPill } from "../StatusPill";
import type {
  DashboardItem,
  RuntimeState,
  RuntimeTopologyMap as RuntimeTopologyMapType,
  RuntimeTopologyNode,
  ServerHeatmapCell,
  ServerHeatmapResponse
} from "../../types";
import { minutes } from "../../utils/format";

// Dashboard and /topology share these views so the investigation path stays
// consistent: click a hot cell, see contributing jobs, then drill into the run.
export function RuntimeTopologyMapView({
  topology,
  selectedRunId
}: {
  topology: RuntimeTopologyMapType | null;
  selectedRunId: number | null;
}) {
  if (!topology) {
    return <div className="state-panel">Loading execution topology...</div>;
  }
  const order = ["Job", "ESS/API", "ESS/WLS", "DB", "SQL", "Unknown/Inferred"];
  const columns = order
    .map((tier) => ({
      tier,
      nodes: topology.nodes.filter((node) => node.tier === tier)
    }))
    .filter((column) => column.nodes.length > 0);

  return (
    <div className="topology-workbench">
      <div className="topology-map" aria-label="Execution topology map">
        {columns.map((column) => (
          <div className="topology-column" key={column.tier}>
            <span className="topology-tier">{column.tier}</span>
            {column.nodes.map((node) => (
              <TopologyNodeCard key={node.node_key} node={node} selectedRunId={selectedRunId} />
            ))}
          </div>
        ))}
      </div>
      <div className="topology-edge-list">
        {topology.edges.slice(0, 8).map((edge) => (
          <span key={`${edge.from_node_key}-${edge.to_node_key}-${edge.label}`} className={`edge-chip edge-${edge.confidence}`}>
            {edge.label}: {edge.confidence}
          </span>
        ))}
      </div>
      <div className="topology-explanations">
        {topology.explanations.map((text) => (
          <p key={text}>{text}</p>
        ))}
      </div>
    </div>
  );
}

function TopologyNodeCard({ node, selectedRunId }: { node: RuntimeTopologyNode; selectedRunId: number | null }) {
  const isSelectedRunNode = node.node_key === `job-${selectedRunId}` || node.node_key === `ess-${selectedRunId}`;
  return (
    <Link
      to={node.node_key.startsWith("job-") ? `/runs/${node.node_key.replace("job-", "")}` : node.top_sql_id ? `/runs/${selectedRunId ?? ""}` : "#"}
      className={`topology-node topology-${node.severity} ${isSelectedRunNode ? "topology-node-selected" : ""}`}
      title={[
        node.display_name,
        `confidence: ${node.confidence}`,
        node.top_sql_id ? `SQL_ID: ${node.top_sql_id}` : "",
        node.top_wait_class ? `wait: ${node.top_wait_class}` : "",
        `heat: ${node.heat_score}`
      ].filter(Boolean).join(" | ")}
    >
      <span className="topology-node-type">{node.node_type.replace(/_/g, " ")}</span>
      <strong>{node.display_name}</strong>
      <div className="topology-node-meta">
        <StatusPill state={node.severity} />
        <span>{node.confidence}</span>
      </div>
      <small>{node.top_sql_id ? `SQL ${node.top_sql_id}` : `${node.active_run_count} active run(s)`}</small>
      {node.top_wait_class ? <small>{node.top_wait_class} / {node.top_event ?? "n/a"}</small> : null}
    </Link>
  );
}

export function ServerTimeHeatmapView({
  heatmap,
  selectedCell,
  showHotOnly,
  items = [],
  topology,
  onCellClick
}: {
  heatmap: ServerHeatmapResponse | null;
  selectedCell: ServerHeatmapCell | null;
  showHotOnly: boolean;
  items?: DashboardItem[];
  topology?: RuntimeTopologyMapType | null;
  onCellClick: (cell: ServerHeatmapCell) => void;
}) {
  if (!heatmap) {
    return <div className="state-panel">Loading server-time heat map...</div>;
  }
  const rows = showHotOnly
    ? heatmap.rows.filter((row) => row.cells.some((cell) => cell.heat_score >= 25))
    : heatmap.rows;
  const buckets = rows[0]?.cells ?? [];

  return (
    <div className="server-heatmap-wrap">
      <div className="heatmap-legend" aria-label="Heat map legend">
        {["unknown", "normal", "watch", "warning", "critical"].map((severity) => (
          <span key={severity}><i className={`heat-cell heat-${severity}`} /> {severity.replace("_", " ")}</span>
        ))}
      </div>
      <div className="server-heatmap" role="grid">
        <div className="heatmap-node-header">Node</div>
        {buckets.map((cell) => (
          <div className="heatmap-time-header" key={cell.bucket_start}>{bucketLabel(cell.bucket_start)}</div>
        ))}
        {rows.map((row) => (
          <div className="heatmap-row" role="row" key={row.node.id}>
            <div className="heatmap-node-label">
              <strong>{row.node.display_name}</strong>
              <span>{row.tier} / {row.node.node_type.replace(/_/g, " ")}</span>
            </div>
            {row.cells.map((cell) => (
              <button
                className={`heat-cell heat-${cell.severity} ${selectedCell?.node_id === cell.node_id && selectedCell.bucket_start === cell.bucket_start ? "heat-cell-selected" : ""}`}
                key={`${row.node.id}-${cell.bucket_start}`}
                type="button"
                onClick={() => onCellClick(cell)}
                title={`Investigate ${row.node.display_name} ${bucketLabel(cell.bucket_start)} heat ${cell.heat_score}: ${cell.explanation}`}
                aria-label={`Investigate ${row.node.display_name} ${bucketLabel(cell.bucket_start)} ${cell.severity} heat ${cell.heat_score}`}
              >
                <span>{Math.round(cell.heat_score)}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
      {selectedCell ? (
        <HeatmapInvestigationPanel heatmap={heatmap} selectedCell={selectedCell} items={items} topology={topology} />
      ) : null}
    </div>
  );
}

function bucketLabel(value: string) {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function HeatmapInvestigationPanel({
  heatmap,
  selectedCell,
  items,
  topology
}: {
  heatmap: ServerHeatmapResponse;
  selectedCell: ServerHeatmapCell;
  items: DashboardItem[];
  topology?: RuntimeTopologyMapType | null;
}) {
  const selectedNode = heatmap.rows.find((row) => row.node.id === selectedCell.node_id)?.node;
  const contributingItems = selectedCell.contributing_run_ids
    .map((runId) => items.find((item) => item.run_id === runId) ?? null)
    .filter((item): item is DashboardItem => item !== null);
  const primaryItem = contributingItems[0] ?? null;
  const selectedRunId = selectedCell.contributing_run_ids[0] ?? topology?.selected_run_id ?? null;
  const recommendedActions = heatmapRecommendedActions(selectedCell, primaryItem);

  return (
    <div className="heatmap-investigation-panel" aria-live="polite">
      <div className="investigation-header">
        <div>
          <span className="eyebrow">Two-click investigation path</span>
          <h4>Heat-map investigation</h4>
          <p>{selectedCell.explanation}</p>
        </div>
        <StatusPill state={selectedCell.severity as RuntimeState} />
      </div>
      <div className="investigation-metrics">
        <Metric label="Node" value={selectedNode?.display_name ?? `Node ${selectedCell.node_id}`} help="Server, DB instance, or inferred runtime node contributing heat." />
        <Metric label="Time bucket" value={`${bucketLabel(selectedCell.bucket_start)} - ${bucketLabel(selectedCell.bucket_end)}`} help="The sampled interval represented by this heat tile." />
        <Metric label="Top wait" value={selectedCell.top_wait_class ?? "unknown"} help="Highest wait class or runtime pressure signal contributing to this tile." />
        <Metric label="SQL_ID" value={selectedCell.contributing_sql_ids[0] ?? "unknown"} help="Top SQL_ID observed in this hot tile, when available." />
      </div>
      <div className="investigation-grid">
        <div className="investigation-card">
          <h5>Associated jobs</h5>
          {contributingItems.length === 0 && selectedCell.contributing_run_ids.length === 0 ? (
            <p className="muted">No dashboard run is linked to this heat cell yet. Open topology to continue from node evidence.</p>
          ) : contributingItems.length > 0 ? (
            contributingItems.slice(0, 4).map((item) => (
              <div className="investigation-job-row" key={item.run_id}>
                <div>
                  <StatusPill state={item.runtime_state} />
                  <strong>{item.job_name}</strong>
                  <span>{item.customer} / {item.environment} / {item.region ?? "global"} / {item.workstream ?? "n/a"}</span>
                  <small>{item.top_suspected_cause ?? "Runtime variance requires investigation."}</small>
                </div>
                <div className="button-row">
                  {item.latest_diagnostic_id ? (
                    <Link className="small-button" to={`/diagnostics/${item.latest_diagnostic_id}`}>
                      <FileSearch size={14} aria-hidden />
                      Open diagnostic
                    </Link>
                  ) : null}
                  <Link className="primary-button explore-link" to={`/runs/${item.run_id}`}>
                    <ExternalLink size={14} aria-hidden />
                    Explore run
                  </Link>
                </div>
              </div>
            ))
          ) : (
            selectedCell.contributing_run_ids.slice(0, 4).map((runId) => (
              <div className="investigation-job-row" key={runId}>
                <div>
                  <StatusPill state={selectedCell.severity} />
                  <strong>Run {runId}</strong>
                  <span>Linked from heat-map runtime evidence</span>
                  <small>Open the run to review alerts, topology, SQL/UDQ observations, and recommendations.</small>
                </div>
                <div className="button-row">
                  <Link className="primary-button explore-link" to={`/runs/${runId}`}>
                    <ExternalLink size={14} aria-hidden />
                    Explore run
                  </Link>
                </div>
              </div>
            ))
          )}
        </div>
        <div className="investigation-card">
          <h5>Recommended fix path</h5>
          <ol className="investigation-steps">
            {recommendedActions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ol>
          <p className="muted">The app only recommends actions. Remediation stays in the runbook and requires the appropriate owner or DBA approval.</p>
        </div>
      </div>
      {topology ? (
        <div className="investigation-topology">
          <h5>Execution path for the selected heat tile</h5>
          <RuntimeTopologyMapView topology={topology} selectedRunId={selectedRunId} />
        </div>
      ) : null}
    </div>
  );
}

function heatmapRecommendedActions(cell: ServerHeatmapCell, item: DashboardItem | null) {
  const reasonCodes = item?.reason_codes ?? [];
  const causeTags = (item?.cause_tags ?? []).map((tag) => tag.toLowerCase());
  const actions: string[] = [];
  actions.push(
    item
      ? `Start with ${item.job_name}: elapsed ${minutes(item.elapsed_minutes)} vs expected ${minutes(item.expected_minutes)}.`
      : "Start from the hot node and confirm which active run owns the session or SQL_ID."
  );
  if (cell.contributing_sql_ids.length > 0 || reasonCodes.includes("SQL_PLAN_CHANGED") || causeTags.some((tag) => tag.includes("plan"))) {
    actions.push("Open the run diagnostic and compare SQL_ID, plan hash, waits, and prior-good plan before declaring an infrastructure issue.");
  }
  if (reasonCodes.includes("NEW_UDQ_HASH") || causeTags.some((tag) => tag.includes("udq"))) {
    actions.push("Review UDQ/query-shape drift with the query owner; for the APJ pattern, check OR predicate risk and consider UNION ALL or separate branches after owner review.");
  }
  if (reasonCodes.includes("STUCK_NO_PROGRESS")) {
    actions.push("Check active session, blocking, ESS progress heartbeat, and the last progress timestamp before escalating as a runtime regression.");
  }
  if (cell.top_wait_class || cell.top_event) {
    actions.push(`Validate whether ${cell.top_wait_class ?? "the wait class"} / ${cell.top_event ?? "top event"} is concentrated on this SQL/job or shared across the node.`);
  }
  if (actions.length < 3) {
    actions.push("Use Explore run for the full timeline, alerts, topology, SQL/UDQ evidence, and recommended next actions.");
  }
  return actions.slice(0, 5);
}
