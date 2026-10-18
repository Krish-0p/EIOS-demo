import { useEffect, useState } from "react";
import { BarChart3, Minus, Square, X, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fresh, measurement, metrics, type FeatureWindow, type IntelligenceStatus, type IntelligenceInsight, type IntelligenceForecast, type IntelligenceModel } from "@/lib/intelligence";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from "@/components/ui/table";

interface Props {
  onClose: () => void;
  onMinimize: () => void;
  onToggleMaximize: () => void;
  isMaximized: boolean;
  operator: string;
}

const time = (value?: string | null) => value ? new Date(value).toLocaleString() : "Unavailable";
const readable = (value: string) => value.replaceAll("_", " ");

function Details({ title, data }: { title: string; data: Record<string, unknown> }) {
  return <details className="rounded-lg border border-border p-3">
    <summary className="cursor-pointer text-sm text-primary">{title}</summary>
    <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-muted-foreground select-text">{JSON.stringify(data, null, 2)}</pre>
  </details>;
}

/** Plot observed samples only; gaps and missing values are never interpolated. */
function Trend({ windows, metric }: { windows: FeatureWindow[]; metric: string }) {
  const observed = windows.filter(w => Number.isFinite(w.features[metric]));
  if (observed.length < 2) return <p className="text-sm text-muted-foreground">Insufficient history for this metric.</p>;
  const start = Date.parse(windows[0].window_end);
  const span = Math.max(60000, Date.parse(windows[windows.length - 1].window_end) - start);
  const values = observed.map(w => w.features[metric]);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const range = Math.max(high - low, Math.abs(high) * 0.02, 0.001);
  const points = windows.map(w => ({ at: Date.parse(w.window_end), value: w.features[metric] }));
  return <figure className="flex flex-col gap-2">
    <svg viewBox="0 0 600 145" className="h-40 w-full text-primary" role="img" aria-label={`${readable(metric)} observed trend from ${time(windows[0].window_end)} to ${time(windows[windows.length - 1].window_end)}`}>
      <title>{readable(metric)}: {measurement(metric, low)} to {measurement(metric, high)}</title>
      {[25, 65, 105].map(y => <line key={y} x1="10" x2="590" y1={y} y2={y} stroke="currentColor" opacity="0.15" />)}
      {points.map((p, index) => {
        if (!Number.isFinite(p.value)) return null;
        const x = 10 + (p.at - start) / span * 580;
        const y = 115 - (p.value - low) / range * 95;
        const prev = points[index - 1];
        return <g key={p.at}>
          {prev && Number.isFinite(prev.value) && p.at - prev.at <= 90000 && <line x1={10 + (prev.at - start) / span * 580} y1={115 - (prev.value - low) / range * 95} x2={x} y2={y} stroke="currentColor" strokeWidth="2" />}
          <circle cx={x} cy={y} r="2" fill="currentColor"><title>{time(new Date(p.at).toISOString())}: {measurement(metric, p.value)}</title></circle>
        </g>;
      })}
    </svg>
    <figcaption className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
      <span>{time(windows[0].window_end)}</span><span>Range: {measurement(metric, low)} – {measurement(metric, high)}</span><span>{time(windows[windows.length - 1].window_end)}</span>
    </figcaption>
  </figure>;
}

export function ReportsWindow({ onClose, onMinimize, onToggleMaximize, isMaximized, operator }: Props) {
  const [service, setService] = useState("");
  const [hours, setHours] = useState(24);
  const [revision, setRevision] = useState(0);
  const [status, setStatus] = useState<IntelligenceStatus | null>(null);
  const [kpis, setKpis] = useState<FeatureWindow[]>([]);
  const [insights, setInsights] = useState<IntelligenceInsight[]>([]);
  const [forecasts, setForecasts] = useState<IntelligenceForecast[]>([]);
  const [models, setModels] = useState<IntelligenceModel[]>([]);
  const [history, setHistory] = useState<FeatureWindow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [metric, setMetric] = useState<string>("memory_fraction");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [savingFeedback, setSavingFeedback] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let busy = false;
    const load = async () => {
      if (busy) return;
      busy = true;
      try {
        const [nextStatus, nextKpis, nextInsights, nextForecasts, nextModels] = await Promise.all([
          api.intelligenceStatus(), api.intelligenceKpis(service), api.intelligenceInsights(service, hours),
          api.intelligenceForecasts(service), api.intelligenceModels(service),
        ]);
        if (!active) return;
        setStatus(nextStatus); setKpis(nextKpis); setInsights(nextInsights);
        setForecasts(nextForecasts); setModels(nextModels); setError(null);
        setUpdatedAt(new Date().toISOString());
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Reports unavailable");
      } finally {
        busy = false;
        if (active) setLoading(false);
      }
    };
    setLoading(true); setStatus(null); setKpis([]); setInsights([]); setForecasts([]); setModels([]);
    setError(null); setSelectedId(null); setFeedbackMessage(""); setUpdatedAt(null);
    void load();
    const timer = setInterval(load, 30000);
    return () => { active = false; clearInterval(timer); };
  }, [service, hours, revision]);

  const selected = insights.find(item => item.insight_id === selectedId) ?? insights[0];
  const chartService = service || selected?.service || kpis.find(w => w.data_fresh)?.service || "";
  useEffect(() => {
    let active = true;
    setHistory([]); setHistoryError(null);
    if (!chartService) return;
    api.intelligenceHistory(chartService, Math.min(1440, hours * 60)).then(value => {
      if (active) setHistory(value);
    }).catch(err => { if (active) setHistoryError(err instanceof Error ? err.message : "History unavailable"); });
    return () => { active = false; };
  }, [chartService, hours, updatedAt]);

  const submitFeedback = async (verdict: "confirm" | "dismiss") => {
    if (!selected) return;
    const id = selected.insight_id;
    setSavingFeedback(true); setFeedbackMessage("");
    try {
      const result = await api.intelligenceFeedback(id, verdict, operator);
      setInsights(current => current.map(item => item.insight_id === id ? { ...item, status: verdict === "confirm" ? "confirmed" : "dismissed" } : item));
      setFeedbackMessage(result.message);
    } catch (err) {
      setFeedbackMessage(`Feedback failed: ${err instanceof Error ? err.message : "Unavailable"}`);
    } finally { setSavingFeedback(false); }
  };

  const services = Array.from(new Set([...(status?.fresh_services ?? []), ...(status?.stale_services ?? []), ...kpis.map(w => w.service), ...models.map(m => m.service), ...insights.map(i => i.service)])).sort();
  const recentKpis = kpis.filter(w => w.data_fresh && fresh(w.window_end));
  const warnings = forecasts.filter(f => f.state === "ready" && f.data_fresh && fresh(f.observed_at) && f.values.warning);
  const agentState = error ? "unavailable" : !status ? "loading" : !fresh(status.worker.last_analysis_at) ? "stale" : status.state;
  const badge = (value: string) => <Badge variant={["critical", "high", "unavailable"].includes(value) ? "destructive" : "secondary"}>{readable(value)}</Badge>;

  const findingPanel = <div className="grid gap-4 lg:grid-cols-2">
    <div className="flex max-h-[460px] flex-col gap-2 overflow-y-auto scrollbar-themed" aria-label="Findings">
      {!insights.length && <p className="text-sm text-muted-foreground">No stored findings in this period. Model detection requires an active model.</p>}
      {insights.map(item => <button key={item.insight_id} onClick={() => { setSelectedId(item.insight_id); setFeedbackMessage(""); }} aria-pressed={selected?.insight_id === item.insight_id}
        className={cn("flex flex-col gap-2 rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", selected?.insight_id === item.insight_id ? "border-primary bg-secondary" : "border-border bg-card hover:bg-secondary")}>
        <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs text-primary font-mono">{item.service}</span>{badge(item.severity)}</div>
        <span className="text-sm font-medium">{item.title}</span>
        <span className="text-xs text-muted-foreground">{readable(item.kind)} · {time(item.window_end)} · {item.status}</span>
      </button>)}
      {insights.length === 500 && <p className="text-xs text-muted-foreground">Showing the newest 500 findings. Narrow service or period for older records.</p>}
    </div>
    {selected && <Card><CardHeader><CardTitle>{selected.title}</CardTitle><CardDescription>{selected.service} · {time(selected.window_start)} – {time(selected.window_end)}</CardDescription></CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-xs text-muted-foreground">Detector: {selected.detector}<br />Model: {selected.model_id ?? "Rule / analytics"} · Status: {selected.status}</p>
        <Details title="Measurements and baseline" data={{ measurements: selected.measurements, baseline: selected.baseline }} />
        <Details title="Analysis and candidate causes" data={selected.analysis} />
        <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm text-primary">Evidence ({selected.evidence_event_ids.length} events)</summary><div className="mt-2 max-h-32 overflow-auto text-xs font-mono text-muted-foreground select-text">{selected.evidence_event_ids.map(id => <p key={id} className="break-all">{id}</p>)}</div></details>
        <p className="text-sm font-medium">{selected.recommendation.title}</p>
        <p className="text-xs text-muted-foreground">{selected.recommendation.rationale}</p>
        <ul className="list-disc pl-4 text-xs text-muted-foreground">{selected.recommendation.preconditions.map(p => <li key={p}>{p}</li>)}</ul>
        <p className="text-xs text-muted-foreground">Recommendation requires manual review. Feedback records your assessment.</p>
        <div className="flex gap-2"><Button size="sm" disabled={savingFeedback || Boolean(error)} onClick={() => void submitFeedback("confirm")}>Confirm finding</Button><Button size="sm" variant="outline" disabled={savingFeedback || Boolean(error)} onClick={() => void submitFeedback("dismiss")}>Dismiss</Button></div>
        {feedbackMessage && <p role="status" className="text-xs text-muted-foreground">{feedbackMessage}</p>}
      </CardContent></Card>}
  </div>;

  return <section aria-label="EIOS Reports" className={cn("os-window flex shrink-0 flex-col overflow-hidden rounded-2xl border border-border bg-background text-foreground shadow-2xl", isMaximized ? "fixed inset-2 z-50" : "w-full min-h-[520px] max-h-[760px]")}>
    <header className="flex min-h-11 shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-card px-4 py-2">
      <div className="flex items-center gap-3"><BarChart3 className="size-5 text-primary" /><div><h2 className="font-display text-xs font-bold tracking-wide">EIOS Enterprise Reports</h2><p className="text-[10px] text-muted-foreground font-mono">Intelligence Agent · Analytics & evidence</p></div></div>
      <div className="flex items-center gap-1">{badge(agentState)}<Button size="sm" variant="outline" aria-label="Refresh reports" disabled={loading} onClick={() => setRevision(v => v + 1)}><RefreshCw data-icon="inline-start" />Refresh</Button><Button variant="outline" size="icon" aria-label="Minimize Reports" onClick={onMinimize}><Minus /></Button><Button variant="outline" size="icon" aria-label={isMaximized ? "Restore Reports" : "Maximize Reports"} onClick={onToggleMaximize}><Square /></Button><Button variant="outline" size="icon" aria-label="Close Reports" onClick={onClose}><X /></Button></div>
    </header>
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto scrollbar-themed p-4 select-text">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">Service<select aria-label="Reports service" value={service} onChange={e => setService(e.target.value)} className="max-w-64 rounded-md border border-input bg-background p-2 text-foreground"><option value="">All services</option>{services.map(s => <option key={s} value={s}>{s}</option>)}{service && !services.includes(service) && <option value={service}>{service}</option>}</select></label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">Finding period<select aria-label="Reports finding period" value={hours} onChange={e => setHours(Number(e.target.value))} className="rounded-md border border-input bg-background p-2 text-foreground"><option value={1}>Last hour</option><option value={6}>Last 6 hours</option><option value={24}>Last 24 hours</option></select></label>
        <p className="text-xs text-muted-foreground">Last analysis: {time(status?.worker.last_analysis_at)}<br />Refreshes every 30 seconds · Latest snapshots in KPIs / Predictions</p>
      </div>
      {loading && <p role="status" className="text-sm text-muted-foreground">Loading reports…</p>}
      {error && <p role="alert" className="text-sm text-destructive">Reports unavailable: {error}. {updatedAt ? `Showing last retrieved data from ${time(updatedAt)}.` : "Check the backend and API key, then refresh."}</p>}
      {!loading && status?.training_required && <p className="text-sm text-muted-foreground">Learning: no active anomaly model. KPI analysis and rules remain available. Model training needs reviewed healthy history.</p>}
      <Tabs defaultValue="overview" className="flex flex-col gap-3">
        <div className="overflow-x-auto"><TabsList aria-label="Reports sections"><TabsTrigger value="overview">Overview</TabsTrigger><TabsTrigger value="findings">Anomalies & Findings</TabsTrigger><TabsTrigger value="predictions">Predictions</TabsTrigger><TabsTrigger value="kpis">KPIs</TabsTrigger><TabsTrigger value="models">Models</TabsTrigger></TabsList></div>
        <TabsContent value="overview" className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[
            ["Stored findings", String(insights.length), "Selected service and period"],
            ["Forecast warnings", String(warnings.length), "Fresh, validated predictions"],
            ["Fresh services", String(recentKpis.length), "Available KPI windows"],
            ["Active models", String(models.filter(m => m.state === "active").length), "Selected service scope"],
          ].map(([title, value, description]) => <Card key={title}><CardHeader><CardTitle>{title}</CardTitle><CardDescription>{description}</CardDescription></CardHeader><CardContent><p className="text-2xl font-mono text-primary">{loading || error ? "Unavailable" : value}</p></CardContent></Card>)}</div>
          <p className="text-xs text-muted-foreground">Findings combine rule evidence, KPI breaches, forecasts, and model anomalies. Severity indicates operational impact; anomaly scores describe unusualness.</p>
          {findingPanel}
        </TabsContent>
        <TabsContent value="findings">{findingPanel}</TabsContent>
        <TabsContent value="predictions" className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">Memory forecasts use recent trends and historical validation. Horizon starts at observation time. Missing or unreliable data produces an abstention.</p>
          {!forecasts.length && !loading && <p className="text-sm text-muted-foreground">No forecasts available.</p>}
          <div className="grid gap-3 md:grid-cols-2">{forecasts.map(f => <Card key={f.forecast_id}><CardHeader><CardTitle>{f.service} · {f.horizon_minutes} minutes</CardTitle><CardDescription>Observed {time(f.observed_at)} · {f.algorithm}</CardDescription></CardHeader><CardContent className="flex flex-col gap-3">
            <div>{badge(!f.data_fresh || !fresh(f.observed_at) ? "stale" : f.state)}</div>
            {f.state === "ready" ? <><p className="font-mono text-sm">Current {measurement("memory_fraction", f.values.current_memory_fraction)} · Projected {measurement("memory_fraction", f.values.projected_memory_fraction)}</p><p className="text-xs text-muted-foreground">Warning boundary: {measurement("memory_fraction", f.values.warning_threshold)} · Validation MAE: {measurement("memory_fraction", f.values.validation_mae_fraction)} percentage of limit</p><p className="text-sm">{f.values.warning ? "Trend crosses the warning boundary within this horizon." : "No projected boundary crossing within this horizon."}</p><p className="text-xs text-muted-foreground">Local trend estimate; no guaranteed failure time.</p></> : <p className="text-sm text-muted-foreground">No prediction: {readable(f.reason ?? "insufficient data")}.</p>}
          </CardContent></Card>)}</div>
          {chartService && <Card><CardHeader><CardTitle>{chartService} memory history</CardTitle><CardDescription>Observed memory fraction, before the forecast horizon</CardDescription></CardHeader><CardContent>{historyError ? <p role="alert">{historyError}</p> : <Trend windows={history} metric="memory_fraction" />}</CardContent></Card>}
        </TabsContent>
        <TabsContent value="kpis" className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">CPU in cores; memory as % of container limit. Missing metrics remain unavailable. Latency is the mean of 5-minute p95 snapshots.</p>
          <Table><TableHeader><TableRow><TableHead>Service / window</TableHead><TableHead>State</TableHead>{metrics.map(m => <TableHead key={m.key}>{m.label}<br /><span className="text-[10px]">{m.unit}</span></TableHead>)}</TableRow></TableHeader><TableBody>
            {kpis.map(w => <TableRow key={w.service}><TableCell><button className="text-primary hover:underline" onClick={() => setService(w.service)}>{w.service}</button><p className="text-[10px] text-muted-foreground">{time(w.window_end)}</p></TableCell><TableCell>{badge(w.data_fresh && fresh(w.window_end) ? "fresh" : "stale")}</TableCell>{metrics.map(m => <TableCell key={m.key} className="font-mono text-xs" title={`Latest source: ${time(w.quality.metric_last_at?.[m.key])}`}>{measurement(m.key, w.features[m.key])}{w.features[m.key] !== undefined && !fresh(w.quality.metric_last_at?.[m.key]) && <span className="block text-muted-foreground">Stale source</span>}</TableCell>)}</TableRow>)}
            {!kpis.length && <TableRow><TableCell colSpan={8}>No KPI windows available.</TableCell></TableRow>}
          </TableBody></Table>
          {chartService && <Card><CardHeader><CardTitle>{chartService} trend</CardTitle><CardDescription>Stored observations; gaps remain visible</CardDescription></CardHeader><CardContent className="flex flex-col gap-3"><label className="flex items-center gap-2 text-xs">Metric<select aria-label="KPI chart metric" className="rounded-md border border-input bg-background p-2" value={metric} onChange={e => setMetric(e.target.value)}>{metrics.map(m => <option key={m.key} value={m.key}>{m.label} ({m.unit})</option>)}</select></label>{historyError ? <p role="alert">{historyError}</p> : <Trend windows={history} metric={metric} />}</CardContent></Card>}
        </TabsContent>
        <TabsContent value="models" className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">Registry is read-only here. Training, promotion, and rollback use the operator workflow.</p>
          {!models.length && !loading && <p className="text-sm text-muted-foreground">Learning: no registered model for this scope. Capture reviewed healthy history, then train and promote a validated candidate.</p>}
          {models.map(m => <Card key={m.model_id}><CardHeader><CardTitle>{m.service} · {m.algorithm}</CardTitle><CardDescription>{m.model_id}</CardDescription></CardHeader><CardContent className="flex flex-col gap-3"><div>{badge(m.state)}</div><p className="text-xs text-muted-foreground">Training: {time(m.train_start)} – {time(m.train_end)}<br />Last inference: {time(m.last_inference_at)}<br />Features: {m.feature_names.join(", ")}</p><Details title="Validation results" data={m.validation} /></CardContent></Card>)}
        </TabsContent>
      </Tabs>
    </div>
    <footer className="shrink-0 border-t border-border bg-card px-4 py-2 text-[10px] font-mono text-muted-foreground">EIOS Reports · Stored telemetry · Retrieved {time(updatedAt)}</footer>
  </section>;
}
