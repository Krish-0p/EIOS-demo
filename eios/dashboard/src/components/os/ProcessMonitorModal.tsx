import { X, Activity, RefreshCw } from "lucide-react";
import { ServicePanel } from "@/components/ServicePanel";
import type { ServicesView } from "@/lib/api";

interface ProcessMonitorModalProps {
  onClose: () => void;
  onRefresh?: () => void;
}

export function ProcessMonitorModal({
  onClose,
}: ProcessMonitorModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="os-window w-full max-w-5xl h-[85vh] rounded-2xl flex flex-col overflow-hidden shadow-2xl border border-[rgb(var(--eios-contrast))]/10 select-none animate-in fade-in zoom-in-95 duration-150">
        {/* Titlebar */}
        <div className="flex h-11 items-center justify-between border-b border-[rgb(var(--eios-contrast))]/[0.08] bg-[rgb(var(--eios-091426))] px-4">
          <div className="flex items-center gap-2.5">
            <Activity className="h-4 w-4 text-[rgb(var(--eios-text-cyan-400))]" />
            <span className="font-display text-xs font-bold text-[rgb(var(--eios-text-white))]">
              EIOS Enterprise Microservices & Process Monitor
            </span>
            <span className="text-[10px] text-[rgb(var(--eios-text-cyan-300))] font-mono bg-[rgb(var(--eios-surface-cyan-950))]/60 border border-cyan-500/30 px-2 py-0.5 rounded-full">
              Live RED Telemetry
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="flex h-6 w-6 items-center justify-center rounded-lg hover:bg-rose-500/80 text-[rgb(var(--eios-text-slate-400))] hover:text-[rgb(var(--eios-text-white))]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Embedded Full ServicePanel with themed scrollbar */}
        <div className="flex-1 overflow-y-auto p-4 bg-[rgb(var(--eios-050b16))]/90 scrollbar-themed">
          <ServicePanel />
        </div>
      </div>
    </div>
  );
}
