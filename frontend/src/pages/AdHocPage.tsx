import { RadioTower, Save } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { LoadingState } from "../components/LoadingState";
import { customerPodParam, useRole } from "../context/RoleContext";
import { minutes, shortDate } from "../utils/format";

const initialForm = {
  customer_key: "CUST_A",
  environment: "PROD",
  manual_job_name: "Ad hoc CalculatePVT monitor",
  job_id: "",
  process_id: "",
  ess_request_id: "",
  sql_id: "",
  api_operation: "CalculatePVT",
  expected_minutes: "120",
  baseline_selection: "ad_hoc",
  warning_threshold_pct: "25",
  critical_threshold_pct: "75",
  destination: "#jobrun-sentinel",
  notes: ""
};

export function AdHocPage() {
  const { customerPod, customerPods } = useRole();
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];
  const [refreshToken, setRefreshToken] = useState(0);
  const { data, error, loading } = useAsync(
    () => api.adHoc(customerPodParam(customerPod)),
    [refreshToken, customerPod]
  );
  const [form, setForm] = useState(initialForm);
  const [createdRunId, setCreatedRunId] = useState<number | null>(null);

  useEffect(() => {
    if (customerPod !== "all") {
      setForm((current) => ({ ...current, customer_key: customerPod }));
    }
  }, [customerPod]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const monitor = await api.createAdHoc({
      ...form,
      job_id: form.job_id || null,
      process_id: form.process_id || null,
      ess_request_id: form.ess_request_id || null,
      sql_id: form.sql_id || null,
      expected_minutes: form.expected_minutes ? Number(form.expected_minutes) : null,
      warning_threshold_pct: Number(form.warning_threshold_pct),
      critical_threshold_pct: Number(form.critical_threshold_pct)
    });
    setCreatedRunId(monitor.run_id);
    setRefreshToken((value) => value + 1);
  }

  function field(name: keyof typeof form, label: string, type = "text") {
    return (
      <label>
        {label}
        <input
          type={type}
          value={form[name]}
          onChange={(event) => setForm((current) => ({ ...current, [name]: event.target.value }))}
        />
      </label>
    );
  }

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2>Ad Hoc Monitor Builder</h2>
          <p>{selectedPod.label}: create one-off monitors for jobs, process IDs, ESS requests, SQL_IDs, or API operations.</p>
        </div>
      </div>
      <div className="two-column">
        <form className="panel form-grid" onSubmit={submit}>
          <h3>One-off monitor</h3>
          {field("customer_key", "Customer key")}
          {field("environment", "Environment")}
          {field("manual_job_name", "Manual job name")}
          {field("job_id", "Job ID")}
          {field("process_id", "Process ID")}
          {field("ess_request_id", "ESS request ID")}
          {field("sql_id", "SQL_ID")}
          {field("api_operation", "API operation")}
          {field("expected_minutes", "Expected minutes", "number")}
          {field("warning_threshold_pct", "Warning threshold %", "number")}
          {field("critical_threshold_pct", "Critical threshold %", "number")}
          {field("destination", "Slack channel")}
          <label className="wide">
            Notes
            <textarea value={form.notes} onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))} />
          </label>
          <button className="primary-button" type="submit">
            <Save size={16} aria-hidden />
            Create monitor
          </button>
          {createdRunId ? <Link to={`/runs/${createdRunId}`} className="success-text">Open created dashboard run</Link> : null}
        </form>
        <div className="panel">
          <h3>Ad hoc monitors</h3>
          <LoadingState loading={loading} error={error} empty={!loading && (data?.length ?? 0) === 0} />
          <div className="record-list">
            {(data ?? []).map((monitor) => (
              <article key={monitor.id} className="record-item">
                <RadioTower size={18} aria-hidden />
                <div>
                  <h4>{monitor.name}</h4>
                  <p>{monitor.destination ?? "no destination"} / expires {shortDate(monitor.expires_at)}</p>
                  {monitor.run_id ? <Link to={`/runs/${monitor.run_id}`}>Run {monitor.run_id}</Link> : null}
                </div>
                <div className="record-side">
                  <strong>{minutes(monitor.expected_minutes)}</strong>
                  <small>warn {monitor.warning_threshold_pct}% / crit {monitor.critical_threshold_pct}%</small>
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
