import type {
  AdHocMonitor,
  Alert,
  ConnectorHealth,
  CustomerExecutiveSummaryResponse,
  CustomerPodOnboardResponse,
  CustomerPodRead,
  DashboardResponse,
  DiagnosticReport,
  DiagnosticReportSummary,
  GlossaryTerm,
  ExpectationRecord,
  QueryTemplate,
  QueryExecutionLog,
  RunDetail,
  RunListItem,
  RuntimeNode,
  RuntimeTopologyMap,
  ServerHeatmapResponse,
  TopologyCorrelation
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function responseErrorMessage(response: Response) {
  // Normalize transport and server failures before they reach page components.
  // Operators should see a recovery path, while developers still get the
  // endpoint/status context from the browser console and backend logs.
  const fallback =
    response.status >= 500
      ? "The server hit an error while loading this view. The page is still safe; retry or return to the dashboard."
      : `Request failed with ${response.status}`;
  try {
    const contentType = response.headers.get("Content-Type") ?? "";
    if (contentType.includes("application/json")) {
      const payload = await response.json();
      const detail = typeof payload?.detail === "string" ? payload.detail : null;
      return detail || fallback;
    }
    const text = await response.text();
    if (!text || text === "Internal Server Error") return fallback;
    return text;
  } catch {
    return fallback;
  }
}

export const api = {
  dashboard: (params?: Record<string, string>, init?: RequestInit) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<DashboardResponse>(`/dashboard${query}`, init);
  },
  customerExecutiveSummary: (customerKey: string, params?: Record<string, string>, init?: RequestInit) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<CustomerExecutiveSummaryResponse>(`/customers/${customerKey}/executive-summary${query}`, init);
  },
  customerPods: (init?: RequestInit) => request<CustomerPodRead[]>("/customer-pods", init),
  onboardCustomerPod: (payload: Record<string, unknown>) =>
    request<CustomerPodOnboardResponse>("/customer-pods/onboard", { method: "POST", body: JSON.stringify(payload) }),
  runs: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<RunListItem[]>(`/runs${query}`);
  },
  run: (id: string | number) => request<RunDetail>(`/runs/${id}`),
  runTopology: (id: string | number) => request<TopologyCorrelation>(`/runs/${id}/topology`),
  correlateRunTopology: (id: string | number, lookbackMinutes = 120) =>
    request<TopologyCorrelation>(`/runs/${id}/correlate-topology?${new URLSearchParams({ lookback_minutes: String(lookbackMinutes) })}`, { method: "POST" }),
  evaluate: (id: number) => request(`/evaluate/${id}`, { method: "POST" }),
  topology: (params?: Record<string, string>, init?: RequestInit) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<RuntimeTopologyMap>(`/topology/current${query}`, init);
  },
  topologyHeatmap: (params?: Record<string, string>, init?: RequestInit) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<ServerHeatmapResponse>(`/topology/heatmap${query}`, init);
  },
  nodes: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<RuntimeNode[]>(`/nodes${query}`);
  },
  expectations: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<ExpectationRecord[]>(`/expectations${query}`);
  },
  createExpectation: (payload: Partial<ExpectationRecord>) =>
    request<ExpectationRecord>("/expectations", { method: "POST", body: JSON.stringify(payload) }),
  alerts: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<Alert[]>(`/alerts${query}`);
  },
  ackAlert: (id: number, reason: string) =>
    request<Alert>(`/alerts/${id}/ack`, {
      method: "POST",
      body: JSON.stringify({ actor: "operator", reason })
    }),
  resolveAlert: (id: number, note: string) =>
    request<Alert>(`/alerts/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ actor: "operator", note })
    }),
  adHoc: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<AdHocMonitor[]>(`/ad-hoc-monitors${query}`);
  },
  createAdHoc: (payload: Record<string, unknown>) =>
    request<AdHocMonitor>("/ad-hoc-monitors", { method: "POST", body: JSON.stringify(payload) }),
  sources: () => request<ConnectorHealth[]>("/sources/health"),
  testConnector: (connector_type: string) =>
    request<{ status: string; message: string; sample: Record<string, unknown> }>("/connectors/test", {
      method: "POST",
      body: JSON.stringify({ connector_type })
    }),
  queryTemplates: () => request<QueryTemplate[]>("/query-templates"),
  createQueryTemplate: (payload: Record<string, unknown>) =>
    request<QueryTemplate>("/query-templates", { method: "POST", body: JSON.stringify(payload) }),
  validateQueryTemplate: (id: number) =>
    request<Record<string, unknown>>(`/query-templates/${id}/validate`, { method: "POST" }),
  executeQueryTemplate: (id: number, payload: Record<string, unknown>) =>
    request<QueryExecutionLog>(`/query-templates/${id}/execute`, { method: "POST", body: JSON.stringify(payload) }),
  ingestQueryTemplate: (id: number, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/query-templates/${id}/ingest`, { method: "POST", body: JSON.stringify(payload) }),
  importQueryCatalog: () =>
    request<Record<string, unknown>>("/query-catalog/import", { method: "POST" }),
  importTopologyTemplates: () =>
    request<Record<string, unknown>>("/query-catalog/import-topology-templates", { method: "POST" }),
  queryExecutions: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<QueryExecutionLog[]>(`/query-executions${query}`);
  },
  syncRunOnce: () => request<Record<string, unknown>>("/sync/run-once", { method: "POST" }),
  diagnostics: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<DiagnosticReportSummary[]>(`/diagnostics${query}`);
  },
  diagnostic: (id: string | number) => request<DiagnosticReport>(`/diagnostics/${id}`),
  runDiagnostic: (payload: Record<string, unknown>) =>
    request<Record<string, unknown>>("/diagnostics/run", { method: "POST", body: JSON.stringify(payload) }),
  refreshDiagnostic: (id: string | number) =>
    request<Record<string, unknown>>(`/diagnostics/${id}/refresh`, { method: "POST" }),
  promoteDiagnosticToAlert: (id: string | number, findingId?: number) => {
    const query = findingId ? `?${new URLSearchParams({ finding_id: String(findingId) })}` : "";
    return request<Record<string, unknown>>(`/diagnostics/${id}/promote-finding-to-alert${query}`, { method: "POST" });
  },
  promoteDiagnosticToPlaybook: (id: string | number, findingId?: number) => {
    const query = findingId ? `?${new URLSearchParams({ finding_id: String(findingId) })}` : "";
    return request<Record<string, unknown>>(`/diagnostics/${id}/promote-finding-to-playbook-note${query}`, { method: "POST" });
  },
  glossary: () => request<GlossaryTerm[]>("/glossary"),
  imports: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<Array<Record<string, unknown>>>(`/imports/plans${query}`);
  },
  importPlan: (file: File, customer_key: string, environment: string) => {
    const body = new FormData();
    body.append("file", file);
    const query = new URLSearchParams({ customer_key, environment });
    return request(`/imports/plans?${query}`, { method: "POST", body });
  },
  playbook: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return request<Record<string, unknown>>(`/playbook${query}`);
  }
};
