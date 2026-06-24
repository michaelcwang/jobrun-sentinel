import { BellRing, DatabaseZap, FileSearch, RefreshCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { Metric } from "../components/Metric";
import { ReasonTags } from "../components/ReasonTags";
import { StatusPill } from "../components/StatusPill";
import { useRole } from "../context/RoleContext";
import type { RunDetail, TopologyCorrelation } from "../types";
import { compactNumber, minutes, pct, shortDate } from "../utils/format";

const tabs = ["Overview", "Diagnostics", "Topology", "Timeline", "SQL/UDQ", "Volumes", "Alerts", "Notes"] as const;
type RunTab = (typeof tabs)[number];

export function RunDetailPage() {
  const { id } = useParams();
  const { role } = useRole();
  const availableTabs = useMemo<RunTab[]>(() => {
    if (role === "executive") return ["Overview", "Diagnostics", "Topology", "Timeline", "Alerts", "Notes"];
    return [...tabs];
  }, [role]);
  const [activeTab, setActiveTab] = useState<RunTab>(role === "dba" ? "SQL/UDQ" : "Overview");
  const [refreshToken, setRefreshToken] = useState(0);
  const { data, error, loading } = useAsync(() => api.run(id ?? ""), [id, refreshToken]);
  const { data: topology } = useAsync(() => api.runTopology(id ?? ""), [id, refreshToken]);

  useEffect(() => {
    if (!availableTabs.includes(activeTab)) {
      setActiveTab("Overview");
    }
  }, [activeTab, availableTabs]);

  async function evaluate() {
    if (!data) return;
    await api.evaluate(data.id);
    setRefreshToken((value) => value + 1);
  }

  async function generateDiagnostic() {
    if (!data) return;
    await api.runDiagnostic({ run_id: data.id, lookback_minutes: 720, collector_mode: "ui" });
    setRefreshToken((value) => value + 1);
  }

  return (
    <section className="page-stack">
      <LoadingState loading={loading} error={error} empty={!loading && !data} />
      {data ? (
        <>
          <div className="detail-hero">
            <div>
              <span className="eyebrow">
                {data.customer.display_name} / {data.environment.name} / {data.region ?? "global"}
              </span>
              <h2>{data.job_name}</h2>
              <p>{data.run_key}</p>
            </div>
            <div className="hero-actions">
              <StatusPill state={data.evaluation.runtime_state} />
              <button className="primary-button" onClick={evaluate}>
                <RefreshCcw size={16} aria-hidden />
                Evaluate
              </button>
            </div>
          </div>

          <div className="summary-grid">
            <Metric
              label="Elapsed"
              value={minutes(data.evaluation.elapsed_minutes)}
              help="How long the job has run so far. If the job completed, this is total runtime."
            />
            <Metric
              label="Expected"
              value={minutes(data.evaluation.expected_minutes)}
              hint={data.evaluation.expected_source}
              help="The selected baseline. Manual goals win first; otherwise the app uses historical runtime when enough comparable history exists."
            />
            <Metric
              label="Variance"
              value={pct(data.evaluation.variance_pct)}
              help="Percent above or below expected runtime. Positive means slower than expected."
            />
            <Metric
              label="ETA"
              value={shortDate(data.evaluation.eta_at)}
              help="Estimated completion time based on expected runtime or reported progress."
            />
            <Metric
              label="Confidence"
              value={`${Math.round(data.evaluation.confidence_score * 100)}%`}
              help="How directly comparable this run is to baseline history. SQL, UDQ, plan, and data-window changes can lower confidence."
            />
          </div>

          <div className="tabs">
            {availableTabs.map((tab) => (
              <button key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)}>
                {tab}
              </button>
            ))}
          </div>

          {activeTab === "Overview" ? (
            <div className="two-column">
              <div className="panel">
                <h3 className="heading-with-help">
                  {role === "executive" ? "Executive readout" : "Why flagged"}
                  <HelpTip
                    label="Why flagged help"
                    text="Reason codes are the evidence behind the status. They explain whether runtime, ETA, volume, SQL, plan, UDQ, or progress changed enough to matter."
                  />
                </h3>
                <ReasonTags tags={role === "executive" ? data.evaluation.cause_tags : data.evaluation.reason_codes} limit={role === "executive" ? 5 : 10} />
                <div className="callout">
                  <BellRing size={18} aria-hidden />
                  <div>
                    <strong>{data.evaluation.top_suspected_cause ?? "No primary cause detected"}</strong>
                    <p>{data.evaluation.recommended_actions[0]}</p>
                  </div>
                </div>
                <ul className="action-list">
                  {data.evaluation.recommended_actions.map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
                {data.latest_diagnostic ? (
                  <Link className="diagnostic-inline-link" to={`/diagnostics/${data.latest_diagnostic.id}`}>
                    <FileSearch size={16} aria-hidden />
                    Diagnostic: {String(data.latest_diagnostic.top_finding?.title ?? data.latest_diagnostic.report_title)}
                  </Link>
                ) : null}
              </div>
              <div className="panel">
                <h3 className="heading-with-help">
                  Historical comparison
                  <HelpTip
                    label="Historical comparison help"
                    text="p50 is the middle historical run, p75 and p90 are slower-but-normal comparison points, and current shows where this run sits against that history."
                  />
                </h3>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart
                    data={[
                      { name: "p50", minutes: data.evaluation.historical_comparison.p50_minutes as number },
                      { name: "p75", minutes: data.evaluation.historical_comparison.p75_minutes as number },
                      { name: "p90", minutes: data.evaluation.historical_comparison.p90_minutes as number },
                      { name: "current", minutes: data.evaluation.elapsed_minutes }
                    ]}
                  >
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip formatter={(value: number) => minutes(value)} />
                    <Line type="monotone" dataKey="minutes" stroke="#2b8a83" strokeWidth={3} dot />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="panel">
                <h3 className="heading-with-help">
                  Data provenance
                  <HelpTip
                    label="Data provenance help"
                    text="Shows whether this run came from seed data, manual import, ad hoc entry, direct DB query, or future telemetry. Direct DB query rows link back to the audited query execution."
                  />
                </h3>
                <dl>
                  <dt>Source</dt>
                  <dd>{data.source_type ?? "unknown"}</dd>
                  <dt>Connector</dt>
                  <dd>{data.source_connector ?? "n/a"}</dd>
                  <dt>Template</dt>
                  <dd>{data.source_template_id ?? String(data.provenance?.template_id ?? "n/a")}</dd>
                  <dt>Execution log</dt>
                  <dd>{data.source_query_execution_id ?? String(data.provenance?.query_execution_log_id ?? "n/a")}</dd>
                  <dt>Ingested</dt>
                  <dd>{shortDate(data.ingested_at ?? String(data.provenance?.ingested_at ?? ""))}</dd>
                  <dt>Comparable</dt>
                  <dd>{directlyComparable(data) ? "Directly comparable to baseline" : "Comparison confidence reduced"}</dd>
                </dl>
              </div>
              {role === "dba" ? <DbaTracePanel data={data} /> : null}
            </div>
          ) : null}

          {activeTab === "Diagnostics" ? (
            <div className="two-column">
              <div className="panel">
                <h3 className="heading-with-help">
                  Diagnostic report
                  <HelpTip
                    label="Diagnostic report help"
                    text="Diagnostics go beyond alert thresholds. They collect evidence, create root-cause findings, score confidence, document ruled-out alternatives, and provide text-only runbook steps."
                  />
                </h3>
                {data.latest_diagnostic ? (
                  <>
                    <span className="eyebrow">{data.latest_diagnostic.overall_confidence} confidence / {data.latest_diagnostic.incident_state}</span>
                    <h4>{data.latest_diagnostic.report_title}</h4>
                    <p>{data.latest_diagnostic.if_you_do_one_thing_today}</p>
                    <div className="card-meta">
                      <StatusPill state={String(data.latest_diagnostic.top_finding?.severity ?? data.latest_diagnostic.overall_status)} />
                      <span>{String(data.latest_diagnostic.top_finding?.finding_type ?? data.latest_diagnostic.diagnostic_type)}</span>
                      <span>{String(data.latest_diagnostic.top_finding?.actionability ?? "n/a")}</span>
                    </div>
                    <div className="button-row">
                      <Link className="primary-button" to={`/diagnostics/${data.latest_diagnostic.id}`}>
                        <FileSearch size={14} aria-hidden /> Full diagnostic
                      </Link>
                      <button className="small-button" onClick={generateDiagnostic}>
                        <RefreshCcw size={14} aria-hidden /> Refresh diagnostic
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <p>No diagnostic report exists for this run yet.</p>
                    <button className="primary-button" onClick={generateDiagnostic}>
                      <FileSearch size={16} aria-hidden /> Generate diagnostic
                    </button>
                  </>
                )}
              </div>
              <div className="panel">
                <h3>Alert reason comparison</h3>
                <ReasonTags tags={data.evaluation.reason_codes} limit={10} />
                <p className="muted">
                  Runtime alert reason codes explain threshold and comparability risk. Diagnostics add direct evidence,
                  ruled-out alternatives, owner/actionability, approval gates, and rollback instructions.
                </p>
              </div>
            </div>
          ) : null}

          {activeTab === "Topology" ? <RuntimeLocationPanel topology={topology} data={data} /> : null}

          {activeTab === "Timeline" ? (
            <div className="panel">
              <h3>Timeline</h3>
              <div className="timeline">
                {data.timeline.map((event) => (
                  <div key={`${event.ts}-${event.label}`} className="timeline-row">
                    <span>{shortDate(event.ts)}</span>
                    <strong>{event.label}</strong>
                    <small>{event.state}</small>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {activeTab === "SQL/UDQ" ? (
            <div className="panel">
              <h3 className="heading-with-help">
                SQL and UDQ observations
                <HelpTip
                  label="SQL and UDQ help"
                  text="This view is for database investigation. Compare SQL_ID, plan hash, profile, waits, rows, and UDQ hash against prior successful runs."
                />
              </h3>
              {data.sql_observations.length === 0 ? (
                <div className="state-panel">No SQL observation is available. Run a read-only DB status query.</div>
              ) : (
                <div className="observation-grid">
                  {data.sql_observations.map((observation) => (
                    <div className="observation-card" key={observation.id}>
                      <DatabaseZap size={18} aria-hidden />
                      <div>
                        <h4>{observation.sql_id ?? "unknown SQL_ID"}</h4>
                        <p>Plan {observation.plan_hash_value ?? "n/a"} / child {observation.child_number ?? "n/a"}</p>
                        <ReasonTags tags={observation.query_shape_tags} />
                        <dl>
                          <dt>UDQ</dt>
                          <dd>{observation.udq_name ?? "n/a"}</dd>
                          <dt>UDQ hash</dt>
                          <dd>{observation.udq_hash ?? "n/a"}</dd>
                          <dt>Wait</dt>
                          <dd>{observation.top_wait_event ?? "n/a"}</dd>
                          <dt>SQL profile</dt>
                          <dd>{observation.sql_profile ?? "none"}</dd>
                        </dl>
                        {observation.index_profile_notes ? <p>{observation.index_profile_notes}</p> : null}
                        {observation.recommendation_text ? <strong>{observation.recommendation_text}</strong> : null}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}

          {activeTab === "Volumes" ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Current</th>
                    <th>Baseline</th>
                    <th>Window</th>
                    <th>Shape tags</th>
                  </tr>
                </thead>
                <tbody>
                  {data.volumes.map((volume) => (
                    <tr key={volume.id}>
                      <td>{volume.metric_name}</td>
                      <td>{compactNumber(volume.metric_value)} {volume.unit}</td>
                      <td>{compactNumber(volume.baseline_value)} {volume.unit}</td>
                      <td>{shortDate(volume.data_window_start)} - {shortDate(volume.data_window_end)}</td>
                      <td><ReasonTags tags={volume.shape_tags} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {activeTab === "Alerts" ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>State</th>
                    <th>Created</th>
                    <th>Cause</th>
                    <th>Variance</th>
                  </tr>
                </thead>
                <tbody>
                  {data.alerts.map((alert) => (
                    <tr key={alert.id}>
                      <td><StatusPill state={alert.severity} /></td>
                      <td>{alert.state}</td>
                      <td>{shortDate(alert.created_at)}</td>
                      <td>{alert.top_suspected_cause ?? "n/a"}</td>
                      <td>{pct(alert.variance_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {activeTab === "Notes" ? (
            <div className="panel">
              <h3 className="heading-with-help">
                Notes
                <HelpTip
                  label="Notes help"
                  text="Notes are operator-facing context. The payload preview shows what a Slack-style alert would include without sending real messages."
                />
              </h3>
              <p>{data.notes ?? "No notes captured for this run."}</p>
              <pre className="payload-preview">{JSON.stringify(data.evaluation.slack_payload, null, 2)}</pre>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function RuntimeLocationPanel({ topology, data }: { topology: TopologyCorrelation | null; data: RunDetail }) {
  if (!topology) {
    return <div className="state-panel">Loading runtime location...</div>;
  }
  const activeSession = topology.active_sessions[0];
  const heatScore = Number(topology.heat_summary.server_heat_score ?? 0);

  return (
    <div className="two-column">
      <div className="panel">
        <h3 className="heading-with-help">
          Runtime location
          <HelpTip
            label="Runtime location help"
            text="This tab answers where the job is running, what SQL is active, which node is hottest, and whether slowness looks job-specific, node-level, middleware-related, or unknown."
          />
        </h3>
        <div className="summary-grid topology-summary-grid">
          <Metric
            label="DB instance"
            value={topology.db_instance_node?.display_name ?? "unknown"}
            help="Confirmed when GV$SESSION.INST_ID and GV$INSTANCE.INSTANCE_NAME identify the active session placement."
          />
          <Metric
            label="DB host"
            value={topology.db_host_node?.display_name ?? "unknown"}
            help="Confirmed from the database instance host name. Raw IP addresses are not displayed."
          />
          <Metric
            label="App server"
            value={topology.app_server_node?.display_name ?? "unknown"}
            hint={topology.app_server_confidence}
            help="Usually inferred from session MACHINE/PROGRAM until WLS or OCI telemetry confirms it."
          />
          <Metric
            label="Active SQL"
            value={topology.active_sql_id ?? data.sql_id ?? "unknown"}
            hint={topology.plan_hash_value ? `plan ${topology.plan_hash_value}` : undefined}
            help="Current SQL_ID and plan hash from the active DB session when available."
          />
          <Metric
            label="Heat score"
            value={Math.round(heatScore)}
            help="0-100 pressure score from slow-job count, wait samples, SQL concentration, CPU/load, GC, and node metrics."
          />
        </div>
        <div className="callout">
          <DatabaseZap size={18} aria-hidden />
          <div>
            <strong>{topology.problem_classification.replace(/_/g, " ")}</strong>
            <p>{topology.explanation ?? "No topology explanation is available yet."}</p>
          </div>
        </div>
        <div className="observation-card topology-session-card">
          <DatabaseZap size={18} aria-hidden />
          <div>
            <h4>Active session</h4>
            <dl>
              <dt>SID / serial</dt>
              <dd>{activeSession ? `${activeSession.sid ?? "n/a"} / ${activeSession.serial_number ?? "n/a"}` : "n/a"}</dd>
              <dt>Module/action</dt>
              <dd>{activeSession ? `${activeSession.module ?? "n/a"} / ${activeSession.action ?? "n/a"}` : "n/a"}</dd>
              <dt>Wait</dt>
              <dd>{activeSession ? `${activeSession.wait_class ?? "n/a"} / ${activeSession.event ?? "n/a"}` : "n/a"}</dd>
              <dt>last_call_et</dt>
              <dd>{activeSession?.last_call_et_seconds ? `${Math.round(activeSession.last_call_et_seconds / 60)}m` : "n/a"}</dd>
              <dt>Client</dt>
              <dd>{activeSession?.client_identifier ?? "n/a"}</dd>
            </dl>
          </div>
        </div>
      </div>
      <div className="panel">
        <h3>Evidence and gaps</h3>
        <ul className="action-list">
          {topology.evidence.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        {topology.missing_inputs.length ? (
          <>
            <h4>Missing inputs</h4>
            <ul className="action-list">
              {topology.missing_inputs.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        ) : null}
        <dl>
          <dt>Recommended next query</dt>
          <dd>{topology.recommended_next_query ?? "n/a"}</dd>
          <dt>ESS request</dt>
          <dd>{topology.ess_request_id ?? "n/a"}</dd>
          <dt>Process ID</dt>
          <dd>{topology.process_id ?? "n/a"}</dd>
          <dt>ECID</dt>
          <dd>{topology.ecid ?? "n/a"}</dd>
        </dl>
        {data.latest_diagnostic ? (
          <Link className="diagnostic-inline-link" to={`/diagnostics/${data.latest_diagnostic.id}`}>
            <FileSearch size={16} aria-hidden />
            Open diagnostic report
          </Link>
        ) : null}
      </div>
    </div>
  );
}

function directlyComparable(data: RunDetail) {
  return !data.evaluation.reason_codes.some((code) =>
    ["NEW_UDQ_HASH", "NEW_SQL_ID", "SQL_PLAN_CHANGED", "CURRENT_VOLUME_GT_BASELINE", "DATA_WINDOW_MISMATCH", "VOLUME_OR_DATA_WINDOW_MISMATCH"].includes(code)
  );
}

function DbaTracePanel({ data }: { data: RunDetail }) {
  const firstObservation = data.sql_observations[0];
  return (
    <div className="panel">
      <h3 className="heading-with-help">
        DBA trace
        <HelpTip
          label="DBA trace help"
          text="Use these identifiers to correlate the app's finding with database views, ESS status, AWR/ASH samples, or read-only support SQL templates."
        />
      </h3>
      <dl>
        <dt>ESS request</dt>
        <dd>{data.ess_request_id ?? "n/a"}</dd>
        <dt>Process ID</dt>
        <dd>{data.process_id ?? "n/a"}</dd>
        <dt>API operation</dt>
        <dd>{data.api_operation ?? "n/a"}</dd>
        <dt>SQL_ID</dt>
        <dd>{firstObservation?.sql_id ?? data.sql_id ?? "n/a"}</dd>
        <dt>Plan hash</dt>
        <dd>{firstObservation?.plan_hash_value ?? data.plan_hash_value ?? "n/a"}</dd>
        <dt>UDQ hash</dt>
        <dd>{firstObservation?.udq_hash ?? data.udq_hash ?? "n/a"}</dd>
      </dl>
    </div>
  );
}
