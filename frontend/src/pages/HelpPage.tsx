import { AlertTriangle, BookOpenCheck, Database, FileSearch, Gauge, PlayCircle, ShieldCheck, Users } from "lucide-react";

import { StatusPill } from "../components/StatusPill";
import { useRole } from "../context/RoleContext";

const sections = [
  { id: "start", label: "Start Here" },
  { id: "scope", label: "Customer Pods" },
  { id: "roles", label: "Role Views" },
  { id: "dashboard", label: "Dashboard" },
  { id: "executive-summary", label: "Exec Summary" },
  { id: "metrics", label: "Metrics" },
  { id: "run-detail", label: "Run Detail" },
  { id: "diagnostics", label: "Diagnostics" },
  { id: "alerts", label: "Alerts" },
  { id: "data", label: "Seed Data" },
  { id: "connectors", label: "Connectors" },
  { id: "resilience", label: "Resilience" },
  { id: "developer", label: "Developer Notes" },
  { id: "security", label: "Security" }
];

export function HelpPage() {
  const { config, customerPod, customerPods } = useRole();
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2>Help</h2>
          <p>Read this guide when you want the full context behind the dashboard, metrics, alerts, and role views.</p>
        </div>
      </div>

      <div className="help-layout">
        <aside className="help-toc">
          <span className="eyebrow">Guide</span>
          {sections.map((section) => (
            <a href={`#${section.id}`} key={section.id}>
              {section.label}
            </a>
          ))}
        </aside>

        <div className="help-content">
          <section id="start" className="help-section">
            <div className="help-section-title">
              <PlayCircle size={20} aria-hidden />
              <h3>Start Here</h3>
            </div>
            <p>
              JobRun Sentinel watches important Oracle enterprise jobs, compares current runtime against the right
              baseline, and explains why a job is normal, risky, slow, or still in learning mode.
            </p>
            <div className="help-callout">
              <strong>Your current view: {config.label}</strong>
              <span>{config.help}</span>
            </div>
            <ol>
              <li>Choose a customer pod from the left panel.</li>
              <li>Open Dashboard for the live operations summary, execution topology, and server-time heat map.</li>
              <li>Filter by state or role-relevant workflow.</li>
              <li>Use Expand on a tile for quick context.</li>
              <li>Use Explore to drill into the run detail page.</li>
            </ol>
          </section>

          <section id="scope" className="help-section">
            <div className="help-section-title">
              <Users size={20} aria-hidden />
              <h3>Customer Pods</h3>
            </div>
            <p>
              The customer pod selector in the left panel controls the scope of the app. Select Demo Customer 1,
              Demo Customer 2, or another pod when you want every page to focus on one customer instead of the full
              scale-test dataset.
            </p>
            <div className="help-callout">
              <strong>Current pod: {selectedPod.label}</strong>
              <span>{selectedPod.description}</span>
            </div>
            <p>
              Dashboard, Runs, Expectations, Alerts, Ad Hoc monitors, Imports, and Playbook views all honor the
              selected pod. Source health and query templates remain shared admin views, but query execution defaults
              to the selected pod when a specific customer is selected.
            </p>
            <p>
              Add a new pod from Sources. The onboarding flow creates the local customer scope, attaches a non-secret
              connector route, applies stock read-only ICM templates, and can run one discovery fetch. Use Imports next
              for custom metrics, manual plan rows, or customer-specific fields not covered by stock templates.
            </p>
          </section>

          <section id="roles" className="help-section">
            <div className="help-section-title">
              <Users size={20} aria-hidden />
              <h3>Role Views</h3>
            </div>
            <div className="help-card-grid">
              <article>
                <h4>Executive</h4>
                <p>Single pane of glass: customer risk, top risks, critical jobs, and high-level suspected causes.</p>
              </article>
              <article>
                <h4>Operator</h4>
                <p>Support workflow: alerts, acknowledgements, ad hoc monitors, imports, reason codes, and next actions.</p>
              </article>
              <article>
                <h4>DBA</h4>
                <p>Investigation workflow: SQL_ID, plan hash, UDQ hash, waits, source health, and read-only query templates.</p>
              </article>
            </div>
          </section>

          <section id="dashboard" className="help-section">
            <div className="help-section-title">
              <Gauge size={20} aria-hidden />
              <h3>Dashboard</h3>
            </div>
            <p>
              The dashboard starts with operations counts and job cards, then adds a true runtime map. The job cards are
              the Runtime summary; they summarize customer, environment, job, elapsed time, expected time, variance, and
              likely causes.
            </p>
            <p>
              Execution topology connects a selected run to ESS/API, inferred app or WLS server, confirmed DB instance
              and host, active DB session, SQL_ID, plan hash, wait class, and wait event. The server-time heat map is the
              actual heat map: rows are nodes, columns are time buckets, and cells show pressure from slow jobs, waits,
              SQL concentration, CPU/load, GC, and node metrics when available.
            </p>
            <div className="status-help-grid">
              <div><StatusPill state="normal" /><span>Within expected runtime.</span></div>
              <div><StatusPill state="watch" /><span>Approaching risk; keep an eye on it.</span></div>
              <div><StatusPill state="warning" /><span>Past warning threshold; review next action.</span></div>
              <div><StatusPill state="critical" /><span>Past critical threshold or severe ETA/progress risk.</span></div>
              <div><StatusPill state="unknown_baseline" /><span>No reliable baseline yet; learning mode.</span></div>
            </div>
            <p>
              Click a hot server-time cell to focus the runtime summary on the contributing jobs and SQL_IDs. The
              Elapsed vs Expected panel remains a supporting chart for runtime variance.
            </p>
          </section>

          <section id="executive-summary" className="help-section">
            <div className="help-section-title">
              <BookOpenCheck size={20} aria-hidden />
              <h3>Executive Summary</h3>
            </div>
            <p>
              Customer pages show a concise critical-event summary at the top of the dashboard. It appears only when a
              specific customer pod is selected, because the all-customer view is intended for triage and capacity
              scanning rather than a customer-ready update.
            </p>
            <p>
              Each bullet emphasizes what matters for a runtime status call: job name, start time, elapsed vs expected,
              likely issue, and proposed solution. Use <strong>Explore run</strong> for diagnostics, topology,
              SQL/UDQ evidence, alert history, and the full recommendation.
            </p>
            <div className="help-callout">
              <strong>Developer contract</strong>
              <span>
                The backend owns summary synthesis through <code>GET /api/customers/&lt;customer_key&gt;/executive-summary</code>.
                Frontend code should keep this panel brief and route detailed evidence to the run detail page.
              </span>
            </div>
          </section>

          <section id="metrics" className="help-section">
            <div className="help-section-title">
              <BookOpenCheck size={20} aria-hidden />
              <h3>Metrics</h3>
            </div>
            <dl className="help-dl">
              <dt>Elapsed</dt>
              <dd>How long the job has run so far, or total duration if complete.</dd>
              <dt>Expected</dt>
              <dd>The selected baseline from a manual expectation or historical runtime model.</dd>
              <dt>Variance</dt>
              <dd>Percent above or below expected runtime. Positive means slower than expected.</dd>
              <dt>ETA</dt>
              <dd>Estimated completion time based on expected runtime or reported progress.</dd>
              <dt>Confidence</dt>
              <dd>How much the app trusts the comparison. Low confidence often means new scale or changed inputs.</dd>
            </dl>
          </section>

          <section id="run-detail" className="help-section">
            <div className="help-section-title">
              <Database size={20} aria-hidden />
              <h3>Run Detail</h3>
            </div>
            <p>
              Run detail explains why a job is flagged. The Overview tab shows the main reason and recommended next
              actions. Topology shows where the run is executing, what SQL is active, and whether the strongest signal is
              job-specific, node-level, middleware-related, or unknown. SQL/UDQ shows database evidence. Volumes shows
              business data shape. Alerts shows workflow history.
            </p>
            <p>
              For the APJ sample incident, the tool highlights runtime breach, volume/data-window drift, new SQL_ID,
              plan change, and changed customer-authored UDQ hash.
            </p>
          </section>

          <section id="diagnostics" className="help-section">
            <div className="help-section-title">
              <FileSearch size={20} aria-hidden />
              <h3>Diagnostics</h3>
            </div>
            <p>
              Diagnostics are evidence-backed RCA reports. They are different from alerts: an alert says a job crossed
              a runtime threshold, while a diagnostic explains likely root cause, evidence, confidence, ruled-out
              alternatives, owner, approval gate, rollback, and stop/re-check condition.
            </p>
            <p>
              Use the Diagnostics tab on a run to generate a report, or open the Diagnostics page from the left panel.
              The seeded ESS 13729027 report demonstrates plan regression and generated formula cache-defect findings.
            </p>
            <p>
              Remediation commands shown in diagnostics are text-only runbook guidance. JobRun Sentinel never executes
              DBMS_STATS, DBMS_SPM, PL/SQL, DDL, DML, or package recompiles against a customer pod.
            </p>
          </section>

          <section id="alerts" className="help-section">
            <div className="help-section-title">
              <AlertTriangle size={20} aria-hidden />
              <h3>Alerts</h3>
            </div>
            <p>
              Alerts are created when a run crosses a warning or critical threshold, has an ETA breach, appears stuck,
              or becomes hard to compare because SQL, plan, UDQ, or volume changed.
            </p>
            <ul>
              <li>Acknowledge means someone is actively looking.</li>
              <li>Resolve means the runtime risk is closed.</li>
              <li>Mock Slack payloads show what would be sent without using real Slack credentials.</li>
            </ul>
          </section>

          <section id="data" className="help-section">
            <div className="help-section-title">
              <BookOpenCheck size={20} aria-hidden />
              <h3>Seed Data</h3>
            </div>
            <p>
              The local MVP includes synthetic Customer A and Customer B examples plus scale-test customers
              <code> DEMO_CUST_01 </code> through <code> DEMO_CUST_10 </code>. Each demo customer has 25 active jobs.
            </p>
            <pre className="help-command">DATABASE_URL=sqlite:///./jobrun_sentinel.db .venv/bin/python -m app.seed --scale --scale-customers 10 --scale-jobs-per-customer 25</pre>
          </section>

          <section id="connectors" className="help-section">
            <div className="help-section-title">
              <Database size={20} aria-hidden />
              <h3>Connectors</h3>
            </div>
            <p>
              Local connectors are mocked. Production connectors are intended for Oracle DB, ESS/API, OCI telemetry,
              SQL observations, volume snapshots, Slack, and Confluence query catalogs.
            </p>
            <div className="help-card-grid">
              <article>
                <h4>1. Establish</h4>
                <p>
                  Create a read-only source account, add secrets to the production secret store or environment, then add
                  a <code>ConnectorConfig</code> row that routes a customer/environment to an env var prefix such as
                  <code> JOBRUN_ORACLE_PROD1</code>.
                </p>
              </article>
              <article>
                <h4>2. Validate</h4>
                <p>
                  Use Sources health, <code>connector-health</code>, and template validation before enabling scheduled
                  sync. Templates must pass the SELECT/WITH-only guardrail and use named bind parameters.
                </p>
              </article>
              <article>
                <h4>3. Operate</h4>
                <p>
                  Run a one-time sync, confirm query execution logs, then enable scheduler polling. Update secrets or
                  routing without storing passwords, DSNs, wallet passwords, or raw customer SQL in Sentinel.
                </p>
              </article>
            </div>
            <p>
              Query templates must be read-only, parameterized, timeout-protected, and audited. Results store metadata
              and small samples, not large customer data extracts.
            </p>
            <p>
              Sentinel may store local analysis results, baselines, notes, and acknowledgements in its own database.
              Those internal records do not change the target customer pod.
            </p>
            <div className="help-callout">
              <strong>Production updates</strong>
              <span>
                Rotate credentials in the secret manager or environment and restart the backend. Change customer routing
                in <code>ConnectorConfig</code>. Disable a connector by setting the config inactive or by turning off
                Oracle connector mode.
              </span>
            </div>
            <p>
              The Sources page includes Add customer pod for production onboarding. Start with stock templates for job
              status, history, volume, SQL, UDQ, and diagnostics. Then upload custom metrics from Imports when a customer
              deployment has UDQs, fields, or business metrics that are not covered by the stock catalog.
            </p>
          </section>

          <section id="resilience" className="help-section">
            <div className="help-section-title">
              <ShieldCheck size={20} aria-hidden />
              <h3>Resilience</h3>
            </div>
            <p>
              Pages refresh data in place. Auto-refresh should update panels and heat-map cells without forcing a full
              browser reload, so selected customer context and drill-down state remain stable.
            </p>
            <p>
              If an API request fails, the app shows a retry path and a dashboard link. If a render bug occurs, the
              application error boundary catches it and keeps a dashboard escape hatch visible.
            </p>
            <ul>
              <li>For operators: retry the panel, then use Dashboard if the view remains unavailable.</li>
              <li>
                For developers: check the failing endpoint, backend stack trace, and browser console before changing UI
                state handling.
              </li>
              <li>
                A diagnostic report may exist before findings are attached; dashboard and back-button flows must handle
                that partial state safely.
              </li>
            </ul>
          </section>

          <section id="developer" className="help-section">
            <div className="help-section-title">
              <Database size={20} aria-hidden />
              <h3>Developer Notes</h3>
            </div>
            <p>
              These are the main local commands and ownership points for future changes. Keep connector calls
              non-destructive, keep executive copy concise, and place investigation detail in Explore run or Diagnostics.
            </p>
            <pre className="help-command">cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000</pre>
            <pre className="help-command">cd frontend && npm run dev</pre>
            <pre className="help-command">cd backend && .venv/bin/python -m pytest app/tests/test_baseline_evaluation.py</pre>
            <pre className="help-command">cd frontend && npm test && npm run build</pre>
            <div className="help-card-grid">
              <article>
                <h4>Backend services</h4>
                <p>
                  <code>evaluation.py</code> sets runtime state, reason codes, and recommendations.
                  <code> executive_summary.py</code> synthesizes customer status bullets.
                  <code> topology.py</code> builds execution topology and server-time heat.
                  <code> query_execution.py</code> validates, executes, logs, and ingests query-template results.
                </p>
              </article>
              <article>
                <h4>API and UI</h4>
                <p>
                  <code>router.py</code> maps services to REST responses.
                  <code> DashboardPage.tsx</code> owns the dashboard layout and heat-map drill-down.
                  <code> useAsync.ts</code> keeps prior data visible during polling.
                </p>
              </article>
              <article>
                <h4>Recovery paths</h4>
                <p>
                  <code>client.ts</code> normalizes API errors.
                  <code> LoadingState.tsx</code> renders retry/dashboard actions.
                  <code> AppErrorBoundary.tsx</code> catches render failures at the route level.
                </p>
              </article>
            </div>
            <p>
              Recent regression coverage includes dashboard tolerance for diagnostic reports without findings, which
              protects browser back/forward navigation when background data changes between visits.
            </p>
          </section>

          <section id="security" className="help-section">
            <div className="help-section-title">
              <ShieldCheck size={20} aria-hidden />
              <h3>Security</h3>
            </div>
            <ul>
              <li>Source database and pod access must be read-only.</li>
              <li>No connector may perform DML, DDL, job control, deployment, or customer-side configuration changes.</li>
              <li>Secrets must come from environment variables or a secrets manager.</li>
              <li>Slack alerts must avoid PII and raw SQL text.</li>
              <li>Raw SQL/query text storage is disabled by default.</li>
              <li>AI analysis, when enabled, receives sanitized metrics and metadata and returns recommendations only.</li>
              <li>Query executions and alert acknowledgements are audit logged.</li>
            </ul>
          </section>
        </div>
      </div>
    </section>
  );
}
