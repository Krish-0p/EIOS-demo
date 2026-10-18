import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Network, RefreshCw, Search, Zap } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ServiceGraph } from "@/components/ServiceGraph";
import { STATUS, STATUS_ORDER, type StatusKey } from "@/components/serviceStatus";
import {
  api,
  type ServiceDetail,
  type ServiceGraph as Graph,
  type ServiceHealth,
  type ServicesView,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const DASH = "—";

function sinceLabel(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

function rate(value: number | null): string {
  if (value === null) return DASH;
  if (value === 0) return "0";
  if (value < 0.01) return "<0.01";
  return value.toFixed(2);
}

function percent(value: number | null): string {
  if (value === null) return DASH;
  return `${(value * 100).toFixed(value < 0.01 && value > 0 ? 2 : 1)}%`;
}

function millis(value: number | null): string {
  if (value === null) return DASH;
  return value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${value.toFixed(0)}ms`;
}

/** A resource bar reads faster than a number when scanning twenty rows. */
function ResourceCell({ value, warn }: { value: number | null; warn: number }) {
  if (value === null) {
    return <span className="text-muted-foreground">{DASH}</span>;
  }
  const hot = value >= warn;
  return (
    <div className="flex items-center gap-2">
      <Progress
        value={Math.min(100, value * 100)}
        className={cn("h-1.5 w-14", hot && "[&>div]:bg-destructive")}
      />
      <span className={cn("tabular-nums", hot && "text-destructive")}>
        {(value * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function StatusCell({ entry }: { entry: ServiceHealth }) {
  const style = STATUS[entry.status as StatusKey] ?? STATUS.unknown;
  return (
    <div className="flex items-center gap-2">
      <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", style.stripe)} aria-hidden />
      <div className="min-w-0">
        <div className="text-xs font-medium">{style.label}</div>
        <div className="truncate text-[11px] text-muted-foreground">{entry.reason}</div>
      </div>
    </div>
  );
}

function SummaryStrip({ services }: { services: ServiceHealth[] }) {
  const counts = useMemo(() => {
    const tally = new Map<StatusKey, number>();
    for (const entry of services) {
      const key = entry.status as StatusKey;
      tally.set(key, (tally.get(key) ?? 0) + 1);
    }
    return tally;
  }, [services]);

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
      {STATUS_ORDER.map((key) => (
        <div key={key} className="flex items-center gap-2">
          <span className={cn("h-2.5 w-2.5 rounded-full", STATUS[key].stripe)} aria-hidden />
          <span className="text-sm tabular-nums">{counts.get(key) ?? 0}</span>
          <span className="text-xs text-muted-foreground">{STATUS[key].label}</span>
        </div>
      ))}
    </div>
  );
}

function DetailPanel({
  detail,
  loading,
  onSelect,
}: {
  detail: ServiceDetail | null;
  loading: boolean;
  onSelect: (name: string) => void;
}) {
  if (!detail) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        {loading ? "Loading…" : "Pick a service to trace it."}
      </p>
    );
  }

  const style = STATUS[detail.service.status as StatusKey] ?? STATUS.unknown;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("h-2.5 w-2.5 rounded-full", style.stripe)} aria-hidden />
          <span className="font-mono text-sm font-medium">{detail.service.service}</span>
          <Badge variant="outline" className="text-[10px] uppercase tracking-wide">
            {style.label}
          </Badge>
        </div>
        <Button size="sm" variant="outline" asChild>
          <a href={detail.traces_url} target="_blank" rel="noreferrer">
            Traces
            <ArrowUpRight className="ml-1 h-3.5 w-3.5" aria-hidden />
          </a>
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Req/s", value: rate(detail.service.rate_per_sec) },
          { label: "Errors", value: percent(detail.service.error_ratio) },
          { label: "p95", value: millis(detail.service.latency_p95_ms) },
          { label: "p99", value: millis(detail.service.latency_p99_ms) },
        ].map((item) => (
          <div key={item.label} className="rounded-md border px-3 py-2">
            <div className="text-[11px] text-muted-foreground">{item.label}</div>
            <div className="font-mono text-sm tabular-nums">{item.value}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {(
          [
            ["Called by", detail.upstreams],
            ["Calls", detail.downstreams],
          ] as const
        ).map(([label, names]) => (
          <div key={label}>
            <div className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
              {label}
            </div>
            {names.length === 0 ? (
              <p className="text-xs text-muted-foreground">Nothing in the graph</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {names.map((name) => (
                  <button
                    key={name}
                    onClick={() => onSelect(name)}
                    className="rounded border px-1.5 py-0.5 font-mono text-[11px] hover:bg-accent hover:text-accent-foreground"
                  >
                    {name}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <Separator />

      <div>
        <div className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">
          Busiest operations
        </div>
        {detail.operations.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No spans for this service in the window.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Span</TableHead>
                <TableHead className="text-right">Req/s</TableHead>
                <TableHead className="text-right">Errors</TableHead>
                <TableHead className="text-right">p95</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {detail.operations.map((operation) => (
                <TableRow key={operation.span_name}>
                  <TableCell className="max-w-[220px] truncate font-mono text-xs">
                    {operation.span_name}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {rate(operation.rate_per_sec)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-mono text-xs tabular-nums",
                      (operation.error_ratio ?? 0) > 0 && "text-destructive",
                    )}
                  >
                    {percent(operation.error_ratio)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {millis(operation.latency_p95_ms)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {detail.incidents.length > 0 ? (
        <>
          <Separator />
          <div>
            <div className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">
              EIOS incidents on this service
            </div>
            <div className="space-y-1.5">
              {detail.incidents.slice(0, 6).map((incident) => (
                <div key={incident.incident_id} className="text-xs">
                  <span className="font-medium">{incident.title}</span>
                  <span className="ml-2 font-mono text-[11px] text-muted-foreground">
                    {incident.detector} · {incident.severity}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

export function ServicePanel({
  warnCpu = 0.85,
  onSummary,
  applicationId,
}: {
  applicationId?: string;
  warnCpu?: number;
  /** Reports how many services are not healthy, so the tab can badge it. */
  onSummary?: (unhealthy: number) => void;
}) {
  const [view, setView] = useState<ServicesView | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ServiceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const applicationScope = useRef(applicationId);
  applicationScope.current = applicationId;

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [services, dependencies] = await Promise.all([
        api.services(applicationId),
        api.serviceGraph(1, applicationId),
      ]);
      if (applicationScope.current !== applicationId) return;
      setView(services);
      setGraph(dependencies);
      setError(null);
      onSummary?.(
        services.services.filter(
          (entry) => entry.status === "critical" || entry.status === "degraded",
        ).length,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [onSummary, applicationId]);

  useEffect(() => {
    setView(null); setGraph(null); setSelected(null); setDetail(null);
    refresh();
    const timer = setInterval(refresh, 20000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let live = true;
    setDetailLoading(true);
    api
      .service(selected, applicationId)
      .then((found) => {
        if (live) setDetail(found);
      })
      .catch(() => {
        if (live) setDetail(null);
      })
      .finally(() => {
        if (live) setDetailLoading(false);
      });
    return () => {
      live = false;
    };
  }, [selected, applicationId]);

  const services = view?.services ?? [];

  const healthByName = useMemo(
    () => new Map(services.map((entry) => [entry.service, entry])),
    [services],
  );

  /** Worst first, so a broken service never sits below a healthy one. */
  const ordered = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return services
      .filter((entry) => !needle || entry.service.toLowerCase().includes(needle))
      .slice()
      .sort((a, b) => {
        // A service under an injected fault is the one being watched, so it
        // leads even while still healthy - the effect may take minutes to show.
        const byFault = Number(!!b.injected_fault) - Number(!!a.injected_fault);
        if (byFault !== 0) return byFault;
        const byStatus =
          (STATUS[a.status as StatusKey]?.rank ?? 9) -
          (STATUS[b.status as StatusKey]?.rank ?? 9);
        if (byStatus !== 0) return byStatus;
        return (b.rate_per_sec ?? 0) - (a.rate_per_sec ?? 0);
      });
  }, [services, filter]);

  return (
    <div className="space-y-6">
      {error ? (
        <Card className="border-destructive">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm text-destructive">
              Could not load service health
            </CardTitle>
            <CardDescription className="font-mono text-xs">{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {view?.open_faults?.length ? (
        <Card className="border-warning">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Zap className="h-4 w-4 text-warning" aria-hidden />
              {view.open_faults.length === 1
                ? "1 fault injected"
                : `${view.open_faults.length} faults injected`}
            </CardTitle>
            <CardDescription className="space-y-1 text-xs">
              {view.open_faults.map((fault) => (
                <div key={fault.window_id}>
                  <span className="font-mono">{fault.flag_key}</span> on{" "}
                  <button
                    onClick={() =>
                      fault.expected_entity && setSelected(fault.expected_entity)
                    }
                    className="font-mono underline underline-offset-2"
                  >
                    {fault.expected_entity ?? "an unmapped service"}
                  </button>
                  , open {sinceLabel(fault.started_at)}.
                </div>
              ))}
              <div className="pt-1 text-muted-foreground">
                Effects are not instant — a leak or cache fault can take minutes
                to move these numbers.
              </div>
            </CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {view?.degraded_sources.length ? (
        <Card className="border-warning">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">
              Reading with {view.degraded_sources.join(", ")} unavailable
            </CardTitle>
            <CardDescription className="text-xs">
              Rows below are incomplete until that source comes back.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="text-base">Service health</CardTitle>
            <CardDescription>
              RED metrics from the span_metrics connector and container stats,
              over the last {view?.window ?? "5m"}.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Filter services"
                aria-label="Filter services"
                className="h-8 w-40 rounded-md border bg-background pl-7 pr-2 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            </div>
            <Button size="sm" variant="outline" onClick={refresh} disabled={refreshing}>
              <RefreshCw
                className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
                aria-hidden
              />
              <span className="sr-only">Refresh</span>
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <SummaryStrip services={services} />
          <Separator />
          <ScrollArea className="max-h-[420px]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Service</TableHead>
                  <TableHead>Health</TableHead>
                  <TableHead className="text-right">Req/s</TableHead>
                  <TableHead className="text-right">Errors</TableHead>
                  <TableHead className="text-right">p95</TableHead>
                  <TableHead>CPU</TableHead>
                  <TableHead>Memory</TableHead>
                  <TableHead className="text-right">Incidents</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ordered.map((entry) => (
                  <TableRow
                    key={entry.service}
                    onClick={() => setSelected(entry.service)}
                    aria-selected={selected === entry.service}
                    className={cn(
                      "cursor-pointer",
                      selected === entry.service && "bg-accent/60",
                    )}
                  >
                    <TableCell className="font-mono text-xs font-medium">
                      <div className="flex flex-col gap-1">
                        <span>{entry.service}</span>
                        {entry.injected_fault ? (
                          <span
                            className="flex items-center gap-1 text-[10px] font-normal text-warning"
                            title={`Fault window open since ${entry.injected_fault.started_at}`}
                          >
                            <Zap className="h-3 w-3 shrink-0" aria-hidden />
                            {entry.injected_fault.flag_key} ·{" "}
                            {sinceLabel(entry.injected_fault.started_at)}
                          </span>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusCell entry={entry} />
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {rate(entry.rate_per_sec)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-mono text-xs tabular-nums",
                        (entry.error_ratio ?? 0) > 0 && "text-destructive",
                      )}
                    >
                      {percent(entry.error_ratio)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {millis(entry.latency_p95_ms)}
                    </TableCell>
                    <TableCell className="text-xs">
                      <ResourceCell value={entry.cpu_ratio} warn={warnCpu} />
                    </TableCell>
                    <TableCell className="text-xs">
                      <ResourceCell value={entry.memory_ratio} warn={0.85} />
                    </TableCell>
                    <TableCell className="text-right text-xs tabular-nums">
                      {entry.incidents_24h > 0 ? (
                        <Badge variant="outline" className="text-[10px]">
                          {entry.incidents_24h}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">{DASH}</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {ordered.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={8}
                      className="py-10 text-center text-sm text-muted-foreground"
                    >
                      {services.length === 0
                        ? "No service telemetry yet. Check Prometheus is reachable from the orchestrator."
                        : "No service matches that filter."}
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </ScrollArea>
        </CardContent>
      </Card>

      {/* min-w-0 on both children: a grid item defaults to min-width:auto, so
          the call graph's intrinsic SVG width (wider than the viewport once the
          topology has a few columns) would otherwise refuse to shrink and push
          the detail panel off the right edge. */}
      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Network className="h-4 w-4" aria-hidden />
              Call graph
            </CardTitle>
            <CardDescription>
              Derived by Jaeger from stored traces. Click a node to trace it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {graph ? (
              <ServiceGraph
                graph={graph}
                health={healthByName}
                selected={selected}
                onSelect={setSelected}
              />
            ) : (
              <p className="py-8 text-center text-sm text-muted-foreground">Loading…</p>
            )}
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle className="text-base">
              {selected ? `Tracing ${selected}` : "Service detail"}
            </CardTitle>
            <CardDescription>
              Operations, neighbours and any incidents EIOS raised against it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <DetailPanel
              detail={detail}
              loading={detailLoading}
              onSelect={setSelected}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
