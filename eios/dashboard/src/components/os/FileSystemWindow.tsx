import { useState, useMemo, useEffect, useCallback } from "react";
import {
  Search,
  ArrowLeft,
  ArrowRight,
  RotateCw,
  LayoutGrid,
  List,
  MoreVertical,
  Minus,
  Square,
  X,
  HardDrive,
} from "lucide-react";
import { api, type FSEntry } from "@/lib/api";

export interface FileItem {
  id: string;
  name: string;
  type: "folder" | "file";
  meta: string;
  category?: string;
  size?: string;
  updated?: string;
  rawContent?: string;
}

interface FileSystemWindowProps {
  onClose: () => void;
  onMinimize: () => void;
  onOpenFile?: (fileName: string, content?: string) => void;
  isMaximized?: boolean;
  onToggleMaximize?: () => void;
}

// Realistic Solid 3D Folder Icon for File Explorer
function RealisticExplorerFolder({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 44 44" className="h-10 w-10 drop-shadow-sm select-none" fill="none">
      {/* Folder Back Tab */}
      <path
        d="M5 12C5 10.3431 6.34315 9 8 9H16L19.5 12.5H36C37.6569 12.5 39 13.8431 39 15.5V32C39 33.6569 37.6569 35 36 35H8C6.34315 35 5 33.6569 5 32V12Z"
        fill="#023859"
        stroke="#26658C"
        strokeWidth="1"
      />
      {/* Paper sheets sticking out */}
      <rect x="9" y="11" width="26" height="12" rx="1" fill="#E8F4F8" />
      <line x1="12" y1="14" x2="24" y2="14" stroke="#26658C" strokeWidth="0.8" />
      <line x1="12" y1="17" x2="31" y2="17" stroke="#54ACBF" strokeWidth="0.8" />
      {/* Front Folder Flap */}
      <path
        d="M4 17C4 15.8954 4.89543 15 6 15H38C39.1046 15 40 15.8954 40 17L38 33C38 34.6569 36.6569 36 35 36H7C5.34315 36 4 34.6569 4 33L4 17Z"
        fill="#083a5c"
        stroke="#54ACBF"
        strokeWidth="1"
      />
      {/* Flap top highlight line */}
      <line x1="5" y1="18" x2="39" y2="18" stroke="#A7EBF2" strokeOpacity="0.4" strokeWidth="0.8" />
      {/* Folder category label */}
      <rect x="17" y="24" width="10" height="4" rx="1" fill="#011C40" stroke="#26658C" strokeWidth="0.6" />
      <text x="22" y="27" fill="#A7EBF2" fontSize="3" fontWeight="bold" textAnchor="middle" fontFamily="monospace">
        {name.slice(0, 3).toUpperCase()}
      </text>
    </svg>
  );
}

// Realistic Solid Dog-Eared File Document Icon
function RealisticExplorerFile({ name }: { name: string }) {
  const ext = name.split(".").pop()?.toUpperCase() || "TXT";
  const isLog = ext === "LOG";
  const isWf = ext === "WF";
  const isYaml = ext === "YAML" || ext === "YML" || ext === "CONF";

  const badgeBg = isLog ? "#051F1C" : isWf ? "#2b1614" : isYaml ? "#023859" : "#02243d";
  const badgeText = isLog ? "#B5E3C8" : isWf ? "#F08A7C" : isYaml ? "#A7EBF2" : "#54ACBF";
  const badgeBorder = isLog ? "#1C5147" : isWf ? "#E04A5F" : isYaml ? "#26658C" : "#0a3a5c";

  return (
    <svg viewBox="0 0 40 44" className="h-10 w-9 drop-shadow-sm select-none" fill="none">
      {/* Paper Sheet with Folded Dog-Ear Top Right */}
      <path
        d="M6 6C6 4.34315 7.34315 3 9 3H26L34 11V37C34 38.6569 32.6569 40 31 40H9C7.34315 40 6 38.6569 6 37V6Z"
        fill="#041a2e"
        stroke="#26658C"
        strokeWidth="1"
      />
      {/* Dog-ear corner fold */}
      <path d="M26 3V11H34L26 3Z" fill="#021424" stroke="#26658C" strokeWidth="0.8" />
      {/* Document text lines */}
      <line x1="11" y1="16" x2="28" y2="16" stroke="#26658C" strokeWidth="1" strokeLinecap="round" />
      <line x1="11" y1="20" x2="25" y2="20" stroke="#0e3a5e" strokeWidth="1" strokeLinecap="round" />
      <line x1="11" y1="24" x2="22" y2="24" stroke="#0e3a5e" strokeWidth="1" strokeLinecap="round" />
      {/* File type badge */}
      <rect x="10" y="29" width="20" height="7" rx="1.5" fill={badgeBg} stroke={badgeBorder} strokeWidth="0.8" />
      <text x="20" y="34.2" fill={badgeText} fontSize="4" fontWeight="bold" textAnchor="middle" fontFamily="monospace">
        {ext.slice(0, 4)}
      </text>
    </svg>
  );
}

export function FileSystemWindow({
  onClose,
  onMinimize,
  onOpenFile,
  isMaximized,
  onToggleMaximize,
}: FileSystemWindowProps) {
  const [currentPath, setCurrentPath] = useState<string>("home");
  const [history, setHistory] = useState<string[]>(["home"]);
  const [historyIdx, setHistoryIdx] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [selectedItem, setSelectedItem] = useState<string | null>("opentelemetry-demo");

  // Comprehensive EIOS Drive file structure
  const filesystemData: Record<string, FileItem[]> = {
    home: [
      {
        id: "opentelemetry-demo",
        name: "opentelemetry-demo",
        type: "folder",
        meta: "34 microservices (Admin)",
      },
      {
        id: "admin-profile.json",
        name: "admin-profile.json",
        type: "file",
        meta: "1.2 KB",
        rawContent: `{\n  "user": "Enterprise Administrator",\n  "role": "SuperAdmin",\n  "cluster": "eios-production-mesh",\n  "wsl2_cap_mb": 3800,\n  "eco_mode": true\n}`,
      },
      {
        id: ".eios-session",
        name: ".eios-session",
        type: "file",
        meta: "512 B",
        rawContent: `SESSION_ID=eios-sec-9948271\nTLS_CIPHER=TLS_AES_256_GCM_SHA384\nAUTHENTICATED_AT=2025-05-25T10:42:00Z`,
      },
      {
        id: "workspace-config.yaml",
        name: "workspace-config.yaml",
        type: "file",
        meta: "2.8 KB",
        rawContent: `# EIOS Admin Workspace Preferences\ntheme: solid-dark-executive\ndashboard:\n  streaming_interval_ms: 1000\n  time_range: "15m"\n  active_governor: "wsl2-eco"`,
      },
    ],

    "home/opentelemetry-demo": [
      { id: "src", name: "src", type: "folder", meta: "32 microservices" },
      {
        id: "compose.yaml",
        name: "compose.yaml",
        type: "file",
        meta: "25.4 KB",
        rawContent: `# OpenTelemetry Demo Core Services\nversion: '3.8'\nservices:\n  frontend:\n    image: otel/demo:frontend\n    ports: ["8080:8080"]\n    deploy:\n      resources:\n        limits:\n          memory: 200M\n  checkout:\n    image: otel/demo:checkout\n    environment:\n      - OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`,
      },
      {
        id: "compose.observability.yaml",
        name: "compose.observability.yaml",
        type: "file",
        meta: "6.8 KB",
        rawContent: `# Observability Stack Overrides\nservices:\n  jaeger:\n    image: jaegertracing/all-in-one:latest\n    ports: ["16686:16686"]\n  prometheus:\n    image: prom/prometheus:latest\n    ports: ["9090:9090"]`,
      },
      {
        id: "otel-config.yml",
        name: "otel-config.yml",
        type: "file",
        meta: "897 B",
        rawContent: `receivers:\n  otlp:\n    protocols:\n      grpc:\n      http:\nprocessors:\n  batch:\n    timeout: 1s\nexporters:\n  prometheus:\n    endpoint: "0.0.0.0:8889"\n  otlp:\n    endpoint: jaeger:4317`,
      },
      {
        id: ".env",
        name: ".env",
        type: "file",
        meta: "6.6 KB",
        rawContent: `IMAGE_VERSION=1.10.0\nOTEL_COLLECTOR_PORT_GRPC=4317\nFRONTEND_PORT=8080\nJAEGER_PORT=16686`,
      },
      {
        id: "Makefile",
        name: "Makefile",
        type: "file",
        meta: "17.4 KB",
        rawContent: `start:\n\tdocker compose up -d\n\nstart-eco:\n\tdocker compose --profile eco up -d`,
      },
      {
        id: "README.md",
        name: "README.md",
        type: "file",
        meta: "11.2 KB",
        rawContent: `# OpenTelemetry Enterprise Astronomy Shop\nComplete microservices architecture demonstrating distributed tracing, metrics, and logs streaming into EIOS Kernel.`,
      },
    ],

    "home/opentelemetry-demo/src": [
      { id: "frontend", name: "frontend", type: "folder", meta: "Next.js 14" },
      { id: "checkout", name: "checkout", type: "folder", meta: "Go 1.22" },
      { id: "cart", name: "cart", type: "folder", meta: "C# / .NET 8" },
      { id: "payment", name: "payment", type: "folder", meta: "Node.js 20" },
      { id: "product-catalog", name: "product-catalog", type: "folder", meta: "Go 1.22" },
      { id: "currency", name: "currency", type: "folder", meta: "C++ 20" },
      { id: "shipping", name: "shipping", type: "folder", meta: "Rust / Actix" },
      { id: "email", name: "email", type: "folder", meta: "Ruby 3.2" },
      { id: "recommendation", name: "recommendation", type: "folder", meta: "Python" },
      { id: "otel-collector", name: "otel-collector", type: "folder", meta: "OTel Contrib" },
    ],

    enterprise: [
      {
        id: "organization-policy.yaml",
        name: "organization-policy.yaml",
        type: "file",
        meta: "14.2 KB",
        rawContent: `# EIOS Global Enterprise Governance\ncluster:\n  name: eios-core-mesh\ngovernance:\n  zero_trust: true\n  mtls_enforced: true`,
      },
      {
        id: "compose.eios.security.yaml",
        name: "compose.eios.security.yaml",
        type: "file",
        meta: "3.2 KB",
        rawContent: `# EIOS Security Compose Extension\n# Authenticated Reverse Proxy, Rate Limiter, and Hash Chaining\nversion: '3.8'\nservices:\n  orchestrator:\n    environment:\n      - EIOS_API_KEY=\${EIOS_API_KEY}\n      - EIOS_RATE_LIMIT_REQUESTS=200\n      - EIOS_RATE_LIMIT_WINDOW=60\n      - EIOS_REDACTION_ENABLED=true\n      - EIOS_AUDIT_INTEGRITY_ENABLED=true`,
      },
      {
        id: "SECURITY.md",
        name: "SECURITY.md",
        type: "file",
        meta: "11.5 KB",
        rawContent: `# EIOS Enterprise Security Architecture\n\n## Threat Model & Guarantees\n- **Authentication**: Constant-time comparison bearer / X-API-Key token validation.\n- **Data Sanitization**: PII & Secrets Redaction engine runs pre-ingest.\n- **Audit Ledger**: Cryptographic SHA-256 hash chaining on all governance events.\n- **Rate Limiting**: Sliding window flood prevention.\n- **Resource Guard**: Strict request payload memory caps (1MB).`,
      },
      {
        id: "migrate_security.sql",
        name: "migrate_security.sql",
        type: "file",
        meta: "1.8 KB",
        rawContent: `-- Security Schema Extension\nALTER TABLE audit_log ADD COLUMN IF NOT EXISTS tenant_id TEXT;\nALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip TEXT;\nALTER TABLE audit_log ADD COLUMN IF NOT EXISTS request_id TEXT;\nALTER TABLE audit_log ADD COLUMN IF NOT EXISTS integrity_hash TEXT;\nCREATE INDEX IF NOT EXISTS idx_audit_log_hash ON audit_log (integrity_hash);`,
      },
      {
        id: "zero-trust-mesh.conf",
        name: "zero-trust-mesh.conf",
        type: "file",
        meta: "8.1 KB",
        rawContent: `[mesh.security]\nstrict_spiffe_validation = true\nca_provider = "eios-internal-vault"\nrate_limit_per_minute = 200`,
      },
      {
        id: "slo-targets.json",
        name: "slo-targets.json",
        type: "file",
        meta: "4.5 KB",
        rawContent: `{\n  "availability": "99.95%",\n  "p95_latency_ms": 120,\n  "p99_latency_ms": 250\n}`,
      },
      {
        id: "enterprise-license.jwt",
        name: "enterprise-license.jwt",
        type: "file",
        meta: "1.1 KB",
      },
    ],

    data: [
      { id: "traces-stream.parquet", name: "traces-stream.parquet", type: "file", meta: "420 MB" },
      { id: "metrics-bucket-hot.db", name: "metrics-bucket-hot.db", type: "file", meta: "180 MB" },
      { id: "telemetry-spans.wal", name: "telemetry-spans.wal", type: "file", meta: "64 MB" },
      { id: "kafka-partition-offset.idx", name: "kafka-partition-offset.idx", type: "file", meta: "12 MB" },
    ],

    workflows: [
      {
        id: "auto-remediation.wf",
        name: "auto-remediation.wf",
        type: "file",
        meta: "4.1 KB",
        rawContent: `# Auto Remediation\ntrigger:\n  memory: "> 75%"\naction:\n  - enable-eco-mode`,
      },
      {
        id: "memory-governor.wf",
        name: "memory-governor.wf",
        type: "file",
        meta: "3.2 KB",
      },
      { id: "canary-rollout.wf", name: "canary-rollout.wf", type: "file", meta: "5.8 KB" },
    ],

    applications: [
      { id: "frontend.deploy.yaml", name: "frontend.deploy.yaml", type: "file", meta: "3.2 KB" },
      { id: "checkout.deploy.yaml", name: "checkout.deploy.yaml", type: "file", meta: "4.1 KB" },
      { id: "cart.deploy.yaml", name: "cart.deploy.yaml", type: "file", meta: "2.8 KB" },
      { id: "payment.deploy.yaml", name: "payment.deploy.yaml", type: "file", meta: "3.6 KB" },
    ],

    integrations: [
      { id: "kafka-connector.yaml", name: "kafka-connector.yaml", type: "file", meta: "4.8 KB" },
      { id: "grpc-mesh-proxy.conf", name: "grpc-mesh-proxy.conf", type: "file", meta: "6.1 KB" },
      { id: "prometheus-remote-write.yml", name: "prometheus-remote-write.yml", type: "file", meta: "2.2 KB" },
    ],

    backups: [
      { id: "eios-snapshot-hourly.tar.gz", name: "eios-snapshot-hourly.tar.gz", type: "file", meta: "1.4 GB" },
      { id: "postgres-cluster.bak", name: "postgres-cluster.bak", type: "file", meta: "210 MB" },
    ],

    logs: [
      { id: "otel-collector.log", name: "otel-collector.log", type: "file", meta: "840 KB" },
      { id: "orchestrator-audit.log", name: "orchestrator-audit.log", type: "file", meta: "312 KB" },
      { id: "anomaly-detection.log", name: "anomaly-detection.log", type: "file", meta: "44 KB" },
      { id: "wsl2-cgroup-monitor.log", name: "wsl2-cgroup-monitor.log", type: "file", meta: "12 KB" },
    ],

    reports: [
      { id: "sla-compliance-99.9.pdf", name: "sla-compliance-99.9.pdf", type: "file", meta: "3.2 MB" },
      { id: "p99-latency-audit.pdf", name: "p99-latency-audit.pdf", type: "file", meta: "1.8 MB" },
      { id: "cloud-spend-optimization.pdf", name: "cloud-spend-optimization.pdf", type: "file", meta: "2.4 MB" },
    ],

    temp: [
      { id: "telemetry-buffer.tmp", name: "telemetry-buffer.tmp", type: "file", meta: "14 KB" },
      { id: "cluster-sync.lock", name: "cluster-sync.lock", type: "file", meta: "1 B" },
    ],
  };

  const sidebarRoots = [
    { id: "home", label: "home", desc: "User & Admin Workspaces" },
    { id: "enterprise", label: "enterprise", desc: "Org Policies & Configs" },
    { id: "data", label: "data", desc: "Incoming Telemetry Data" },
    { id: "workflows", label: "workflows", desc: "Automation Definitions" },
    { id: "applications", label: "applications", desc: "App & Deployment Files" },
    { id: "integrations", label: "integrations", desc: "API & Kafka Connectors" },
    { id: "backups", label: "backups", desc: "Snapshots & Data Backups" },
    { id: "logs", label: "logs", desc: "System & Audit Logs" },
    { id: "reports", label: "reports", desc: "AI & SLA Analytics" },
    { id: "temp", label: "temp", desc: "Intermediate Cache" },
  ];

  const [realFiles, setRealFiles] = useState<FileItem[] | null>(null);

  // Map OS drive path to workspace relative path
  const resolveWorkspacePath = (p: string): string => {
    if (p === "home") return "";
    if (p.startsWith("home/")) return p.replace(/^home\//, "");
    if (p === "data") return "db";
    if (p === "workflows") return "detect";
    if (p === "applications") return "orchestrator";
    if (p === "integrations") return "ingest";
    if (p === "enterprise") return "security";
    return p;
  };

  const loadRealFiles = useCallback(async (path: string) => {
    try {
      const relPath = resolveWorkspacePath(path);
      const res = await api.fsList(relPath).catch(() => null);
      if (res && res.entries && res.entries.length > 0) {
        const mapped: FileItem[] = res.entries.map((e: FSEntry) => ({
          id: e.name,
          name: e.name,
          type: e.type === "directory" ? "folder" : "file",
          meta: e.type === "directory" ? "Directory" : (e.size_human || "File"),
          size: e.size_human || undefined,
          updated: new Date(e.modified * 1000).toLocaleDateString(),
          category: e.extension,
        }));
        setRealFiles(mapped);
        return;
      }
    } catch {
      // fallback
    }
    setRealFiles(null);
  }, []);

  useEffect(() => {
    loadRealFiles(currentPath);
  }, [currentPath, loadRealFiles]);

  const currentFiles = useMemo(() => {
    if (realFiles && realFiles.length > 0) return realFiles;
    return filesystemData[currentPath] || filesystemData.home;
  }, [realFiles, currentPath]);

  const filteredFiles = useMemo(() => {
    if (!searchQuery.trim()) return currentFiles;
    return currentFiles.filter((f) =>
      f.name.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [currentFiles, searchQuery]);

  const navigateTo = (path: string) => {
    setCurrentPath(path);
    setSelectedItem(null);
    setHistory((prev) => {
      const next = prev.slice(0, historyIdx + 1);
      return [...next, path];
    });
    setHistoryIdx((prev) => prev + 1);
  };

  const handleBack = () => {
    if (historyIdx > 0) {
      const newIdx = historyIdx - 1;
      setHistoryIdx(newIdx);
      setCurrentPath(history[newIdx]);
    }
  };

  const handleForward = () => {
    if (historyIdx < history.length - 1) {
      const newIdx = historyIdx + 1;
      setHistoryIdx(newIdx);
      setCurrentPath(history[newIdx]);
    }
  };

  const handleItemClick = async (item: FileItem) => {
    setSelectedItem(item.name);
    if (item.type === "file") {
      const relPath = resolveWorkspacePath(currentPath);
      const filePath = relPath ? `${relPath}/${item.name}` : item.name;
      try {
        const fileData = await api.fsRead(filePath).catch(() => null);
        if (fileData?.content) {
          onOpenFile?.(item.name, fileData.content);
          return;
        }
      } catch {
        // fallback
      }
      onOpenFile?.(item.name, item.rawContent);
    } else {
      const nextPath = `${currentPath}/${item.id}`;
      navigateTo(nextPath);
    }
  };

  const activeRoot = currentPath.split("/")[0];

  return (
    <div
      className={`os-window flex flex-col overflow-hidden transition-all duration-200 select-none ${
        isMaximized
          ? "fixed inset-6 z-40 rounded-xl shadow-2xl"
          : "h-[305px] w-full rounded-xl"
      }`}
    >
      {/* 1. Window Header (User Palette: #021424, #0d2e49) */}
      <div className="flex h-8 items-center justify-between border-b border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-021424))] px-3">
        <div className="flex items-center gap-2">
          <span className="text-[rgb(var(--eios-54acbf))] text-xs">📁</span>
          <span className="font-display text-xs font-semibold text-[rgb(var(--eios-text-slate-200))]">
            File System
          </span>
          <span className="text-[10px] text-[rgb(var(--eios-54acbf))] font-mono hidden sm:inline">
            eios://enterprise/{currentPath}/
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={onMinimize}
            className="flex h-5 w-5 items-center justify-center rounded hover:bg-[rgb(var(--eios-023859))] text-[rgb(var(--eios-text-slate-400))] hover:text-[rgb(var(--eios-text-white))]"
            title="Minimize"
          >
            <Minus className="h-3 w-3" />
          </button>
          <button
            onClick={onToggleMaximize}
            className="flex h-5 w-5 items-center justify-center rounded hover:bg-[rgb(var(--eios-023859))] text-[rgb(var(--eios-text-slate-400))] hover:text-[rgb(var(--eios-text-white))]"
            title={isMaximized ? "Restore" : "Maximize"}
          >
            <Square className="h-2.5 w-2.5" />
          </button>
          <button
            onClick={onClose}
            className="flex h-5 w-5 items-center justify-center rounded hover:bg-[rgb(var(--eios-e04a5f))] text-[rgb(var(--eios-text-slate-400))] hover:text-[rgb(var(--eios-text-white))]"
            title="Close"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* 2. Navigation & Breadcrumbs Bar */}
      <div className="flex h-9 items-center gap-2 border-b border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-010e1c))] px-3">
        <div className="flex items-center gap-0.5 text-[rgb(var(--eios-text-slate-300))]">
          <button
            onClick={handleBack}
            disabled={historyIdx === 0}
            className="rounded p-1 hover:bg-[rgb(var(--eios-023859))] disabled:opacity-25"
            title="Back"
          >
            <ArrowLeft className="h-3.5 w-3.5 text-[rgb(var(--eios-54acbf))]" />
          </button>
          <button
            onClick={handleForward}
            disabled={historyIdx >= history.length - 1}
            className="rounded p-1 hover:bg-[rgb(var(--eios-023859))] disabled:opacity-25"
            title="Forward"
          >
            <ArrowRight className="h-3.5 w-3.5 text-[rgb(var(--eios-54acbf))]" />
          </button>
          <button
            onClick={() => setSearchQuery("")}
            className="rounded p-1 hover:bg-[rgb(var(--eios-023859))]"
            title="Refresh"
          >
            <RotateCw className="h-3.5 w-3.5 text-[rgb(var(--eios-54acbf))]" />
          </button>
        </div>

        {/* Dynamic Breadcrumbs Bar */}
        <div className="flex flex-1 items-center gap-1 overflow-x-auto rounded border border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-021424))] px-2.5 py-1 text-xs font-mono text-[rgb(var(--eios-text-slate-300))] scrollbar-themed">
          <span className="text-[rgb(var(--eios-54acbf))] text-[11px] shrink-0">📁</span>
          <button
            onClick={() => navigateTo("home")}
            className="hover:text-[rgb(var(--eios-text-white))] text-[rgb(var(--eios-54acbf))]"
          >
            eios:
          </button>
          <span className="text-[rgb(var(--eios-text-slate-500))]">/</span>
          {currentPath.split("/").map((segment, idx, arr) => {
            const isLast = idx === arr.length - 1;
            const subPath = arr.slice(0, idx + 1).join("/");
            return (
              <span key={subPath} className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => navigateTo(subPath)}
                  className={`hover:text-[rgb(var(--eios-a7ebf2))] transition-colors ${
                    isLast ? "text-[rgb(var(--eios-a7ebf2))] font-bold" : "text-[rgb(var(--eios-54acbf))]"
                  }`}
                >
                  {segment}
                </button>
                {!isLast && <span className="text-[rgb(var(--eios-text-slate-500))]">/</span>}
              </span>
            );
          })}
        </div>

        {/* Search */}
        <div className="relative flex w-36 items-center">
          <Search className="absolute left-2 h-3 w-3 text-[rgb(var(--eios-54acbf))]" />
          <input
            type="text"
            placeholder="Search files..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-6 w-full rounded border border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-021424))] pl-6 pr-2 text-xs text-[rgb(var(--eios-text-slate-200))] placeholder-slate-500 outline-none focus:border-[rgb(var(--eios-54acbf))]"
          />
        </div>

        {/* View Switchers */}
        <div className="flex items-center gap-0.5 border-l border-[rgb(var(--eios-0d2e49))] pl-2 text-[rgb(var(--eios-text-slate-400))]">
          <button
            onClick={() => setViewMode("grid")}
            className={`rounded p-1 hover:text-[rgb(var(--eios-text-white))] ${
              viewMode === "grid" ? "bg-[rgb(var(--eios-023859))] text-[rgb(var(--eios-a7ebf2))]" : ""
            }`}
            title="Grid view"
          >
            <LayoutGrid className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setViewMode("list")}
            className={`rounded p-1 hover:text-[rgb(var(--eios-text-white))] ${
              viewMode === "list" ? "bg-[rgb(var(--eios-023859))] text-[rgb(var(--eios-a7ebf2))]" : ""
            }`}
            title="List view"
          >
            <List className="h-3.5 w-3.5" />
          </button>
          <button className="rounded p-1 hover:text-[rgb(var(--eios-text-white))]" title="Options">
            <MoreVertical className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* 3. Main Workspace: Sidebar Tree + Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Tree Sidebar matching the EIOS Drive specification */}
        <div className="w-40 border-r border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-010e1c))] p-2 overflow-y-auto scrollbar-themed">
          <div className="flex items-center justify-between px-2 pb-1.5 border-b border-[rgb(var(--eios-0d2e49))]/40">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[rgb(var(--eios-text-slate-300))]">
              EIOS Drive
            </span>
            <span className="text-[9px] font-mono text-[rgb(var(--eios-54acbf))]">Enterprise</span>
          </div>

          <div className="mt-1.5 space-y-0.5">
            {sidebarRoots.map((folder) => {
              const isActive = activeRoot === folder.id;
              return (
                <button
                  key={folder.id}
                  onClick={() => navigateTo(folder.id)}
                  title={folder.desc}
                  className={`flex w-full items-center justify-between rounded px-2 py-1 text-xs font-medium transition-colors ${
                    isActive
                      ? "bg-[rgb(var(--eios-023859))] text-[rgb(var(--eios-a7ebf2))] border border-[rgb(var(--eios-26658c))]"
                      : "text-[rgb(var(--eios-text-slate-300))] hover:bg-[rgb(var(--eios-02243d))] hover:text-[rgb(var(--eios-text-white))]"
                  }`}
                >
                  <div className="flex items-center gap-1.5 truncate">
                    <span className="text-[11px]">{isActive ? "📂" : "📁"}</span>
                    <span className="truncate">{folder.label}</span>
                  </div>
                  {folder.id === "home" && (
                    <span className="text-[8px] px-1 rounded bg-[rgb(var(--eios-021f36))] text-[rgb(var(--eios-a7ebf2))] font-mono border border-[rgb(var(--eios-26658c))]">
                      OTel
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Right Content Grid / List with REALISTIC SOLID ICONS */}
        <div className="flex-1 overflow-y-auto p-3 scrollbar-themed bg-[rgb(var(--eios-010814))]">
          {filteredFiles.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-[rgb(var(--eios-text-slate-400))]">
              <span className="text-2xl mb-1">📂</span>
              <span className="text-xs">No files match '{searchQuery}'</span>
            </div>
          ) : viewMode === "grid" ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2.5">
              {filteredFiles.map((item) => {
                const isSelected = selectedItem === item.name;
                const isFile = item.type === "file";

                return (
                  <div
                    key={item.id}
                    onClick={() => handleItemClick(item)}
                    className={`group relative flex flex-col items-center justify-center rounded-xl p-2.5 border transition-all cursor-pointer ${
                      isSelected
                        ? "border-[rgb(var(--eios-54acbf))] bg-[rgb(var(--eios-02243d))]"
                        : "border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-021424))] hover:border-[rgb(var(--eios-26658c))] hover:bg-[rgb(var(--eios-031d33))]"
                    }`}
                  >
                    {/* Realistic Solid Icon (Folder / File) */}
                    <div className="relative mb-1 flex items-center justify-center transition-transform group-hover:scale-105">
                      {isFile ? (
                        <RealisticExplorerFile name={item.name} />
                      ) : (
                        <RealisticExplorerFolder name={item.name} />
                      )}
                    </div>

                    <span className="w-full text-center text-xs font-semibold text-[rgb(var(--eios-text-slate-200))] truncate group-hover:text-[rgb(var(--eios-a7ebf2))]">
                      {item.name}
                    </span>
                    <span className="text-[9.5px] text-[rgb(var(--eios-54acbf))] font-mono truncate max-w-full">
                      {item.meta}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="divide-y divide-[rgb(var(--eios-0d2e49))]">
              {filteredFiles.map((item) => (
                <div
                  key={item.id}
                  onClick={() => handleItemClick(item)}
                  className={`flex items-center justify-between py-1.5 px-3 rounded cursor-pointer transition-colors ${
                    selectedItem === item.name
                      ? "bg-[rgb(var(--eios-023859))] text-[rgb(var(--eios-a7ebf2))]"
                      : "hover:bg-[rgb(var(--eios-02243d))] text-[rgb(var(--eios-text-slate-300))]"
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="text-sm shrink-0">
                      {item.type === "folder" ? "📁" : "📄"}
                    </span>
                    <span className="text-xs font-medium truncate">{item.name}</span>
                  </div>
                  <span className="font-mono text-xs text-[rgb(var(--eios-54acbf))] shrink-0">{item.meta}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 4. Bottom Status Bar */}
      <div className="flex h-6 items-center justify-between border-t border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-010e1c))] px-3 text-[11px] text-[rgb(var(--eios-text-slate-300))]">
        <div className="flex items-center gap-2">
          <span>{filteredFiles.length} items</span>
          <span>|</span>
          <span className="text-[rgb(var(--eios-a7ebf2))]">
            {selectedItem ? `1 selected (${selectedItem})` : "0 selected"}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <HardDrive className="h-3 w-3 text-[rgb(var(--eios-54acbf))]" />
          <span>EIOS Drive</span>
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-[rgb(var(--eios-021424))] border border-[rgb(var(--eios-0d2e49))]">
            <div className="h-full w-1/2 bg-[rgb(var(--eios-26658c))] rounded-full" />
          </div>
          <span className="font-mono text-[10px] text-[rgb(var(--eios-a7ebf2))]">
            256 GB free of 512 GB
          </span>
        </div>
      </div>
    </div>
  );
}
