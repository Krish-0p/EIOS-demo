import { useState, useEffect } from "react";
import { Terminal, Shield, Zap, Cpu, HardDrive, CheckCircle2, ChevronRight } from "lucide-react";

interface EIOSBootScreenProps {
  onBootComplete: () => void;
}

export function EIOSBootScreen({ onBootComplete }: EIOSBootScreenProps) {
  const [progress, setProgress] = useState(0);
  const [currentStep, setCurrentStep] = useState(0);

  const bootLogs = [
    { text: "EIOS Microkernel v1.0.0-enterprise initializing...", delay: 200 },
    { text: "Detecting CPU architecture: x86_64 (8 virtual cores, 4 concurrent threads)", delay: 400 },
    { text: "Attaching WSL2 host protection governor: 3800MB RAM cap active", delay: 700 },
    { text: "Zero-Trust Security Mesh: Validating SHA-256 cryptographic modules... [OK]", delay: 1000 },
    { text: "Probing container runtime socket: /var/run/docker.sock discovered", delay: 1300 },
    { text: "Kubernetes / Docker Compose microservice environment detected (34 containers)", delay: 1600 },
    { text: "Initializing OpenTelemetry gRPC receivers (4317) & HTTP exporters (4318)...", delay: 1900 },
    { text: "Binding EIOS Kafka event streams and PostgreSQL telemetry storage...", delay: 2200 },
    { text: "Deploying Autonomous Agent Framework: Integration, Intelligence, Orchestration...", delay: 2500 },
    { text: "Mounting EIOS Secure Virtual File System (/home, /enterprise, /data, /workflows)...", delay: 2800 },
    { text: "Boot sequence complete. Transferring execution to EIOS Display Compositor.", delay: 3100 },
  ];

  useEffect(() => {
    const timer = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 100) {
          clearInterval(timer);
          setTimeout(onBootComplete, 400);
          return 100;
        }
        return prev + 2;
      });
    }, 45);

    return () => clearInterval(timer);
  }, [onBootComplete]);

  useEffect(() => {
    const logInterval = setInterval(() => {
      setCurrentStep((prev) => {
        if (prev < bootLogs.length - 1) return prev + 1;
        return prev;
      });
    }, 280);

    return () => clearInterval(logInterval);
  }, [bootLogs.length]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-between bg-[rgb(var(--eios-01040a))] text-[rgb(var(--eios-text-slate-200))] font-mono select-none p-6 sm:p-10">
      {/* Top OS Branding Bar */}
      <div className="flex items-center justify-between border-b border-[rgb(var(--eios-0d2e49))]/70 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[rgb(var(--eios-02243d))] border border-[rgb(var(--eios-26658c))] shadow-lg">
            <svg viewBox="0 0 24 24" className="h-5 w-5 text-[rgb(var(--eios-54acbf))]" fill="currentColor">
              <polygon
                points="12,2 22,8.5 22,15.5 12,22 2,15.5 2,8.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
              />
              <circle cx="12" cy="12" r="3" fill="#A7EBF2" />
            </svg>
          </div>
          <div>
            <h1 className="font-display text-base font-bold tracking-wider text-[rgb(var(--eios-text-white))]">
              EIOS BOOTLOADER
            </h1>
            <span className="text-[11px] text-[rgb(var(--eios-54acbf))] tracking-wide">
              Enterprise Intelligent Operating System • Kernel 1.0.0
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onBootComplete}
            className="flex items-center gap-1.5 rounded-lg border border-[rgb(var(--eios-26658c))] bg-[rgb(var(--eios-02243d))] px-3 py-1.5 text-xs text-[rgb(var(--eios-a7ebf2))] hover:bg-[rgb(var(--eios-033457))] transition-colors"
          >
            <span>Fast Boot</span>
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Center Console Log Canvas */}
      <div className="my-auto max-w-4xl w-full mx-auto space-y-5">
        <div className="flex items-center justify-center mb-6">
          <div className="relative flex flex-col items-center">
            {/* Medallion */}
            <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-b from-[rgb(var(--eios-124164))] to-[rgb(var(--eios-041a2e))] border-2 border-[rgb(var(--eios-54acbf))] shadow-[0_0_40px_rgba(38,101,140,0.3)]">
              <span className="font-display text-2xl font-black text-[rgb(var(--eios-a7ebf2))] tracking-widest">
                EIOS
              </span>
            </div>
            <div className="mt-3 flex items-center gap-2 text-xs font-mono text-[rgb(var(--eios-text-slate-400))]">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>SUPERVISOR KERNEL ACTIVE</span>
            </div>
          </div>
        </div>

        {/* Boot Terminal Output Window */}
        <div className="rounded-xl border border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-010914))] p-4 shadow-2xl h-60 overflow-y-auto scrollbar-themed flex flex-col justify-end">
          <div className="space-y-1.5 text-xs">
            {bootLogs.slice(0, currentStep + 1).map((log, idx) => (
              <div key={idx} className="flex items-start gap-2.5">
                <span className="text-[rgb(var(--eios-54acbf))] shrink-0 font-bold">
                  [{((idx * 0.28) + 0.04).toFixed(6)}]
                </span>
                <span className={idx === currentStep ? "text-[rgb(var(--eios-text-emerald-300))] font-semibold" : "text-[rgb(var(--eios-text-slate-300))]"}>
                  {log.text}
                </span>
              </div>
            ))}
            <div className="flex items-center gap-1 text-[rgb(var(--eios-text-emerald-400))] animate-pulse pt-1">
              <span>_</span>
            </div>
          </div>
        </div>

        {/* Progress Metric Bar */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-[rgb(var(--eios-text-slate-400))] font-mono">
            <span>KERNEL INITIALIZATION STATUS</span>
            <span className="text-[rgb(var(--eios-a7ebf2))] font-bold">{progress}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-[rgb(var(--eios-021324))] border border-[rgb(var(--eios-0d2e49))]">
            <div
              className="h-full bg-gradient-to-r from-[rgb(var(--eios-26658c))] via-[rgb(var(--eios-54acbf))] to-[rgb(var(--eios-a7ebf2))] rounded-full transition-all duration-75"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      </div>

      {/* Footer Diagnostic Chips */}
      <div className="flex flex-wrap items-center justify-between border-t border-[rgb(var(--eios-0d2e49))]/70 pt-4 text-xs text-[rgb(var(--eios-text-slate-400))]">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <Cpu className="h-3.5 w-3.5 text-[rgb(var(--eios-54acbf))]" />
            Host: Windows 11 WSL2
          </span>
          <span className="flex items-center gap-1.5">
            <HardDrive className="h-3.5 w-3.5 text-[rgb(var(--eios-54acbf))]" />
            Cap: 3.8GB Eco-Guard
          </span>
          <span className="flex items-center gap-1.5">
            <Shield className="h-3.5 w-3.5 text-[rgb(var(--eios-text-emerald-400))]" />
            Zero-Trust Mesh
          </span>
        </div>

        <div className="text-[11px] text-[rgb(var(--eios-text-slate-400))]">
          Press any key or click Fast Boot to proceed
        </div>
      </div>
    </div>
  );
}
