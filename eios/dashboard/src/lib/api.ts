const BASE = import.meta.env.VITE_API_BASE ?? "";
import type { IntelligenceStatus, FeatureWindow, IntelligenceInsight, IntelligenceForecast, IntelligenceModel } from "./intelligence";

export interface ApplicationInput {
  name: string;
  environment: string;
  runtime_type: "docker";
  discovery_scope: { compose_project?: string; labels?: Record<string, string>; container_names?: string[]; exclude_services?: string[] };
  telemetry_config: Record<string, string>;
  labels?: Record<string, string>;
}

export interface Application extends ApplicationInput {
  application_id: string;
  connection_state: "not_discovered" | "connected" | "unavailable" | "stale";
  telemetry_connection_state: "configured" | "not_configured";
  discovery_checked_at: string | null;
  discovery_error: string | null;
  created_at: string;
}

export interface CatalogService {
  service_id: string;
  application_id: string;
  name: string;
  runtime_identifier: string | null;
  runtime_state: "online" | "offline" | "unknown" | "starting";
  last_runtime_state: string;
  connection_state: string;
  telemetry_state: "fresh" | "stale" | "not_observed";
  last_telemetry_at: string | null;
  last_seen_at: string | null;
  runtime_instances: { container_id: string; container_name: string; image: string; runtime_state: string; health_state: string }[];
}

function intelligenceQuery(service: string, extra: Record<string, string> = {}) {
  const query = new URLSearchParams(extra);
  if (service) query.set("service", service);
  return `?${query}`;
}

export type Severity = "info" | "low" | "medium" | "high" | "critical";

export interface Incident {
  incident_id: string;
  application_id?: string | null;
  service_id?: string | null;
  domain: string;
  entity_kind: string;
  entity_id: string;
  entity_service: string | null;
  detected_at: string;
  window_start: string;
  window_end: string;
  detector: string;
  score: number;
  severity: Severity;
  title: string;
  features: Record<string, number>;
  labels: Record<string, string>;
  status: string;
  evidence_count?: number;
}

export interface Stats {
  totals: { events: number; incidents: number; open_faults: number };
  events_by_domain: { domain: string; events: number; latest: string }[];
  incidents_by_severity: { severity: Severity; incidents: number }[];
}

export interface Flag {
  key: string;
  defaultVariant: string;
  variants: string[];
  description: string;
  on: boolean;
}

export interface FaultWindow {
  window_id: string;
  flag_key: string;
  variant: string | null;
  started_at: string;
  ended_at: string | null;
  expected_domain: string | null;
  expected_entity: string | null;
  notes: string | null;
}

export type ServiceStatus =
  | "offline"
  | "stale"
  | "healthy"
  | "degraded"
  | "critical"
  | "idle"
  | "unknown";

/** An open fault window, as attached to the service it targets. */
export interface InjectedFault {
  window_id: string;
  flag_key: string;
  variant: string | null;
  started_at: string;
  expected_domain: string | null;
  expected_entity: string | null;
}

export interface ServiceHealth {
  service: string;
  application_id?: string;
  service_id?: string | null;
  status: ServiceStatus;
  reason: string;
  rate_per_sec: number | null;
  error_rate_per_sec: number | null;
  error_ratio: number | null;
  latency_p95_ms: number | null;
  latency_p99_ms: number | null;
  cpu_ratio: number | null;
  memory_ratio: number | null;
  sources: string[];
  incidents_24h: number;
  /** Set when a fault window is open against this service. */
  injected_fault: InjectedFault | null;
}

export interface ServicesView {
  state?: string;
  window: string;
  services: ServiceHealth[];
  degraded_sources: string[];
  jaeger_ui: string;
  open_faults: InjectedFault[];
}

export interface ServiceEdge {
  source: string;
  target: string;
  calls: number;
}

export interface ServiceGraph {
  edges: ServiceEdge[];
  nodes: string[];
  available: boolean;
  reason: string | null;
}

export interface Operation {
  span_name: string;
  rate_per_sec: number;
  error_rate_per_sec: number;
  error_ratio: number | null;
  latency_p95_ms: number | null;
}

export type ServiceIncident = Pick<
  Incident,
  | "incident_id"
  | "domain"
  | "entity_kind"
  | "entity_id"
  | "entity_service"
  | "detected_at"
  | "detector"
  | "score"
  | "severity"
  | "title"
  | "labels"
  | "status"
>;

export interface ServiceDetail {
  service: ServiceHealth;
  window: string;
  operations: Operation[];
  upstreams: string[];
  downstreams: string[];
  incidents: ServiceIncident[];
  traces_url: string;
}

export interface SecurityStatus {
  security_enabled: boolean;
  session_authentication?: boolean;
  api_key_enabled?: boolean;
  rate_limiting?: {
    requests_per_window: number;
    window_seconds: number;
  };
  redaction_enabled?: boolean;
  audit_integrity?: boolean;
  cors_origins?: string[];
  version?: string;
}

export interface SecurityAuditEntry {
  entry_id?: number;
  at: string;
  actor: string;
  action: string;
  subject_kind?: string;
  subject_id?: string;
  detail?: Record<string, any>;
  tenant_id?: string;
  ip?: string;
  request_id?: string;
  integrity_hash?: string;
}

export interface SecurityAlert {
  alert_id?: string;
  at: string;
  action: string;
  actor: string;
  ip: string;
  detail?: Record<string, any>;
  severity?: Severity;
}

function discoverySignal(signal: AbortSignal | undefined, timeout: number): AbortSignal {
  const deadline = AbortSignal.timeout(timeout);
  return signal ? AbortSignal.any([signal, deadline]) : deadline;
}

async function apiError(response: Response, path: string): Promise<Error> {
  const body = await response.text();
  let message = response.statusText;
  try {
    const parsed = JSON.parse(body);
    message = typeof parsed.detail === "string" ? parsed.detail
      : Array.isArray(parsed.detail) ? parsed.detail.map((item: { msg: string }) => item.msg).join("; ") : message;
  } catch { if (body) message = body; }
  if (response.status === 401 && !path.startsWith("/api/auth/") && typeof window !== "undefined") {
    window.dispatchEvent(new Event("eios:unauthorized"));
  }
  return new Error(`${response.status} ${message}`);
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const apiKey = sessionStorage.getItem("eios_api_key");
  const headers: Record<string, string> = {};
  if (apiKey) headers["X-API-Key"] = apiKey;

  const res = await fetch(`${BASE}${path}`, { headers, signal, credentials: "include" });
  if (!res.ok) throw await apiError(res, path);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const apiKey = sessionStorage.getItem("eios_api_key");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (apiKey) headers["X-API-Key"] = apiKey;

  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    credentials: "include",
    signal,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw await apiError(res, path);
  return res.json() as Promise<T>;
}

// ── Docker Container types ─────────────────────────────────────────────────
export interface DockerContainer {
  id: string;
  full_id: string;
  name: string;
  image: string;
  status: "running" | "stopped" | "paused" | "restarting" | "dead" | "created" | string;
  state: string;
  ports: string;
  created: number;
  uptime: string;
  compose_service: string;
  compose_project: string;
  labels: Record<string, string>;
  otlp_connected: boolean;
  category: "app" | "infra" | "database" | string;
}

export interface ContainerStats {
  id: string;
  cpu_pct: number;
  memory_bytes: number;
  memory_mb: number;
  memory_limit_mb: number;
  memory_pct: number;
  networks: Record<string, { rx_bytes: number; tx_bytes: number }>;
}

export interface DockerInfo {
  containers: number;
  containers_running: number;
  containers_paused: number;
  containers_stopped: number;
  images: number;
  server_version: string;
  os: string;
  architecture: string;
  mem_total_gb: number;
  cpus: number;
}

// ── System Metrics types ───────────────────────────────────────────────────
export interface SystemMetrics {
  cpu: {
    percent: number;
    per_core: number[];
    count_logical: number;
    count_physical: number;
    freq_mhz: number | null;
    freq_max_mhz: number | null;
  };
  memory: {
    total_gb: number;
    available_gb: number;
    used_gb: number;
    percent: number;
    cached_gb: number;
    buffers_gb: number;
  };
  swap: { total_gb: number; used_gb: number; percent: number };
  disk: {
    device: string;
    mountpoint: string;
    fstype: string;
    total_gb: number;
    used_gb: number;
    free_gb: number;
    percent: number;
  }[];
  network: {
    rx_kbps: number;
    tx_kbps: number;
    interfaces: {
      interface: string;
      bytes_sent: number;
      bytes_recv: number;
    }[];
  };
  platform: {
    system: string;
    node: string;
    release: string;
    machine: string;
    python: string;
  };
}

export interface SystemProcess {
  pid: number;
  name: string;
  cpu_pct: number;
  mem_pct: number;
  mem_mb: number;
  status: string;
  user: string;
}

// ── K8s types ─────────────────────────────────────────────────────────────
export interface K8sWorkloads {
  available: boolean;
  reason?: string;
  namespace?: string;
  pods: {
    name: string; namespace: string; phase: string;
    ready: number; total_containers: number; node: string;
    images: string[]; restart_count: number; pod_ip: string;
  }[];
  deployments: {
    name: string; namespace: string; replicas: number;
    ready_replicas: number; available_replicas: number; image: string;
  }[];
  services: {
    name: string; namespace: string; type: string;
    cluster_ip: string; ports: string;
  }[];
}

// ── FS types ──────────────────────────────────────────────────────────────
export interface FSEntry {
  name: string;
  path: string;
  type: "file" | "directory";
  size: number | null;
  size_human: string | null;
  modified: number;
  extension: string;
  mime: string;
  is_text: boolean;
}

export interface FSListing {
  path: string;
  entries: FSEntry[];
  total: number;
}

export interface FSFile {
  path: string;
  name: string;
  content: string;
  size: number;
  size_human: string;
  mime: string;
  extension: string;
  modified: number;
}

// ── Terminal types ─────────────────────────────────────────────────────────
export interface TerminalResult {
  command: string;
  output: string;
  exit_code: number;
  timestamp: string;
  duration_ms: number;
}

export interface TelemetrySource {
  source_id: string;
  kind: "kafka" | "prometheus" | "jaeger" | "opensearch";
  state: "connected" | "disconnected" | "stale" | "unknown";
  checked_at: string | null;
  last_data_at: string | null;
  last_error: string | null;
  freshness_seconds: number;
}

export const api = {
  telemetrySources: (id: string, signal?: AbortSignal) => get<TelemetrySource[]>(`/api/applications/${id}/telemetry/sources`, discoverySignal(signal, 15000)),
  // Core EIOS
  stats: () => get<Stats>("/api/stats"),
  incidents: (limit = 50,applicationId?: string) => get<Incident[]>(`/api/incidents?limit=${limit}${applicationId ? `&application_id=${applicationId}` : ""}`),
  flags: () => get<Flag[]>("/api/flags"),
  faults: () => get<FaultWindow[]>("/api/faults"),
  services: (applicationId?: string) => get<ServicesView>(`/api/services${applicationId ? `?application_id=${applicationId}` : ""}`),
  serviceGraph: (hours = 1, applicationId?: string) => get<ServiceGraph>(`/api/services/graph?hours=${hours}${applicationId ? `&application_id=${applicationId}` : ""}`),
  service: (name: string, applicationId?: string) =>
    get<ServiceDetail>(`/api/services/${encodeURIComponent(name)}${applicationId ? `?application_id=${applicationId}` : ""}`),
  startFault: (body: {
    flag_key: string;
    variant: string;
    expected_domain?: string;
    expected_entity?: string;
    notes?: string;
  }) => post<{ window_id: string }>("/api/faults/start", body),
  stopFault: (windowId: string) => post(`/api/faults/${windowId}/stop`),

  // Security (Rehan)
  securityStatus: () => get<SecurityStatus>("/api/security/status"),
  securityRedact: (text: string) => post<{ redacted: string; scope: string }>("/api/security/redact", { text }),
  securityAlerts: () => get<SecurityAlert[]>("/api/security/alerts"),
  securityAudit: () => get<SecurityAuditEntry[]>("/api/security/audit"),

  // Docker Engine — REAL container data
  dockerContainers: (all = true, signal?: AbortSignal) =>
    get<DockerContainer[]>(`/api/docker/containers?all=${all}`, discoverySignal(signal, 20000)),
  dockerContainerStats: (id: string) =>
    get<ContainerStats>(`/api/docker/containers/${id}/stats`),
  dockerStats: (signal?: AbortSignal) => get<ContainerStats[]>("/api/docker/stats", discoverySignal(signal, 10000)),
  dockerInfo: (signal?: AbortSignal) => get<DockerInfo>("/api/docker/info", discoverySignal(signal, 5000)),
  dockerNetworks: () => get<{ id: string; name: string; driver: string; containers: number }[]>("/api/docker/networks"),
  dockerStart: (id: string) => post(`/api/docker/containers/${id}/start`),
  dockerStop: (id: string) => post(`/api/docker/containers/${id}/stop`),
  dockerRestart: (id: string) => post(`/api/docker/containers/${id}/restart`),

  // System Metrics — REAL host metrics
  systemMetrics: () => get<SystemMetrics>("/api/system/metrics"),
  systemProcesses: (limit = 20) => get<SystemProcess[]>(`/api/system/processes?limit=${limit}`),

  // Kubernetes
  k8sWorkloads: (namespace = "default", signal?: AbortSignal) =>
    get<K8sWorkloads>(`/api/k8s/workloads?namespace=${namespace}`, discoverySignal(signal, 5000)),
  k8sNamespaces: () => get<string[]>("/api/k8s/namespaces"),

  // Terminal
  terminalExec: (command: string) =>
    post<TerminalResult>("/api/terminal/exec", { command }),
  terminalHistory: (limit = 50) =>
    get<TerminalResult[]>(`/api/terminal/history?limit=${limit}`),

  // Filesystem (real EIOS workspace)
  fsList: (path = "") => get<FSListing>(`/api/fs/list?path=${encodeURIComponent(path)}`),
  fsRead: (path: string) => get<FSFile>(`/api/fs/read?path=${encodeURIComponent(path)}`),
  fsTree: (depth = 3) => get<FSEntry>(`/api/fs/tree?depth=${depth}`),
  fsInfo: () => get<{ root: string; exists: boolean; disk: { total_gb: number; used_gb: number; free_gb: number; percent: number } }>("/api/fs/info"),

  // Intelligence & Agents
  intelligenceStatus: () => get<IntelligenceStatus>("/api/intelligence/status"),
  intelligenceKpis: (service = "") => get<FeatureWindow[]>(`/api/intelligence/kpis${intelligenceQuery(service)}`),
  intelligenceInsights: (service = "", hours = 24) => get<IntelligenceInsight[]>(`/api/intelligence/insights${intelligenceQuery(service, { since: new Date(Date.now() - hours * 3600000).toISOString(), limit: "500" })}`),
  intelligenceForecasts: (service = "") => get<IntelligenceForecast[]>(`/api/intelligence/forecasts${intelligenceQuery(service)}`),
  intelligenceModels: (service = "") => get<IntelligenceModel[]>(`/api/intelligence/models${intelligenceQuery(service)}`),
  intelligenceHistory: (service: string, minutes = 60) => get<FeatureWindow[]>(`/api/intelligence/history${intelligenceQuery(service, { minutes: String(minutes) })}`),
  intelligenceFeedback: (insight_id: string, verdict: "confirm" | "dismiss", operator: string) => post<{ message: string }>("/api/intelligence/feedback", { insight_id, verdict, operator }),
  aiChat: (query: string, context?: any) =>
    post<{ reply: string; timestamp: string; context_snapshot: any }>("/api/ai/chat", { query, context }),
  cases: () => get<any[]>("/api/cases"),
  case: (id: string) => get<any>(`/api/cases/${id}`),
  approvals: () => get<any[]>("/api/approvals"),
  executeApproval: (id: string, decision: string, notes?: string) =>
    post<any>(`/api/approvals/${id}/action`, { decision, notes }),

  // Workload Management & OTel Pipeline
  connectWorkload: (body: { workload_type?: string; name?: string; collector_endpoint?: string; prometheus_url?: string; jaeger_url?: string }) =>
    post<any>("/api/workloads/connect", body),
  workloadStatus: () => get<any>("/api/workloads/status"),

  // Administrator Authentication
  authLogin: (username: string, password: string) =>
    post<{ status: string; user: string; role: string; expires_at: string }>("/api/auth/login", { username, password }),
  authRegister: (username: string, password: string, role?: string) =>
    post<{ status: string; user: string; role: string }>("/api/auth/register", { username, password, role }),
  authSignup: (username: string, password: string) =>
    post<{ status: string; user: string; role: string }>("/api/auth/signup", { username, password }),
  authForgotPassword: (username: string) =>
    post<{ status: string; message: string; reset_token?: string }>("/api/auth/forgot-password", { username }),
  authResetPassword: (token: string, password: string) =>
    post<{ status: string }>("/api/auth/reset-password", { token, password }),
  authStatus: () => get<{ setup_required: boolean; self_signup_enabled: boolean; password_reset_enabled: boolean }>("/api/auth/status"),
  authMe: () => get<{ username: string; role: string; status: string; expires_at: string }>("/api/auth/me"),
  authLogout: () => post<{ status: string }>("/api/auth/logout"),
  applications: (signal?: AbortSignal) => get<Application[]>("/api/applications", discoverySignal(signal, 10000)),
  createApplication: (body: ApplicationInput) => post<Application>("/api/applications", body),
  applicationServices: (id: string, signal?: AbortSignal) => get<CatalogService[]>(`/api/applications/${id}/services`, discoverySignal(signal, 15000)),
  registerService: (id: string, body: { name: string; runtime_identifier?: string }) => post<CatalogService>(`/api/applications/${id}/services`, body),
  discoverApplication: (id: string) => post<{ matched_containers: number }>(`/api/applications/${id}/discovery`, undefined, AbortSignal.timeout(45000)),
};


/** Live incident feed. Reconnects on drop so a demo survives a restart. */
export function subscribeIncidents(
  onIncident: (incident: Incident) => void,
  onState: (connected: boolean) => void,
): () => void {
  let socket: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let closed = false;

  const connect = () => {
    const url = (BASE || window.location.origin).replace(/^http/, "ws") + "/ws";
    socket = new WebSocket(url);
    socket.onopen = () => onState(true);
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "incident") onIncident(payload.data as Incident);
      } catch {
        // A malformed frame should not take the feed down.
      }
    };
    socket.onclose = () => {
      onState(false);
      if (!closed) retry = setTimeout(connect, 3000);
    };
    socket.onerror = () => socket?.close();
  };

  connect();
  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    socket?.close();
  };
}
