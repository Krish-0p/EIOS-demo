import { afterEach, beforeEach, expect, mock, spyOn, test } from "bun:test";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { api } from "../src/lib/api";

mock.module("../src/components/os/EIOSBootScreen", () => ({
  EIOSBootScreen: ({ onBootComplete }: any) => createElement("button", { onClick: onBootComplete }, "Continue boot"),
}));
mock.module("../src/components/os/EIOSDesktop", () => ({
  EIOSDesktop: ({ adminUser, onLockScreen, onReboot }: any) => createElement("div", null,
    createElement("span", null, adminUser),
    createElement("button", { onClick: onLockScreen }, "Lock"),
    createElement("button", { onClick: onReboot }, "Reboot")),
}));
mock.module("../src/components/ThemeToggle", () => ({ ThemeToggle: () => null }));
const { default: App } = await import("../src/App");
const { EIOSLoginScreen } = await import("../src/components/os/EIOSLoginScreen");
let renderer: ReturnType<typeof create> | undefined;
let originalStorage: PropertyDescriptor | undefined;
let originalWindow: PropertyDescriptor | undefined;
let originalAnimationFrame: PropertyDescriptor | undefined;
let originalCancelAnimationFrame: PropertyDescriptor | undefined;
const authenticated = { username: "operator", role: "operator", status: "active", expires_at: "" };

beforeEach(() => {
  originalStorage = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  originalAnimationFrame = Object.getOwnPropertyDescriptor(globalThis, "requestAnimationFrame");
  originalCancelAnimationFrame = Object.getOwnPropertyDescriptor(globalThis, "cancelAnimationFrame");
  Object.defineProperty(globalThis, "requestAnimationFrame", { configurable: true, value: (callback: FrameRequestCallback) => setTimeout(() => callback(0), 0) });
  Object.defineProperty(globalThis, "cancelAnimationFrame", { configurable: true, value: clearTimeout });
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  } });
  Object.defineProperty(globalThis, "window", { configurable: true, value: new EventTarget() });
  spyOn(api, "authMe").mockRejectedValue(new Error("401 Unauthorized"));
  spyOn(api, "authStatus").mockResolvedValue({ setup_required: false });
  spyOn(api, "authLogout").mockResolvedValue({ status: "signed_out" });
});
afterEach(() => {
  act(() => renderer?.unmount());
  renderer = undefined;
  mock.restore();
  if (originalStorage) Object.defineProperty(globalThis, "sessionStorage", originalStorage);
  else Reflect.deleteProperty(globalThis, "sessionStorage");
  if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
  else Reflect.deleteProperty(globalThis, "window");
  if (originalAnimationFrame) Object.defineProperty(globalThis, "requestAnimationFrame", originalAnimationFrame);
  else Reflect.deleteProperty(globalThis, "requestAnimationFrame");
  if (originalCancelAnimationFrame) Object.defineProperty(globalThis, "cancelAnimationFrame", originalCancelAnimationFrame);
  else Reflect.deleteProperty(globalThis, "cancelAnimationFrame");
});
function text() { return JSON.stringify(renderer!.toJSON()); }
async function mountApp() { await act(async () => { renderer = create(<App />); }); }
async function click(label: string) {
  await act(async () => { renderer!.root.findAllByType("button").find(button => button.children.includes(label))!.props.onClick(); });
}

test("browser login flags never bypass server session validation", async () => {
  sessionStorage.setItem("eios_login_session", JSON.stringify({ user: "admin" }));
  await mountApp();
  expect(api.authMe).toHaveBeenCalledTimes(1);
  expect(text()).toContain("Continue boot");
  expect(sessionStorage.getItem("eios_login_session")).toBeNull();
});

test("refresh restores a valid session only after the server responds", async () => {
  let resolve!: (user: any) => void;
  api.authMe.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await mountApp();
  expect(text()).toContain("Validating your EIOS session");
  expect(text()).not.toContain("operator");
  await act(async () => { resolve(authenticated); });
  expect(text()).toContain("operator");
  act(() => renderer!.unmount());
  api.authMe.mockResolvedValue(authenticated);
  await mountApp();
  expect(api.authMe).toHaveBeenCalledTimes(2);
  expect(text()).toContain("operator");
});

test.each(["Lock", "Reboot"])("%s revokes the server session before leaving the desktop", async action => {
  api.authMe.mockResolvedValue(authenticated);
  await mountApp();
  await click(action);
  expect(api.authLogout).toHaveBeenCalledTimes(1);
  expect(text()).not.toContain('"operator"');
  expect(action === "Lock" ? text().includes("Sign In to EIOS") : text().includes("Continue boot")).toBe(true);
});

test("logout failure is shown without pretending the server session was revoked", async () => {
  api.authMe.mockResolvedValue(authenticated);
  api.authLogout.mockRejectedValue(new Error("Unavailable"));
  await mountApp();
  await click("Lock");
  expect(text()).toContain("Could not sign out");
  expect(text()).toContain("operator");
});

test("session expiry returns the user to sign in", async () => {
  api.authMe.mockResolvedValue(authenticated);
  await mountApp();
  await act(async () => { window.dispatchEvent(new Event("eios:unauthorized")); });
  expect(text()).toContain("Sign In to EIOS");
});

test("backend failure never restores an unvalidated desktop", async () => {
  api.authMe.mockRejectedValue(new Error("502 Bad Gateway"));
  await mountApp();
  expect(text()).toContain("Retry Connection");
  expect(text()).not.toContain('"operator"');
});

async function mountLogin(onLoginSuccess = mock()) {
  await act(async () => { renderer = create(<EIOSLoginScreen onLoginSuccess={onLoginSuccess} />); });
  act(() => renderer!.root.findByProps({ id: "admin-password", name: "password", type: "password" })
    .props.onChange({ target: { value: "test-password" } }));
  return onLoginSuccess;
}
async function submit() {
  await act(async () => { await renderer!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
}

test("login sends credentials without asking for an API key", async () => {
  const login = spyOn(api, "authLogin").mockResolvedValue({ status: "authenticated", user: "admin", role: "administrator", expires_at: "" });
  const onSuccess = await mountLogin();
  expect(renderer!.root.findAllByType("input")).toHaveLength(2);
  await submit();
  expect(login).toHaveBeenCalledWith("admin", "test-password");
  expect(onSuccess).toHaveBeenCalledTimes(1);
});

test("rejected credentials never enter the desktop", async () => {
  spyOn(api, "authLogin").mockRejectedValue(new Error("401 Unauthorized"));
  const onSuccess = await mountLogin();
  await submit();
  expect(onSuccess).not.toHaveBeenCalled();
  expect(text()).toContain("Invalid username or password.");
});

test("first administrator setup propagates registration failure", async () => {
  api.authStatus.mockResolvedValue({ setup_required: true });
  spyOn(api, "authRegister").mockRejectedValue(new Error("Registration unavailable"));
  const login = spyOn(api, "authLogin");
  const onSuccess = await mountLogin();
  act(() => renderer!.root.findByProps({ id: "confirm-password", name: "confirmPassword", type: "password" })
    .props.onChange({ target: { value: "test-password" } }));
  await submit();
  expect(login).not.toHaveBeenCalled();
  expect(onSuccess).not.toHaveBeenCalled();
  expect(text()).toContain("Registration unavailable");
});

test("API session transport sends cookies", async () => {
  const transport = spyOn(globalThis, "fetch").mockResolvedValue(Response.json({
    status: "authenticated", user: "admin", role: "administrator", expires_at: "",
  }));
  await api.authLogin("admin", "test-password");
  expect(transport.mock.calls[0][1]?.credentials).toBe("include");
});

test("an unauthorized operational API response expires the dashboard session", async () => {
  const expired = mock();
  window.addEventListener("eios:unauthorized", expired);
  spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ detail: "Sign in required" }, { status: 401 }));
  await expect(api.stats()).rejects.toThrow("401 Sign in required");
  expect(expired).toHaveBeenCalledTimes(1);
});

test.each([false, true])("Security Center reports server controls without a browser machine key editor %s", async enabled => {
  spyOn(api, "securityStatus").mockResolvedValue({
    security_enabled: true, session_authentication: true, api_key_enabled: enabled,
    rate_limiting: { requests_per_window: 200, window_seconds: 60 },
    redaction_enabled: true, audit_integrity: true, cors_origins: [], version: "1.0.0",
  });
  spyOn(api, "securityAlerts").mockResolvedValue([]);
  spyOn(api, "securityAudit").mockResolvedValue([]);
  const { SecurityCenterWindow } = await import("../src/components/os/SecurityCenterWindow");
  await act(async () => { renderer = create(<SecurityCenterWindow onClose={() => {}} onMinimize={() => {}}
    isMaximized={false} onToggleMaximize={() => {}} />); });
  expect(text()).not.toContain("API Key & Secrets");
  expect(text()).toContain("Server-validated cookie sessions");
  expect(text()).toContain("200 per 60s per process.");
  expect(text()).not.toContain("SHA-256 Chained");
});
