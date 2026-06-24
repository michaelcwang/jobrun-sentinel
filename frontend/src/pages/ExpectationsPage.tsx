import { Save } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { LoadingState } from "../components/LoadingState";
import { StatusPill } from "../components/StatusPill";
import { customerPodParam, useRole } from "../context/RoleContext";
import { minutes } from "../utils/format";

const emptyForm = {
  customer_key: "CUST_A",
  environment: "PROD",
  job_family: "ICM Calculation",
  job_type: "CalculatePVT",
  job_name: "",
  region: "",
  workstream: "",
  baseline_method: "manual_goal",
  expected_minutes: "350",
  warning_threshold_pct: "25",
  critical_threshold_pct: "75",
  customer_goal_minutes: "",
  minimum_history_count: "5",
  confidence_score: "0.6",
  owner: "ICM Support",
  alert_channel: "#jobrun-sentinel",
  notes: "",
  risk_assumptions: ""
};

export function ExpectationsPage() {
  const { customerPod, customerPods } = useRole();
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];
  const [refreshToken, setRefreshToken] = useState(0);
  const { data, error, loading } = useAsync(
    () => api.expectations(customerPodParam(customerPod)),
    [refreshToken, customerPod]
  );
  const [form, setForm] = useState(emptyForm);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (customerPod !== "all") {
      setForm((current) => ({ ...current, customer_key: customerPod }));
    }
  }, [customerPod]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await api.createExpectation({
      ...form,
      region: form.region || null,
      workstream: form.workstream || null,
      expected_minutes: Number(form.expected_minutes),
      warning_threshold_pct: Number(form.warning_threshold_pct),
      critical_threshold_pct: Number(form.critical_threshold_pct),
      customer_goal_minutes: form.customer_goal_minutes ? Number(form.customer_goal_minutes) : null,
      minimum_history_count: Number(form.minimum_history_count),
      confidence_score: Number(form.confidence_score)
    });
    setMessage("Expectation record created.");
    setRefreshToken((value) => value + 1);
    setForm({ ...emptyForm, customer_key: customerPod === "all" ? emptyForm.customer_key : customerPod });
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
          <h2>Expectation Records</h2>
          <p>{selectedPod.label}: create manual goals or imported-plan baselines for the selected customer scope.</p>
        </div>
      </div>
      <div className="two-column">
        <form className="panel form-grid" onSubmit={submit}>
          <h3>Create expectation</h3>
          {field("customer_key", "Customer key")}
          {field("environment", "Environment")}
          {field("job_family", "Job family")}
          {field("job_type", "Job type")}
          {field("job_name", "Job name")}
          {field("region", "Region")}
          {field("workstream", "Workstream")}
          <label>
            Baseline method
            <select
              value={form.baseline_method}
              onChange={(event) => setForm((current) => ({ ...current, baseline_method: event.target.value }))}
            >
              <option>manual_goal</option>
              <option>historical_p50_p90</option>
              <option>volume_adjusted</option>
              <option>imported_plan</option>
              <option>ad_hoc</option>
            </select>
          </label>
          {field("expected_minutes", "Expected minutes", "number")}
          {field("warning_threshold_pct", "Warning threshold %", "number")}
          {field("critical_threshold_pct", "Critical threshold %", "number")}
          {field("customer_goal_minutes", "Customer goal minutes", "number")}
          {field("minimum_history_count", "Minimum history count", "number")}
          {field("confidence_score", "Confidence score", "number")}
          {field("owner", "Owner")}
          {field("alert_channel", "Alert channel")}
          <label className="wide">
            Notes
            <textarea value={form.notes} onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))} />
          </label>
          <label className="wide">
            Risk assumptions
            <textarea
              value={form.risk_assumptions}
              onChange={(event) => setForm((current) => ({ ...current, risk_assumptions: event.target.value }))}
            />
          </label>
          <button className="primary-button" type="submit">
            <Save size={16} aria-hidden />
            Save expectation
          </button>
          {message ? <p className="success-text">{message}</p> : null}
        </form>
        <div className="panel">
          <h3>Active records</h3>
          <LoadingState loading={loading} error={error} empty={!loading && (data?.length ?? 0) === 0} />
          <div className="record-list">
            {(data ?? []).map((record) => (
              <article key={record.id} className="record-item">
                <div>
                  <span className="eyebrow">{record.customer_key} / {record.environment}</span>
                  <h4>{record.job_name ?? record.job_type ?? "Wildcard expectation"}</h4>
                  <p>{record.region ?? "any region"} / {record.workstream ?? "any workstream"}</p>
                </div>
                <div className="record-side">
                  <StatusPill state={record.baseline_method} />
                  <strong>{minutes(record.expected_minutes)}</strong>
                  <small>{Math.round(record.confidence_score * 100)}% confidence</small>
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
