import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

import { telemetryClient } from "../services/TelemetryClient";

describe("TelemetryClient", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ ok: true });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("track adds events to the queue", () => {
    const before = telemetryClient.queueSize;
    telemetryClient.track("test_event", { foo: "bar" });
    expect(telemetryClient.queueSize).toBe(before + 1);
  });

  it("flush sends queued events to /api/telemetry", async () => {
    telemetryClient.track("flush_test", { x: 1 });
    await telemetryClient.flush();

    expect(fetchMock).toHaveBeenCalledWith("/api/telemetry", expect.objectContaining({
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }));
  });

  it("flush clears the queue", async () => {
    telemetryClient.track("clear_test");
    await telemetryClient.flush();
    expect(telemetryClient.queueSize).toBe(0);
  });

  it("flush is a no-op when queue is empty", async () => {
    // Ensure queue is empty
    await telemetryClient.flush();
    fetchMock.mockReset();

    await telemetryClient.flush();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
