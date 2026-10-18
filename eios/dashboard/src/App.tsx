import { useCallback, useEffect, useState } from "react";
import { EIOSBootScreen } from "./components/os/EIOSBootScreen";
import { EIOSLoginScreen } from "./components/os/EIOSLoginScreen";
import { EIOSDesktop } from "./components/os/EIOSDesktop";
import { ThemeToggle } from "./components/ThemeToggle";
import { Alert, AlertDescription, AlertTitle } from "./components/ui/alert";
import { Button } from "./components/ui/button";
import { endSession, restoreSession } from "./lib/session";
import { api } from "./lib/api";

type OSStage = "checking" | "boot" | "login" | "desktop";

export default function App() {
  const [stage, setStage] = useState<OSStage>("checking");
  const [user, setUser] = useState({ username: "", role: "viewer" });
  const [error, setError] = useState<string | null>(null);

  const checkSession = useCallback(async () => {
    setError(null);
    setStage("checking");
    try {
      const current = await restoreSession();
      setUser(current);
      setStage("desktop");
    } catch (err) {
      if (err instanceof Error && err.message.includes("401")) setStage("boot");
      else setError("EIOS could not validate your session. Check the API connection and retry.");
    }
  }, []);

  useEffect(() => {
    void checkSession();
    const expired = () => { setStage("login"); setUser({ username: "", role: "viewer" }); };
    window.addEventListener("eios:unauthorized", expired);
    return () => window.removeEventListener("eios:unauthorized", expired);
  }, [checkSession]);

  const signOut = async (nextStage: OSStage) => {
    setError(null);
    try {
      await endSession();
      setUser({ username: "", role: "viewer" });
      setStage(nextStage);
    } catch {
      setError("Could not sign out of EIOS. Retry when the API connection is available.");
    }
  };

  return (
    <div className="h-screen w-screen overflow-hidden bg-background text-foreground">
      <ThemeToggle />
      {error && <Alert variant="destructive" className="fixed left-4 top-12 w-auto max-w-lg">
        <AlertTitle>Connection unavailable</AlertTitle><AlertDescription>{error}</AlertDescription>
      </Alert>}
      {stage === "checking" && <div className="flex h-full flex-col items-center justify-center gap-4">
        <p role="status">Validating your EIOS session...</p>
        {error && <Button onClick={() => void checkSession()}>Retry Connection</Button>}
      </div>}
      {stage === "boot" && <EIOSBootScreen onBootComplete={() => setStage("login")} />}
      {stage === "login" && <EIOSLoginScreen onLoginSuccess={async () => {
        const current = await api.authMe();
        setUser(current);
        setStage("desktop");
      }} />}
      {stage === "desktop" && <EIOSDesktop initialOnboardingOpen adminUser={user.username} userRole={user.role}
        onLockScreen={() => void signOut("login")} onReboot={() => void signOut("boot")} />}
    </div>
  );
}
