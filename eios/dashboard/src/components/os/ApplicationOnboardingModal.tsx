import { useCallback, useEffect, useState } from "react";
import { api, type Application, type CatalogService } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from "@/components/ui/table";
import { Loader2, RefreshCw } from "lucide-react";
import { TelemetrySourceStatus } from "./TelemetrySourceStatus";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onComplete: () => void;
  role?: string;
}
const emptyForm = { name: "", environment: "development", project: "", containerNames: "", labelSelector: "", prometheus: "", jaeger: "" };
const time = (value: string | null) => value ? new Date(value).toLocaleString() : "Not observed";

export function ApplicationOnboardingModal({ isOpen, onClose, onComplete, role = "viewer" }: Props) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [services, setServices] = useState<CatalogService[]>([]);
  const [loading, setLoading] = useState(false);
  const [registryLoading, setRegistryLoading] = useState(false);
  const [now, setNow] = useState(Date.now);
  const [discovering, setDiscovering] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [newService, setNewService] = useState("");
  const [filter, setFilter] = useState("");
  const canDiscover = role === "administrator" || role === "operator";
  const selected = applications.find(app => app.application_id === selectedId);
  const expired = (value: string | null, seconds: number) => !!value && now - Date.parse(value) > seconds * 1000;
  // Age cached observations even when an API outage prevents polling updates.
  const connection = selected?.connection_state === "connected" && expired(selected.discovery_checked_at, 90)
    ? "stale" : selected?.connection_state;

  useEffect(() => {
    if (!isOpen) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(timer);
  }, [isOpen]);

  const loadApplications = useCallback(async (signal?: AbortSignal) => {
    const list = await api.applications(signal);
    if (signal?.aborted) return;
    setApplications(list);
    setSelectedId(current => list.some(app => app.application_id === current) ? current : list[0]?.application_id ?? "");
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();
    setError(null);
    setRegistryLoading(true);
    void loadApplications(controller.signal).catch(err => {
      if (!controller.signal.aborted) setError(err.message ?? "Application registry unavailable.");
    }).finally(() => { if (!controller.signal.aborted) setRegistryLoading(false); });
    const timer = setInterval(() => {
      void loadApplications(controller.signal).catch(err => {
        if (!controller.signal.aborted) setError(err.message ?? "Application registry unavailable.");
      });
    }, 10000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [isOpen, loadApplications]);

  useEffect(() => {
    if (!isOpen || !selectedId) return;
    const controller = new AbortController();
    setServices([]);
    setLoading(true);
    const load = async () => {
      try {
        const rows = await api.applicationServices(selectedId, controller.signal);
        if (!controller.signal.aborted) { setServices(rows); setError(null); }
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Service catalog unavailable.");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [isOpen, selectedId]);

  const discover = async () => {
    setDiscovering(true);
    setError(null);
    setNotice("");
    try {
      const result = await api.discoverApplication(selectedId);
      const rows = await api.applicationServices(selectedId);
      setServices(rows);
      await loadApplications();
      setNotice(`Discovery completed: ${result.matched_containers} matching containers. Registered services are retained when offline.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Discovery failed. Registered services have been retained.");
      await loadApplications().catch(() => {});
    } finally { setDiscovering(false); }
  };

  const createApplication = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const labels: Record<string, string> = {};
      for (const entry of form.labelSelector.split(",").filter(value => value.trim())) {
        const index = entry.indexOf("=");
        if (index < 1 || !entry.slice(index + 1).trim()) throw new Error("Use key=value for each Docker label.");
        labels[entry.slice(0, index).trim()] = entry.slice(index + 1).trim();
      }
      const names = form.containerNames.split(",").map(name => name.trim()).filter(Boolean);
      if (!form.project.trim() && !Object.keys(labels).length && !names.length) {
        throw new Error("Choose a Compose project, Docker label, or explicit container name.");
      }
      const app = await api.createApplication({
        name: form.name.trim(), environment: form.environment.trim(), runtime_type: "docker",
        discovery_scope: { compose_project: form.project.trim() || undefined, labels, container_names: names },
        telemetry_config: Object.fromEntries([["prometheus_url", form.prometheus], ["jaeger_url", form.jaeger]].filter(([, value]) => value.trim())),
      });
      await loadApplications();
      setSelectedId(app.application_id);
      setShowCreate(false);
      setForm(emptyForm);
      setNotice("Application saved. Discover its services using the configured Docker scope.");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create application."); }
    finally { setSaving(false); }
  };

  const register = async () => {
    if (!newService.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.registerService(selectedId, { name: newService.trim() });
      setNewService("");
      setServices(await api.applicationServices(selectedId));
      setNotice("Service registered. Its runtime state stays unknown until discovery observes a matching service.");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not register service."); }
    finally { setSaving(false); }
  };

  const visible = services.filter(service => service.name.toLowerCase().includes(filter.toLowerCase()));
  return <Dialog open={isOpen} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="flex max-h-[90vh] max-w-5xl flex-col overflow-y-auto">
      <DialogHeader>
        <DialogTitle>Applications & Service Catalog</DialogTitle>
        <DialogDescription>Register an application, discover its Docker services, and keep their history when containers stop.</DialogDescription>
      </DialogHeader>
      {error && <Alert variant="destructive"><AlertTitle>Operation unavailable</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
      {notice && <Alert><AlertTitle>Catalog updated</AlertTitle><AlertDescription>{notice}</AlertDescription></Alert>}
      <div className="flex flex-wrap items-end gap-3">
        <Field className="min-w-56 flex-1">
          <FieldLabel htmlFor="application-selector">Application</FieldLabel>
          <Select value={selectedId} onValueChange={id => { setSelectedId(id); setNotice(""); setError(null); }} disabled={discovering || saving}>
            <SelectTrigger id="application-selector"><SelectValue placeholder="Choose an application" /></SelectTrigger>
            <SelectContent><SelectGroup>{applications.map(app =>
              <SelectItem key={app.application_id} value={app.application_id}>{app.name} · {app.environment}</SelectItem>
            )}</SelectGroup></SelectContent>
          </Select>
        </Field>
        {role === "administrator" && <Button variant="outline" onClick={() => setShowCreate(!showCreate)} disabled={saving}>Add Application</Button>}
        <Button onClick={() => void discover()} disabled={!selectedId || discovering || !canDiscover}>
          {discovering ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <RefreshCw data-icon="inline-start" />}
          {discovering ? "Discovering..." : "Discover Services"}
        </Button>
      </div>
      {showCreate && <Card>
        <CardHeader><CardTitle>Add Application</CardTitle><CardDescription>At least one Docker scope is required. Multiple selectors narrow the discovery.</CardDescription></CardHeader>
        <CardContent><form onSubmit={createApplication} className="flex flex-col gap-4">
          <FieldGroup className="grid gap-4 sm:grid-cols-2">
            {([
              ["name", "Application Name", "My application", true],
              ["environment", "Environment", "development", true],
              ["project", "Docker Compose Project", "my-compose-project", false],
              ["containerNames", "Container Names", "payment, checkout", false],
              ["labelSelector", "Docker Labels", "team=payments, environment=demo", false],
              ["prometheus", "Prometheus Endpoint", "http://prometheus:9090", false],
              ["jaeger", "Jaeger Endpoint", "http://jaeger:16686", false],
            ] as const).map(([key, label, placeholder, required]) => <Field key={key}>
              <FieldLabel htmlFor={`application-${key}`}>{label}</FieldLabel>
              <Input id={`application-${key}`} value={form[key]} placeholder={placeholder} required={required}
                onChange={event => setForm(previous => ({ ...previous, [key]: event.target.value }))} disabled={saving} />
            </Field>)}
          </FieldGroup>
          <p className="text-sm text-muted-foreground">Endpoint configuration is saved. Telemetry state reflects persisted observations; saving an endpoint does not establish a live connection.</p>
          <Button type="submit" disabled={saving}>{saving ? "Saving..." : "Save Application"}</Button>
        </form></CardContent>
      </Card>}
      {selected && <TelemetrySourceStatus key={selected.application_id} applicationId={selected.application_id} />}
      {selected && <Card>
        <CardHeader><CardTitle>{selected.name}</CardTitle>
          <CardDescription>{selected.environment} · Docker · Application ID: {selected.application_id}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">Discovery: {connection?.replaceAll("_", " ")}</Badge>
            <Badge variant="secondary">{loading && !services.length ? "Loading services..." : `${services.length} registered services`}</Badge>
            <Badge variant="outline">Telemetry configuration: {selected.telemetry_connection_state.replaceAll("_", " ")}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">Last successful discovery: {time(selected.discovery_checked_at)}</p>
          {selected.discovery_error && <p role="status" className="text-sm text-destructive">{selected.discovery_error}. Last observations are retained.</p>}
          <Field>
            <FieldLabel htmlFor="service-filter">Filter Services</FieldLabel>
            <Input id="service-filter" value={filter} onChange={event => setFilter(event.target.value)} placeholder="Service name" />
          </Field>
          <div className="max-h-80 overflow-auto rounded-md border">
            <Table aria-label="Registered services" aria-busy={loading}>
              <TableHeader><TableRow>
                <TableHead>Service</TableHead><TableHead>Runtime</TableHead><TableHead>Health Check</TableHead>
                <TableHead>Telemetry</TableHead><TableHead>Latest Telemetry</TableHead><TableHead>Containers</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {!visible.length && <TableRow><TableCell colSpan={6}>{loading ? "Loading registered services..." : "No registered services match. Discover services or register one below."}</TableCell></TableRow>}
                {visible.map(service => {
                  const current = service.runtime_instances.filter(instance => instance.runtime_state !== "missing");
                  const runtimeState = connection !== "connected" ? "unknown" : service.runtime_state;
                  const telemetryState = service.telemetry_state === "fresh" && expired(service.last_telemetry_at, 240) ? "stale" : service.telemetry_state;
                  const health = runtimeState !== "online" ? "unknown" : current.some(instance => instance.health_state === "unhealthy")
                    ? "unhealthy" : current.some(instance => instance.health_state === "healthy") ? "healthy" : "unknown";
                  return <TableRow key={service.service_id}>
                    <TableCell><span className="font-medium">{service.name}</span><p className="text-xs text-muted-foreground">{service.service_id}</p></TableCell>
                    <TableCell><Badge variant="outline">{runtimeState}</Badge>{connection !== "connected" && <p className="text-xs text-muted-foreground">{connection}; last: {service.last_runtime_state}</p>}</TableCell>
                    <TableCell>{health}</TableCell>
                    <TableCell><Badge variant={telemetryState === "fresh" ? "secondary" : "outline"}>{telemetryState.replaceAll("_", " ")}</Badge></TableCell>
                    <TableCell>{time(service.last_telemetry_at)}</TableCell>
                    <TableCell>{(current.length ? current : service.runtime_instances).map(instance => instance.container_name).join(", ") || "Not bound"}</TableCell>
                  </TableRow>;
                })}
              </TableBody>
            </Table>
          </div>
          {canDiscover && <div className="flex items-end gap-3">
            <Field className="flex-1"><FieldLabel htmlFor="register-service">Register Service Manually</FieldLabel>
              <Input id="register-service" value={newService} onChange={event => setNewService(event.target.value)} placeholder="Logical service name" disabled={saving} />
            </Field>
            <Button variant="outline" onClick={() => void register()} disabled={saving || !newService.trim()}>Register Service</Button>
          </div>}
        </CardContent>
      </Card>}
      {!applications.length && !error && <p role="status">{registryLoading ? "Loading applications..." : "No applications registered. An administrator can add one."}</p>}
      <DialogFooter><Button onClick={onComplete}>Done</Button></DialogFooter>
    </DialogContent>
  </Dialog>;
}
