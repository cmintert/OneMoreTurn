
---
title: "PBEM 4X Game — Design Document"
status: "Groundwork / Exploration Phase"
last_updated: 2026-03-29
---

# PBEM 4X Game — Design Document

## Vision

Build an asynchronous, turn-based 4X strategy game where players submit orders.
The server resolves turns deterministically and the design targets PBEM (play-by-email) multiplayer.

Inspired by Stars!, VGA Planets, and the elegance of asynchronous gameplay mechanics.

## Core Design Principles

### Architecture

- **ECS Pattern (Entity-Component-System):** Entities: planets, ships, players.
- **Components:** Attributes such as `Position`, `Resources`, and `Owner`.
- **Systems:** Operate on components each turn.
- **Extensibility First:** Design should allow adding new entity types and mechanics
        without requiring refactoring of core systems.

### Entity Model

- **Flat hierarchy:** No nested structures — everything is an entity.
- **Spatial references:** Entities reference their parent/container via `parent_id`.
        This avoids nested objects and keeps entity relationships flat.

Example: a ship has `parent_id = <star_system_id>` (not embedded in the star system).

Query pattern example:

```text
Give me all entities where parent_id == X
```

### Turn Resolution

- **Deterministic:** Same input state and orders produce the same output.
        No implicit RNG is used.
- **Simultaneous:** All players submit orders for a turn; the server resolves all at once.
- **Serializable:** Turn state can be saved, loaded, and reconstructed for PBEM compatibility.

## Game State

- **Database per game:** Each game uses its own SQLite file initially.
- **Engine owns schema:** The core engine defines and manages migrations.
- **Path to scale:** Start with SQLite files locally; migrate to Postgres for hosted multiplayer.

Database location (initial):

```text
games/{game_name}/{game_name}.db
```

## Tech Stack

### Core Engine

- **Language:** Python 3.11+
- **Dependencies:** None required for core — pure Python, importable as a library.
- **Testable:** All game logic must be runnable without a UI.

### CLI Layer

- **Framework:** Typer
- **Purpose:** Scriptable interface for testing, automation, and local play.

Example commands:

```bash
create_game --name "Game1" --players 4
submit_turn --game-id "game-123" --orders "orders.json"
query_state --game-id "game-123"
```

### Backend (optional)

- **Framework:** FastAPI
- **Purpose:** Turn submission endpoints, game state queries, player auth, hosting.
- **Note:** Not required; game works CLI-only initially.

### Frontend

- **Technology:** Vanilla HTML/CSS/JavaScript (no build step).
- **Structure:** Static files served from `src/web/`.
- **Approach:** JS calls FastAPI endpoints; frontend is decoupled from engine internals.

## Development Phases

### Phase 1 — Foundation (1–2 weeks)

Goal: Prove the ECS pattern works and that state is serializable.

- Implement ECS skeleton (`Entity`, `Component`, `System`).
- Define basic components: `Position`, `Owner`, `Resources`, etc.
- Build a simple system (e.g., resource production).
- Implement DB schema and migrations; serialize/deserialize state.
- Write tests that validate state round-trips.

Deliverable: Working ECS with one complete resource cycle, testable in Python.

### Phase 2 — Turn Loop (2–3 weeks)

Goal: Build a full game loop and make a playable prototype.

- Create Typer CLI commands.
- Implement turn submission and resolution.
- Build minimal game state (players, resources, one action type).
- Optional: FastAPI backend + static web UI to visualize state and submit orders.
- Write scenarios/tests that exercise the loop.

Deliverable: Playable game via CLI or browser (5–10 turns).

### Phase 3 — Assess (1 week)

Goal: Evaluate design, identify friction, and decide next steps.

- Play the game and surface issues in the ECS pattern or mechanics.
- Decide whether to continue, pivot, or stop.

Deliverable: Clear decision and roadmap for Phase 4.

## Architectural Decisions (Locked)

### Entity ID & Referencing

- **Decision:** UUIDs for all entity IDs.
- **Rationale:** Globally unique, DB-agnostic, supports portability of turn files.

Entities reference others by `entity_id` (never local DB PKs).

### Component Data Layout

- **Decision:** Tall table schema:

```text
entity_id | component_type | component_data_json
```

- **Rationale:** Adding components does not require schema migrations.

### Turn State Snapshots

- **Decision:** Store full JSON snapshots every turn.
- **Rationale:** Debuggability over storage savings at this scale.

Turns table example columns:

```text
turn_id, game_id, turn_number, state_snapshot (JSON), resolved_at
```

### Component Initialization

- **Decision:** Use archetypes/templates (e.g., `planet_template`, `ship_template`).

Rationale: type-safety, predictable initialization, fewer lazy-init bugs.

### System Execution Order

- **Decision:** Manual orchestration in `Game` class; explicit ordering of systems.
- **Rationale:** Simpler debugging at Phase 1 scale.
        Example order: ResourceProduction → Movement → Decay.

### Determinism & RNG

- **Decision:** Seeded RNG per turn. Seed = `(game_id, turn_number)`.
- **Rationale:** Reproducible turn resolution for PBEM.

### Turn Submission & Validation

- **Decision:** Strict validation: reject entire submission if any order is invalid.
- **Rationale:** Simpler, clearer behavior and error feedback.

### Spatial Hierarchy

- **Decision:** One-level spatial model; entities reference `parent_id`.
- **Rationale:** Simpler queries and spatial logic.

### Testing Strategy

- **Decision:** Factory functions for unit tests + seed-based scenarios for integration tests.

Example fixture:

```python
GameFactory.create_game_with_players(2)
```

## Key Design Decisions (Deferred)

- Movement & travel (instant vs multi-turn, fuel costs)
- Conflict resolution and combat model
- Player interaction systems (diplomacy, trade)

These will be decided in Phase 2.

## Project Structure (Planned)

```text
PBEMGame/
├── README.md
├── DESIGN.md
├── pyproject.toml
├── src/
│   ├── engine/
│   │   ├── ecs.py
│   │   ├── components.py
│   │   ├── systems.py
│   │   └── game.py
│   ├── database/
│   │   ├── db.py
│   │   └── models.py
│   ├── cli/
│   │   └── main.py
│   ├── api/
│   │   └── main.py
│   └── web/
│       ├── index.html
│       ├── style.css
│       └── game.js
├── tests/
│   ├── test_ecs.py
│   ├── test_game_loop.py
│   └── ...
├── games/
└── .gitignore
```

## Notes & Constraints

- No UI dependency in core engine; logic must be testable in pure Python.
- CLI-first approach: prove mechanics before building UI.
- Deterministic turn resolution is required.
- Extensibility via ECS pattern is a primary goal.

## References & Inspiration

- Stars! (1995)
- VGA Planets
- Thousand Parsec
- ECS Pattern (used in Unity, Godot)

## Setup Decisions (Locked)

### Git & Publishing

- **Decision:** Use GitHub private repo for version control and issue tracking.
- **Rationale:** Private repo ensures code confidentiality during early development.

- repo is at  <https://github.com/cmintert/OneMoreTurn>

### Python Version

- **Decision:** Target Python 3.11+.

### Naming Conventions

- **Decision:** `PascalCase` for component class names (e.g., `ResourceProduction`).

## Error Handling & Logging Strategy (Locked)

### Audience & Verbosity

- Primary audience: developers.
        Log game-observable events (orders, outcomes, state changes), not low-level ECS internals.

### Failure Behavior

- On system failure during turn resolution: skip that system and continue others.
        Log the error for admins so issues can be diagnosed and replayed.

### Error Visibility

- Players receive summaries; detailed traces are admin-only.

### Log Storage & Schema

Logs are stored in the DB (structured JSON) and printed to stdout during development.

Example `logs` table columns:

```text
log_id (UUID), game_id, turn_number, timestamp, severity,
event_type, system_name, entity_id, order_id, context (JSON), message
```

Severity levels: `EXCEPTION`, `VALIDATION`, `WARNING`, `INFO`.

### Event Architecture

- Centralized `EventBus`: systems emit events; `GameLogger` subscribes and writes to DB/stdout.

## Next Steps

1. Define event taxonomy for Phase 1.
2. Implement `EventBus` class.
3. Implement `GameLogger` (DB writes + stdout).
4. Wire logging and event emission into `Game` and `System` base classes.
5. Add tests for event emission and log queries.

---

*End of design document.*
