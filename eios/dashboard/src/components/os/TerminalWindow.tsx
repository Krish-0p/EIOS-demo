import { useState, useRef, useEffect, useCallback } from "react";
import { Terminal, Minus, Square, X, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

interface TerminalWindowProps {
  onClose: () => void;
  onMinimize: () => void;
  isMaximized?: boolean;
  onToggleMaximize?: () => void;
  onRunEco?: () => void;
  activeServicesCount?: number;
  totalServicesCount?: number;
}

interface HistoryEntry {
  cmd: string;
  output: string | JSX.Element;
  exit_code?: number;
  duration_ms?: number;
  timestamp?: string;
}

// Quick-command bar items (must match backend whitelist)
const QUICK_CMDS = [
  "eios status",
  "eios health",
  "eios version",
  "docker ps",
  "docker stats --no-stream",
  "df -h",
  "free -h",
  "help",
  "clear",
];

export function TerminalWindow({
  onClose,
  onMinimize,
  isMaximized,
  onToggleMaximize,
  onRunEco,
  activeServicesCount = 48,
  totalServicesCount = 52,
}: TerminalWindowProps) {
  const [inputVal, setInputVal] = useState("");
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([
    {
      cmd: "eios status",
      output: (
        <div className="flex flex-col sm:flex-row items-center gap-3 py-1 select-none">
          <div className="border border-[rgb(var(--eios-26658c))] bg-[rgb(var(--eios-021f36))] rounded p-2 text-[rgb(var(--eios-a7ebf2))]">
            <div className="text-center font-bold text-[rgb(var(--eios-a7ebf2))] border-b border-[rgb(var(--eios-26658c))] pb-0.5 mb-1 tracking-wider text-[9.5px]">
              EIOS ENTERPRISE STATUS
            </div>
            <div className="grid grid-cols-2 gap-x-3 text-[10px] leading-relaxed">
              <span className="text-[rgb(var(--eios-text-slate-400))]">System Health</span>
              <span className="text-[rgb(var(--eios-b5e3c8))] font-bold">: OK</span>
              <span className="text-[rgb(var(--eios-text-slate-400))]">Enterprise Score</span>
              <span className="text-[rgb(var(--eios-a7ebf2))] font-bold">: 94%</span>
              <span className="text-[rgb(var(--eios-text-slate-400))]">Active Services</span>
              <span className="text-[rgb(var(--eios-text-slate-200))]">: {activeServicesCount} / {totalServicesCount}</span>
              <span className="text-[rgb(var(--eios-text-slate-400))]">AI Engine</span>
              <span className="text-[rgb(var(--eios-b5e3c8))]">: RUNNING</span>
              <span className="text-[rgb(var(--eios-text-slate-400))]">Event Bus</span>
              <span className="text-[rgb(var(--eios-b5e3c8))]">: CONNECTED</span>
              <span className="text-[rgb(var(--eios-text-slate-400))]">Database</span>
              <span className="text-[rgb(var(--eios-54acbf))]">: OPERATIONAL</span>
              <span className="text-[rgb(var(--eios-text-slate-400))]">Security</span>
              <span className="text-[rgb(var(--eios-b5e3c8))]">: SECURE</span>
            </div>
          </div>
          <div className="flex flex-col justify-center text-[rgb(var(--eios-54acbf))] font-bold text-[8px] leading-tight">
            <pre className="text-[rgb(var(--eios-54acbf))]">
{`  ######  ####  ####   ####
  #         #  #    # #
  #####     #  #    #  ####
  #         #  #    #      #
  ######  ####  ####   #### `}
            </pre>
            <div className="mt-1 text-[9px] text-[rgb(var(--eios-text-slate-300))] font-medium">Enterprise Intelligent OS</div>
            <div className="text-[8.5px] text-[rgb(var(--eios-54acbf))]">Kernel 1.0.0-enterprise</div>
          </div>
        </div>
      ),
    },
  ]);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const executeCommand = useCallback(async (cmd: string) => {
    const trimmed = cmd.trim();
    if (!trimmed) return;

    // Local 'clear' handler
    if (trimmed === "clear") {
      setHistory([]);
      setInputVal("");
      return;
    }

    // eco shortcut (still local)
    if (trimmed === "eco" || trimmed === "eios fix-ram") {
      onRunEco?.();
      setHistory((prev) => [
        ...prev,
        {
          cmd: trimmed,
          output: (
            <div className="text-[rgb(var(--eios-b5e3c8))] font-mono text-[10px]">
              [Eco Governor Applied] Heavy background indexing throttled. Windows host responsiveness preserved.
            </div>
          ),
        },
      ]);
      setInputVal("");
      return;
    }

    // Append pending entry
    setHistory((prev) => [...prev, { cmd: trimmed, output: "" }]);
    setInputVal("");
    setRunning(true);

    try {
      const result = await api.terminalExec(trimmed);

      const isError = result.exit_code !== 0;
      const isClear = result.output === "__CLEAR__";

      if (isClear) {
        setHistory([]);
        setRunning(false);
        return;
      }

      const outputEl = (
        <pre
          className={`whitespace-pre-wrap text-[10.5px] leading-relaxed font-mono ${
            isError ? "text-[rgb(var(--eios-f08a7c))]" : "text-[rgb(var(--eios-a7ebf2))]"
          }`}
        >
          {result.output || "(no output)"}
        </pre>
      );

      setHistory((prev) => {
        const updated = [...prev];
        // Replace the last (pending) entry
        updated[updated.length - 1] = {
          cmd: trimmed,
          output: outputEl,
          exit_code: result.exit_code,
          duration_ms: result.duration_ms,
          timestamp: result.timestamp,
        };
        return updated;
      });
    } catch (err: any) {
      setHistory((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          cmd: trimmed,
          output: (
            <span className="text-[rgb(var(--eios-f08a7c))] text-[10px]">
              Backend error: {err.message ?? "Could not reach orchestrator"}
            </span>
          ),
          exit_code: 1,
        };
        return updated;
      });
    } finally {
      setRunning(false);
    }
  }, [onRunEco]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  // Refocus input after each command
  useEffect(() => {
    if (!running) inputRef.current?.focus();
  }, [running]);

  return (
    <div
      className={`os-window flex flex-col overflow-hidden transition-all duration-200 ${
        isMaximized
          ? "fixed inset-6 z-40 rounded-xl shadow-2xl"
          : "h-[305px] w-full rounded-xl"
      }`}
    >
      {/* Titlebar */}
      <div className="flex h-8 items-center justify-between border-b border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-021424))] px-3 select-none">
        <div className="flex items-center gap-2">
          <Terminal className="h-3.5 w-3.5 text-[rgb(var(--eios-54acbf))]" />
          <span className="font-display text-xs font-semibold text-[rgb(var(--eios-text-slate-200))]">
            EIOS Terminal
          </span>
          {running && (
            <Loader2 className="h-3 w-3 text-[rgb(var(--eios-54acbf))] animate-spin" />
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={onMinimize} className="flex h-5 w-5 items-center justify-center rounded hover:bg-[rgb(var(--eios-023859))] text-[rgb(var(--eios-text-slate-400))] hover:text-[rgb(var(--eios-text-white))]" title="Minimize">
            <Minus className="h-3 w-3" />
          </button>
          <button onClick={onToggleMaximize} className="flex h-5 w-5 items-center justify-center rounded hover:bg-[rgb(var(--eios-023859))] text-[rgb(var(--eios-text-slate-400))] hover:text-[rgb(var(--eios-text-white))]" title={isMaximized ? "Restore" : "Maximize"}>
            <Square className="h-2.5 w-2.5" />
          </button>
          <button onClick={onClose} className="flex h-5 w-5 items-center justify-center rounded hover:bg-[rgb(var(--eios-e04a5f))] text-[rgb(var(--eios-text-slate-400))] hover:text-[rgb(var(--eios-text-white))]" title="Close">
            <X className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Terminal Buffer */}
      <div className="flex-1 overflow-y-auto p-3 font-mono-code text-[11px] leading-relaxed scrollbar-themed bg-[rgb(var(--eios-010814))] text-[rgb(var(--eios-text-slate-300))]">
        {history.map((item, idx) => (
          <div key={idx} className="mb-2 space-y-1">
            <div className="flex items-center gap-1 text-[rgb(var(--eios-a7ebf2))] font-semibold">
              <span className="text-[rgb(var(--eios-b5e3c8))]">eios@core:~$</span>
              <span>{item.cmd}</span>
              {item.duration_ms !== undefined && (
                <span className="ml-auto text-[9px] text-[rgb(var(--eios-text-slate-600))] font-normal">
                  {item.duration_ms.toFixed(0)}ms
                </span>
              )}
            </div>
            {item.output && <div className="mt-0.5 pl-1">{item.output}</div>}
          </div>
        ))}

        {/* Active Prompt */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!running) executeCommand(inputVal);
          }}
          className="flex items-center gap-1.5 mt-1"
        >
          <span className="text-[rgb(var(--eios-b5e3c8))] font-semibold text-[11px]">
            eios@core:~$
          </span>
          <input
            ref={inputRef}
            type="text"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            disabled={running}
            placeholder={running ? "Executing..." : "Type 'help' to see available commands..."}
            className="flex-1 bg-transparent text-[rgb(var(--eios-text-slate-200))] outline-none placeholder-slate-600 font-mono-code text-[11px] disabled:opacity-50"
            autoFocus
          />
          {!running && <span className="inline-block h-3.5 w-1.5 bg-[rgb(var(--eios-54acbf))] animate-pulse" />}
        </form>

        <div ref={bottomRef} />
      </div>

      {/* Quick Command Bar */}
      <div className="flex h-7 items-center gap-1.5 border-t border-[rgb(var(--eios-0d2e49))] bg-[rgb(var(--eios-010e1c))] px-2.5 text-[10px] text-[rgb(var(--eios-text-slate-400))] overflow-x-auto scrollbar-themed select-none">
        <span className="text-[rgb(var(--eios-54acbf))] font-mono text-[9px] shrink-0">Quick:</span>
        {QUICK_CMDS.map((cmd) => (
          <button
            key={cmd}
            onClick={() => !running && executeCommand(cmd)}
            disabled={running}
            className="rounded bg-[rgb(var(--eios-02243d))] px-2 py-0.5 text-[rgb(var(--eios-a7ebf2))] hover:bg-[rgb(var(--eios-023859))] hover:text-[rgb(var(--eios-text-white))] border border-[rgb(var(--eios-0d2e49))] transition-colors shrink-0 disabled:opacity-40"
          >
            {cmd}
          </button>
        ))}
      </div>
    </div>
  );
}
