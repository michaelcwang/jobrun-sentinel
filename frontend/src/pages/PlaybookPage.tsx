import { Bell, CalendarDays } from "lucide-react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { ReasonTags } from "../components/ReasonTags";
import { StatusPill } from "../components/StatusPill";
import { customerPodParam, useRole } from "../context/RoleContext";
import { minutes, pct } from "../utils/format";

interface PlaybookRisk {
  run_id: number;
  runtime_state: string;
  severity: string;
  elapsed_minutes: number;
  expected_minutes: number | null;
  variance_pct: number | null;
  reason_codes: string[];
  top_suspected_cause: string | null;
  recommended_actions: string[];
}

export function PlaybookPage() {
  const { customerPod, customerPods } = useRole();
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];
  const { data, error, loading } = useAsync(
    () => api.playbook(customerPodParam(customerPod)),
    [customerPod]
  );
  const riskRuns = ((data?.risk_runs ?? []) as PlaybookRisk[]);
  const notes = ((data?.notes ?? []) as Array<Record<string, string>>);

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2 className="heading-with-help">
            Daily Playbook
            <HelpTip
              label="Daily playbook help"
              text="The playbook rolls up active risks and notes into a daily operating view. Executives can use it as a status readout; operators can use it for handoff."
            />
          </h2>
          <p>{selectedPod.label}: planned jobs, current progress, breach risks, and digest-ready support handoff.</p>
        </div>
      </div>
      <LoadingState loading={loading} error={error} empty={!loading && !data} />
      {data ? (
        <>
          <div className="summary-grid">
            <MetricLike icon={<CalendarDays size={18} />} label="Date" value={String(data.date)} />
            <MetricLike icon={<Bell size={18} />} label="Planned jobs" value={String(data.planned_jobs)} />
            <MetricLike icon={<Bell size={18} />} label="Critical" value={String(((data.daily_digest as Record<string, unknown>)?.critical as unknown[] | undefined)?.length ?? 0)} />
          </div>
          <div className="two-column">
            <div className="panel">
              <h3 className="heading-with-help">
                Current breach risks
                <HelpTip
                  label="Current breach risks help"
                  text="These are active runs that the evaluator believes may breach expected runtime, customer goals, or progress expectations."
                />
              </h3>
              <div className="record-list">
                {riskRuns.map((risk) => (
                  <article key={risk.run_id} className="record-item">
                    <div>
                      <StatusPill state={risk.runtime_state} />
                      <h4>Run {risk.run_id}</h4>
                      <p>{risk.top_suspected_cause ?? "No primary cause detected"}</p>
                      <ReasonTags tags={risk.reason_codes} limit={5} />
                    </div>
                    <div className="record-side">
                      <strong>{minutes(risk.elapsed_minutes)} / {minutes(risk.expected_minutes)}</strong>
                      <small>{pct(risk.variance_pct)}</small>
                    </div>
                  </article>
                ))}
              </div>
            </div>
            <div className="panel">
              <h3>Notes</h3>
              <div className="record-list">
                {notes.map((note) => (
                  <article key={String(note.id)} className="record-item">
                    <div>
                      <span className="eyebrow">{note.risk_level}</span>
                      <h4>{note.title}</h4>
                      <p>{note.body}</p>
                    </div>
                    <div className="record-side"><small>{note.owner}</small></div>
                  </article>
                ))}
              </div>
            </div>
          </div>
          <div className="panel">
            <h3>Digest payload</h3>
            <pre className="payload-preview">{JSON.stringify(data.daily_digest, null, 2)}</pre>
          </div>
        </>
      ) : null}
    </section>
  );
}

function MetricLike({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="metric metric-icon">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
