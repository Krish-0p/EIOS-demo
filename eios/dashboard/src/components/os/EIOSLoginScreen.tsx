import { useEffect, useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface EIOSLoginScreenProps {
  onLoginSuccess: () => void | Promise<void>;
}

export function EIOSLoginScreen({ onLoginSuccess }: EIOSLoginScreenProps) {
  const [mode, setMode] = useState<"login" | "register" | "signup" | "forgot" | "reset">("login");
  const [resetToken, setResetToken] = useState("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [setupRequired, setSetupRequired] = useState(false);
  const [checkingSetup, setCheckingSetup] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.authStatus().then(status => {
      if (!mounted) return;
      setSetupRequired(status.setup_required);
      if (status.setup_required) setMode("register");
    }).catch(() => {
      if (mounted) setError("Could not check administrator setup. Check the API connection.");
    }).finally(() => { if (mounted) setCheckingSetup(false); });
    return () => { mounted = false; };
  }, []);

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    if (loading) return;
    if (!password || (mode !== "reset" && !username.trim())) {
      setError("Enter your username and password.");
      return;
    }
    if (["register", "signup", "reset"].includes(mode) && password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      if (mode === "register") {
        await api.authRegister(username.trim(), password);
      } else if (mode === "signup") {
        await api.authSignup(username.trim(), password);
      } else if (mode === "reset") {
        await api.authResetPassword(resetToken.trim(), password);
        setMode("login"); setPassword(""); setConfirmPassword(""); setResetToken("");
        setNotice("Password updated. Sign in with your new password.");
        return;
      }
      const result = await api.authLogin(username.trim(), password);
      if (result.status !== "authenticated" || !result.user) {
        throw new Error("Authentication failed. Check your credentials.");
      }
      await onLoginSuccess();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Authentication failed.";
      setError(message.includes("401") ? "Invalid username or password." : message);
    } finally {
      setLoading(false);
    }
  };

  const handleForgot = async (event: React.FormEvent) => {
    event.preventDefault(); setLoading(true); setError(null);
    try {
      const result = await api.authForgotPassword(username.trim());
      if (result.reset_token) { setResetToken(result.reset_token); setMode("reset"); }
      else setNotice(result.message);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not start password reset."); }
    finally { setLoading(false); }
  };

  const title = mode === "login" ? "Sign In to EIOS" : mode === "register" ? "Set Up First Administrator" : mode === "signup" ? "Create EIOS Account" : mode === "forgot" ? "Reset Your Password" : "Choose a New Password";

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-background p-4 text-foreground">
      <Card className="w-full max-w-md">
        <Tabs value={mode} onValueChange={value => { setMode(value as typeof mode); setError(null); }}>
          <CardHeader className="items-center text-center">
            <CardTitle>{title}</CardTitle>
            <CardDescription>Enterprise Intelligent Operating System</CardDescription>
            {mode !== "forgot" && mode !== "reset" && <TabsList className="mt-3">
              <TabsTrigger value="login" disabled={loading}>Sign In</TabsTrigger>
              <TabsTrigger value={setupRequired ? "register" : "signup"} disabled={loading}>Create Account</TabsTrigger>
            </TabsList>}
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {notice && <Alert><AlertDescription>{notice}</AlertDescription></Alert>}
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Sign-in failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <form onSubmit={mode === "forgot" ? handleForgot : handleLogin} className="flex flex-col gap-4">
              <FieldGroup>
                {mode === "reset" && <Field>
                  <FieldLabel htmlFor="reset-token">Reset token</FieldLabel>
                  <Input id="reset-token" value={resetToken} onChange={event => setResetToken(event.target.value)} required disabled={loading} />
                </Field>}
                {mode !== "reset" && <Field>
                  <FieldLabel htmlFor="admin-username">Username</FieldLabel>
                  <Input id="admin-username" name="username" autoComplete="username" value={username}
                    onChange={event => setUsername(event.target.value)} required disabled={loading} />
                </Field>}
                {mode !== "forgot" && <Field>
                  <FieldLabel htmlFor="admin-password">Password</FieldLabel>
                  <Input id="admin-password" name="password" type="password"
                    minLength={mode === "login" ? 1 : 8}
                    autoComplete={mode === "login" ? "current-password" : "new-password"} value={password}
                    onChange={event => setPassword(event.target.value)} required disabled={loading} />
                </Field>}
                {["register", "signup", "reset"].includes(mode) && (
                  <Field>
                    <FieldLabel htmlFor="confirm-password">Confirm Password</FieldLabel>
                    <Input id="confirm-password" name="confirmPassword" type="password" autoComplete="new-password"
                      value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)}
                      required disabled={loading} />
                  </Field>
                )}
              </FieldGroup>
              <Button type="submit" disabled={loading || checkingSetup}>
                {loading ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <ArrowRight data-icon="inline-start" />}
                {loading ? "Working..." : mode === "forgot" ? "Send Reset Instructions" : mode === "reset" ? "Update Password" : ["register", "signup"].includes(mode) ? "Create Account & Sign In" : "Sign In to EIOS Desktop"}
              </Button>
            </form>
            {mode === "login" && <div className="flex justify-between text-sm"><Button type="button" variant="link" className="px-0" onClick={() => { setMode("forgot"); setError(null); }}>Forgot password?</Button>{!setupRequired && <Button type="button" variant="link" className="px-0" onClick={() => { setMode("signup"); setError(null); }}>Create account</Button>}</div>}
            {(mode === "forgot" || mode === "reset") && <Button type="button" variant="link" onClick={() => { setMode("login"); setError(null); }}>Back to sign in</Button>}
            {mode === "forgot" && <Button type="button" variant="outline" onClick={() => { setMode("reset"); setError(null); setPassword(""); setConfirmPassword(""); }}>I have a recovery token</Button>}
          </CardContent>
        </Tabs>
        <CardFooter className="justify-center text-sm text-muted-foreground">
          You stay signed in until your session expires or you lock EIOS.
        </CardFooter>
      </Card>
    </div>
  );
}
