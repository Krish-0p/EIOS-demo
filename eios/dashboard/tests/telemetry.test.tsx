import { afterEach, expect, mock, spyOn, test } from "bun:test";
import { act, create } from "react-test-renderer";
import { api } from "../src/lib/api";
import { TelemetrySourceStatus } from "../src/components/os/TelemetrySourceStatus";

let renderer: ReturnType<typeof create> | undefined;
afterEach(() => { act(() => renderer?.unmount()); renderer = undefined; mock.restore(); });

test("source panel shows observed disconnection and timestamps without healthy fallback", async () => {
  spyOn(api, "telemetrySources").mockResolvedValue([{ source_id: "source", kind: "prometheus", state: "disconnected",
    last_data_at: null, checked_at: new Date().toISOString(), last_error: "Query failed", freshness_seconds: 240 }]);
  await act(async () => { renderer = create(<TelemetrySourceStatus applicationId="app" />); });
  const text = JSON.stringify(renderer!.toJSON());
  expect(text).toContain("disconnected");
  expect(text).toContain("Not observed");
  expect(text).not.toContain("healthy");
});

test("source status failure shows unavailable instead of no-source success", async () => {
  spyOn(api, "telemetrySources").mockRejectedValue(new Error("down"));
  await act(async () => { renderer = create(<TelemetrySourceStatus applicationId="app" />); });
  const text = JSON.stringify(renderer!.toJSON());
  expect(text).toContain("Source status unavailable");
  expect(text).not.toContain("No telemetry sources activated");
});

test("old connected observations render stale", async () => {
  spyOn(api, "telemetrySources").mockResolvedValue([{ source_id: "source", kind: "jaeger", state: "connected",
    last_data_at: new Date(Date.now() - 600000).toISOString(), checked_at: new Date(Date.now() - 600000).toISOString(),
    last_error: null, freshness_seconds: 240 }]);
  await act(async () => { renderer = create(<TelemetrySourceStatus applicationId="app" />); });
  expect(JSON.stringify(renderer!.toJSON())).toContain("stale");
});
