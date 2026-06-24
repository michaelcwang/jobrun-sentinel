import { CheckCircle2, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { ReasonTags } from "../components/ReasonTags";
import { StatusPill } from "../components/StatusPill";
import { customerPodParam, useRole } from "../context/RoleContext";
import { minutes, pct, shortDate } from "../utils/format";

export function AlertsPage() {
  const { role, customerPod, customerPods } = useRole();
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];
  const [refreshToken, setRefreshToken] = useState(0);
  const { data, error, loading } = useAsync(
    () => api.alerts({ ...customerPodParam(customerPod), limit: "300" }),
    [refreshToken, customerPod]
  );

  async function ack(id: number) {
    await api.ackAlert(id, "Acknowledged in JobRun Sentinel.");
    setRefreshToken((value) => value + 1);
  }

  async function resolve(id: number) {
    await api.resolveAlert(id, "Resolved from operator console.");
    setRefreshToken((value) => value + 1);
  }

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2 className="heading-with-help">
            Alerts
            <HelpTip
              label="Alerts help"
              text="Alerts are generated when a run crosses a runtime threshold, ETA risk, progress stall, or comparability change. Acknowledge means someone is looking; resolve means the risk is closed."
            />
          </h2>
          <p>{selectedPod.label}: new, escalated, acknowledged, and resolved runtime alerts with audit-ready actions.</p>
        </div>
      </div>
      <LoadingState loading={loading} error={error} empty={!loading && (data?.length ?? 0) === 0} />
      {(data?.length ?? 0) > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Severity</th>
                <th>State</th>
                <th>Run</th>
                <th>Elapsed / Expected</th>
                <th>Variance</th>
                <th>{role === "executive" ? "Explanation" : "Reason codes"}</th>
                <th>Cause</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(data ?? []).map((alert) => (
                <tr key={alert.id}>
                  <td><StatusPill state={alert.severity} /></td>
                  <td>{alert.state}<span className="subtext">{shortDate(alert.created_at)}</span></td>
                  <td>{alert.run_id ? <Link to={`/runs/${alert.run_id}`} className="table-link">Run {alert.run_id}</Link> : "n/a"}</td>
                  <td>{minutes(alert.elapsed_minutes)} / {minutes(alert.expected_minutes)}</td>
                  <td>{pct(alert.variance_pct)}</td>
                  <td><ReasonTags tags={alert.reason_codes} limit={role === "executive" ? 2 : 4} /></td>
                  <td>{alert.top_suspected_cause ?? "n/a"}</td>
                  <td>
                    <div className="button-row">
                      <button className="small-button" onClick={() => ack(alert.id)} disabled={alert.state === "resolved"}>
                        <ShieldCheck size={14} aria-hidden /> Ack
                      </button>
                      <button className="small-button" onClick={() => resolve(alert.id)} disabled={alert.state === "resolved"}>
                        <CheckCircle2 size={14} aria-hidden /> Resolve
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
