import { useState } from "react";
import { X, FileCode, Check, Copy, Terminal } from "lucide-react";

interface ConfigViewerModalProps {
  fileName: string;
  fileContent?: string;
  onClose: () => void;
}

export function ConfigViewerModal({
  fileName,
  fileContent,
  onClose,
}: ConfigViewerModalProps) {
  const [copied, setCopied] = useState(false);

  const defaultContent = `# EIOS Kernel Enterprise Configuration
[kernel.system]
version = "1.0.0-enterprise"
environment = "production"
cluster_name = "eios-core-mesh"
node_role = "master-supervisor"

[kernel.performance]
memory_governor = "aggressive-throttle"
wsl2_cap_mb = 3800
eco_mode = true
host_protection = "enabled"
thread_concurrency_limit = 4

[kernel.telemetry]
prometheus_collector = "http://prometheus:9090"
jaeger_tracing = "http://jaeger:16686"
kafka_event_stream = "kafka:9092"
postgres_storage = "postgresql://eios:eios@eios-postgres:5432/eios"

[kernel.security]
zero_trust_mesh = true
audit_logging = "strict"
anomaly_detection_score_threshold = 0.85
`;

  const contentToDisplay = fileContent || defaultContent;

  const handleCopy = () => {
    navigator.clipboard.writeText(contentToDisplay);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-4">
      <div className="os-window w-full max-w-2xl rounded-2xl overflow-hidden shadow-2xl border border-[rgb(var(--eios-contrast))]/10 select-none animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex h-10 items-center justify-between border-b border-[rgb(var(--eios-contrast))]/[0.08] bg-[rgb(var(--eios-070e1c))] px-4">
          <div className="flex items-center gap-2">
            <FileCode className="h-4 w-4 text-[rgb(var(--eios-text-cyan-400))]" />
            <span className="font-display text-xs font-semibold text-[rgb(var(--eios-text-slate-200))]">
              {fileName}
            </span>
            <span className="text-[10px] text-[rgb(var(--eios-text-slate-400))] font-mono">
              EIOS Enterprise File Viewer
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 px-2 py-0.5 rounded bg-[rgb(var(--eios-contrast))]/[0.06] hover:bg-[rgb(var(--eios-contrast))]/[0.12] text-[rgb(var(--eios-text-slate-300))] text-[10px] font-mono transition-colors"
            >
              {copied ? (
                <>
                  <Check className="h-3 w-3 text-[rgb(var(--eios-text-emerald-400))]" />
                  <span className="text-[rgb(var(--eios-text-emerald-400))]">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3 text-[rgb(var(--eios-text-slate-400))]" />
                  <span>Copy</span>
                </>
              )}
            </button>
            <button
              onClick={onClose}
              className="flex h-6 w-6 items-center justify-center rounded-lg hover:bg-rose-500/80 text-[rgb(var(--eios-text-slate-400))] hover:text-[rgb(var(--eios-text-white))]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Code Content */}
        <div className="p-4 bg-[rgb(var(--eios-02050c))] font-mono-code text-xs text-[rgb(var(--eios-text-sky-200))] overflow-y-auto max-h-[420px] scrollbar-themed leading-relaxed select-text">
          <pre className="whitespace-pre-wrap">{contentToDisplay}</pre>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-[rgb(var(--eios-contrast))]/[0.08] bg-[rgb(var(--eios-050b18))] px-4 py-2.5">
          <div className="flex items-center gap-2 text-[11px] text-[rgb(var(--eios-text-slate-400))]">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            <span>OpenTelemetry & EIOS Verified Integrity • UTF-8</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg bg-cyan-500/20 px-3 py-1 text-xs font-medium text-[rgb(var(--eios-text-cyan-300))] hover:bg-cyan-500/30 border border-cyan-500/30 transition-colors"
          >
            Close Viewer
          </button>
        </div>
      </div>
    </div>
  );
}
