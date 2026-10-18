import { useEffect, useState } from "react";
import { api, type Incident } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

interface OSRightSidebarProps {
  username?: string; role?: string; onOpenSettings?: () => void; onOpenAlerts?: () => void;
  onOpenSecurity?: () => void; onOpenAIInsight?: (insight: string) => void; onLockScreen?: () => void;
  onRestartStack?: () => void; servicesRunningCount?: number; totalServicesCount?: number; healthScore?: number;
}

export function OSRightSidebar({ username = "", role = "viewer", onOpenSettings, onOpenAlerts, onOpenSecurity,
  onLockScreen, onRestartStack, servicesRunningCount, totalServicesCount, healthScore }: OSRightSidebarProps) {
  const [incidents,setIncidents] = useState<Incident[] | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.incidents(4).then(items => { if (live) setIncidents(items); }).catch(() => { if (live) setIncidents(null); });
    void load(); const timer = setInterval(load,15000);
    return () => { live = false; clearInterval(timer); };
  }, []);
  return <aside className="hidden w-72 shrink-0 flex-col gap-3 overflow-y-auto p-3 xl:flex" aria-label="Account and operations shortcuts">
    <Card><CardHeader><CardTitle>{username}</CardTitle><CardDescription>EIOS account</CardDescription></CardHeader><CardContent><Badge variant="outline">{role}</Badge></CardContent>
      <CardFooter className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={onLockScreen}>Sign out</Button><Button variant="outline" size="sm" onClick={onRestartStack}>Lock desktop</Button></CardFooter></Card>
    <Card><CardHeader><CardTitle>Service overview</CardTitle><CardDescription>Current selected application observations</CardDescription></CardHeader><CardContent className="flex flex-col gap-2">
      <p>Healthy: {servicesRunningCount ?? "Unavailable"} / {totalServicesCount ?? "Unavailable"}</p><p>Healthy service share: {healthScore === undefined ? "Unknown" : `${healthScore}%`}</p>
    </CardContent><CardFooter><Button variant="outline" size="sm" onClick={onOpenAlerts}>Open Operations</Button></CardFooter></Card>
    <Card><CardHeader><CardTitle>Recent legacy detections</CardTitle><CardDescription>Existing detector history remains available in Reports.</CardDescription></CardHeader><CardContent className="flex flex-col gap-2">
      {incidents === null ? <Alert><AlertDescription>Detection API unavailable.</AlertDescription></Alert> : incidents.length ? incidents.map(item => <p key={item.incident_id} className="text-sm">{item.title} <Badge variant="outline">{item.severity}</Badge></p>) : <p className="text-sm text-muted-foreground">No recent detections.</p>}
    </CardContent><CardFooter><Button variant="outline" size="sm" onClick={onOpenSecurity}>Security and governance</Button></CardFooter></Card>
    <Button variant="outline" onClick={onOpenSettings}>Applications and settings</Button>
  </aside>;
}
