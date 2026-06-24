import { PlugZap, PlusCircle } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { StatusPill } from "../components/StatusPill";
import { useRole } from "../context/RoleContext";
import type { CustomerPodOnboardResponse } from "../types";
import { shortDate } from "../utils/format";

export function SourcesPage() {
  const { customerPod } = useRole();
  const [refreshToken, setRefreshToken] = useState(0);
  const { data, error, loading } = useAsync(() => api.sources(), [refreshToken]);
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null);
  const defaultCustomerKey = customerPod === "all" ? "CUSTOMER_POD_01" : customerPod;
  const [form, setForm] = useState({
    customer_key: defaultCustomerKey,
    display_name: customerPod === "all" ? "Customer Pod 01" : customerPod.replace(/_/g, " "),
    environment: "PROD",
    region: "global",
    config_key: "",
    env_var_prefix: "",
    notes: "",
    apply_stock_templates: true,
    run_initial_fetch: true,
    minimum_elapsed_minutes: 120
  });
  const [onboardingResult, setOnboardingResult] = useState<CustomerPodOnboardResponse | null>(null);
  const [onboardingError, setOnboardingError] = useState<string | null>(null);
  const [onboardingLoading, setOnboardingLoading] = useState(false);

  const derivedEnvPrefix = useMemo(() => {
    const key = form.customer_key.trim().toUpperCase().replace(/[^A-Z0-9_]+/g, "_");
    const env = form.environment.trim().toUpperCase().replace(/[^A-Z0-9_]+/g, "_") || "PROD";
    return key ? `JOBRUN_ORACLE_${key}_${env}` : "JOBRUN_ORACLE_CUSTOMER_PROD";
  }, [form.customer_key, form.environment]);

  async function test(connectorType: string) {
    setTestResult(await api.testConnector(connectorType));
  }

  async function onboard(event: FormEvent) {
    event.preventDefault();
    setOnboardingError(null);
    setOnboardingLoading(true);
    try {
      const result = await api.onboardCustomerPod({
        ...form,
        env_var_prefix: form.env_var_prefix.trim() || derivedEnvPrefix,
        config_key: form.config_key.trim() || undefined,
        connector_type: "OracleDbConnector",
        minimum_elapsed_minutes: Number(form.minimum_elapsed_minutes) || 120
      });
      setOnboardingResult(result);
      setRefreshToken((value) => value + 1);
    } catch (error) {
      setOnboardingError(error instanceof Error ? error.message : "Customer pod onboarding failed.");
    } finally {
      setOnboardingLoading(false);
    }
  }

  function updateForm(key: keyof typeof form, value: string | boolean | number) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2 className="heading-with-help">
            Source Connectors
            <HelpTip
              label="Source connectors help"
              text="Connectors are where runtime, ESS, SQL, volume, and alert data come from. In local mode they are mocked; production connectors must be read-only and use environment-managed secrets."
            />
          </h2>
          <p>Mock connector health today, with extension points for Oracle DB, ESS/API, OCI telemetry, Slack, Confluence, and Jira.</p>
        </div>
      </div>
      <div className="read-only-banner">
        <strong>Read-only operating mode</strong>
        <span>
          Source connectors inspect pod status, telemetry, SQL metadata, and volume metrics. They do not perform
          customer-side writes, DDL, job control, or configuration changes.
        </span>
      </div>
      <div className="two-column">
        <form className="panel form-grid" onSubmit={onboard}>
          <h3 className="heading-with-help">
            Add customer pod
            <HelpTip
              label="Add customer pod help"
              text="Register the pod in Sentinel, attach a non-secret connector route, apply stock read-only ICM templates, and optionally run one discovery fetch. Credentials stay in environment variables or a secrets manager."
            />
          </h3>
          <label>
            Customer pod key
            <input value={form.customer_key} onChange={(event) => updateForm("customer_key", event.target.value)} />
          </label>
          <label>
            Display name
            <input value={form.display_name} onChange={(event) => updateForm("display_name", event.target.value)} />
          </label>
          <label>
            Environment
            <input value={form.environment} onChange={(event) => updateForm("environment", event.target.value)} />
          </label>
          <label>
            Region
            <input value={form.region} onChange={(event) => updateForm("region", event.target.value)} />
          </label>
          <label>
            Connector config key
            <input
              placeholder="auto-generated if blank"
              value={form.config_key}
              onChange={(event) => updateForm("config_key", event.target.value)}
            />
          </label>
          <label>
            Env var prefix
            <input
              placeholder={derivedEnvPrefix}
              value={form.env_var_prefix}
              onChange={(event) => updateForm("env_var_prefix", event.target.value)}
            />
          </label>
          <label className="wide">
            Notes
            <textarea
              value={form.notes}
              onChange={(event) => updateForm("notes", event.target.value)}
              placeholder="Optional pod routing notes. Do not paste credentials."
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={form.apply_stock_templates}
              onChange={(event) => updateForm("apply_stock_templates", event.target.checked)}
            />
            Apply bundled stock ICM templates
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={form.run_initial_fetch}
              onChange={(event) => updateForm("run_initial_fetch", event.target.checked)}
            />
            Run one read-only discovery fetch
          </label>
          <label>
            Discovery threshold minutes
            <input
              type="number"
              min={0}
              value={form.minimum_elapsed_minutes}
              onChange={(event) => updateForm("minimum_elapsed_minutes", Number(event.target.value))}
            />
          </label>
          <button className="primary-button" type="submit" disabled={onboardingLoading || !form.customer_key.trim()}>
            <PlusCircle size={16} aria-hidden />
            {onboardingLoading ? "Adding pod..." : "Add pod and apply stock templates"}
          </button>
          <p className="muted">
            This creates Sentinel routing and runs approved SELECT/WITH templates only. Add custom customer metrics or
            manual plan rows from Imports after stock discovery.
          </p>
        </form>
        <div className="panel">
          <h3>Onboarding path</h3>
          <ol className="guardrail-list">
            <li>Create or update the customer and environment scope.</li>
            <li>Store only connector routing metadata in Sentinel.</li>
            <li>Resolve credentials later from the env var prefix or secret manager.</li>
            <li>Apply stock job, history, volume, SQL, and diagnostic query templates.</li>
            <li>Upload custom metrics or manual-plan CSVs from Imports.</li>
          </ol>
          <div className="help-callout">
            <strong>No credential entry here</strong>
            <span>
              Use variables like <code>{form.env_var_prefix.trim() || derivedEnvPrefix}_USER</code>,
              <code> _PASSWORD</code>, and <code> _DSN</code> in production.
            </span>
          </div>
        </div>
      </div>
      {onboardingError ? (
        <div className="state-panel state-error">
          <strong>Pod onboarding failed</strong>
          <p>{onboardingError}</p>
        </div>
      ) : null}
      {onboardingResult ? (
        <div className="panel">
          <h3>{onboardingResult.customer.display_name} is ready for discovery</h3>
          <p>
            Connector route <strong>{onboardingResult.connector_config_key}</strong> uses env prefix{" "}
            <strong>{onboardingResult.env_var_prefix}</strong>. {onboardingResult.stock_template_ids.length} stock
            templates are available for read-only fetches.
          </p>
          <div className="button-row">
            <Link className="small-button" to="/query-templates">Review stock templates</Link>
            <Link className="small-button" to="/imports">Upload custom metrics</Link>
            <Link className="small-button" to="/dashboard">Open dashboard</Link>
          </div>
          {onboardingResult.initial_fetch ? (
            <pre className="payload-preview">{JSON.stringify(onboardingResult.initial_fetch, null, 2)}</pre>
          ) : null}
        </div>
      ) : null}
      <div className="panel">
        <h3 className="heading-with-help">
          Topology collector coverage
          <HelpTip
            label="Topology collector help"
            text="Execution topology uses read-only Oracle session and ASH-style queries first, then future WLS, OCI, Grafana, or Prometheus metrics to confirm inferred app-server and node-pressure signals."
          />
        </h3>
        <div className="connector-capability-grid">
          {[
            ["Oracle DB session placement", "available in mock / enabled by Oracle connector", "active_db_session_by_ecid_or_client_identifier"],
            ["ASH time buckets", "optional; falls back safely if unavailable", "ash_samples_by_ecid_or_sql_id"],
            ["Instance health", "available in mock / read-only production template", "instance_health_snapshot"],
            ["WLS/OCI/Grafana metrics", "future telemetry connector", "middleware pressure confirmation"],
            ["Scheduler heartbeat", "visible from connector config", "topology sync status"]
          ].map(([label, status, detail]) => (
            <div className="capability-card" key={label}>
              <strong>{label}</strong>
              <span>{status}</span>
              <small>{detail}</small>
            </div>
          ))}
        </div>
      </div>
      <LoadingState loading={loading} error={error} empty={!loading && (data?.length ?? 0) === 0} />
      <div className="connector-grid">
        {(data ?? []).map((source) => (
          <article className="connector-card" key={source.id}>
            <div className="connector-icon"><PlugZap size={20} aria-hidden /></div>
            <div>
              <span className="eyebrow">{source.connector_type}</span>
              <h3>{source.display_name ?? source.name}</h3>
              <p>{source.health_message}</p>
              <div className="card-meta">
                <StatusPill state={source.status} />
                <span>{source.config_key ?? "default"}</span>
                <span className="read-only-chip">{source.access_mode.replace("_", " ")}</span>
                <span>{source.destructive_operations_allowed ? "writes allowed" : "no destructive ops"}</span>
                <span>{source.enabled ? "enabled" : "disabled"}</span>
                <span>{shortDate(source.last_checked_at)}</span>
              </div>
              <dl className="connector-dl">
                <dt>Last success</dt>
                <dd>{shortDate(source.last_successful_sync_at)}</dd>
                <dt>Last failure</dt>
                <dd>{shortDate(source.last_failed_sync_at)}</dd>
                <dt>Scheduler</dt>
                <dd>{shortDate(source.scheduler_heartbeat_at)}</dd>
              </dl>
              <ul className="guardrail-list">
                {source.guardrails.slice(0, 4).map((guardrail) => (
                  <li key={guardrail}>{guardrail}</li>
                ))}
              </ul>
              {source.config ? <pre className="mini-preview">{JSON.stringify(source.config, null, 2)}</pre> : null}
              <button className="small-button" onClick={() => test(source.connector_type)}>
                Test
              </button>
            </div>
          </article>
        ))}
      </div>
      {testResult ? (
        <div className="panel">
          <h3 className="heading-with-help">
            Connector test result
            <HelpTip
              label="Connector test result help"
              text="A connector test confirms that the source can be reached and shows a small sample response. It should not expose passwords, PII, or raw customer SQL."
            />
          </h3>
          <pre className="payload-preview">{JSON.stringify(testResult, null, 2)}</pre>
        </div>
      ) : null}
    </section>
  );
}
