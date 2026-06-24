import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { customerPodParam, useRole } from "../context/RoleContext";
import type { ServerHeatmapCell } from "../types";
import { shortDate } from "../utils/format";
import { RuntimeTopologyMap, ServerTimeHeatmap } from "./DashboardPage";

const LIVE_REFRESH_MS = 15000;

export function TopologyPage() {
  const { customerPod, customerPods } = useRole();
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];
  const [refreshToken, setRefreshToken] = useState(0);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const { data: topology, error: topologyError, loading: topologyLoading } = useAsync(
    (signal) => api.topology(customerPodParam(customerPod), { signal }),
    [customerPod, refreshToken]
  );
  const { data: heatmap, error: heatmapError, loading: heatmapLoading, refreshing: heatmapRefreshing } = useAsync(
    (signal) => api.topologyHeatmap({ ...customerPodParam(customerPod), bucket_minutes: "10" }, { signal }),
    [customerPod, refreshToken]
  );
  const [selectedCell, setSelectedCell] = useState<ServerHeatmapCell | null>(null);
  const [showHotOnly, setShowHotOnly] = useState(false);
  const selectedTopologyRunId = selectedCell?.contributing_run_ids[0] ?? topology?.selected_run_id ?? null;

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      setRefreshToken((value) => value + 1);
    }, LIVE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [autoRefresh, customerPod]);

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2 className="heading-with-help">
            Runtime Map
            <HelpTip
              label="Runtime map help"
              text="This view focuses on execution placement and server-time heat: job, ESS/API, middleware, DB instance, active SQL_ID, waits, and node pressure."
            />
          </h2>
          <p>{selectedPod.label}: topology and server-time heat for the selected customer scope.</p>
        </div>
      </div>
      <LoadingState loading={(topologyLoading && !topology) || (heatmapLoading && !heatmap)} error={topologyError ?? heatmapError} empty={false} />
      <div className="panel">
        <div className="compact-header section-header">
          <div>
            <h3>Server-time heat map</h3>
            <p className="muted live-refresh-copy">
              Live refresh {autoRefresh ? `on, every ${LIVE_REFRESH_MS / 1000}s` : "paused"}.
              Last heat-map update {shortDate(heatmap?.generated_at ?? null)}.
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
        <ServerTimeHeatmap
          heatmap={heatmap}
          selectedCell={selectedCell}
          showHotOnly={showHotOnly}
          topology={topology}
          onCellClick={setSelectedCell}
        />
      </div>
      <div className="panel">
        <h3>Execution topology</h3>
        <RuntimeTopologyMap topology={topology} selectedRunId={selectedTopologyRunId} />
      </div>
    </section>
  );
}
