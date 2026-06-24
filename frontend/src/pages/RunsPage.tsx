import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useAsync } from "../api/useAsync";
import { HelpTip } from "../components/HelpTip";
import { LoadingState } from "../components/LoadingState";
import { ReasonTags } from "../components/ReasonTags";
import { StatusPill } from "../components/StatusPill";
import { customerPodParam, useRole } from "../context/RoleContext";
import { minutes, pct, shortDate } from "../utils/format";

export function RunsPage() {
  const { role, customerPod, customerPods } = useRole();
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];
  const [query, setQuery] = useState("");
  const { data, error, loading } = useAsync(
    () => api.runs({ ...customerPodParam(customerPod), limit: "1000" }),
    [customerPod]
  );
  const rows = useMemo(() => {
    const lower = query.toLowerCase();
    return (data ?? []).filter((row) => {
      if (!lower) return true;
      return [row.run_key, row.job_name, row.customer_key, row.process_id, row.status]
        .join(" ")
        .toLowerCase()
        .includes(lower);
    });
  }, [data, query]);

  return (
    <section className="page-stack">
      <div className="section-header">
        <div>
          <h2 className="heading-with-help">
            Runs
            <HelpTip
              label="Runs page help"
              text="This table lists monitored job executions. Use search for a customer, job, process ID, or ESS request. Open a row to see the explanation and alert payload."
            />
          </h2>
          <p>{selectedPod.label}: search current and recent job runs by process, ESS request, status, and reason codes.</p>
        </div>
      </div>
      <label className="search-box">
        <Search size={17} aria-hidden />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search runs..." />
      </label>
      <LoadingState loading={loading} error={error} empty={!loading && rows.length === 0} />
      {rows.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {role !== "executive" ? <th>Run</th> : null}
                <th>Customer</th>
                <th>Job</th>
                {role === "dba" ? <th>Identifiers</th> : null}
                <th>Region</th>
                <th>Status</th>
                <th>Elapsed</th>
                <th>Variance</th>
                {role !== "executive" ? <th>Started</th> : null}
                <th>{role === "executive" ? "Cause" : "Drivers"}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  {role !== "executive" ? (
                    <td>
                      <Link to={`/runs/${row.id}`} className="table-link">
                        {row.run_key}
                      </Link>
                    </td>
                  ) : null}
                  <td>
                    {row.customer_name}
                    <span className="subtext">{row.environment}</span>
                  </td>
                  <td>
                    <Link to={`/runs/${row.id}`} className="table-link">
                      {row.job_name}
                    </Link>
                    <span className="subtext">{row.job_type}</span>
                  </td>
                  {role === "dba" ? (
                    <td>
                      {row.process_id ?? "n/a"}
                      <span className="subtext">{row.ess_request_id ?? "no ESS request"}</span>
                    </td>
                  ) : null}
                  <td>{row.region ?? "global"}</td>
                  <td>
                    <StatusPill state={row.runtime_state} />
                  </td>
                  <td>{minutes(row.elapsed_minutes)}</td>
                  <td>{pct(row.variance_pct)}</td>
                  {role !== "executive" ? <td>{shortDate(row.started_at)}</td> : null}
                  <td>
                    <ReasonTags tags={row.reason_codes} limit={role === "executive" ? 2 : 4} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
