import { useState } from "react";
import {
  Bot,
  X,
  Sparkles,
  Send,
} from "lucide-react";

interface AIAssistantModalProps {
  onClose: () => void;
  initialQuery?: string;
  onApplyRemediation?: (action: string) => void;
}

import { api } from "@/lib/api";

export function AIAssistantModal({
  onClose,
  initialQuery,
}: AIAssistantModalProps) {
  const [messages, setMessages] = useState<
    { sender: "ai" | "user"; text: string; action?: string }[]
  >([
    {
      sender: "ai",
      text: initialQuery
        ? `Ask about '${initialQuery}' to review the available measurements and findings.`
        : "I can summarize stored service measurements and findings. Ask about latency, checkout errors, or memory trends. I will explain the evidence and suggest what to inspect next.",
    },
  ]);
  const [inputVal, setInputVal] = useState(initialQuery ?? "");
  const [isThinking, setIsThinking] = useState(false);

  const handleSend = async () => {
    if (!inputVal.trim() || isThinking) return;
    const userMsg = inputVal;
    setInputVal("");
    setIsThinking(true);

    setMessages((prev) => [...prev, { sender: "user", text: userMsg }]);

    try {
      const res = await api.aiChat(userMsg);
      if (!res?.reply?.trim()) throw new Error("Empty assistant response");
      setMessages((prev) => [...prev, { sender: "ai", text: res.reply }]);
    } catch {
      setMessages((prev) => [...prev, {
        sender: "ai",
        text: "I could not retrieve an analysis from EIOS. Check the API connection and your session, then try again. Current service health could not be verified.",
      }]);
    } finally {
      setIsThinking(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="os-window w-full max-w-2xl h-[520px] rounded-2xl flex flex-col overflow-hidden shadow-2xl border border-[rgb(var(--eios-contrast))]/10 select-none animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex h-11 items-center justify-between border-b border-[rgb(var(--eios-contrast))]/[0.08] bg-[rgb(var(--eios-091426))] px-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-tr from-purple-500 to-fuchsia-600 shadow-[0_0_12px_rgba(168,85,247,0.5)]">
              <Bot className="h-4 w-4 text-[rgb(var(--eios-text-white))]" />
            </div>
            <div>
              <span className="font-display text-xs font-bold text-[rgb(var(--eios-text-white))] block leading-tight">
                EIOS Assistant
              </span>
              <span className="text-[10px] text-[rgb(var(--eios-text-purple-300))] font-mono">
                Service measurements and findings
              </span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="flex h-6 w-6 items-center justify-center rounded-lg hover:bg-rose-500/80 text-[rgb(var(--eios-text-slate-400))] hover:text-[rgb(var(--eios-text-white))]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Message Log */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-[rgb(var(--eios-030712))]/90 scrollbar-themed text-xs">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`flex gap-2.5 ${m.sender === "user" ? "justify-end" : "justify-start"}`}
            >
              {m.sender === "ai" && (
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-purple-500/20 text-[rgb(var(--eios-text-purple-400))] border border-purple-500/40">
                  <Sparkles className="h-3 w-3" />
                </div>
              )}
              <div
                className={`max-w-[80%] whitespace-pre-wrap break-words select-text rounded-xl px-3.5 py-2.5 leading-relaxed ${
                  m.sender === "user"
                    ? "bg-sky-500/20 text-[rgb(var(--eios-text-sky-200))] border border-sky-500/30"
                    : "os-glass-card text-[rgb(var(--eios-text-slate-200))] border border-[rgb(var(--eios-contrast))]/[0.08]"
                }`}
              >
                {m.text}
              </div>
            </div>
          ))}
          {isThinking && <p role="status" className="text-muted-foreground">Reviewing stored measurements...</p>}
        </div>

        {/* Input Bar */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex items-center gap-2 border-t border-[rgb(var(--eios-contrast))]/[0.08] bg-[rgb(var(--eios-070e1c))] p-3"
        >
          <input
            type="text"
            value={inputVal}
            aria-label="Ask the EIOS assistant"
            onChange={(e) => setInputVal(e.target.value)}
            placeholder="Ask about latency, checkout errors, or memory..."
            className="flex-1 rounded-xl border border-[rgb(var(--eios-contrast))]/10 bg-[rgb(var(--eios-surface-slate-900))]/80 px-3 py-2 text-xs text-[rgb(var(--eios-text-white))] placeholder-slate-500 outline-none focus:border-purple-500/50"
          />
          <button
            type="submit"
            aria-label="Send message"
            disabled={isThinking || !inputVal.trim()}
            className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 text-[rgb(var(--eios-text-white))] shadow-md hover:scale-105 active:scale-95 transition-all"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </form>
      </div>
    </div>
  );
}
