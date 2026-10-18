import { useState, useEffect, useCallback } from "react";
import { OSHeader } from "./OSHeader";
import { DesktopIcons, type WindowId } from "./DesktopIcons";
import { FileSystemWindow } from "./FileSystemWindow";
import { TerminalWindow } from "./TerminalWindow";
import { SystemMonitorWindow } from "./SystemMonitorWindow";
import { OSRightSidebar } from "./OSRightSidebar";
import { ConfigViewerModal } from "./ConfigViewerModal";
import { AIAssistantModal } from "./AIAssistantModal";
import { ProcessMonitorModal } from "./ProcessMonitorModal";
import { SecurityCenterWindow } from "./SecurityCenterWindow";
import { ReportsWindow } from "./ReportsWindow";
import { ApplicationOnboardingModal } from "./ApplicationOnboardingModal";
import { OperationsWorkspace } from "./OperationsWorkspace";
import {
  api,
  type ServicesView,
  type Stats,
  type Incident,
} from "@/lib/api";

interface EIOSDesktopProps {
  initialOnboardingOpen?: boolean;
  adminUser?: string;
  userRole?: string;
  onLockScreen?: () => void;
  onReboot?: () => void;
}

export function EIOSDesktop({
  initialOnboardingOpen = true,
  adminUser = "admin",
  userRole = "viewer",
  onLockScreen,
  onReboot,
}: EIOSDesktopProps) {
  // Window open/close states
  const [windows, setWindows] = useState<Record<WindowId, boolean>>({
    filesystem: false,
    terminal: false,
    systemmonitor: false,
    processes: false,
    ai: false,
    workflows: true,
    integrations: false,
    security: false,
    reports: false,
    settings: false,
    recycle: false,
  });

  // Maximized states
  const [maximizedWindow, setMaximizedWindow] = useState<WindowId | null>(null);

  // Modals
  const [openedFile, setOpenedFile] = useState<{
    name: string;
    content?: string;
  } | null>(null);
  const [aiInsightQuery, setAiInsightQuery] = useState<string | null>(null);
  const [showAIAssistant, setShowAIAssistant] = useState(false);
  const [showProcessMonitor, setShowProcessMonitor] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(initialOnboardingOpen);

  // RAM Saver / Eco Mode
  const [ecoMode, setEcoMode] = useState(true);
  const [applicationId, setApplicationId] = useState(() => localStorage.getItem('eios.application_id') ?? '');
  const selectApplication = useCallback((id: string) => {
    setApplicationId(id);
    localStorage.setItem('eios.application_id',id);
  }, []);

  // Live telemetry data from orchestrator
  const [servicesView, setServicesView] = useState<ServicesView | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);

  // Fetch live backend telemetry
  const loadTelemetry = useCallback(async () => {
    try {
      const [sView, st, inc] = await Promise.all([
        api.services(applicationId || undefined).catch(() => null),
        api.stats().catch(() => null),
        api.incidents(10,applicationId || undefined).catch(() => []),
      ]);
      setServicesView(sView);
      setStats(st);
      setIncidents(inc);
    } catch {
      // Backend gracefully handles offline or warm-up
    }
  }, [applicationId]);

  useEffect(() => {
    loadTelemetry();
    const interval = setInterval(loadTelemetry, 8000);
    return () => clearInterval(interval);
  }, [loadTelemetry]);

  // Window Toggling
  const handleToggleWindow = (id: WindowId) => {
    if (id === 'settings') {
      setShowOnboarding(true);
      return;
    }
    if (id === "processes") {
      setShowProcessMonitor(true);
      return;
    }
    if (id === "ai") {
      setShowAIAssistant(true);
      return;
    }
    if (id === "integrations") {
      setShowOnboarding(true);
      return;
    }
    setWindows((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleCloseWindow = (id: WindowId) => {
    setWindows((prev) => ({ ...prev, [id]: false }));
    if (maximizedWindow === id) setMaximizedWindow(null);
  };

  const handleToggleMaximize = (id: WindowId) => {
    setMaximizedWindow((prev) => (prev === id ? null : id));
  };

  // Counts & Status
  const activeServicesCount = servicesView?.services.length
    ? servicesView.services.filter((s) => s.status === "healthy").length
    : 0;
  const totalServicesCount = servicesView?.services.length ?? 0;
  const healthScore = servicesView?.state === 'available' && servicesView.services.some(s => ['healthy','degraded','critical','offline'].includes(s.status))
    ? Math.round(
        (servicesView.services.filter((s) => s.status === "healthy").length /
          servicesView.services.filter(s => ['healthy','degraded','critical','offline'].includes(s.status)).length) *
          100
      )
    : undefined;

  return (
    <div className="os-wallpaper relative flex h-screen w-screen flex-col overflow-hidden text-[rgb(var(--eios-text-slate-100))] font-sans select-none antialiased bg-[rgb(var(--eios-01040a))]">
      {/* 1. Global OS Header Bar */}
      <OSHeader
        ecoMode={ecoMode}
        onToggleEco={() => setEcoMode(!ecoMode)}
        systemHealth={healthScore}
        onOpenSecurity={() => handleToggleWindow("security")}
        onOpenOnboarding={() => setShowOnboarding(true)}
      />

      {/* 2. Main Desktop Canvas (Left Icons + Center Windows + Right Sidebar) */}
      <main className="relative flex flex-1 overflow-hidden min-h-0 bg-[rgb(var(--eios-01040a))]">
        {/* Left Desktop Launcher Column */}
        <DesktopIcons
          activeWindows={windows}
          onToggleWindow={handleToggleWindow}
        />

        {/* Center Desktop Windows Workspace */}
        <div className="relative flex-1 p-2.5 overflow-y-auto scrollbar-themed flex flex-col gap-2.5 min-h-0 bg-[rgb(var(--eios-01040a))]">
          {windows.workflows && <OperationsWorkspace role={userRole} applicationId={applicationId} onApplicationChange={selectApplication}
            onOpenApplications={() => setShowOnboarding(true)} onClose={() => handleCloseWindow('workflows')} />}
          {/* Top Row: File System Window */}
          {windows.reports && (
            <ReportsWindow
              onClose={() => handleCloseWindow("reports")}
              onMinimize={() => handleCloseWindow("reports")}
              isMaximized={maximizedWindow === "reports"}
              onToggleMaximize={() => handleToggleMaximize("reports")}
              operator={adminUser}
            />
          )}
          {windows.filesystem && (
            <div className="w-full">
              <FileSystemWindow
                onClose={() => handleCloseWindow("filesystem")}
                onMinimize={() => handleCloseWindow("filesystem")}
                onOpenFile={(name, content) => setOpenedFile({ name, content })}
                isMaximized={maximizedWindow === "filesystem"}
                onToggleMaximize={() => handleToggleMaximize("filesystem")}
              />
            </div>
          )}

          {/* Security Center Window */}
          {windows.security && (
            <div className="w-full">
              <SecurityCenterWindow
                onClose={() => handleCloseWindow("security")}
                onMinimize={() => handleCloseWindow("security")}
                isMaximized={maximizedWindow === "security"}
                onToggleMaximize={() => handleToggleMaximize("security")}
              />
            </div>
          )}

          {/* Bottom Row: Terminal Window (Left) + System Monitor (Right) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-2.5 w-full">
            {windows.terminal && (
              <div className={windows.systemmonitor ? "lg:col-span-5" : "lg:col-span-12"}>
                <TerminalWindow
                  onClose={() => handleCloseWindow("terminal")}
                  onMinimize={() => handleCloseWindow("terminal")}
                  isMaximized={maximizedWindow === "terminal"}
                  onToggleMaximize={() => handleToggleMaximize("terminal")}
                  onRunEco={() => setEcoMode(true)}
                  activeServicesCount={activeServicesCount}
                  totalServicesCount={totalServicesCount}
                />
              </div>
            )}

            {windows.systemmonitor && (
              <div className={windows.terminal ? "lg:col-span-7" : "lg:col-span-12"}>
                <SystemMonitorWindow
                  onClose={() => handleCloseWindow("systemmonitor")}
                  onMinimize={() => handleCloseWindow("systemmonitor")}
                  isMaximized={maximizedWindow === "systemmonitor"}
                  onToggleMaximize={() => handleToggleMaximize("systemmonitor")}
                  onViewAllProcesses={() => setShowProcessMonitor(true)}
                  liveServices={servicesView?.services}
                  ecoMode={ecoMode}
                />
              </div>
            )}
          </div>
        </div>

        {/* Right Sidebar Widget Center */}
        <OSRightSidebar
          username={adminUser}
          role={userRole}
          onOpenSettings={() => setShowOnboarding(true)}
          onOpenAlerts={() => setWindows(previous => ({...previous,workflows:true}))}
          onOpenSecurity={() => handleToggleWindow("security")}
          onOpenAIInsight={(query) => {
            setAiInsightQuery(query);
            setShowAIAssistant(true);
          }}
          onLockScreen={
            onLockScreen ||
            (() => alert("EIOS Enterprise Terminal Locked. Re-enter credentials to resume."))
          }
          onRestartStack={
            onReboot ||
            (() => {
              if (confirm("Restart EIOS stack services?")) {
                loadTelemetry();
              }
            })
          }
          servicesRunningCount={servicesView ? activeServicesCount : undefined}
          totalServicesCount={servicesView ? totalServicesCount : undefined}
          healthScore={healthScore}
        />
      </main>

      {/* Interactive Modals */}
      {openedFile && (
        <ConfigViewerModal
          fileName={openedFile.name}
          fileContent={openedFile.content}
          onClose={() => setOpenedFile(null)}
        />
      )}

      {showAIAssistant && (
        <AIAssistantModal
          onClose={() => setShowAIAssistant(false)}
          initialQuery={aiInsightQuery || undefined}
        />
      )}

      {showProcessMonitor && (
        <ProcessMonitorModal
          onClose={() => setShowProcessMonitor(false)}
        />
      )}

      <ApplicationOnboardingModal
        isOpen={showOnboarding}
        role={userRole}
        onClose={() => setShowOnboarding(false)}
        onComplete={() => setShowOnboarding(false)}
      />
    </div>
  );
}
