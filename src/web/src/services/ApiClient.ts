/**
 * Instrumented API client — all backend calls go through here.
 *
 * Every request:
 *  - injects X-Request-ID header
 *  - measures round-trip latency
 *  - reports to TelemetryClient (if provided)
 */

import type {
  CreateGameResponse,
  GameListItem,
  GameState,
  MetricsResponse,
  ResolveTurnResponse,
  SubmitActionResponse,
} from "./types";
import { telemetryClient } from "./TelemetryClient";

function requestId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
}

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const rid = requestId();
  const start = performance.now();

  const headers = new Headers(init?.headers);
  headers.set("X-Request-ID", rid);
  if (init?.body) headers.set("Content-Type", "application/json");

  let resp: Response;
  try {
    resp = await fetch(url, { ...init, headers });
  } catch (err) {
    telemetryClient.track("api_error", { url, error: String(err) });
    throw new Error(`Network error — is the Flask server running? (${String(err)})`);
  }

  const duration = performance.now() - start;

  // Safe JSON parse — proxy errors may return empty or HTML bodies
  const contentType = resp.headers.get("content-type") ?? "";
  let data: unknown;
  if (contentType.includes("application/json")) {
    data = await resp.json();
  } else {
    const text = await resp.text();
    try {
      data = text.length ? JSON.parse(text) : {};
    } catch {
      throw new Error(`HTTP ${resp.status} — expected JSON but got: ${text.slice(0, 120)}`);
    }
  }

  telemetryClient.track("api_call", {
    request_id: rid,
    url,
    method: init?.method ?? "GET",
    status: resp.status,
    duration_ms: Math.round(duration),
  });

  if (!resp.ok) {
    const errMsg = (data as { error?: string })?.error ?? `HTTP ${resp.status}`;
    throw new Error(errMsg);
  }

  return data as T;
}

// -- typed endpoints --------------------------------------------------------

export function listGames(): Promise<GameListItem[]> {
  return apiFetch<GameListItem[]>("/api/games");
}

export function createGame(
  name: string,
  player1: string,
  player2: string,
): Promise<CreateGameResponse> {
  return apiFetch<CreateGameResponse>("/api/games", {
    method: "POST",
    body: JSON.stringify({ name, player1, player2 }),
  });
}

export function getGameState(
  gameId: string,
  player: string,
): Promise<GameState> {
  return apiFetch<GameState>(
    `/api/game/${gameId}/state?player=${encodeURIComponent(player)}`,
  );
}

export function submitAction(
  gameId: string,
  player: string,
  actionType: string,
  actionData: Record<string, unknown>,
): Promise<SubmitActionResponse> {
  return apiFetch<SubmitActionResponse>(`/api/game/${gameId}/orders`, {
    method: "POST",
    body: JSON.stringify({
      player,
      action_type: actionType,
      action_data: actionData,
    }),
  });
}

export function resolveTurn(
  gameId: string,
): Promise<ResolveTurnResponse> {
  return apiFetch<ResolveTurnResponse>(`/api/game/${gameId}/resolve`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getMetrics(format: "json" | "csv" = "json"): Promise<MetricsResponse | string> {
  if (format === "csv") {
    return fetch(`/api/metrics?format=csv`).then((r) => r.text()) as Promise<string>;
  }
  return apiFetch<MetricsResponse>(`/api/metrics?format=json`);
}
