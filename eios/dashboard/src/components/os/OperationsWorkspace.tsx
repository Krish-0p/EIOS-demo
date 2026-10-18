import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, RefreshCw, X } from "lucide-react";
import { api, type Application, type ServiceHealth } from "@/lib/api";
import { operations, subscribeOperations, type Data, type Overview, type OperationalIncident } from "@/lib/operations";
import { ServiceGraph } from "@/components/ServiceGraph";
import { ServicePanel } from "@/components/ServicePanel";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectGroup, SelectItem } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "@/components/ui/table";

const timestamp = (value: unknown) => typeof value === "string" ? new Date(value).toLocaleString() : "Unavailable";
const number = (value: unknown, suffix = "") => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}${suffix}` : "Unavailable";
const text = (value: unknown) => value === null || value === undefined ? "Unavailable" : typeof value === "object" ? JSON.stringify(value) : String(value);

function Notice({ children }: { children: React.ReactNode }) {
  return <Alert><AlertDescription>{children}</AlertDescription></Alert>;
}
function DataView({ value }: { value: unknown }) {
  return <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-xs select-text">{JSON.stringify(value, null, 2)}</pre>;
}
function Choice({ id, label, value, options, onChange, disabled = false }: {
  id: string; label: string; value: string; options: { value: string; label: string; disabled?: boolean }[];
  onChange: (value: string) => void; disabled?: boolean;
}) {
  return <Field><FieldLabel htmlFor={id}>{label}</FieldLabel><Select value={value} onValueChange={onChange} disabled={disabled}>
    <SelectTrigger id={id}><SelectValue placeholder={`Select ${label.toLowerCase()}`} /></SelectTrigger>
    <SelectContent><SelectGroup>{options.map(o => <SelectItem key={o.value} value={o.value} disabled={o.disabled}>{o.label}</SelectItem>)}</SelectGroup></SelectContent>
  </Select></Field>;
}

export function OperationsWorkspace({ role, applicationId, onApplicationChange, onOpenApplications, onClose }: {
  role: string; applicationId: string; onApplicationChange: (id: string) => void; onOpenApplications: () => void; onClose: () => void;
}) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [view, setView] = useState<Overview | null>(null);
  const [incidents, setIncidents] = useState<OperationalIncident[]>([]);
  const [anomalies, setAnomalies] = useState<Data[]>([]);
  const [selectedIncident, setSelectedIncident] = useState<string | null>(null);
  const [incident, setIncident] = useState<OperationalIncident | null>(null);
  const [selectedService, setSelectedService] = useState<string | null>(null);
  const [serviceDetail, setServiceDetail] = useState<Data | null>(null);
  const [evidence, setEvidence] = useState<Data | null>(null);
  const [experiments, setExperiments] = useState<Data[]>([]);
  const [evaluations, setEvaluations] = useState<Data[]>([]);
  const [scenarios, setScenarios] = useState<Data[]>([]);
  const [scenario, setScenario] = useState("paymentFailure");
  const [target, setTarget] = useState("");
  const [duration, setDuration] = useState("120");
  const [variant, setVariant] = useState("");
  const [loadMode, setLoadMode] = useState("existing");
  const [users, setUsers] = useState("10");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [tab, setTab] = useState("overview");
  const [notes, setNotes] = useState("");
  const [audit, setAudit] = useState<Data[] | null>(null);
  const [integrity, setIntegrity] = useState<Data | null>(null);
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const [evaluationCandidate, setEvaluationCandidate] = useState("");
  const [experimentDetail, setExperimentDetail] = useState<Data | null>(null);
  const [proposalAction, setProposalAction] = useState("automatic");
  const [annotationRun, setAnnotationRun] = useState("");
  const [annotationAnomaly, setAnnotationAnomaly] = useState("");
  const [annotationVerdict, setAnnotationVerdict] = useState("exclude");
  const [annotationNotes, setAnnotationNotes] = useState("");
  const [accounts, setAccounts] = useState<Data[] | null>(null);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("operator");
  const [recovery, setRecovery] = useState<Data | null>(null);
  const epoch = useRef(0);
  const activeApplication = useRef(applicationId);
  activeApplication.current = applicationId;
  const refreshPending = useRef<{ applicationId: string; epoch: number } | null>(null);
  const operator = role === "operator" || role === "administrator";
  const administrator = role === "administrator";

  useEffect(() => {
    let live = true;
    api.applications().then(items => {
      if (!live) return;
      setApplications(items);
      if (!items.some(a => a.application_id === applicationId) && items[0]) onApplicationChange(items[0].application_id);
    }).catch(err => { if (live) setError(String(err)); });
    return () => { live = false; };
  }, [applicationId, onApplicationChange]);

  const refresh = useCallback(async () => {
    if (!applicationId || applicationId !== activeApplication.current ||
        refreshPending.current?.applicationId === applicationId && refreshPending.current.epoch === epoch.current) return;
    const version = epoch.current;
    const pending = { applicationId, epoch: version };
    refreshPending.current = pending;
    setLoading(true);
    try {
      const [overview, records, signals, runs, results, definitions] = await Promise.all([
        operations.overview(applicationId), operations.incidents(applicationId), operations.anomalies(applicationId),
        operations.experiments(applicationId), operations.evaluations(applicationId), operations.scenarios(applicationId),
      ]);
      if (version !== epoch.current || applicationId !== activeApplication.current) return;
      setView(overview); setIncidents(records); setAnomalies(signals); setExperiments(runs); setEvaluations(results); setScenarios(definitions); setError(null);
    } catch (err) {
      if (version === epoch.current) { setError(err instanceof Error ? err.message : String(err)); setView(null); }
    } finally { if (refreshPending.current === pending) refreshPending.current = null; if (version === epoch.current) setLoading(false); }
  }, [applicationId]);

  useEffect(() => {
    epoch.current += 1;
    setView(null); setIncident(null); setSelectedIncident(null); setSelectedService(null); setServiceDetail(null); setEvidence(null);
    setIncidents([]); setAnomalies([]); setExperiments([]); setEvaluations([]); setSelectedRuns([]); setExperimentDetail(null);
    setTarget(""); setMessage(null); setAnnotationRun(""); setScenarios([]);
    void refresh();
    const interval = setInterval(refresh, 20000);
    if (!applicationId) return () => clearInterval(interval);
    const unsubscribe = subscribeOperations(applicationId, () => { void refresh(); }, setConnected);
    return () => { clearInterval(interval); unsubscribe(); };
  }, [applicationId, refresh]);

  useEffect(() => {
    if (!selectedIncident || !applicationId) { setIncident(null); return; }
    let live = true;
    operations.incident(applicationId,selectedIncident).then(record => { if (live) setIncident(record); })
      .catch(err => { if (live) { setIncident(null); setError(String(err)); } });
    return () => { live = false; };
  }, [applicationId, selectedIncident, view]);

  const definition = scenarios.find(s => s.scenario === scenario);
  useEffect(() => {
    setVariant(definition?.default_variant ?? "");
    const expected = view?.topology.services.find(s => s.service === definition?.expected_service);
    if (expected) setTarget(expected.service_id);
  }, [definition?.default_variant, definition?.expected_service, applicationId]);

  const action = async (work: () => Promise<unknown>) => {
    if (busy) return;
    const version=epoch.current;
    setBusy(true); setError(null); setMessage(null);
    try {
      const result = await work();
      if (version !== epoch.current || applicationId !== activeApplication.current) return;
      setMessage("Request recorded. Review the resulting state and evidence below.");
      await refresh();
      if (selectedIncident) setIncident(await operations.incident(applicationId,selectedIncident));
      return result;
    } catch (err) { if (version === epoch.current) setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };

  const selectService = (name: string) => {
    const node = view?.topology.services.find(s => s.service === name);
    setSelectedService(name); setServiceDetail(null); setEvidence(null);
    if (node) void action(async () => { setServiceDetail(await operations.service(applicationId,node.service_id)); });
  };
  const nodes = view?.topology.services ?? [];
  const fresh = view?.topology.state === "available";
  const graph = { nodes: nodes.map(s => s.service), edges: view?.topology.edges ?? [], available: nodes.length > 0, reason: view?.topology.reason ?? null };
  const selectedNode = nodes.find(n => n.service === selectedService);

  return <Card className="w-full shrink-0" aria-label="EIOS Operations workspace">
    <CardHeader>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1"><CardTitle className="flex items-center gap-2"><Activity /> Operations</CardTitle>
          <CardDescription>Observe services, investigate incidents, approve actions, and measure recovery.</CardDescription></div>
        <div className="flex flex-wrap items-center gap-2"><Badge variant={connected ? "default" : "secondary"}>{connected ? "Live updates connected" : "Polling; live feed disconnected"}</Badge>
          <Button variant="outline" size="sm" onClick={onOpenApplications}>Applications</Button>
          <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}><RefreshCw data-icon="inline-start" />{loading ? "Loading" : "Refresh"}</Button>
          <Button variant="ghost" size="icon" aria-label="Close Operations" onClick={onClose}><X /></Button></div>
      </div>
      <FieldGroup><Choice id="operations-application" label="Application" value={applicationId}
        options={applications.map(a => ({ value: a.application_id, label: `${a.name} · ${a.environment}` }))} onChange={onApplicationChange} /></FieldGroup>
    </CardHeader>
    <CardContent className="flex flex-col gap-4">
      {error && <Alert variant="destructive"><AlertTitle>Unavailable</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
      {message && <Notice>{message}</Notice>}
      {!applicationId && <Notice>Register an application to begin. Open Applications to create or discover its services.</Notice>}
      {view && !fresh && <Notice>{view.topology.reason ?? "Awaiting current topology observations."} Metrics and counts cannot establish current health.</Notice>}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto flex flex-wrap justify-start">
          <TabsTrigger value="overview">Overview</TabsTrigger><TabsTrigger value="topology">Service Explorer</TabsTrigger>
          <TabsTrigger value="incidents">Incidents</TabsTrigger><TabsTrigger value="experiments">Experiment Lab</TabsTrigger>
          <TabsTrigger value="evaluation">Evaluation</TabsTrigger>{administrator && <TabsTrigger value="governance">Governance</TabsTrigger>}
        </TabsList>
        <TabsContent value="overview" className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">{[
            ["Registered services", view ? nodes.length : null], ["Healthy", fresh ? nodes.filter(n => n.status === "healthy").length : null],
            ["Degraded / critical", fresh ? nodes.filter(n => n.status === "degraded" || n.status === "critical").length : null],
            ["Offline", fresh ? nodes.filter(n => n.status === "offline").length : null], ["Open incidents", view?.open_incidents],
          ].map(([label,value]) => <Card key={String(label)}><CardHeader><CardDescription>{label}</CardDescription><CardTitle>{value == null ? "Unavailable" : value}</CardTitle></CardHeader></Card>)}</div>
          <p className="text-sm text-muted-foreground">Observed {timestamp(view?.topology.observed_at)} · {view?.active_findings ?? "Unavailable"} active findings · {view?.anomalies_24h ?? "Unavailable"} anomalies in 24 hours</p>
          <div className="flex flex-wrap gap-2">{view?.sources.map(source => <Badge key={source.source_id} variant="outline">{source.kind}: {source.state}</Badge>)}</div>
          <Notice>Dependencies: {view?.topology.dependency_state ?? "unknown"}. Stale and declared edges are labelled in service details; absent traces never create invented dependencies.</Notice>
          <ServiceGraph graph={graph} health={new Map<string,ServiceHealth>(nodes.map(n => [n.service,n]))} selected={selectedService} onSelect={selectService} />
          {selectedNode && <Card><CardHeader><CardTitle>{selectedNode.service}</CardTitle><CardDescription>{selectedNode.status.toUpperCase()} · {selectedNode.reason}</CardDescription></CardHeader>
            <CardContent className="flex flex-col gap-3"><div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {[['Health score',number(selectedNode.health_score)],['CPU',number(selectedNode.metrics.cpu_cores,' cores')],['Memory',number(selectedNode.metrics.memory_fraction === undefined ? null : selectedNode.metrics.memory_fraction*100,'%')],
                ['Requests',number(selectedNode.metrics.request_rate_per_sec,'/s')],['Errors',number(selectedNode.metrics.error_fraction === undefined ? null : selectedNode.metrics.error_fraction*100,'%')],['p95',number(selectedNode.metrics.latency_p95_ms,' ms')],
                ['Runtime',selectedNode.runtime_state],['Telemetry',selectedNode.telemetry_state]].map(([label,value]) => <div key={label}><p className="text-sm text-muted-foreground">{label}</p><p>{value}</p></div>)}</div>
              {serviceDetail && <DataView value={{ dependencies: serviceDetail.dependencies, incidents: serviceDetail.incidents, findings: serviceDetail.findings, metric_timestamps: selectedNode.metric_timestamps, penalties: selectedNode.health_penalties }} />}
              {evidence && <DataView value={evidence} />}
            </CardContent><CardFooter className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void action(async () => setEvidence(await operations.evidence(applicationId,selectedNode.service_id,"trace")))}>Retrieve recent traces</Button>
              <Button variant="outline" disabled={busy} onClick={() => void action(async () => setEvidence(await operations.evidence(applicationId,selectedNode.service_id,"log")))}>Retrieve recent logs</Button></CardFooter></Card>}
          <Card><CardHeader><CardTitle>Recent activity</CardTitle><CardDescription>Persisted incident events and observed service changes</CardDescription></CardHeader><CardContent className="flex flex-col gap-2">
            {!view?.recent_activity.length && !view?.recent_service_changes?.length && <Notice>No recorded activity yet.</Notice>}
            {view?.recent_service_changes?.map((change,i) => <p key={`change-${i}`} className="text-sm">{timestamp(change.at)} · {change.service}: {change.from ?? "unknown"} to {change.to}</p>)}
            {view?.recent_activity.slice(0,12).map(item => <p key={item.event_id} className="text-sm">{timestamp(item.at)} · {item.kind} · {item.actor}</p>)}
          </CardContent></Card>
        </TabsContent>
        <TabsContent value="topology">{applicationId && <ServicePanel applicationId={applicationId} />}</TabsContent>
        <TabsContent value="incidents" className="flex flex-col gap-4">
          <Table><TableHeader><TableRow><TableHead>Incident</TableHead><TableHead>Severity</TableHead><TableHead>State</TableHead><TableHead>Created</TableHead></TableRow></TableHeader><TableBody>
            {incidents.map(item => <TableRow key={item.incident_id}><TableCell><Button variant="link" onClick={() => { setSelectedIncident(item.incident_id); setIncident(null); }}>{item.title}</Button></TableCell><TableCell>{item.severity}</TableCell><TableCell><Badge variant="outline">{item.state}</Badge></TableCell><TableCell>{timestamp(item.created_at)}</TableCell></TableRow>)}
          </TableBody></Table>
          {!incidents.length && <Notice>No correlated incidents recorded for this application.</Notice>}
          {selectedIncident && !incident && <Notice>Incident detail loading or unavailable.</Notice>}
          {incident && <Card><CardHeader><CardTitle>{incident.title}</CardTitle><CardDescription>{incident.incident_id} · {incident.state} · {incident.severity}</CardDescription></CardHeader><CardContent className="flex flex-col gap-4">
            <DataView value={incident.summary} />
            <Tabs defaultValue="timeline"><TabsList className="h-auto flex flex-wrap justify-start"><TabsTrigger value="timeline">Timeline</TabsTrigger><TabsTrigger value="evidence">Evidence</TabsTrigger><TabsTrigger value="rca">RCA</TabsTrigger><TabsTrigger value="ai">AI investigation</TabsTrigger><TabsTrigger value="remediation">Remediation</TabsTrigger><TabsTrigger value="verification">Verification</TabsTrigger></TabsList>
              <TabsContent value="timeline"><Table><TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Event</TableHead><TableHead>Actor</TableHead><TableHead>Detail</TableHead></TableRow></TableHeader><TableBody>{incident.timeline?.map(event => <TableRow key={event.event_id}><TableCell>{timestamp(event.at)}</TableCell><TableCell>{event.kind}</TableCell><TableCell>{event.actor}</TableCell><TableCell className="max-w-72 break-words">{text(event.detail)}</TableCell></TableRow>)}</TableBody></Table></TabsContent>
              <TabsContent value="evidence" className="flex flex-col gap-3">{incident.anomalies?.map(a => <Card key={a.anomaly_id}><CardHeader><CardTitle>{a.title}</CardTitle><CardDescription>{a.service} · {a.detector} · {a.category} · {a.severity}</CardDescription></CardHeader><CardContent><DataView value={{ anomaly_id: a.anomaly_id, values: a.current_values, baseline: a.baseline, evidence: a.evidence, correlation: a.correlation }} /></CardContent></Card>)}</TabsContent>
              <TabsContent value="rca" className="flex flex-col gap-3"><Notice>RCA scores are explainable heuristic rankings, not calibrated probabilities.</Notice>{incident.rca?.length ? <><p>{incident.rca[0].state}: {incident.rca[0].explanation}</p><Table><TableHeader><TableRow><TableHead>Service</TableHead><TableHead>Ranking score</TableHead><TableHead>Score breakdown</TableHead><TableHead>Evidence</TableHead></TableRow></TableHeader><TableBody>{incident.rca[0].candidates.map((candidate: Data) => <TableRow key={candidate.service_id}><TableCell>{candidate.service}</TableCell><TableCell>{candidate.score}/100</TableCell><TableCell>{text(candidate.score_breakdown)}</TableCell><TableCell>{text(candidate.anomaly_ids)}</TableCell></TableRow>)}</TableBody></Table></> : <Notice>Awaiting sufficient evidence for RCA.</Notice>}</TabsContent>
              <TabsContent value="ai" className="flex flex-col gap-3"><Notice>AI-generated explanations supplement deterministic evidence. Provider failures do not block incident handling.</Notice><Button disabled={busy || !operator} onClick={() => void action(() => operations.investigate(applicationId,incident.incident_id))}>Investigate current evidence</Button>
                {!incident.investigations?.length && <Notice>No AI investigation recorded. Configure the investigation provider to enable it.</Notice>}{incident.investigations?.map(run => <Card key={run.investigation_id}><CardHeader><CardTitle>{run.state}</CardTitle><CardDescription>{timestamp(run.created_at)} · {run.model ?? "Provider unconfigured"}</CardDescription></CardHeader><CardContent className="flex flex-col gap-2">{run.error && <Notice>{run.error}</Notice>}<DataView value={run.output} /><details><summary>Retrieved evidence and tools</summary><DataView value={run.tool_records} /></details></CardContent></Card>)}</TabsContent>
              <TabsContent value="remediation" className="flex flex-col gap-3"><Notice>Service changes require administrator approval. Execution uses registered service identities; command acceptance does not establish recovery.</Notice>
                <FieldGroup><Choice id="proposal-action" label="Recommendation" value={proposalAction} options={[{value:"automatic",label:"Use deterministic recommendation"},...['restart_service','start_service','stop_service','run_health_check','capture_diagnostics'].map(value => ({value,label:value.replaceAll('_',' ')}))]} onChange={setProposalAction} />
                  <Field><FieldLabel htmlFor="approval-notes">Decision notes</FieldLabel><Input id="approval-notes" value={notes} onChange={event => setNotes(event.target.value)} /></Field></FieldGroup>
                <Button disabled={busy || !operator || !['ROOT_CAUSE_IDENTIFIED','AWAITING_APPROVAL'].includes(incident.state)} onClick={() => void action(() => operations.propose(applicationId,incident.incident_id,proposalAction === "automatic" ? undefined : proposalAction))}>Create recommendation</Button>
                {incident.proposals?.map(p => <Card key={p.proposal_id}><CardHeader><CardTitle>{p.action_type.replaceAll('_',' ')}</CardTitle><CardDescription>{p.state} · Risk: {p.risk} · Approval expires {timestamp(p.expires_at)}</CardDescription></CardHeader><CardContent className="flex flex-col gap-2"><p>{p.reason}</p><p>{p.expected_effect}</p><DataView value={{ policy: p.policy, approval_id: p.approval_id, decision: p.decision, decided_by: p.decided_by }} /></CardContent>
                  <CardFooter className="flex flex-wrap gap-2"><Button disabled={busy || p.state !== 'pending' || !(administrator || p.risk === 'low' && operator)} onClick={() => void action(() => operations.decide(applicationId,p.proposal_id,"approve",notes))}>Approve</Button><Button variant="outline" disabled={busy || p.state !== 'pending' || !(administrator || p.risk === 'low' && operator)} onClick={() => void action(() => operations.decide(applicationId,p.proposal_id,"reject",notes))}>Reject</Button><Button variant="destructive" disabled={busy || !operator || p.state !== 'approved'} onClick={() => void action(() => operations.execute(applicationId,p.proposal_id))}>Execute approved action</Button></CardFooter></Card>)}
                {!!incident.executions?.length && <DataView value={incident.executions} />}
              </TabsContent>
              <TabsContent value="verification" className="flex flex-col gap-3"><Notice>Resolution requires distinct fresh observations and sustained healthy affected services. Missing telemetry produces INCONCLUSIVE.</Notice>{incident.verifications?.length ? incident.verifications.map(v => <Card key={v.verification_id}><CardHeader><CardTitle>{v.outcome}</CardTitle><CardDescription>Observation deadline: {timestamp(v.deadline)}</CardDescription></CardHeader><CardContent><DataView value={{ criteria: v.criteria, before: v.before_snapshot, after: v.samples }} /></CardContent></Card>) : <Notice>No recovery verification recorded yet.</Notice>}</TabsContent>
            </Tabs>
          </CardContent><CardFooter>{['ESCALATED','ROOT_CAUSE_IDENTIFIED','ACTION_RECOMMENDED','AWAITING_APPROVAL'].includes(incident.state) && <Button variant="outline" disabled={busy || !operator} onClick={() => void action(() => operations.reopen(applicationId,incident.incident_id))}>Return to investigation</Button>}</CardFooter></Card>}
          <Card><CardHeader><CardTitle>Raw anomalies</CardTitle><CardDescription>Source detections are preserved independently of correlation.</CardDescription></CardHeader><CardContent><Table><TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Service</TableHead><TableHead>Detector</TableHead><TableHead>Category</TableHead></TableRow></TableHeader><TableBody>{anomalies.slice(0,30).map(a => <TableRow key={a.anomaly_id}><TableCell>{timestamp(a.detected_at)}</TableCell><TableCell>{a.service}</TableCell><TableCell>{a.detector}</TableCell><TableCell>{a.category}</TableCell></TableRow>)}</TableBody></Table></CardContent></Card>
        </TabsContent>
        <TabsContent value="experiments" className="flex flex-col gap-4">
          <Notice>One controlled experiment may run at a time. Faults are restored at their deadline; failed cleanup remains visible and blocks the next experiment.</Notice>
          <form onSubmit={event => { event.preventDefault(); void action(() => operations.startExperiment(applicationId,{ scenario, service_id: target, duration_seconds: Number(duration), variant: variant || undefined, load_profile: loadMode === "existing" ? {mode:"existing"} : {mode:"managed",users:Number(users),spawn_rate:1} })); }}>
            <FieldGroup className="md:grid md:grid-cols-2"><Choice id="experiment-scenario" label="Scenario" value={scenario} options={scenarios.map(s => ({value:s.scenario,label:`${s.scenario}${s.supported ? '' : ' (unavailable)'}`,disabled:!s.supported}))} onChange={setScenario} />
              <Choice id="experiment-target" label="Target service" value={target} options={nodes.map(n => ({value:n.service_id,label:n.service}))} onChange={setTarget} />
              <Field><FieldLabel htmlFor="experiment-duration">Duration (seconds)</FieldLabel><Input id="experiment-duration" type="number" min={15} max={3600} value={duration} onChange={event => setDuration(event.target.value)} required /></Field>
              {definition && definition.variants?.length > 0 && <Choice id="experiment-variant" label="Fault variant" value={variant} options={definition.variants.map((value: string) => ({value,label:value}))} onChange={setVariant} />}
              <Choice id="experiment-load" label="Load profile" value={loadMode} options={[{value:"existing",label:"Observe existing traffic"},{value:"managed",label:"Managed Locust load (requires configuration)"}]} onChange={setLoadMode} />
              {loadMode === "managed" && <Field><FieldLabel htmlFor="experiment-users">Concurrent users</FieldLabel><Input id="experiment-users" type="number" min={1} max={200} value={users} onChange={event => setUsers(event.target.value)} /></Field>}
            </FieldGroup><Button type="submit" className="mt-3" disabled={busy || !operator || !target || !definition?.supported}>Start controlled experiment</Button>
          </form>
          <Table><TableHeader><TableRow><TableHead>Scenario</TableHead><TableHead>State</TableHead><TableHead>Start</TableHead><TableHead>End</TableHead><TableHead>Actions</TableHead></TableRow></TableHeader><TableBody>{experiments.map(run => <TableRow key={run.experiment_id}><TableCell>{run.scenario}</TableCell><TableCell><Badge variant="outline">{run.state}</Badge>{run.error && <p className="text-sm text-destructive">{run.error}</p>}</TableCell><TableCell>{timestamp(run.started_at)}</TableCell><TableCell>{timestamp(run.ended_at)}</TableCell><TableCell><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void action(async () => setExperimentDetail(await operations.experiment(applicationId,run.experiment_id)))}>Artifacts</Button>{!['COMPLETED','FAILED'].includes(run.state) && <Button size="sm" variant="destructive" disabled={busy || !operator} onClick={() => void action(() => operations.stopExperiment(applicationId,run.experiment_id))}>Stop / retry cleanup</Button>}</div></TableCell></TableRow>)}</TableBody></Table>
          {!experiments.length && <Notice>No experiments recorded. Run a healthy baseline before fault experiments to obtain negative controls for evaluation.</Notice>}
          {experimentDetail && <DataView value={experimentDetail} />}
          {operator && <Card><CardHeader><CardTitle>Ground-truth annotation</CardTitle><CardDescription>Record an independent judgement. Leave anomaly ID empty only to exclude an entire run.</CardDescription></CardHeader><CardContent><FieldGroup>
            <Choice id="annotation-run" label="Experiment" value={annotationRun} options={experiments.map(r => ({value:r.experiment_id,label:`${r.scenario} · ${timestamp(r.started_at)}`}))} onChange={setAnnotationRun} />
            <Field><FieldLabel htmlFor="annotation-anomaly">Anomaly ID (optional)</FieldLabel><Input id="annotation-anomaly" value={annotationAnomaly} onChange={event => setAnnotationAnomaly(event.target.value)} /></Field>
            <Choice id="annotation-verdict" label="Verdict" value={annotationVerdict} options={['true_positive','false_positive','exclude'].map(value => ({value,label:value.replaceAll('_',' ')}))} onChange={setAnnotationVerdict} />
            <Field><FieldLabel htmlFor="annotation-notes">Evidence and rationale</FieldLabel><Input id="annotation-notes" value={annotationNotes} onChange={event => setAnnotationNotes(event.target.value)} /></Field>
          </FieldGroup></CardContent><CardFooter><Button disabled={busy || !annotationRun || annotationNotes.length < 3} onClick={() => void action(() => operations.annotate(applicationId,annotationRun,{anomaly_id:annotationAnomaly || null,verdict:annotationVerdict,notes:annotationNotes}))}>Record annotation</Button></CardFooter></Card>}
        </TabsContent>
        <TabsContent value="evaluation" className="flex flex-col gap-4"><Notice>Metrics use actual saved detector outputs and completed experiments. Precision and F1 remain unavailable until uncontaminated healthy baseline runs exist. No sample results are supplied.</Notice>
          <FieldGroup><Choice id="evaluation-runs" label="Completed experiment" value={evaluationCandidate} options={experiments.filter(r => r.state === 'COMPLETED').map(r => ({value:r.experiment_id,label:`${r.scenario} · ${timestamp(r.started_at)}`}))} onChange={setEvaluationCandidate} /></FieldGroup>
          <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={!evaluationCandidate || selectedRuns.includes(evaluationCandidate)} onClick={() => setSelectedRuns(previous => [...previous,evaluationCandidate])}>Include selected run</Button>{selectedRuns.map(id => <Button key={id} size="sm" variant="secondary" onClick={() => setSelectedRuns(previous => previous.filter(value => value !== id))}>{experiments.find(r => r.experiment_id === id)?.scenario ?? id.slice(0,8)} · Remove</Button>)}</div>
          <Button disabled={busy || !operator || !selectedRuns.length} onClick={() => void action(() => operations.evaluate(applicationId,selectedRuns))}>Generate persisted evaluation</Button>
          {!evaluations.length && <Notice>No academic evaluation has been generated.</Notice>}{evaluations.map(result => <Card key={result.evaluation_id}><CardHeader><CardTitle>Evaluation {result.evaluation_id.slice(0,8)}</CardTitle><CardDescription>{timestamp(result.created_at)} · {result.definition_version}</CardDescription></CardHeader><CardContent className="flex flex-col gap-3"><Table><TableHeader><TableRow><TableHead>Detector</TableHead><TableHead>TP / FP / FN</TableHead><TableHead>Precision</TableHead><TableHead>Recall</TableHead><TableHead>F1</TableHead></TableRow></TableHeader><TableBody>{Object.entries(result.metrics.detectors ?? {}).map(([name,value]) => { const metric=value as Data; return <TableRow key={name}><TableCell>{name}</TableCell><TableCell>{metric.TP} / {metric.FP} / {metric.FN}</TableCell><TableCell>{number(metric.precision)}</TableCell><TableCell>{number(metric.recall)}</TableCell><TableCell>{number(metric.F1)}</TableCell></TableRow>; })}</TableBody></Table><DataView value={result.metrics} /><details><summary>Reproducible inputs</summary><DataView value={result.inputs} /></details></CardContent><CardFooter className="flex gap-2"><Button asChild variant="outline"><a href={operations.exportUrl(applicationId,result.evaluation_id,"json")} download>Export JSON</a></Button><Button asChild variant="outline"><a href={operations.exportUrl(applicationId,result.evaluation_id,"csv")} download>Export CSV</a></Button></CardFooter></Card>)}</TabsContent>
        {administrator && <TabsContent value="governance" className="flex flex-col gap-4"><Notice>Viewer: read telemetry/incidents. Operator: investigate, propose, run experiments and execute approved actions. Administrator: application/user administration and service-changing approvals. Terminal/filesystem access is disabled by default.</Notice>
          <Card><CardHeader><CardTitle>Users and recovery</CardTitle><CardDescription>Public signup creates viewers. Administrators provision operator accounts and deliver recovery tokens privately.</CardDescription></CardHeader><CardContent className="flex flex-col gap-3">
            <FieldGroup><Field><FieldLabel htmlFor="new-account-name">Username</FieldLabel><Input id="new-account-name" value={newUsername} onChange={event => setNewUsername(event.target.value)} autoComplete="off" /></Field><Field><FieldLabel htmlFor="new-account-password">Initial password</FieldLabel><Input id="new-account-password" type="password" minLength={8} value={newPassword} onChange={event => setNewPassword(event.target.value)} autoComplete="new-password" /></Field>
              <Choice id="new-account-role" label="Role" value={newRole} options={['viewer','operator','administrator'].map(value => ({value,label:value}))} onChange={setNewRole} /></FieldGroup>
            {accounts && <Table><TableHeader><TableRow><TableHead>User</TableHead><TableHead>Role</TableHead><TableHead>State</TableHead><TableHead>Administration</TableHead></TableRow></TableHeader><TableBody>{accounts.map(account => <TableRow key={account.user_id}><TableCell>{account.username}</TableCell><TableCell>{account.role}</TableCell><TableCell>{account.disabled ? 'Disabled' : 'Enabled'}</TableCell><TableCell><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy || account.disabled} onClick={() => void action(async () => { setRecovery(await operations.issueRecovery(account.user_id)); })}>Issue recovery token</Button><Button size="sm" variant="destructive" disabled={busy || account.disabled} onClick={() => void action(async () => { await operations.disableUser(account.user_id); setAccounts(await operations.users()); })}>Disable</Button></div></TableCell></TableRow>)}</TableBody></Table>}
            {recovery && <Alert><AlertTitle>Private recovery token</AlertTitle><AlertDescription className="flex flex-col gap-2"><p>Deliver privately to the verified account owner. Expires in 30 minutes.</p><code className="break-all select-text">{recovery.reset_token}</code><Button variant="outline" onClick={() => setRecovery(null)}>Hide token</Button></AlertDescription></Alert>}
          </CardContent><CardFooter className="flex flex-wrap gap-2"><Button disabled={busy || newUsername.length < 3 || newPassword.length < 8} onClick={() => void action(async () => { await operations.createUser(newUsername,newPassword,newRole); setNewPassword(''); setAccounts(await operations.users()); })}>Create account</Button><Button variant="outline" disabled={busy} onClick={() => void action(async () => setAccounts(await operations.users()))}>Load accounts</Button></CardFooter></Card>
          <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void action(async () => setAudit(await operations.audit()))}>Load audit history</Button><Button variant="outline" disabled={busy} onClick={() => void action(async () => setIntegrity(await operations.integrity()))}>Assess audit chain</Button></div>
          {integrity && <DataView value={integrity} />}{audit && <Table><TableHeader><TableRow><TableHead>Sequence</TableHead><TableHead>Time</TableHead><TableHead>Actor</TableHead><TableHead>Action</TableHead></TableRow></TableHeader><TableBody>{audit.map(entry => <TableRow key={entry.sequence}><TableCell>{entry.sequence}</TableCell><TableCell>{timestamp(entry.at)}</TableCell><TableCell>{entry.actor}</TableCell><TableCell>{entry.action}</TableCell></TableRow>)}</TableBody></Table>}
        </TabsContent>}
      </Tabs>
    </CardContent><CardFooter className="flex flex-wrap justify-between gap-2"><span className="text-sm text-muted-foreground">{busy ? "Request in progress…" : loading ? "Updating observations…" : "Source failures remain visible as unavailable or stale."}</span><Badge variant="secondary">{role}</Badge></CardFooter>
  </Card>;
}
