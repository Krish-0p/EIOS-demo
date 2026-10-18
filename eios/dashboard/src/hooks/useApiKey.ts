import { useState, useCallback } from "react";

export function useApiKey() {
  const [apiKey, setApiKeyState] = useState<string | null>(
    sessionStorage.getItem("eios_api_key")
  );

  const setApiKey = useCallback((k: string) => {
    sessionStorage.setItem("eios_api_key", k);
    setApiKeyState(k);
  }, []);

  const clearApiKey = useCallback(() => {
    sessionStorage.removeItem("eios_api_key");
    setApiKeyState(null);
  }, []);

  return { apiKey, setApiKey, clearApiKey };
}
