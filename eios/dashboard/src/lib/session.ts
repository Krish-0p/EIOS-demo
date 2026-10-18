import { api } from "./api";

// Prototype browser flags are never accepted as authentication.
export function clearLegacySession() {
  for (const key of ["eios_login_session", "eios_admin_user", "eios_api_key"]) {
    sessionStorage.removeItem(key);
  }
}

export async function restoreSession() {
  clearLegacySession();
  return api.authMe();
}

export async function endSession() {
  await api.authLogout();
  clearLegacySession();
}
