---
title: "Phase 6 Documentation: Web UI Layer"
status: "Complete"
date: 2026-03-31
---

# Phase 6 Documentation: Web UI Layer

## Overview

Phase 6 introduces a **layered web UI architecture** that decouples game state export from HTTP
transport. The goal is to provide stateless JSON export functions that are reusable from CLI,
scripts, or any other interface — not just from a web server.

Three components ship together:

1. **JSON Export Layer** (`src/cli/json_export.py`) — pure, stateless functions for exporting
   game state (with fog-of-war applied) and processing player actions. No HTTP coupling.

2. **Flask HTTP API** (`src/cli/server.py`) — RESTful routes that wrap the JSON layer with
   proper error handling and status codes. Flask is optional (`[web]` extra in `pyproject.toml`).

3. **Web UI** (`src/web/`) — HTML, CSS, and JavaScript for game visualization and interaction.

**Status:** Complete. 29 new tests (17 for JSON export, 12 for Flask API). All 370 Phase 1–5
tests still passing. Grand total: 399 tests. Ruff checks pass. Zero engine changes.

---

## What Was Built

### New Files

| File | Purpose |
|------|---------|
| `src/cli/json_export.py` | 5 stateless functions for game lifecycle and action processing |
| `src/cli/server.py` | Flask app with 5 API routes and static file serving |
| `src/web/index.html` | Game board UI and control panels |
| `src/web/game.js` | Client-side state management and DOM updates |
| `src/web/style.css` | Responsive styling for game visualization |
| `tests/test_json_export.py` | 17 tests: game CRUD, fog-of-war filtering, stale entities, action validation |
| `tests/test_server.py` | 12 tests: Flask routes, request validation, HTTP status codes |

### Modified Files

| File | Change |
|------|--------|
| `pyproject.toml` | Added `flask>=3.0` under `[project.optional-dependencies]` as `web = [...]` |
| `src/cli/main.py` | Added `serve` command with `--host`, `--port`, `--debug` options; deferred Flask import |

---

## Architecture

### 1. [src/cli/json_export.py](src/cli/json_export.py) — JSON Export Layer

**The problem it solves:** The CLI (`src/cli/main.py`) and any future HTTP API or UI need to
export game state with fog-of-war filtering applied. Rather than embedding HTTP concerns into
the export logic, a pure JSON layer separates game-state export from transport.

**The solution:** Five module-level functions that open a DB, read what is needed, close the
DB, and return a plain dict. No session management, no connection pooling, no HTTP context.

#### `list_games() -> list[dict]`

Lists all games under the `games/` directory with metadata:

```python
[
    {
        "id": "game1",
        "name": "game1",
        "turn": 5,
        "players": ["Alice", "Bob"]
    }
]
```

Skips corrupt/unreadable DBs silently (e.g., missing `.db` file for a directory).

#### `create_game(name, player1="Player1", player2="Player2", seed="") -> dict`

Creates a new 2-player game:

1. Create `games/<name>/` directory
2. Initialize SQLite DB at `games/<name>/<name>.db`
3. Call `setup_game(world, [player1, player2], rng)` with seeded RNG
4. Save initial world snapshot at turn 0
5. Return `{game_id, players: {name -> player_uuid}, turn}`

**Determinism:** If `seed` is provided, identical player names and seed produce identical player
UUIDs. This enables reproducible games for testing and demos.

#### `export_game_state(game_id, player_name) -> dict`

Returns the full game state visible to a player with fog-of-war applied:

```python
{
    "turn": 5,
    "game_id": "game1",
    "player_name": "Alice",
    "player_id": "<uuid>",
    "fleets": [
        {
            "id": "<uuid>",
            "name": "Alice_Fleet1",
            "position_x": 0.0,
            "position_y": 0.0,
            "system_id": "<uuid>",
            "system_name": "Alpha",
            "destination_id": "<uuid>",
            "destination_name": "Beta",
            "turns_remaining": 3,
            "speed": 5.0,
            "resources": {"minerals": 50.0}
        }
    ],
    "planets": [...],
    "star_systems": [...],
    "visible_entities": [
        {
            "id": "<uuid>",
            "name": "Bob_Fleet1",
            "type": "fleet",
            "position_x": 50.0,
            "position_y": 50.0,
            "stale": false
        }
    ],
    "events": [
        {
            "type": "FleetArrived",
            "description": "...",
            "entity_name": "Alice_Fleet1"
        }
    ],
    "research": {
        "active_tech": "ion_drive",
        "progress": 2.0,
        "required_progress": 3.0,
        "unlocked": []
    }
}
```

**Fog-of-war filtering:**

- `fleets` and `planets` — only player's own entities
- `star_systems` — always visible (map frame)
- `visible_entities` — enemy fleets/planets filtered by `VisibilityComponent`:
  - In `visible_to` → included with `stale=False`
  - In `revealed_to` only → included with `stale=True`
  - Neither → omitted entirely (not visible at all)
- `events` — filtered by `_event_visible_to_player()` using the same visibility scope logic
- `research` — only returned if the player has a `ResearchComponent`

Omitting invisible entities entirely (rather than redacting them) prevents the client from
discovering entity locations by analyzing JSON diffs.

#### `submit_action(game_id, player_name, action_type, action_data) -> dict`

Validates and queues a player action:

```python
{
    "valid": true,
    "errors": [],
    "warnings": []
}
```

Steps:

1. Load world at current turn
2. Resolve player by name → `player_id`
3. Build typed `Action` from `action_type` + `action_data` (mirrors CLI logic)
4. Call `TurnManager.submit_order(action)` — validation only, no execution
5. Save queued orders back to DB if validation succeeds
6. Return validation result

Valid action types: `MoveFleet`, `ColonizePlanet`, `HarvestResources` (game-specific).

#### `resolve_turn(game_id) -> dict`

Executes the current turn:

1. Load world + all queued orders
2. Create `TurnManager`
3. Submit each queued order (may be rejected if validated differently at resolution time)
4. Call `resolve_turn()` — executes actions, runs systems, saves snapshot
5. Return `{turn, action_results, event_count}`

```python
{
    "turn": 6,  # next current turn after resolution
    "action_results": [
        {"action_type": "MoveFleet", "status": "executed", "errors": []},
        {"action_type": "ColonizePlanet", "status": "conflict", "errors": ["Planet already owned"]}
    ],
    "event_count": 3
}
```

**Why deferred imports:** `from cli.server import run_server` inside `main.py` only occurs when
the `serve` command is invoked. Flask is not imported until then, so the CLI remains fast and
Flask-free when running game logic.

**Why no state class:** Each function opens a fresh `GameDatabase` connection, does its work,
and closes. No stateful `GameServer` class holding DBs or connections. This pattern scales to
multiple concurrent requests (e.g., Flask/Gunicorn workers).

---

### 2. [src/cli/server.py](src/cli/server.py) — Flask HTTP API

**The problem it solves:** RESTful endpoints expose the JSON layer to web clients with
proper HTTP semantics (status codes, JSON responses, error messages).

**The solution:** Flask app with 5 routes, all thin wrappers around `json_export` functions.

#### Routes

| Method | Path | Function | Status Codes |
|--------|------|----------|--------------|
| `GET` | `/` | Serve `index.html` | 200 |
| `GET` | `/web/<path>` | Serve static files (CSS, JS) | 200, 404 |
| `GET` | `/api/games` | `list_games()` | 200 |
| `POST` | `/api/games` | `create_game(name, player1, player2, seed)` | 201, 400, 500 |
| `GET` | `/api/game/<game_id>/state?player=...` | `export_game_state()` | 200, 400, 404, 500 |
| `POST` | `/api/game/<game_id>/orders` | `submit_action(game_id, player, action_type, action_data)` | 200, 422, 400, 404, 500 |
| `POST` | `/api/game/<game_id>/resolve` | `resolve_turn()` | 200, 404, 500 |

**Error handling:**

- `KeyError` (player not found, game not found) → 404 + `{"error": "..."}`
- Validation failure (invalid action_type) → 422 (Unprocessable Entity) + `{"valid": false, "errors": [...]}`
- Missing required query/body params → 400 + `{"error": "..."}`
- Unexpected exception → 500 + `{"error": "..."}`

**Why separate from `json_export`:** The HTTP layer is orthogonal to game logic. If a new
transport (gRPC, WebSocket, REST-like DSL) is needed, only `server.py` is replaced; `json_export`
remains unchanged. Tests can call `json_export` functions directly without spinning up a Flask app.

---

### 3. [src/web/](src/web/) — Static Web UI

#### `index.html`

Responsive single-page app structure:

- **Header:** Game title, current player, turn counter
- **Game Board:** Scaled SVG canvas with star systems, planets, and fleets
- **Panels:** Player fleets, planets, visible enemies, events, tech research
- **Controls:** Action buttons (move, colonize, harvest), turn resolution, game selection

The DOM is initialized by `game.js` on page load and updated after each API call.

#### `game.js`

Client-side state management:

- `GameState` object holds: current game, player, turn, entities, visibility map
- `initGame()` loads game list on startup
- `selectGame(gameId, playerName)` calls `/api/game/<id>/state?player=...` and renders the board
- `submitAction(actionType, actionData)` calls `/api/game/<id>/orders` and refreshes state
- `resolveTurn()` calls `/api/game/<id>/resolve`, then calls `selectGame()` to reload
- `renderBoard()` updates SVG with positions, highlights observable entities, marks stale
- `renderPanels()` updates fleets, planets, events, research panels

No polling; each user action triggers an API call and a UI update.

#### `style.css`

Responsive layout with:

- Flexbox for panels
- SVG canvas styles for entity markers
- Color coding: own entities (green), visible enemies (red), stale entities (gray)
- Hover tooltips with entity details

---

### 4. [src/cli/main.py](src/cli/main.py) — CLI Integration

Added `serve` command:

```bash
onemoreturn serve --host 127.0.0.1 --port 8000 --debug
```

Options:

- `--host` (default `127.0.0.1`) — bind address
- `--port` (default `8000`) — port number
- `--debug` (flag) — Flask debug mode (auto-reload, verbose errors)

Flask is imported only when the command is invoked:

```python
@app.command()
def serve(host: str = ..., port: int = ..., debug: bool = ...):
    from cli.server import run_server  # deferred
    ...
```

This keeps the CLI fast and Flask-optional.

---

### 5. [pyproject.toml](pyproject.toml) — Optional Dependency

Added to `[project.optional-dependencies]`:

```toml
web = ["flask>=3.0"]
```

Users who need only the CLI skip Flask:

```bash
pip install -e ".[cli]"           # CLI only
pip install -e ".[cli,web]"       # CLI + web UI
pip install -e ".[test,cli,web]"  # Development (test + CLI + web)
```

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Separate `json_export.py` from `server.py` | JSON layer reusable from any transport (CLI, gRPC, scripts, tests) |
| Stateless functions (no `GameServer` class) | Scales to multiple concurrent HTTP workers; each request opens/closes DB |
| Omit invisible entities from JSON | Prevents location leakage via JSON diffs; reveals only what visibility allows |
| Mark stale entities with `stale=true` | Client can render out-of-date locations with visual distinction (gray, low opacity) |
| Star systems always visible | Map frame is known; players navigate by system names, not by discovery |
| Flask as optional (`[web]` extra) | CLI remains fast; web UI is optional; users pay for what they use |
| Deferred Flask import in CLI | Flask not loaded unless `serve` command invoked |
| Single-page app (no server-side rendering) | API provides all data; client-side rendering scales to many concurrent users |
| No polling, event-driven updates | Each user action (button click, turn submission) triggers a fresh state fetch |

---

## Test Coverage: 29 New Tests

### test_json_export.py: 17 Tests

| Class | Tests | What is covered |
|-------|-------|-----------------|
| `TestListGames` | 3 | Empty dir, no games, lists existing game with turn and players |
| `TestCreateGame` | 3 | Returns expected shape, creates DB file, deterministic with seed |
| `TestExportGameState` | 7 | Expected keys, own fleets, enemy fleets omitted, own planets, star systems always present, fog-of-war filters enemy fleet outside range, stale entities marked correctly, unknown player raises |
| `TestSubmitAction` | 3 | Valid move fleet, invalid action type, invalid player |
| `TestResolveTurn` | 2 | Turn increments, action executes |

**Key test:** `test_fog_of_war_backend_filtering()` creates a minimal world with Alice and Bob
fleets at distance > OBSERVATION_RANGE, verifies Bob's fleet is absent from Alice's JSON export
(not just hidden, but completely absent).

### test_server.py: 12 Tests

| Class | Tests | What is covered |
|-------|-------|-----------------|
| `TestListGamesRoute` | 2 | Empty list, returns created game |
| `TestCreateGameRoute` | 2 | Creates game (201), missing name (400) |
| `TestGameStateRoute` | 4 | Returns state, missing player param (400), unknown player (404), unknown game (404 or 500) |
| `TestSubmitOrdersRoute` | 3 | Valid order (200), invalid action type (422), missing fields (400) |
| `TestResolveTurnRoute` | 2 | Increments turn, submit-then-resolve workflow |

**Test fixtures:** `client` (empty Flask test client), `game_client` (pre-created game). Both
use `tmp_path` and `monkeypatch.chdir()` to isolate file I/O.

### Totals

| | Count |
|---|---|
| Phase 6 new tests | 29 |
| Phase 1–5 (unchanged) | 370 |
| **Grand total** | **399** |

---

## Extensibility Assessment

Phase 6 demonstrates that **transport and game logic are fully decoupled:**

| Layer | New/changed | Notes |
|-------|----------|-------|
| `src/engine/` | 0 | No changes |
| `src/persistence/` | 0 | No changes |
| `src/game/` | 0 | No changes |
| `src/cli/` | 3 files (json_export.py, server.py, +1 line in main.py) | Pure game export; HTTP is optional |
| `src/web/` | 3 files (new) | Client-side UI; independent of backend transport |
| `tests/` | 2 new files | 29 tests, no changes to engine/persistence tests |

**Future extensibility:**

- Add a new transport (gRPC, WebSocket, MQTT) by importing `json_export` functions into a new
  module — no changes to `json_export.py` or game layer.
- Replace the web UI (React, Vue, terminal TUI) by calling the same API endpoints — no changes
  to backend.
- Add new fields to game state (ship damage, treaties, espionage) — update `export_game_state()`
  to include them; all transports inherit the feature.

---

## Known Limitations (Deferred to Phase 7)

1. **No authentication/authorization** — all players can query any game and submit orders for any player.
2. **Synchronous turn resolution** — `/api/game/<id>/resolve` blocks until done; no job queues.
3. **Single-threaded Flask** — no production WSGI server (Gunicorn, uWSGI); Flask's dev server
   only for testing/demo.
4. **Lossy event summary** — events are aggregated to strings; full event objects are not exposed.
5. **No WebSocket support** — clients poll by calling `selectGame()` manually; no server push.
6. **No replay/undo** — once a turn is resolved, orders cannot be withdrawn or replayed.
