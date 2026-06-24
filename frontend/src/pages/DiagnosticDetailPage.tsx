import { AlertTriangle, BookOpenCheck, FileSearch, RefreshCw, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { Metric } from "../components/Metric";
import { ReasonTags } from "../components/ReasonTags";
import { StatusPill } from "../components/StatusPill";
import type { DiagnosticFinding, DiagnosticReport, GlossaryTerm } from "../types";
import { compactNumber, shortDate } from "../utils/format";

export function DiagnosticDetailPage() {
  const { id } = useParams();
  const [refreshToken, setRefreshToken] = useState(0);
  const { data, error, loading } = useAsync(() => api.diagnostic(id ?? ""), [id, refreshToken]);
  const { data: glossary } = useAsync(() => api.glossary(), []);
  const [actionResult, setActionResult] = useState<unknown | null>(null);

  async function refreshReport() {
    if (!data) return;
    setActionResult(await api.refreshDiagnostic(data.id));
    setRefreshToken((value) => value + 1);
  }

  async function promoteAlert(findingId: number) {
    if (!data) return;
    setActionResult(await api.promoteDiagnosticToAlert(data.id, findingId));
  }

  async function promotePlaybook(findingId: number) {
    if (!data) return;
    setActionResult(await api.promoteDiagnosticToPlaybook(data.id, findingId));
  }

  return (
    <section className="page-stack">
      <LoadingState loading={loading} error={error} empty={!loading && !data} />
      {data ? (
        <>
          <DiagnosticHeader report={data} onRefresh={refreshReport} />
          <div className="incident-banner">
            <AlertTriangle size={18} aria-hidden />
            <div>
              <strong>{data.incident_state === "active" ? "Incident active" : "Incident not confirmed active"}</strong>
              <span>
                Freshness {data.freshness_status}. Snapshot {shortDate(data.snapshot_start_at)} - {shortDate(data.snapshot_end_at)}.
              </span>
            </div>
          </div>
          <div className="one-thing">
            <strong>If you do only one thing today</strong>
            <p>{data.if_you_do_one_thing_today}</p>
          </div>
          <MetricStrip report={data} />

          <section className="diagnostic-section">
            <h3 className="heading-with-help">
              Root-cause findings
              <HelpTip
                label="Root-cause finding help"
                text="Each finding shows confidence, evidence, what to do, who owns it, approval gate, rollback, and stop/re-check condition."
              />
            </h3>
            <div className="finding-grid">
              {data.findings.map((finding) => (
                <FindingCard
                  key={finding.id}
                  finding={finding}
                  onPromoteAlert={() => promoteAlert(finding.id)}
                  onPromotePlaybook={() => promotePlaybook(finding.id)}
                />
              ))}
            </div>
          </section>

          <div className="two-column">
            <RuledOutPanel report={data} />
            <DataQualityPanel report={data} />
          </div>
          <GlossaryPanel terms={glossary ?? []} />
          {actionResult ? (
            <div className="panel">
              <h3>Latest action result</h3>
              <pre className="payload-preview">{JSON.stringify(actionResult, null, 2)}</pre>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function DiagnosticHeader({ report, onRefresh }: { report: DiagnosticReport; onRefresh: () => void }) {
  return (
    <div className="detail-hero diagnostic-hero">
      <div>
        <span className="eyebrow">{report.customer_key} / {report.environment} / {report.diagnostic_type}</span>
        <h2>{report.report_title}</h2>
        <p>{report.job_definition}</p>
        <div className="diagnostic-header-grid">
          <span>ESS {report.ess_request_id ?? "n/a"}</span>
          <span>ECID {report.ecid ?? "n/a"}</span>
          <span>Client {report.client_identifier ?? "n/a"}</span>
          <span>RAC {report.rac_cluster_size ?? "n/a"} instances</span>
          <span>{report.collector_name} {report.collector_version}</span>
        </div>
      </div>
      <div className="hero-actions">
        <StatusPill state={report.overall_status} />
        {report.run_id ? <Link className="small-button" to={`/runs/${report.run_id}`}>Run</Link> : null}
        <button className="primary-button" onClick={onRefresh}>
          <RefreshCw size={16} aria-hidden /> Refresh
        </button>
      </div>
    </div>
  );
}

function MetricStrip({ report }: { report: DiagnosticReport }) {
  const summary = report.executive_summary ?? {};
  return (
    <div className="summary-grid">
      <Metric label="Root causes" value={String(summary.root_cause_count ?? report.findings.length)} help="Number of primary root-cause findings in this diagnostic." />
      <Metric label="Plan factor" value={`${summary.plan_regression_factor ?? "n/a"}x`} help="Approximate current plan cost factor versus historical good plan." />
      <Metric label="Live runtime" value={`${summary.live_runtime_hours ?? "n/a"}h`} help="Live database call runtime when collected." />
      <Metric label="Executions" value={compactNumber(Number(summary.bottleneck_executions ?? 0))} help="Bottleneck SQL cumulative executions." />
      <Metric label="Confirmed packages" value={compactNumber(Number(summary.confirmed_formula_packages ?? 0))} help="Packages directly confirmed by source evidence." />
      <Metric label="Potential refs" value={compactNumber(Number(summary.potential_formula_references ?? 0))} help="Potential references are not confirmed affected packages." />
    </div>
  );
}

function FindingCard({
  finding,
  onPromoteAlert,
  onPromotePlaybook
}: {
  finding: DiagnosticFinding;
  onPromoteAlert: () => void;
  onPromotePlaybook: () => void;
}) {
  const tags = [finding.finding_type, finding.lifecycle, finding.actionability, finding.confidence];
  return (
    <article className="finding-card">
      <div className="finding-card-top">
        <div>
          <span className="eyebrow">Finding {finding.finding_number} / {finding.finding_key}</span>
          <h4>{finding.title}</h4>
        </div>
        <StatusPill state={finding.severity} />
      </div>
      <ReasonTags tags={tags} limit={6} />
      <div className="finding-body">
        <strong>Plain-English problem</strong>
        <p>{finding.problem_statement}</p>
        <strong>Business impact</strong>
        <p>{finding.business_impact}</p>
        <strong>Technical detail</strong>
        <p>{finding.technical_detail}</p>
        <strong>What to do now</strong>
        <p>{finding.recommended_action}</p>
      </div>
      <div className="finding-metrics">
        {finding.metric_rows.map((metric) => (
          <Metric key={metric.id} label={metric.label} value={metric.value_numeric ?? metric.value_text ?? "n/a"} hint={metric.unit ?? undefined} />
        ))}
      </div>
      <details className="evidence-details">
        <summary>Show full evidence & ruled-out alternatives</summary>
        <div className="evidence-list">
          {finding.evidence.map((evidence) => (
            <article key={evidence.id} className="evidence-card">
              <span className="eyebrow">{evidence.evidence_type}</span>
              <h5>{evidence.title}</h5>
              <p>{evidence.evidence_summary}</p>
              <small>Template {evidence.query_template_id ?? "n/a"} / execution {evidence.query_execution_id ?? "n/a"}</small>
              <pre className="mini-preview">{JSON.stringify(evidence.raw_sample, null, 2)}</pre>
            </article>
          ))}
          {finding.ruled_out_alternatives.map((alternative) => (
            <div key={alternative.id} className="ruleout-row">
              <StatusPill state={alternative.status} />
              <strong>{alternative.alternative_type}</strong>
              <span>{alternative.reason}</span>
            </div>
          ))}
        </div>
      </details>
      <div className="runbook-grid">
        {finding.runbook_steps.map((step) => (
          <div key={step.id} className="runbook-card">
            <span className="eyebrow">{step.step_number}. {step.step_type}</span>
            <strong>{step.title}</strong>
            <p>{step.body}</p>
            {step.command_text ? <pre className="mini-preview">{step.command_text}</pre> : null}
            <small>{step.executable_by_app ? "Executable by app" : "Text-only"} / {step.requires_approval ? `Approval: ${step.approval_role ?? "required"}` : "No approval required"}</small>
          </div>
        ))}
      </div>
      <div className="approval-grid">
        <div><strong>Expected result</strong><p>{finding.expected_result}</p></div>
        <div><strong>Approval gate</strong><p>{finding.approval_gate}</p></div>
        <div><strong>Owner</strong><p>{finding.owner_team}</p></div>
        <div><strong>Risk</strong><p>{finding.risk_if_done_wrong}</p></div>
        <div><strong>Rollback</strong><p>{finding.rollback_plan}</p></div>
        <div><strong>Stop/re-check</strong><p>{finding.stop_recheck_condition}</p></div>
      </div>
      <div className="button-row">
        <button className="small-button" onClick={onPromoteAlert}>
          <ShieldCheck size={14} aria-hidden /> Promote alert
        </button>
        <button className="small-button" onClick={onPromotePlaybook}>
          <BookOpenCheck size={14} aria-hidden /> Playbook note
        </button>
      </div>
    </article>
  );
}

function RuledOutPanel({ report }: { report: DiagnosticReport }) {
  return (
    <div className="panel">
      <h3>Ruled out / no action</h3>
      <div className="record-list">
        {report.ruled_out_alternatives.map((alternative) => (
          <div className="ruleout-row" key={alternative.id}>
            <StatusPill state={alternative.status} />
            <strong>{alternative.alternative_type}</strong>
            <span>{alternative.reason}</span>
            <small>{alternative.supporting_evidence}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

function DataQualityPanel({ report }: { report: DiagnosticReport }) {
  return (
    <div className="panel">
      <h3>Data-quality gate</h3>
      <div className="record-list">
        {report.data_quality_checks.map((check) => (
          <div className="quality-row" key={check.id}>
            <StatusPill state={check.status} />
            <div>
              <strong>{check.description}</strong>
              <p>{check.message}</p>
              <small>{check.evidence_count} evidence rows</small>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function GlossaryPanel({ terms }: { terms: GlossaryTerm[] }) {
  const visibleTerms = useMemo(() => terms.slice(0, 12), [terms]);
  return (
    <details className="panel glossary-panel">
      <summary>
        <FileSearch size={16} aria-hidden /> Terms and glossary
      </summary>
      <div className="glossary-grid">
        {visibleTerms.map((term) => (
          <div key={term.id}>
            <strong>{term.term}</strong>
            <p>{term.definition}</p>
          </div>
        ))}
      </div>
    </details>
  );
}
