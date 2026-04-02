import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock global fetch before importing the module
const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

// Mock crypto.randomUUID — jsdom may not provide it
vi.stubGlobal("crypto", {
  ...globalThis.crypto,
  randomUUID: () => "aaaabbbb-cccc-dddd-eeee-ffffffffffff",
});

import { listGames, createGame, getGameState, submitAction, resolveTurn } from "../services/ApiClient";

/** Build a minimal Response-compatible mock with proper headers. */
function mockResponse(body: unknown, status = 200): Response {
  const json = JSON.stringify(body);
  return new Response(json, {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ApiClient", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("listGames sends GET with X-Request-ID header", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse([{ id: "g1", name: "Test", turn: 0, players: ["Alice"] }]),
    );

    const games = await listGames();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/games");
    expect((init.headers as Headers).get("X-Request-ID")).toBeTruthy();
    expect(games).toHaveLength(1);
    expect(games[0]!.id).toBe("g1");
  });

  it("createGame sends POST with JSON body", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse({ game_id: "ng", players: { Alice: "uuid1" }, turn: 0 }, 201),
    );

    const result = await createGame("ng", "Alice", "Bob");

    const [, init] = fetchMock.mock.calls[0]!;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      name: "ng",
      player1: "Alice",
      player2: "Bob",
    });
    expect(result.game_id).toBe("ng");
  });

  it("getGameState encodes player name in URL", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse({ turn: 1, player_name: "Al ice" }),
    );

    await getGameState("g1", "Al ice");

    const [url] = fetchMock.mock.calls[0]!;
    expect(url).toContain("player=Al%20ice");
  });

  it("submitAction sends correct payload", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse({ valid: true, errors: [], warnings: [] }),
    );

    const result = await submitAction("g1", "Alice", "MoveFleet", { fleet: "F1", target: "Alpha" });

    const [, init] = fetchMock.mock.calls[0]!;
    const body = JSON.parse(init.body as string);
    expect(body.player).toBe("Alice");
    expect(body.action_type).toBe("MoveFleet");
    expect(body.action_data.fleet).toBe("F1");
    expect(result.valid).toBe(true);
  });

  it("resolveTurn sends POST to correct URL", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse({ turn: 2, action_results: [], event_count: 0 }),
    );

    const result = await resolveTurn("g1");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/game/g1/resolve");
    expect(init.method).toBe("POST");
    expect(result.turn).toBe(2);
  });
});
