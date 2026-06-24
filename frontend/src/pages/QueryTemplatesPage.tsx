import { Database, DownloadCloud, Play, ShieldCheck, UploadCloud } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { StatusPill } from "../components/StatusPill";
import { useRole } from "../context/RoleContext";
import type { QueryTemplate } from "../types";
import { shortDate } from "../utils/format";

const defaultSql = "SELECT request_id, phase_code, status_code FROM ess_request_history WHERE request_id = :request_id";

export function QueryTemplatesPage() {
  const { customerPod } = useRole();
  const selectedCustomer = customerPod === "all" ? "CUST_A" : customerPod;
  const [refreshToken, setRefreshToken] = useState(0);
  const { data, error, loading } = useAsync(() => api.queryTemplates(), [refreshToken]);
  const { data: logs } = useAsync(() => api.queryExecutions({ limit: "8" }), [refreshToken]);
  const [category, setCategory] = useState("all");
  const [form, setForm] = useState({
    template_id: "custom_icm_status",
    name: "Custom ICM status query",
    description: "",
    source_reference: "Local MVP",
    database_type: "oracle",
    connector_type: "oracle_db",
    template_category: "diagnostic",
    sql_text: defaultSql,
    owning_team: "ICM Support",
    required_parameters: "{\"request_id\":{\"type\":\"string\"}}",
    default_parameters: "{\"request_id\":\"ESS-APJ-90045\"}",
    output_mapping: "{}"
  });
  const [result, setResult] = useState<unknown | null>(null);

  const templates = useMemo(() => {
    return (data ?? []).filter((template) => category === "all" || template.template_category === category);
  }, [category, data]);
  const categories = Array.from(new Set((data ?? []).map((template) => template.template_category))).sort();

  async function submit(event: FormEvent) {
    event.preventDefault();
    await api.createQueryTemplate({
      ...form,
      required_parameters: JSON.parse(form.required_parameters || "{}"),
      default_parameters: JSON.parse(form.default_parameters || "{}"),
      output_mapping: JSON.parse(form.output_mapping || "{}"),
      active: true
    });
    setRefreshToken((value) => value + 1);
  }

  async function importCatalog() {
    setResult(await api.importQueryCatalog());
    setRefreshToken((value) => value + 1);
  }

  async function validate(template: QueryTemplate) {
    setResult(await api.validateQueryTemplate(template.id));
    setRefreshToken((value) => value + 1);
  }

  async function execute(template: QueryTemplate) {
    setResult(await api.executeQueryTemplate(template.id, {
      customer_key: selectedCustomer,
      environment: "PROD",
      parameters: template.default_parameters ?? {},
      executed_by: "operator"
    }));
    setRefreshToken((value) => value + 1);
  }

  async function ingest(template: QueryTemplate) {
    setResult(await api.ingestQueryTemplate(template.id, {
      customer_key: selectedCustomer,
      environment: "PROD",
      parameters: template.default_parameters ?? {},
      executed_by: "operator",
      initiated_by: "user"
    }));
    setRefreshToken((value) => value + 1);
  }

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2 className="heading-with-help">
            SQL Template Registry
            <HelpTip
              label="SQL template registry help"
              text="Register approved read-only SQL, validate it, preview small samples, and ingest mapped rows into canonical JobRun, VolumeSnapshot, and SQL observation records."
            />
          </h2>
          <p>Read-only Oracle query templates, output mappings, execution audit logs, and bundled ICM catalog import.</p>
        </div>
        <div className="button-row">
          <button className="small-button" type="button" onClick={importCatalog}>
            <DownloadCloud size={14} aria-hidden /> Import bundled catalog
          </button>
          <button className="small-button" type="button" onClick={async () => setResult(await api.syncRunOnce())}>
            <UploadCloud size={14} aria-hidden /> Run sync once
          </button>
        </div>
      </div>

      <div className="two-column">
        <form className="panel form-grid" onSubmit={submit}>
          <h3 className="heading-with-help">
            Register template
            <HelpTip
              label="Register template help"
              text="Only SELECT/WITH SQL with named bind parameters is accepted. Destructive SQL is blocked before execution."
            />
          </h3>
          {(["template_id", "name", "source_reference", "database_type", "connector_type", "template_category", "owning_team"] as const).map((name) => (
            <label key={name}>
              {name.replace("_", " ")}
              <input value={form[name]} onChange={(event) => setForm((current) => ({ ...current, [name]: event.target.value }))} />
            </label>
          ))}
          <label className="wide">
            Description
            <textarea value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} />
          </label>
          <label className="wide">
            SQL text
            <textarea value={form.sql_text} onChange={(event) => setForm((current) => ({ ...current, sql_text: event.target.value }))} />
          </label>
          <label className="wide">
            Required parameters JSON
            <textarea value={form.required_parameters} onChange={(event) => setForm((current) => ({ ...current, required_parameters: event.target.value }))} />
          </label>
          <label className="wide">
            Default parameters JSON
            <textarea value={form.default_parameters} onChange={(event) => setForm((current) => ({ ...current, default_parameters: event.target.value }))} />
          </label>
          <label className="wide">
            Output mapping JSON
            <textarea value={form.output_mapping} onChange={(event) => setForm((current) => ({ ...current, output_mapping: event.target.value }))} />
          </label>
          <button className="primary-button" type="submit">
            <Database size={16} aria-hidden /> Register template
          </button>
        </form>

        <div className="panel">
          <div className="section-header compact-header">
            <h3>Published templates</h3>
            <label>
              Category
              <select value={category} onChange={(event) => setCategory(event.target.value)}>
                <option value="all">All</option>
                {categories.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
          </div>
          <LoadingState loading={loading} error={error} empty={!loading && templates.length === 0} />
          <div className="record-list">
            {templates.map((template) => (
              <article key={template.id} className="record-item">
                <div>
                  <span className="eyebrow">{template.template_category} / {template.template_id}</span>
                  <h4>{template.name}</h4>
                  <p>{template.description ?? template.source_reference}</p>
                  <small>validated {shortDate(template.last_validated_at)} / executed {shortDate(template.last_executed_at)}</small>
                  <pre className="mini-preview">{JSON.stringify(template.output_mapping, null, 2)}</pre>
                </div>
                <div className="record-side">
                  <StatusPill state={template.is_read_only_validated ? "validated" : template.validation_error ? "critical" : "inactive"} />
                  <button className="small-button" onClick={() => validate(template)}>
                    <ShieldCheck size={14} aria-hidden /> Validate
                  </button>
                  <button className="small-button" onClick={() => execute(template)}>
                    <Play size={14} aria-hidden /> Preview
                  </button>
                  <button className="small-button" onClick={() => ingest(template)}>
                    <UploadCloud size={14} aria-hidden /> Ingest
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>

      <div className="two-column">
        <div className="panel">
          <h3>Recent execution logs</h3>
          <div className="record-list">
            {(logs ?? []).map((log) => (
              <article key={log.id} className="record-item">
                <div>
                  <span className="eyebrow">{log.query_execution_id ?? `log-${log.id}`}</span>
                  <h4>{log.status}</h4>
                  <p>{log.row_count} rows / {log.elapsed_ms ?? 0} ms / {log.connector_config_key ?? "default"}</p>
                  {log.sanitized_error_message ? <small>{log.sanitized_error_message}</small> : null}
                </div>
                <div className="record-side">
                  <StatusPill state={log.status} />
                  <small>{shortDate(log.started_at)}</small>
                </div>
              </article>
            ))}
          </div>
        </div>
        {result ? (
          <div className="panel">
            <h3>Latest action result</h3>
            <pre className="payload-preview">{JSON.stringify(result, null, 2)}</pre>
          </div>
        ) : null}
      </div>
    </section>
  );
}
