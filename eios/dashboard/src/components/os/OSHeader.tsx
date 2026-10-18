import { useEffect, useState } from "react";
import {
  Cloud,
  Wifi,
  Volume2,
  Battery,
  Zap,
  ShieldCheck,
  Box,
} from "lucide-react";

interface OSHeaderProps {
  ecoMode: boolean;
  onToggleEco: () => void;
  systemHealth?: number;
  onOpenSecurity?: () => void;
  onOpenOnboarding?: () => void;
}

export function OSHeader({
  ecoMode,
  onToggleEco,
  systemHealth,
  onOpenSecurity,
  onOpenOnboarding,
}: OSHeaderProps) {
  const [timeStr, setTimeStr] = useState(() => new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}));
  const [dateStr, setDateStr] = useState(() => new Date().toLocaleDateString());

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(
        now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      );
      setDateStr(
        now.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" })
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="relative z-30 flex h-10 w-full items-center justify-between border-b border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-010814))] pl-4 pr-14 select-none">
      {/* Brand & Kernel identity */}
      <div className="flex items-center gap-3">
        {/* Solid EIOS Hex Logo (Zero glow) */}
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[rgb(var(--eios-02243d))] border border-[rgb(var(--eios-26658c))]">
          <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-[rgb(var(--eios-54acbf))]" fill="currentColor">
            <polygon
              points="12,2 22,8.5 22,15.5 12,22 2,15.5 2,8.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            />
            <circle cx="12" cy="12" r="3" fill="#A7EBF2" />
          </svg>
        </div>

        <div className="flex items-baseline gap-2">
          <span className="font-display text-sm font-bold tracking-wider text-[rgb(var(--eios-text-white))]">
            EIOS
          </span>
          <span className="hidden text-xs font-medium text-[rgb(var(--eios-text-slate-300))] sm:inline">
            Enterprise Intelligent Operating System
          </span>
          <span className="hidden text-[10px] font-mono text-[rgb(var(--eios-54acbf))] md:inline">
            Operations control plane
          </span>
        </div>
      </div>

      {/* Center Status & RAM Saver Toggle (Solid Palette, No Glow) */}
      <div className="hidden items-center gap-2 sm:flex">
        <button
          onClick={onToggleEco}
          title="Click to toggle Eco RAM Saver mode (keeps PC responsive and cool)"
          className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors ${
            ecoMode
              ? "border-[rgb(var(--eios-1c5147))] bg-[rgb(var(--eios-0b302c))] text-[rgb(var(--eios-b5e3c8))]"
              : "border-[rgb(var(--eios-26658c))] bg-[rgb(var(--eios-02243d))] text-[rgb(var(--eios-a7ebf2))]"
          }`}
        >
          <Zap className={`h-3 w-3 ${ecoMode ? "fill-[rgb(var(--eios-b5e3c8))] text-[rgb(var(--eios-b5e3c8))]" : "text-[rgb(var(--eios-54acbf))]"}`} />
          <span>{ecoMode ? "Eco mode: On" : "Eco mode: Off"}</span>
        </button>

        <div className="flex items-center gap-1.5 rounded-full border border-[rgb(var(--eios-1c5147))] bg-[rgb(var(--eios-051f1c))] px-2.5 py-0.5 text-[11px] text-[rgb(var(--eios-d1f7de))]">
          <span className="h-1.5 w-1.5 rounded-full bg-[rgb(var(--eios-6eaa90))]" />
          <span>Known healthy share: {systemHealth === undefined ? "Unknown" : `${systemHealth}%`}</span>
        </div>

        <button
          onClick={onOpenSecurity}
          title="Open EIOS Zero-Trust Security Center (Rehan Module)"
          className="flex items-center gap-1.5 rounded-full border border-[rgb(var(--eios-26658c))] bg-[rgb(var(--eios-02243d))] px-2.5 py-0.5 text-[11px] text-[rgb(var(--eios-a7ebf2))] hover:bg-[rgb(var(--eios-033457))] hover:border-[rgb(var(--eios-54acbf))] transition-colors"
        >
          <ShieldCheck className="h-3 w-3 text-[rgb(var(--eios-54acbf))]" />
          <span>Zero-Trust: Enforced</span>
        </button>

        <button
          onClick={onOpenOnboarding}
          title="Click to view discovered containers and OTel pipeline"
          className="flex items-center gap-1.5 rounded-full border border-[rgb(var(--eios-26658c))] bg-[rgb(var(--eios-02243d))] px-2.5 py-0.5 text-[11px] text-[rgb(var(--eios-a7ebf2))] hover:bg-[rgb(var(--eios-033457))] hover:border-[rgb(var(--eios-54acbf))] transition-colors"
        >
          <Box className="h-3 w-3 text-[rgb(var(--eios-54acbf))]" />
          <span>Workload: Online Boutique (34 Pods)</span>
        </button>
      </div>

      {/* Right System Indicators & Clock */}
      <div className="flex items-center gap-3 text-[rgb(var(--eios-text-slate-300))]">
        <div className="flex items-center gap-2.5 pr-2 border-r border-[rgb(var(--eios-0d2e49))]">
          <span title="Cloud Sync: Connected">
            <Cloud className="h-3.5 w-3.5 text-[rgb(var(--eios-54acbf))] hover:text-[rgb(var(--eios-a7ebf2))] cursor-pointer" />
          </span>
          <span title="Enterprise Mesh: 5 GHz">
            <Wifi className="h-3.5 w-3.5 text-[rgb(var(--eios-text-slate-300))] hover:text-[rgb(var(--eios-text-white))] cursor-pointer" />
          </span>
          <span title="Volume: 80%">
            <Volume2 className="h-3.5 w-3.5 text-[rgb(var(--eios-text-slate-300))] hover:text-[rgb(var(--eios-text-white))] cursor-pointer" />
          </span>
          <div className="flex items-center gap-1 text-[11px] text-[rgb(var(--eios-b5e3c8))]">
            <Battery className="h-3.5 w-3.5 text-[rgb(var(--eios-6eaa90))]" />
            <span className="font-mono text-[10px]">100%</span>
          </div>
        </div>

        {/* Live Clock & Date */}
        <div className="flex flex-col items-end leading-none">
          <span className="font-mono text-xs font-semibold text-[rgb(var(--eios-text-slate-200))]">
            {timeStr}
          </span>
          <span className="text-[9px] text-[rgb(var(--eios-54acbf))] tracking-wider font-mono">
            {dateStr}
          </span>
        </div>
      </div>
    </header>
  );
}
