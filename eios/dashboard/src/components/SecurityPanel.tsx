import { useEffect, useState } from "react";
import { Shield, ShieldAlert, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useApiKey } from "@/hooks/useApiKey";
import { ScrollArea } from "@/components/ui/scroll-area";

export function SecurityPanel() {
  const { apiKey } = useApiKey();
  const [status, setStatus] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    
    async function load() {
      try {
        const s = await api.securityStatus();
        if (!mounted) return;
        setStatus(s);
        
        if (s.security_enabled && apiKey) {
          const a = await api.securityAlerts().catch(() => []);
          if (mounted) setAlerts(a);
        }
      } catch (err) {
        if (mounted) setError(err instanceof Error ? err.message : String(err));
      }
    }

    load();
    const timer = setInterval(load, 30000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [apiKey]);

  if (error) {
    return (
      <Card className="border-destructive/50">
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2 text-destructive">
            <ShieldAlert className="h-4 w-4" /> Security Panel Error
          </CardTitle>
        </CardHeader>
      </Card>
    );
  }

  if (!status) return null;

  return (
    <Card className={status.security_enabled ? "border-primary/20 bg-primary/5" : ""}>
      <CardHeader className="py-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            {status.security_enabled ? (
              <ShieldCheck className="h-4 w-4 text-primary" />
            ) : (
              <Shield className="h-4 w-4 text-muted-foreground" />
            )}
            Security Posture
          </CardTitle>
          <Badge variant={status.security_enabled ? "default" : "secondary"}>
            {status.security_enabled ? "SECURED" : "DEV MODE"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-xs">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-muted-foreground mb-1">Rate Limiting</div>
            <div className="font-mono">
              {status.rate_limiting 
                ? `${status.rate_limiting.requests_per_window} req / ${status.rate_limiting.window_seconds}s`
                : "Disabled"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground mb-1">PII Redaction</div>
            <div className="font-mono">
              {status.redaction_enabled ? "Active" : "Disabled"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground mb-1">Audit Integrity</div>
            <div className="font-mono">
              {status.audit_integrity ? "SHA-256 Chained" : "Disabled"}
            </div>
          </div>
          <div>
            <div className="text-muted-foreground mb-1">CORS Origins</div>
            <div className="font-mono truncate" title={status.cors_origins?.join(", ")}>
              {status.cors_origins?.length} allowed
            </div>
          </div>
        </div>

        {status.security_enabled && (
          <div className="pt-2 border-t">
            <div className="text-muted-foreground mb-2 flex justify-between items-center">
              <span>Recent Security Alerts</span>
              <Badge variant="outline">{alerts.length}</Badge>
            </div>
            
            {alerts.length === 0 ? (
              <div className="text-center py-4 text-muted-foreground">
                No recent alerts.
              </div>
            ) : (
              <ScrollArea className="h-[120px]">
                <div className="space-y-2">
                  {alerts.map((a, i) => (
                    <div key={i} className="flex gap-2 items-baseline text-[11px]">
                      <span className="text-muted-foreground whitespace-nowrap">
                        {new Date(a.at).toLocaleTimeString()}
                      </span>
                      <span className="font-semibold text-destructive">{a.action}</span>
                      <span className="font-mono text-muted-foreground truncate">{a.ip}</span>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
