import type { Application, ServiceHealth, TelemetrySource } from "./api";

const BASE = import.meta.env.VITE_API_BASE ?? "";
export type Data = Record<string, any>;
export interface TopologyNode extends ServiceHealth {
  service_id: string;
  name: string;
  metrics: Record<string, number>;
  metric_timestamps: Record<string, string>;
  telemetry_state: string;
  runtime_state: string;
  connection_state: string;
  health_score: number | null;
  health_penalties: Record<string, number>;
  runtime_instances: Data[];
  evidence_event_ids: string[];
}
export interface Topology {
  application_id: string;
  state: string;
  observed_at?: string;
  services: TopologyNode[];
  edges: { source: string; target: string; calls: number; provenance: string; state: string }[];
  dependency_state?: string;
  connection_state?: string;
  counts?: Record<string, number>;
  changes?: Data[];
  reason?: string;
}
export interface Overview {
  application: Application;
  topology: Topology;
  open_incidents: number;
  anomalies_24h: number;
  active_findings: number;
  recent_activity: Data[];
  recent_service_changes: Data[];
  sources: TelemetrySource[];
}
export interface OperationalIncident {
  incident_id: string;
  application_id: string;
  title: string;
  state: string;
  severity: string;
  created_at: string;
  updated_at: string;
  summary: Data;
  anomalies?: Data[];
  timeline?: Data[];
  rca?: Data[];
  investigations?: Data[];
  proposals?: Data[];
  executions?: Data[];
  verifications?: Data[];
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const key = sessionStorage.getItem("eios_api_key");
  if (key) headers["X-API-Key"] = key;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(BASE + path, { method: body === undefined ? "GET" : "POST", credentials: "include",
    headers, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(path.endsWith("/investigate") ? 90000 : 45000) });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("eios:unauthorized"));
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : `Request unavailable (${response.status})`);
  }
  return response.json();
}
const root = (app: string) => `/api/applications/${encodeURIComponent(app)}/operations`;
export const operations = {
  overview: (app: string) => request<Overview>(root(app)+"/overview"),
  anomalies: (app: string) => request<Data[]>(root(app)+"/anomalies"),
  incidents: (app: string) => request<OperationalIncident[]>(root(app)+"/incidents"),
  incident: (app: string,id: string) => request<OperationalIncident>(root(app)+`/incidents/${id}`),
  service: (app: string,id: string) => request<Data>(root(app)+`/services/${id}`),
  evidence: (app: string,id: string,signal: "trace" | "log") => request<Data>(`/api/applications/${app}/telemetry/services/${id}/evidence/${signal}`),
  investigate: (app: string,id: string) => request<Data>(root(app)+`/incidents/${id}/investigate`,{}),
  reopen: (app: string,id: string) => request<Data>(root(app)+`/incidents/${id}/reopen`,{}),
  propose: (app: string,id: string,action_type?: string) => request<Data>(root(app)+`/incidents/${id}/proposals`,{action_type}),
  decide: (app: string,id: string,decision: "approve" | "reject",notes: string) => request<Data>(root(app)+`/proposals/${id}/decision`,{decision,notes}),
  execute: (app: string,id: string) => request<Data>(root(app)+`/proposals/${id}/execute`,{}),
  scenarios: (app: string) => request<Data[]>(root(app)+"/experiments/scenarios"),
  experiments: (app: string) => request<Data[]>(root(app)+"/experiments"),
  experiment: (app: string,id: string) => request<Data>(root(app)+`/experiments/${id}`),
  startExperiment: (app: string,body: Data) => request<Data>(root(app)+"/experiments",body),
  stopExperiment: (app: string,id: string) => request<Data>(root(app)+`/experiments/${id}/stop`,{}),
  annotate: (app: string,id: string,body: Data) => request<Data>(root(app)+`/experiments/${id}/annotations`,body),
  evaluations: (app: string) => request<Data[]>(root(app)+"/evaluations"),
  evaluate: (app: string,experiment_ids: string[]) => request<Data>(root(app)+"/evaluations",{experiment_ids}),
  exportUrl: (app: string,id: string,format: "json" | "csv") => BASE+root(app)+`/evaluations/${id}/export?format=${format}`,
  audit: () => request<Data[]>("/api/governance/audit"),
  integrity: () => request<Data>("/api/governance/audit/integrity"),
  permissions: () => request<Data>("/api/governance/permissions"),
  users: () => request<Data[]>("/api/auth/users"),
  createUser: (username: string,password: string,role: string) => request<Data>("/api/auth/register",{username,password,role}),
  disableUser: (id: string) => request<Data>(`/api/auth/users/${id}/disable`,{}),
  issueRecovery: (id: string) => request<Data>(`/api/auth/users/${id}/password-reset`,{}),
};

export function subscribeOperations(app: string,onUpdate: () => void,onState: (value: boolean) => void) {
  let socket: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let closed = false;
  const connect = () => {
    socket = new WebSocket((BASE || location.origin).replace(/^http/,"ws")+"/ws");
    socket.onopen = () => onState(true);
    socket.onmessage = event => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "operations" && payload.application_id === app) onUpdate();
      } catch { /* Ignore malformed frames; polling remains available. */ }
    };
    socket.onclose = () => { onState(false); if (!closed) retry = setTimeout(connect,3000); };
    socket.onerror = () => socket?.close();
  };
  connect();
  return () => { closed = true; if (retry) clearTimeout(retry); socket?.close(); };
}
