---
title: "Development Phases"
status: "Planning"
last_updated: 2026-03-29
---

# Development Phases

> **Approach:** Build bottom-up. Each phase produces a tested, working layer that the
> next phase builds on. No orphan code. Game content does not appear until the engine
> underneath it is solid. Phases are checkpoints, not deadlines — things will change.
> Reassess the roadmap after each phase gate.

---

## Phase 1 — ECS Core

**Goal:** A working ECS engine with no game-specific code. Pure Python. Fully tested.

This is the hardest phase to get right and the most important to get right first.
Everything else is built on it.

### Deliverables

- `Entity` class: UUID, component bag, lifecycle (create, destroy).
- `Component` base class: schema protocol (name, dependencies, property types,
  constraints, version). No implicit relationships. Schema is mandatory.
- `System` base class: dependency declaration (phase, required components, required
  prior systems, skip-if-missing flag).
- `World` class: queryable interface (`query(ComponentType, ...)`, `add_component`,
  `remove_component` with schema validation, `get_entity`).
- `EventBus`: typed events (who, what, when, why, effects). Publish/subscribe.
  Visibility scope field on events (populated later; field exists now).
- Topological sort of system execution order (build dependency graph, detect cycles,
  execute in phase order).
- Seeded RNG per system per turn: seed = `(game_id, turn_number, system_name)`.
- `ContainerComponent` and `ChildComponent`: arbitrary nesting, constraint
  declaration, parent-child navigation.

### Tests

- Component schema validation catches missing dependencies at entity creation.
- Cycle detection in system dependency graph raises a clear error.
- Topological order is stable and deterministic.
- `World.query()` returns correct entities for multi-component queries.
- `add_component` / `remove_component` respects schema constraints.
- RNG produces identical results for identical seeds.

### Exit Criteria

All tests pass. A `World` with 3 entities, 2 component types, and 2 systems resolves
in declared order and emits events.

---

## Phase 2 — Persistence Layer

**Goal:** World state can be saved, loaded, and migrated. PBEM depends on this.
Do not build the turn loop until state round-trips reliably.

### Deliverables

- SQLite DB integration: tall table schema
  (`entity_id | component_type | component_data_json`).
- World → DB serialization (serialize all entities + components to DB).
- DB → World deserialization (reconstruct full world from DB).
- Full JSON snapshot per turn: `turn_id, game_id, turn_number, state_snapshot,
  resolved_at`.
- Save format versioning: `format_version` in snapshot root; component schemas carry
  own version.
- Migration registry: chainable migration functions, idempotent, applied in order on
  load.
- Log table: `log_id, game_id, turn_number, timestamp, severity, event_type,
  system_name, entity_id, order_id, context, message`.

### Tests

- Full round-trip: serialize world → deserialize → world state identical.
- Migration: load a v1.0 snapshot into a v1.1 schema, result is valid.
- Snapshot for turn N can be loaded and produces identical world to live state.

### Exit Criteria

A world with 10 entities survives save/load with zero data loss. An intentional
schema change (rename one component field) migrates an old snapshot cleanly.

---

## Phase 3 — Turn Engine

**Goal:** A complete turn resolution loop. Orders in → state change → events out.
No game-specific content yet; use stub components and systems.

### Deliverables

- Action protocol: `validate(world) -> ValidationResult` and
  `execute(world) -> list[Event]` interface. All actions implement this.
- `ActionSystem`: receives all actions, validates each independently, executes valid
  ones in deterministic order, emits events. Invalid actions are rejected with clear
  feedback; valid ones are not blocked by invalid ones.
- Order submission window: orders can be submitted and replaced until turn evaluation.
  On evaluation, only the current state of each player's orders is processed.
- Per-order validation at submission time (early feedback) and again at resolution
  (authoritative).
- Conflict resolution: detect conflicting orders, seed RNG with
  `(game_id, turn_number, system_name, conflict_id)`, resolve using unit modifiers.
  One succeeds, others fail with feedback.
- Full turn loop: receive → validate → execute actions → run systems in topo order →
  collect events → snapshot → emit to subscribers.
- Typer CLI commands: `create_game`, `submit_orders`, `resolve_turn`, `query_state`.
- Name-to-UUID resolver: player-facing names mapped to UUIDs transparently.

### Tests

- Two conflicting orders on the same turn: one succeeds, one fails with feedback.
  Same seed produces same winner every time.
- An invalid order in a batch does not block valid orders.
- Turn N resolved twice with the same input produces identical output (determinism).
- Orders submitted before evaluation window closes; replacement order supersedes
  original.

### Deferred Decisions (resolve in Phase 4)

- Exact conflict modifier formula (speed, type, weight).
- Multi-turn action representation (queued construction, etc.).

### Exit Criteria

A 2-player game resolves 3 turns via CLI with stub components. Replaying turn 2 from
its snapshot produces identical state.

---

## Phase 4 — Minimum Playable Game

**Goal:** Real game content on the engine. Two players can play a short, meaningful
game. First time the design meets actual gameplay.

### Deliverables

**Components:**

- `Position` (location in space, parent star system).
- `Owner` (player UUID, name).
- `Resources` (amounts by type, capacity).
- `FleetStats` (speed, capacity, condition).
- `PopulationStats` (size, growth rate, morale).
- `VisibilityComponent` (`visible_to: [player_ids]`, `revealed_to: [player_ids]`).

**Archetypes (templates):**

- `star_system_template` (Position, ContainerComponent, Resources).
- `planet_template` (Position, ChildComponent, Resources, PopulationStats).
- `fleet_template` (Position, ChildComponent, Owner, FleetStats, Resources).

**Systems:**

- `ProductionSystem`: planets produce resources each turn based on PopulationStats.
- `MovementSystem`: fleets move toward destination; resolve multi-turn travel via
  state on FleetStats (deferred: exact travel model).
- `VisibilitySystem`: update VisibilityComponent based on fleet positions and
  ownership.

**Actions:**

- `MoveFleetAction`: validate ownership, fuel/range; update FleetStats destination.
- `ColonizePlanetAction`: validate fleet at planet, uncolonized target; transfer
  owner.
- `HarvestResourcesAction`: validate ownership; transfer resources from planet to
  fleet.

**Player output:**

- Per-player turn summary generated from events filtered through VisibilityComponent.
- Players see only what their fleets can observe. Stale data shown for out-of-range
  entities.

### Tests

- Player A cannot see Player B's fleet outside observation range.
- Turn summary for Player A contains no data Player A shouldn't have.
- ProductionSystem runs only on planets with PopulationStats; skips cleanly otherwise.
- Full 5-turn game resolves without errors.

### Deferred Decisions (resolve during or after Phase 4 playtesting)

- Exact travel time formula for movement.
- Fuel costs (if any).
- Starting positions and resource distribution.
- Victory conditions.

### Exit Criteria

Two players can play 10 turns via CLI with meaningful decisions (move fleets, claim
planets, accumulate resources). Game state is correct after each turn.

---

## Phase 5 — Assess & Extensibility Test

**Goal:** Evaluate the design under real use. Prove extensibility by adding one new
mechanic from scratch without touching the core engine.

### Tasks

- Play a full game (10–20 turns). Surface friction in the design.
- Document what required workarounds or felt wrong.
- Add one new mechanic — candidate options:
  - **Combat:** `CombatSystem`, `CombatAction`, health/damage components.
  - **Diplomacy:** `DiplomacySystem`, `FactionRelation` component, trade actions.
  - **Tech tree:** `ResearchQueue`, `ResearchSystem`, `TechnologyUnlocked` component.
- Measure: did the new mechanic require any core engine changes? If yes, why?
- Revisit deferred decisions from Phases 3 and 4.
- Decide: continue, pivot, or stop.

### Exit Criteria

New mechanic added with zero changes to Phase 1–3 engine code. Deferred decisions
resolved or explicitly re-deferred with rationale. Roadmap for Phase 6+ exists.

---

# Phase 6: Dead Simple Web UI

## Overview

Phase 6 builds a **minimal web interface** to visualize and play the game. No FastAPI, no authentication, no database migration. The Python CLI engine stays as-is; this layer wraps it in a web UI.

**Goal:** You can see the galaxy, see your fleets, submit moves, resolve turns, and understand what's happening.

**Success criteria:**
- Load an existing game (or create one)
- View current turn state as a readable galaxy map
- Submit actions via forms
- Resolve turns via button click
- See updated state after each turn
- Play a full 15–20 turn game without confusion

**Scope:** ~3–5 days of focused work.

---

## Architecture

### Technology Stack

| Layer | Tech |
|-------|------|
| **Backend** | Existing Python CLI + Python HTTP server wrapper |
| **Frontend** | vanilla HTML/CSS/JS in `src/web/` |
| **Data format** | JSON exported from game state (existing serialization) |
| **Storage** | SQLite (unchanged from Phase 4) |

### Design Philosophy

- **Zero FastAPI.** We import the Python game module directly and call functions.
- **No build step.** If using React, it's inline (jsx artifact). If vanilla JS, it's static HTML in `src/web/`.
- **Game logic stays in Python.** The UI is 100% display + form submission; all validation and turn resolution happens in the engine.
- **Deterministic state display.** UI reads snapshots and renders them; no client-side game state.

---

## What Gets Built

### Backend (Python CLI Enhancement)

Add one new module: `src/cli/json_export.py`

**Purpose:** Export current game state as JSON suitable for frontend consumption.

**Exports:**
- `export_game_state(game_id: str) -> dict` — returns:
  ```json
  {
    "turn": 5,
    "players": [
      {
        "id": "uuid",
        "name": "Player A",
        "resources": { "metal": 100, "fuel": 50 },
        "fleets": [
          {
            "id": "uuid",
            "name": "Fleet 1",
            "position": { "system_id": "uuid", "x": 10, "y": 20 },
            "speed": 3,
            "resources": { "metal": 10 }
          }
        ],
        "planets": [
          {
            "id": "uuid",
            "name": "Homeworld",
            "position": { "x": 5, "y": 5 },
            "resources": { "metal": 500 },
            "population": 1000
          }
        ]
      }
    ],
    "star_systems": [
      {
        "id": "uuid",
        "name": "Sol",
        "position": { "x": 5, "y": 5 },
        "planets": [...]
      }
    ],
    "visible_to": "player_id" (fog of war filtering)
  }
  ```

- `list_games() -> list[dict]` — returns list of available games with name, last turn, players.

- `create_game_from_ui(name, num_players) -> dict` — creates game, returns initial state.

- `submit_action(game_id, player_id, action_type, action_data) -> ValidationResult` — validates and queues an action.

- `resolve_turn(game_id) -> dict` — resolves turn, returns new state.

### Frontend

#### Option A: React Artifact (recommended for speed)

Single `.jsx` artifact that:
1. **Sidebar:** Game list; button to create new game; player name/resources display
2. **Map canvas:** SVG or canvas showing star systems as dots, planets as smaller dots, fleets as triangles
3. **Fleet/action panel:** Select a fleet → show speed/position → form to set destination → "Submit Move" button
4. **Events log:** Last 5 events from the turn
5. **Turn counter & resolve button:** Current turn number; big button to resolve turn

Minimal interactivity:
- Click a fleet on the map → select it
- Click a destination system → set move target
- Click "Submit" → calls backend, updates display
- Click "Resolve Turn" → resolves, refreshes state

#### Option B: Vanilla HTML/CSS/JS in `src/web/`

Same structure, but as three separate files:
- `index.html` — layout
- `style.css` — styling
- `game.js` — DOM manipulation and backend calls

---

## Tasks (Minimal)

### Backend (Python)

1. **Create `src/cli/json_export.py`**
   - `export_game_state()` — serialize visible entities for current player
   - `list_games()` — return available games
   - `create_game_from_ui()` — wrapper around existing CLI create_game
   - `submit_action()` — wrapper around existing CLI submit_orders
   - `resolve_turn()` — wrapper around existing CLI resolve_turn

2. **Add `src/cli/server.py`** (optional, but helpful)
   - Simple Flask or built-in `http.server` that serves static files + JSON exports
   - Endpoints: GET `/api/games`, GET `/api/game/:id`, POST `/api/game/:id/action`, POST `/api/game/:id/resolve`
   - No authentication; local development only

### Frontend

1. **Create React artifact (or static HTML)**
   - Galaxy map display (SVG)
   - Fleet/planet list sidebar
   - Action submission forms
   - Turn resolution button
   - Events log

2. **Connect to backend**
   - Fetch `/api/games` on load
   - Fetch `/api/game/:id` to get current state
   - POST to submit actions
   - POST to resolve turn
   - Auto-refresh after turn resolution

---

## Exit Criteria

✓ Create a new game via web UI
✓ See galaxy map with at least 3 star systems and 6+ planets
✓ View current fleet positions and resources
✓ Submit a "move fleet" action and see validation feedback
✓ Resolve a turn and see updated positions
✓ Play 15 turns without console errors
✓ Game state is correct after each turn (no silent corruption)

---

## Not in Phase 6 (Deferred to Phase 7+)

- FastAPI backend
- Player authentication
- Postgres migration
- Turn email notifications
- Multi-server multiplayer hosting
- Undo/save/load UI
- Advanced game mechanics UI (research, diplomacy, etc.)

---

## What Changes, What Doesn't

**Unchanged:** All Python engine code (Phases 1–5), CLI commands, database schema.

**New:** One `json_export.py` module, one optional `server.py`, one frontend (React or static HTML).

**Updated:** This file (DEV_PHASES.md) to clarify Phase 6 scope.

---

*End of Phase 6 specification.*

---

## What Changes, What Doesn't

**Phases 1–3 (engine) should be stable.** The whole point of the design is that
adding new mechanics doesn't touch the core. If Phase 5 reveals that it does, that's
the most important finding of the project.

**Phase 4 content will evolve.** Game balance, component shapes, and system behavior
will change through playtesting. That's expected.

**Phase order is fixed.** Persistence before turn loop. Turn loop before content.
Content before assessment. Skipping layers creates rework.

---

## Phase 7 — Data-Driven Configuration

**Goal:** Make the game tunable without touching Python. Every designer-owned balance
value migrates out of source code into external TOML files under `data/`.

### Deliverables

- `data/balance.toml` — production rates, resource splits, observation range
- `data/archetypes.toml` — default fleet, planet, and star system values
- `data/tech_tree.toml` — research costs and speed multipliers
- `data/map.toml` — home world positions, neutral systems, resource ranges
- `src/game/config.py` — Pydantic models, TOML loaders, module-level singletons
  (`BALANCE`, `ARCHETYPES`, `TECH_TREE`, `MAP`)
- All 28 hardcoded constants removed from `systems.py`, `archetypes.py`, `setup.py`,
  `actions.py` and replaced with config references
- `tests/test_config.py` — loading, validation, migration, and integration tests

### Tests

- Invalid config (splits not summing to 1.0, negative rates) raises a clear error at
  startup — no silent wrong values mid-game
- Overriding a config singleton in tests changes downstream system output (confirms wiring)
- A v1 config file migrates cleanly to v2 via the migration chain
- All 399 Phase 1–6 tests still pass

### Exit Criteria

A designer can change `observation_range` in `data/balance.toml` and the visibility
system uses the new value with zero Python edits. `ruff check src/ tests/` still passes.

See [PHASE_7_DOCU.md](PHASE_7_DOCU.md) for the full implementation plan.

---

*End of development phases.*
