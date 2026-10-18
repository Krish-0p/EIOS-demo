export interface IntelligenceStatus {
  state: string;
  worker_alive: boolean;
  worker: { last_analysis_at?: string };
  fresh_services: string[];
  stale_services: string[];
  active_models: { service: string; model_id: string }[];
  training_required: boolean;
}

export interface FeatureWindow {
  service: string;
  window_start: string;
  window_end: string;
  features: Record<string, number>;
  quality: { metric_last_at?: Record<string, string>; missing_metrics?: string[] };
  evidence_event_ids: string[];
  data_fresh?: boolean;
}

export interface IntelligenceInsight {
  insight_id: string;
  service: string;
  kind: string;
  severity: string;
  title: string;
  window_start: string;
  window_end: string;
  detector: string;
  model_id: string | null;
  measurements: Record<string, number>;
  baseline: Record<string, unknown>;
  analysis: Record<string, unknown>;
  evidence_event_ids: string[];
  recommendation: { title: string; rationale: string; preconditions: string[]; execution: string };
  status: string;
}

export interface IntelligenceForecast {
  forecast_id: string;
  service: string;
  observed_at: string;
  horizon_minutes: number;
  state: string;
  data_fresh: boolean;
  reason: string | null;
  algorithm: string;
  values: {
    current_memory_fraction?: number;
    projected_memory_fraction?: number;
    warning_threshold?: number;
    minutes_to_warning?: number | null;
    warning?: boolean;
    validation_mae_fraction?: number;
  };
}

export interface IntelligenceModel {
  model_id: string;
  service: string;
  algorithm: string;
  state: string;
  train_start: string;
  train_end: string;
  feature_names: string[];
  validation: Record<string, unknown>;
  last_inference_at: string | null;
}

export const metrics = [
  { key: "cpu_cores", label: "CPU", unit: "cores" },
  { key: "memory_fraction", label: "Memory", unit: "% of limit" },
  { key: "request_rate_per_sec", label: "Requests", unit: "requests/s" },
  { key: "error_fraction", label: "Error ratio", unit: "%" },
  { key: "latency_p95_ms", label: "p95 latency", unit: "ms" },
  { key: "orders_per_min", label: "Orders", unit: "orders/min" },
] as const;

export function measurement(key: string, value?: number): string {
  if (value === undefined || !Number.isFinite(value)) return "Unavailable";
  if (key.endsWith("fraction")) return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

export function fresh(at?: string, now = Date.now()): boolean {
  if (!at) return false;
  const age = now - Date.parse(at);
  return Number.isFinite(age) && age >= -60000 && age <= 240000;
}
