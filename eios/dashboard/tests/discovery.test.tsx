import { afterEach, beforeEach, expect, mock, spyOn, test } from "bun:test";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { api } from "../src/lib/api";
import { Badge } from "../src/components/ui/badge";

// Exercise catalog state without requiring a browser to render Radix portals.
const part = ({ children, ...props }: any) => createElement("div", props, children);
mock.module("../src/components/ui/dialog", () => ({
  Dialog: ({ open, children }: any) => open ? createElement("div", null, children) : null,
  DialogContent: part, DialogHeader: part, DialogTitle: part, DialogDescription: part, DialogFooter: part,
}));
mock.module("../src/components/ui/select", () => ({
  Select: part, SelectTrigger: part, SelectValue: part, SelectContent: part, SelectGroup: part, SelectItem: part,
}));
const { ApplicationOnboardingModal } = await import("../src/components/os/ApplicationOnboardingModal");
const { Select } = await import("../src/components/ui/select");

const application = {
  application_id: "app-one", name: "Astronomy Shop", environment: "demo", runtime_type: "docker",
  discovery_scope: { compose_project: "demo" }, telemetry_config: {}, connection_state: "connected",
  telemetry_connection_state: "not_configured", discovery_checked_at: null, discovery_error: null, created_at: "",
};
const service = {
  service_id: "stable-checkout", application_id: "app-one", name: "checkout",
  runtime_identifier: "checkout", runtime_state: "offline", last_runtime_state: "offline",
  connection_state: "connected", telemetry_state: "stale", last_telemetry_at: null, last_seen_at: null,
  runtime_instances: [{ container_id: "old-id", container_name: "checkout", image: "demo:checkout", runtime_state: "exited", health_state: "unknown" }],
};
let renderer: ReturnType<typeof create> | undefined;

beforeEach(() => {
  spyOn(api, "telemetrySources").mockResolvedValue([]);
  spyOn(api, "applications").mockResolvedValue([application] as any);
  spyOn(api, "applicationServices").mockResolvedValue([service] as any);
  spyOn(api, "discoverApplication").mockResolvedValue({ matched_containers: 1 });
  spyOn(api, "dockerStats").mockImplementation(() => new Promise(() => {}));
});
afterEach(() => {
  act(() => renderer?.unmount());
  renderer = undefined;
  mock.restore();
});
async function mount(role = "administrator") {
  await act(async () => { renderer = create(<ApplicationOnboardingModal isOpen role={role} onClose={() => {}} onComplete={() => {}} />); });
}
function button(label: string) {
  return renderer!.root.findAllByType("button").find(node => node.children.includes(label))!;
}
function text() { return JSON.stringify(renderer!.toJSON()); }

test("persistent catalog renders offline services without waiting for container stats", async () => {
  await mount();
  expect(text()).toContain("stable-checkout");
  expect(text()).toContain("offline");
  expect(text()).toContain("stale");
  expect(renderer!.root.findByType("table").props["aria-busy"]).toBe(false);
  expect(api.dockerStats).not.toHaveBeenCalled();
});

test("pending registry requests show loading instead of claiming applications are missing", async () => {
  api.applications.mockImplementation(() => new Promise(() => {}));
  await mount();
  expect(text()).toContain("Loading applications...");
  expect(text()).not.toContain("No applications registered.");
});

test("slow discovery keeps the registered catalog visible", async () => {
  api.discoverApplication.mockImplementation(() => new Promise(() => {}));
  await mount();
  act(() => { button("Discover Services").props.onClick(); });
  expect(text()).toContain("stable-checkout");
  expect(button("Discovering...").props.disabled).toBe(true);
});

test("failed discovery preserves catalog rows and shows its error", async () => {
  api.discoverApplication.mockRejectedValue(new Error("Docker discovery unavailable"));
  await mount();
  await act(async () => { button("Discover Services").props.onClick(); });
  expect(text()).toContain("stable-checkout");
  expect(text()).toContain("Docker discovery unavailable");
  expect(button("Discover Services").props.disabled).toBe(false);
});

test("changing application cancels old requests so late rows cannot overwrite another catalog", async () => {
  let resolveOld!: (rows: any) => void;
  api.applications.mockResolvedValue([application, { ...application, application_id: "app-two", name: "Other App" }] as any);
  api.applicationServices.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  await mount();
  const oldSignal = api.applicationServices.mock.calls[0][1];
  api.applicationServices.mockResolvedValue([{ ...service, service_id: "other-id", name: "other-service" }] as any);
  await act(async () => { renderer!.root.findAllByType(Select).find(node => typeof node.props.onValueChange === "function")!.props.onValueChange("app-two"); });
  expect(oldSignal!.aborted).toBe(true);
  await act(async () => { resolveOld([service]); });
  expect(text()).toContain("other-service");
  expect(text()).not.toContain("stable-checkout");
});

test("application creation saves a Docker scope through the persistent API", async () => {
  const created = { ...application, application_id: "app-new", name: "Payments" };
  const save = spyOn(api, "createApplication").mockResolvedValue(created as any);
  await mount();
  act(() => button("Add Application").props.onClick());
  for (const [key, value] of [["name", "Payments"], ["project", "payments-stack"]]) {
    act(() => renderer!.root.findByProps({ id: `application-${key}` }).props.onChange({ target: { value } }));
  }
  api.applications.mockResolvedValue([application, created] as any);
  await act(async () => { await renderer!.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  expect(save.mock.calls[0][0].discovery_scope.compose_project).toBe("payments-stack");
  expect(save.mock.calls[0][0].name).toBe("Payments");
  expect(api.applicationServices.mock.calls.some(call => call[0] === "app-new")).toBe(true);
});

test("viewer can inspect persisted services without discovery or registration controls", async () => {
  await mount("viewer");
  expect(button("Discover Services").props.disabled).toBe(true);
  expect(renderer!.root.findAllByType("button").some(node => node.children.includes("Add Application"))).toBe(false);
  expect(renderer!.root.findAllByProps({ id: "register-service" })).toHaveLength(0);
});

test("aged cached observations never continue to claim online or fresh state", async () => {
  const old = new Date(Date.now() - 10 * 60 * 1000).toISOString();
  api.applications.mockResolvedValue([{ ...application, discovery_checked_at: old }] as any);
  api.applicationServices.mockResolvedValue([{ ...service, runtime_state: "online", last_runtime_state: "online",
    telemetry_state: "fresh", last_telemetry_at: old }] as any);
  await mount();
  expect(renderer!.root.findAllByType(Badge).some(badge => badge.props.children === "unknown")).toBe(true);
  expect(renderer!.root.findAllByType(Badge).some(badge => badge.props.children === "stale")).toBe(true);
  expect(renderer!.root.findAllByType(Badge).some(badge => badge.props.children === "fresh")).toBe(false);
});
