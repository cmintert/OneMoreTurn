"""In-memory metrics store and telemetry helpers for PHASE_8.

Collects server-side request metrics (route, duration, status) and
client-side telemetry events in a bounded ring buffer.  Exposes
helpers to export as JSON or CSV.

This module is deliberately lightweight — no external dependencies.
"""

from __future__ import annotations

import collections
import csv
import io
import statistics
import time
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestRecord:
    """Single server-side request measurement."""

    request_id: str
    route: str
    method: str
    status: int
    duration_ms: float
    ts: float  # time.time()


@dataclass(frozen=True)
class TelemetryEvent:
    """Single client-submitted telemetry event."""

    request_id: str
    event_type: str
    ts_ms: float
    data: dict


class MetricsStore:
    """Bounded ring-buffer for request records and telemetry events."""

    def __init__(self, max_records: int = 5000, max_events: int = 5000) -> None:
        self._records: collections.deque[RequestRecord] = collections.deque(maxlen=max_records)
        self._events: collections.deque[TelemetryEvent] = collections.deque(maxlen=max_events)

    # -- recording -----------------------------------------------------------

    def record_request(self, rec: RequestRecord) -> None:
        self._records.append(rec)

    def record_telemetry(self, event: TelemetryEvent) -> None:
        self._events.append(event)

    # -- aggregation ---------------------------------------------------------

    def route_summary(self) -> list[dict]:
        """Aggregate request metrics per (route, method)."""
        buckets: dict[tuple[str, str], list[float]] = {}
        error_counts: dict[tuple[str, str], int] = {}
        for r in self._records:
            key = (r.route, r.method)
            buckets.setdefault(key, []).append(r.duration_ms)
            if r.status >= 400:
                error_counts[key] = error_counts.get(key, 0) + 1

        rows = []
        for (route, method), durations in sorted(buckets.items()):
            sorted_d = sorted(durations)
            p95_idx = max(0, int(len(sorted_d) * 0.95) - 1)
            rows.append(
                {
                    "route": route,
                    "method": method,
                    "count": len(durations),
                    "avg_ms": round(statistics.mean(durations), 2),
                    "p95_ms": round(sorted_d[p95_idx], 2),
                    "error_count": error_counts.get((route, method), 0),
                }
            )
        return rows

    # -- export --------------------------------------------------------------

    def export_json(self) -> dict:
        return {
            "routes": self.route_summary(),
            "recent_requests": [
                {
                    "request_id": r.request_id,
                    "route": r.route,
                    "method": r.method,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                    "ts": r.ts,
                }
                for r in self._records
            ],
            "telemetry_events": [
                {
                    "request_id": e.request_id,
                    "event_type": e.event_type,
                    "ts_ms": e.ts_ms,
                    "data": e.data,
                }
                for e in self._events
            ],
        }

    def export_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["route", "method", "count", "avg_ms", "p95_ms", "error_count"])
        for row in self.route_summary():
            writer.writerow(
                [row["route"], row["method"], row["count"], row["avg_ms"], row["p95_ms"], row["error_count"]]
            )
        return buf.getvalue()

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def generate_request_id() -> str:
        return uuid.uuid4().hex[:16]

    @staticmethod
    def perf_now() -> float:
        return time.perf_counter()

    @staticmethod
    def wall_now() -> float:
        return time.time()

    def clear(self) -> None:
        self._records.clear()
        self._events.clear()
