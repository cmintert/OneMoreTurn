/**
 * Client-side telemetry — batches UI events and flushes to POST /api/telemetry.
 *
 * Enabled by default; disable via VITE_TELEMETRY_ENABLED=false.
 */

interface TelemetryPayload {
  request_id: string;
  event_type: string;
  ts_ms: number;
  data: Record<string, unknown>;
}

const FLUSH_INTERVAL_MS = 5_000;
const MAX_BATCH = 50;
const ENABLED = import.meta.env.VITE_TELEMETRY_ENABLED !== "false";

class TelemetryClient {
  private queue: TelemetryPayload[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    if (ENABLED && typeof window !== "undefined") {
      this.timer = setInterval(() => this.flush(), FLUSH_INTERVAL_MS);
    }
  }

  track(eventType: string, data: Record<string, unknown> = {}): void {
    if (!ENABLED) return;
    this.queue.push({
      request_id: data["request_id"] as string ?? "",
      event_type: eventType,
      ts_ms: Date.now(),
      data,
    });
    if (this.queue.length >= MAX_BATCH) this.flush();
  }

  async flush(): Promise<void> {
    if (this.queue.length === 0) return;
    const batch = this.queue.splice(0, MAX_BATCH);
    try {
      await fetch("/api/telemetry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(batch),
      });
    } catch {
      // Silently drop on failure — telemetry is best-effort
    }
  }

  get queueSize(): number {
    return this.queue.length;
  }

  destroy(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}

export const telemetryClient = new TelemetryClient();
