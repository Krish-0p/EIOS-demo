import { useEffect, useState } from "react";
import { api, type TelemetrySource } from "@/lib/api";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";

export function TelemetrySourceStatus({ applicationId }: { applicationId: string }) {
  const [sources, setSources] = useState<TelemetrySource[] | null>(null);
  const [error, setError] = useState(false);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const controller = new AbortController();
    setSources(null);
    setError(false);
    const load = async () => {
      setNow(Date.now());
      try {
        const rows = await api.telemetrySources(applicationId, controller.signal);
        if (!controller.signal.aborted) { setSources(rows); setError(false); }
      } catch {
        if (!controller.signal.aborted) setError(true);
      }
    };
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [applicationId]);
  return <Card>
    <CardHeader><CardTitle>Telemetry Sources</CardTitle>
      <CardDescription>Source connection and data freshness are independent of Docker service state.</CardDescription>
    </CardHeader>
    <CardContent className="flex flex-col gap-3">
      {error && <Alert variant="destructive"><AlertDescription>Source status unavailable. Cached observations may be stale.</AlertDescription></Alert>}
      {!sources && !error && <p role="status">Loading telemetry sources...</p>}
      {sources?.length === 0 && <p>No telemetry sources activated for this application.</p>}
      {sources?.map(source => {
        const oldCheck = !!source.checked_at && now - Date.parse(source.checked_at) > 90000;
        const oldData = !!source.last_data_at && now - Date.parse(source.last_data_at) > source.freshness_seconds * 1000;
        const state = oldCheck || (source.state === "connected" && oldData) ? "stale" : source.state;
        const label = { kafka: "Kafka business events", prometheus: "Prometheus metrics", jaeger: "Jaeger traces", opensearch: "OpenSearch logs" }[source.kind];
        return <div key={source.source_id} className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2"><span>{label}</span><Badge variant={state === "disconnected" ? "destructive" : "outline"}>{state}</Badge></div>
          <p className="text-xs text-muted-foreground">Last source data: {source.last_data_at ? new Date(source.last_data_at).toLocaleString() : "Not observed"}. Last check: {source.checked_at ? new Date(source.checked_at).toLocaleString() : "Not observed"}.</p>
          {source.last_error && <p className="text-sm text-destructive">{source.last_error}</p>}
        </div>;
      })}
    </CardContent>
  </Card>;
}
