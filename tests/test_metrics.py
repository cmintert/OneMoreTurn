"""Unit tests for cli.metrics — MetricsStore ring buffer and export."""

from __future__ import annotations

from cli.metrics import MetricsStore, RequestRecord, TelemetryEvent


class TestMetricsStore:
    def test_record_and_route_summary(self):
        store = MetricsStore()
        store.record_request(
            RequestRecord(
                request_id="aaa", route="/api/games", method="GET",
                status=200, duration_ms=12.5, ts=1.0,
            )
        )
        store.record_request(
            RequestRecord(
                request_id="bbb", route="/api/games", method="GET",
                status=200, duration_ms=7.5, ts=2.0,
            )
        )
        summary = store.route_summary()
        assert len(summary) == 1
        assert summary[0]["route"] == "/api/games"
        assert summary[0]["count"] == 2
        assert summary[0]["avg_ms"] == 10.0
        assert summary[0]["error_count"] == 0

    def test_error_count(self):
        store = MetricsStore()
        store.record_request(
            RequestRecord(
                request_id="a", route="/api/x", method="GET",
                status=500, duration_ms=1, ts=1.0,
            )
        )
        store.record_request(
            RequestRecord(
                request_id="b", route="/api/x", method="GET",
                status=200, duration_ms=1, ts=2.0,
            )
        )
        summary = store.route_summary()
        assert summary[0]["error_count"] == 1

    def test_ring_buffer_eviction(self):
        store = MetricsStore(max_records=2)
        for i in range(5):
            store.record_request(
                RequestRecord(
                    request_id=str(i), route="/r", method="GET",
                    status=200, duration_ms=1, ts=float(i),
                )
            )
        data = store.export_json()
        assert len(data["recent_requests"]) == 2
        assert data["recent_requests"][0]["request_id"] == "3"

    def test_telemetry_recording(self):
        store = MetricsStore()
        store.record_telemetry(
            TelemetryEvent(
                request_id="r1", event_type="click", ts_ms=100, data={"btn": "resolve"},
            )
        )
        data = store.export_json()
        assert len(data["telemetry_events"]) == 1
        assert data["telemetry_events"][0]["event_type"] == "click"

    def test_export_csv(self):
        store = MetricsStore()
        store.record_request(
            RequestRecord(
                request_id="a", route="/r", method="POST",
                status=200, duration_ms=5, ts=1.0,
            )
        )
        csv_text = store.export_csv()
        assert "route,method,count,avg_ms,p95_ms,error_count" in csv_text
        assert "/r" in csv_text

    def test_clear(self):
        store = MetricsStore()
        store.record_request(
            RequestRecord(
                request_id="a", route="/r", method="GET",
                status=200, duration_ms=1, ts=1.0,
            )
        )
        store.record_telemetry(
            TelemetryEvent(request_id="a", event_type="x", ts_ms=1, data={})
        )
        store.clear()
        data = store.export_json()
        assert data["recent_requests"] == []
        assert data["telemetry_events"] == []

    def test_generate_request_id(self):
        rid = MetricsStore.generate_request_id()
        assert isinstance(rid, str)
        assert len(rid) == 16
