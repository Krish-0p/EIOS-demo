import { useCallback, useEffect, useState } from "react";
import { api, type SecurityStatus, type SecurityAuditEntry, type SecurityAlert } from "@/lib/api";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "@/components/ui/table";
interface SecurityCenterWindowProps {
  onClose: () => void; onMinimize: () => void; isMaximized: boolean; onToggleMaximize: () => void;
}

export function SecurityCenterWindow({ onClose, onMinimize, isMaximized, onToggleMaximize }: SecurityCenterWindowProps) {
  const [status,setStatus]=useState<SecurityStatus | null>(null);
  const [audit,setAudit]=useState<SecurityAuditEntry[]>([]);
  const [alerts,setAlerts]=useState<SecurityAlert[]>([]);
  const [error,setError]=useState<string | null>(null);
  const [loading,setLoading]=useState(false);
  const [previewText,setPreviewText]=useState('');
  const [preview,setPreview]=useState<string | null>(null);
  const refresh=useCallback(async () => {
    setLoading(true);
    try {
      const [state,entries,signals]=await Promise.all([api.securityStatus(),api.securityAudit(),api.securityAlerts()]);
      setStatus(state);setAudit(entries);setAlerts(signals);setError(null);
    } catch (err) { setStatus(null);setAudit([]);setAlerts([]);setError(err instanceof Error ? err.message : String(err)); }
    finally { setLoading(false); }
  },[]);
  useEffect(() => { void refresh(); },[refresh]);
  return <Card className={isMaximized ? "min-h-[75vh] w-full" : "w-full"} aria-label="Security Center">
    <CardHeader><CardTitle>Security Center</CardTitle><CardDescription>Server-reported configuration and persisted security records. Governance audit chains are available in Operations.</CardDescription></CardHeader>
    <CardContent className="flex flex-col gap-4">{error && <Alert variant="destructive"><AlertTitle>Security API unavailable</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
      <Tabs defaultValue="posture"><TabsList><TabsTrigger value="posture">Controls</TabsTrigger><TabsTrigger value="alerts">Alerts</TabsTrigger><TabsTrigger value="audit">Legacy audit</TabsTrigger><TabsTrigger value="redactor">Redaction preview</TabsTrigger></TabsList>
        <TabsContent value="redactor" className="flex flex-col gap-3"><FieldGroup><Field><FieldLabel htmlFor="redaction-preview">Text to preview (not persisted)</FieldLabel><Input id="redaction-preview" value={previewText} onChange={event => setPreviewText(event.target.value)} maxLength={10000} /></Field></FieldGroup><Button variant="outline" disabled={loading || !previewText} onClick={async () => { setLoading(true); try { setPreview((await api.securityRedact(previewText)).redacted); } catch (err) { setError(String(err)); } finally { setLoading(false); } }}>Run server redactor</Button>{preview !== null && <pre className="whitespace-pre-wrap break-words select-text">{preview}</pre>}</TabsContent>
        <TabsContent value="posture" className="flex flex-col gap-3">{status ? <><Badge variant="outline">Server-validated cookie sessions</Badge><p>Request limit: {status.rate_limiting ? `${status.rate_limiting.requests_per_window} per ${status.rate_limiting.window_seconds}s per process.` : 'Unavailable.'}</p><p>Redaction configured: {status.redaction_enabled ? 'enabled' : 'disabled'}</p><p>Governance chain configured: {status.audit_integrity ? 'enabled' : 'disabled'}. Configuration alone does not establish chain integrity.</p><p className="text-sm text-muted-foreground">Viewer accounts are read-only. Operators investigate and run experiments. Service-changing approvals and user/application administration require administrators. Terminal/filesystem access is disabled by default.</p></> : <Alert><AlertDescription>No current control status is available.</AlertDescription></Alert>}</TabsContent>
        <TabsContent value="alerts">{alerts.length ? <Table><TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Action</TableHead><TableHead>Actor</TableHead></TableRow></TableHeader><TableBody>{alerts.map((entry,i) => <TableRow key={entry.alert_id ?? i}><TableCell>{new Date(entry.at).toLocaleString()}</TableCell><TableCell>{entry.action}</TableCell><TableCell>{entry.actor}</TableCell></TableRow>)}</TableBody></Table> : <p>No persisted alerts returned.</p>}</TabsContent>
        <TabsContent value="audit">{audit.length ? <Table><TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Actor</TableHead><TableHead>Action</TableHead></TableRow></TableHeader><TableBody>{audit.map(entry => <TableRow key={entry.entry_id}><TableCell>{new Date(entry.at).toLocaleString()}</TableCell><TableCell>{entry.actor}</TableCell><TableCell>{entry.action}</TableCell></TableRow>)}</TableBody></Table> : <p>No persisted audit records returned.</p>}</TabsContent>
      </Tabs></CardContent><CardFooter className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => void refresh()} disabled={loading}>{loading ? 'Loading' : 'Refresh'}</Button><Button variant="outline" onClick={onToggleMaximize}>Toggle size</Button><Button variant="outline" onClick={onMinimize}>Minimize</Button><Button variant="outline" onClick={onClose}>Close</Button></CardFooter>
  </Card>;
}
