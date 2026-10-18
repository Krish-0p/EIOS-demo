import { useState } from "react";
import { Key, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useApiKey } from "@/hooks/useApiKey";
import { api } from "@/lib/api";

export function ApiKeyPrompt({ onValidated }: { onValidated: () => void }) {
  const { setApiKey } = useApiKey();
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    
    setLoading(true);
    setError(null);
    try {
      // Temporarily store in session storage to let api.ts pick it up
      sessionStorage.setItem("eios_api_key", input.trim());
      
      // Test the key by calling an authenticated endpoint
      await api.stats();
      
      // If it worked, set it permanently via the hook
      setApiKey(input.trim());
      onValidated();
    } catch (err) {
      sessionStorage.removeItem("eios_api_key");
      if (err instanceof Error && err.message.includes("401")) {
        setError("Invalid API Key. Please try again.");
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-md border-primary/20 shadow-lg">
        <CardHeader className="space-y-1 pb-4 text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Key className="h-6 w-6 text-primary" />
          </div>
          <CardTitle className="text-2xl">API Authentication</CardTitle>
          <CardDescription>
            This EIOS instance is secured. Please provide your API key to access operations.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <input
                type="password"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Enter EIOS_API_KEY..."
                className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                autoFocus
                disabled={loading}
              />
              {error && (
                <p className="text-sm font-medium text-destructive">{error}</p>
              )}
            </div>
            <Button className="w-full" type="submit" disabled={!input.trim() || loading}>
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Verifying...
                </>
              ) : (
                <>
                  <Check className="mr-2 h-4 w-4" />
                  Authenticate
                </>
              )}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
