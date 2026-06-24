import { FileSearch, Filter, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { StatusPill } from "../components/StatusPill";
import { customerPodParam, useRole } from "../context/RoleContext";
import { shortDate } from "../utils/format";

export function DiagnosticsPage() {
  const { customerPod } = useRole();
  const [filters, setFilters] = useState({ severity: "all", confidence: "all", finding_type: "all", q: "" });
  const query = useMemo(() => ({ ...customerPodParam(customerPod) }), [customerPod]);
  const { data, error, loading } = useAsync(() => api.diagnostics(query), [customerPod]);

  const reports = (data ?? []).filter((report) => {
    const top = report.top_finding ?? {};
    if (filters.severity !== "all" && top.severity !== filters.severity) return false;
    if (filters.confidence !== "all" && top.confidence !== filters.confidence) return false;
    if (filters.finding_type !== "all" && top.finding_type !== filters.finding_type) return false;
    if (filters.q) {
      const haystack = `${report.report_title} ${report.ess_request_id ?? ""} ${report.ecid ?? ""} ${report.job_name ?? ""}`.toLowerCase();
      if (!haystack.includes(filters.q.toLowerCase())) return false;
    }
    return true;
  });

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2 className="heading-with-help">
            Diagnostic Workbench
            <HelpTip
              label="Diagnostic workbench help"
              text="Diagnostics are evidence-backed RCA reports. They explain why a slow job is slow, what was ruled out, who owns next action, and what approval/rollback gates apply."
            />
          </h2>
          <p>Evidence-backed slow job reports with root-cause findings, confidence, runbooks, ruled-out alternatives, and data-quality gates.</p>
        </div>
      </div>

      <div className="filter-row">
        <label>
          <Filter size={14} aria-hidden /> Search
          <input value={filters.q} onChange={(event) => setFilters((current) => ({ ...current, q: event.target.value }))} placeholder="ESS, ECID, job" />
        </label>
        <label>
          Severity
          <select value={filters.severity} onChange={(event) => setFilters((current) => ({ ...current, severity: event.target.value }))}>
            <option value="all">All</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </label>
        <label>
          Confidence
          <select value={filters.confidence} onChange={(event) => setFilters((current) => ({ ...current, confidence: event.target.value }))}>
            <option value="all">All</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label>
          Finding
          <select value={filters.finding_type} onChange={(event) => setFilters((current) => ({ ...current, finding_type: event.target.value }))}>
            <option value="all">All</option>
            <option value="PLAN_REGRESSION">Plan regression</option>
            <option value="CODE_GENERATION_DEFECT">Code generation</option>
            <option value="SQL_HOTSPOT">SQL hotspot</option>
          </select>
        </label>
      </div>

      <LoadingState loading={loading} error={error} empty={!loading && reports.length === 0} />

      <div className="record-list">
        {reports.map((report) => {
          const top = report.top_finding ?? {};
          return (
            <Link className="record-item diagnostic-list-item" to={`/diagnostics/${report.id}`} key={report.id}>
              <FileSearch size={20} aria-hidden />
              <div>
                <span className="eyebrow">{report.customer_key} / {report.environment} / ESS {report.ess_request_id ?? "n/a"}</span>
                <h3>{report.report_title}</h3>
                <p>{report.if_you_do_one_thing_today}</p>
                <div className="card-meta">
                  <span>{report.job_name ?? "job unknown"}</span>
                  <span>{report.incident_state}</span>
                  <span>{report.overall_confidence} confidence</span>
                  <span>{shortDate(report.updated_at)}</span>
                </div>
              </div>
              <div className="record-side">
                <StatusPill state={String(top.severity ?? report.overall_status)} />
                <small>{String(top.finding_type ?? report.diagnostic_type)}</small>
                <strong>{String(top.title ?? "No top finding")}</strong>
                <span className="read-only-chip"><ShieldCheck size={12} aria-hidden /> evidence-backed</span>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
