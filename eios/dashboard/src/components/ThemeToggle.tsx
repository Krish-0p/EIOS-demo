import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    document.documentElement.style.colorScheme = next ? "dark" : "light";
    try { localStorage.setItem("eios_theme", next ? "dark" : "light"); } catch { /* Theme still works when storage is blocked. */ }
    setDark(next);
  };
  const label = dark ? "Switch to light mode" : "Switch to dark mode";
  return <div className="fixed right-3 top-1.5 z-[100]">
    <Button variant="outline" size="icon" className="size-7" onClick={toggle} aria-label={label} title={label} aria-pressed={!dark}>
      {dark ? <Sun /> : <Moon />}
    </Button>
  </div>;
}
