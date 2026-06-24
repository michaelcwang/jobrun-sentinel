import { Upload } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { LoadingState } from "../components/LoadingState";
import { customerPodParam, useRole } from "../context/RoleContext";
import { shortDate } from "../utils/format";

export function ImportsPage() {
  const { customerPod, customerPods } = useRole();
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];
  const [refreshToken, setRefreshToken] = useState(0);
  const { data, error, loading } = useAsync(
    () => api.imports(customerPodParam(customerPod)),
    [refreshToken, customerPod]
  );
  const [file, setFile] = useState<File | null>(null);
  const [customerKey, setCustomerKey] = useState("CUST_A");
  const [environment, setEnvironment] = useState("PROD");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (customerPod !== "all") {
      setCustomerKey(customerPod);
    }
  }, [customerPod]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setResult(await api.importPlan(file, customerKey, environment) as Record<string, unknown>);
    setRefreshToken((value) => value + 1);
  }

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2>Manual Plan Imports</h2>
          <p>
            {selectedPod.label}: upload CSV plan rows or custom customer metrics after stock pod discovery has created
            the customer scope.
          </p>
        </div>
      </div>
      <div className="two-column">
        <form className="panel form-grid" onSubmit={submit}>
          <h3>Import CSV</h3>
          <label>
            Customer key
            <input value={customerKey} onChange={(event) => setCustomerKey(event.target.value)} />
          </label>
          <label>
            Environment
            <input value={environment} onChange={(event) => setEnvironment(event.target.value)} />
          </label>
          <label className="wide file-input">
            CSV file
            <input type="file" accept=".csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
          <button className="primary-button" type="submit" disabled={!file}>
            <Upload size={16} aria-hidden />
            Import plan
          </button>
          <p className="muted">
            Supported columns include Step, Status, Process ID, Actual Execution Time, Estimated Run Time, Owner,
            Comment, and Volume. Use Volume for custom metrics that are not covered by stock query templates. XLSX is a
            documented extension point; CSV is supported in this MVP.
          </p>
        </form>
        <div className="panel">
          <h3>Import batches</h3>
          <LoadingState loading={loading} error={error} empty={!loading && (data?.length ?? 0) === 0} />
          <div className="record-list">
            {(data ?? []).map((batch) => (
              <article key={String(batch.id)} className="record-item">
                <div>
                  <h4>{String(batch.filename)}</h4>
                  <p>{String(batch.notes ?? "")}</p>
                  <small>{shortDate(String(batch.created_at))}</small>
                </div>
                <div className="record-side">
                  <strong>{String(batch.row_count)} rows</strong>
                  <small>{String(batch.status)}</small>
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
      {result ? (
        <div className="panel">
          <h3>Import result</h3>
          <pre className="payload-preview">{JSON.stringify(result, null, 2)}</pre>
        </div>
      ) : null}
    </section>
  );
}
