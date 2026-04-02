import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getMetrics } from "../services/ApiClient";
import type { MetricsResponse, RouteSummary } from "../services/types";

interface Props {
  onBack: () => void;
}

type SortKey = keyof RouteSummary;

export default function MetricsView({ onBack }: Props) {
  const { data, error, isError } = useQuery<MetricsResponse>({
    queryKey: ["metrics"],
    queryFn: () => getMetrics("json") as Promise<MetricsResponse>,
    refetchInterval: 3_000,
    retry: 1,
  });

  const [sortKey, setSortKey] = useState<SortKey>("route");
  const [sortAsc, setSortAsc] = useState(true);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const sorted = [...(data?.routes ?? [])].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (typeof av === "number" && typeof bv === "number") {
      return sortAsc ? av - bv : bv - av;
    }
    return sortAsc
      ? String(av).localeCompare(String(bv))
      : String(bv).localeCompare(String(av));
  });

  const handleExport = async () => {
    const csv = await getMetrics("csv");
    const blob = new Blob([csv as string], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "metrics.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <div className="metrics-header">
        <span className="nav-link" onClick={onBack} data-testid="nav-back">
          &larr; Back to Game
        </span>
        <h1>Metrics &amp; Telemetry</h1>
        <button onClick={handleExport} data-testid="export-csv">
          Export CSV
        </button>
      </div>

      {isError && (
        <div className="feedback feedback--err" data-testid="metrics-error">
          {(error as Error)?.message ?? "Could not reach server"}
        </div>
      )}

      <div className="metrics-view" data-testid="metrics-view">
        <h2>Request Summary</h2>
        <table className="metrics-table" data-testid="request-table">
          <thead>
            <tr>
              {(["route", "method", "count", "avg_ms", "p95_ms", "error_count"] as SortKey[]).map(
                (col) => (
                  <th key={col} onClick={() => handleSort(col)}>
                    {col} {sortKey === col ? (sortAsc ? "▲" : "▼") : ""}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr key={i}>
                <td>{row.route}</td>
                <td>{row.method}</td>
                <td>{row.count}</td>
                <td>{row.avg_ms}</td>
                <td>{row.p95_ms}</td>
                <td>{row.error_count}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {data && data.telemetry_events.length > 0 && (
          <>
            <h2>Recent Telemetry</h2>
            <table className="metrics-table" data-testid="telemetry-table">
              <thead>
                <tr>
                  <th>event_type</th>
                  <th>request_id</th>
                  <th>ts_ms</th>
                  <th>data</th>
                </tr>
              </thead>
              <tbody>
                {data.telemetry_events.slice(-20).map((ev, i) => (
                  <tr key={i}>
                    <td>{ev.event_type}</td>
                    <td>{ev.request_id}</td>
                    <td>{ev.ts_ms}</td>
                    <td>{JSON.stringify(ev.data)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        {data && data.recent_requests.length > 0 && (
          <>
            <h2>Recent Requests</h2>
            <table className="metrics-table" data-testid="recent-requests-table">
              <thead>
                <tr>
                  <th>request_id</th>
                  <th>route</th>
                  <th>method</th>
                  <th>status</th>
                  <th>duration_ms</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_requests.slice(-20).map((r, i) => (
                  <tr key={i}>
                    <td>{r.request_id}</td>
                    <td>{r.route}</td>
                    <td>{r.method}</td>
                    <td>{r.status}</td>
                    <td>{r.duration_ms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </>
  );
}
