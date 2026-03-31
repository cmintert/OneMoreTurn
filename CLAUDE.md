# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
python -m pytest

# Run a single test module
python -m pytest tests/test_game_systems.py -v

# Run with short tracebacks
python -m pytest --tb=short

# List all tests without running
python -m pytest --co -q

# Install dev dependencies
pip install -e ".[test,cli]"

# Run the CLI
python -m cli.main --help
onemoreturn --help   # after install

# Lint markdown
markdownlint "**/*.md"

# Check for god classes (too-many-public-methods, too-many-instance-attributes)
.venv/Scripts/ruff check src/ tests/
```

The pytest configuration is in `pyproject.toml`: `testpaths = ["tests"]`, `pythonpath = ["src", "tests"]`.

## Architecture

OneMoreTurn is a PBEM (play-by-email) 4X game engine built on a pure ECS (Entity-Component-System) architecture. The engine layer has **zero game-specific code** — all game content lives in `src/game/`.

### Layer overview

```
src/cli/          Typer CLI: create-game, submit-orders, resolve-turn, query-state, turn-summary
src/game/         Game content: components, actions, systems, archetypes, setup, summary
src/persistence/  SQLite layer: snapshots, orders, events, serialization, migrations
src/engine/       ECS core: Entity, World, Component, System, Action, EventBus, TurnManager, RNG
```

### Engine core (`src/engine/`)

- **`ecs.py`** — `Entity` (UUID-based), `World` (central registry), `SchemaError`
- **`components.py`** — Abstract `Component` with schema protocol: `component_name()`, `version()`, `dependencies()`, `properties_schema()`, `constraints()`, plus validation hooks `validate()` / `on_add_validation()` / `on_remove_validation()`
- **`systems.py`** — Abstract `System` with phase ordering (PRE_TURN → MAIN → POST_TURN → CLEANUP) and topological sort via Kahn's algorithm using `required_prior_systems()`
- **`actions.py`** — Abstract `Action` with `validate(world) -> ValidationResult` and `execute(world) -> list[Event]`; `ActionSystem` handles conflict resolution
- **`events.py`** — `Event` (immutable, with `visibility_scope` for fog-of-war), `EventBus` (typed pub/sub)
- **`turn.py`** — `TurnManager`: receive orders → validate → execute → run systems → save snapshot → emit events
- **`rng.py`** — `SystemRNG` seeded per `(game_id, turn_number, system_name)` — ensures determinism
- **`names.py`** — `NameComponent` + `NameResolver` for player-facing names → UUID mapping

### Game content (`src/game/`)

- **`components.py`** — `Position`, `Owner`, `Resources` (dict stockpile with capacity), `FleetStats` (destination, turns_remaining), `PopulationStats`, `VisibilityComponent` (visible_to, revealed_to sets)
- **`systems.py`** — `ProductionSystem` (MAIN), `MovementSystem` (MAIN), `VisibilitySystem` (POST_TURN); `OBSERVATION_RANGE = 10.0`
- **`actions.py`** — `MoveFleetAction`, `ColonizePlanetAction`, `HarvestResourcesAction`
- **`archetypes.py`** — Factory functions: `create_star_system()`, `create_planet()`, `create_fleet()`
- **`setup.py`** — Procedural, seeded map generation
- **`registry.py`** — `game_component_registry()`, `game_action_registry()`, `game_systems()` — the wiring layer connecting persistence to game content
- **`summary.py`** — `generate_turn_summary()` filters entity state and events by per-player fog-of-war

### Persistence (`src/persistence/`)

SQLite database with 5 tables: `entity_components`, `turns` (full snapshots), `orders`, `events`, `event_log`.

- **`db.py`** — `GameDatabase`: `save_snapshot()`, `load_world()`, `save_order()`, `get_current_orders()`, `save_events()`, `load_events()`
- **`serialization.py`** — `ComponentRegistry` / `ActionRegistry` (name → class mappings), `serialize_world()` / `deserialize_world()` (with schema validation)
- **`migrations.py`** — `MigrationRegistry`: idempotent, chained migrations applied on world load

### Key design invariants

1. **No game logic in the engine.** The engine (`src/engine/`) must remain game-agnostic and extensible.
2. **Determinism.** System execution order is topologically sorted; RNG is seeded per `(game_id, turn_number, system_name)`. Identical inputs always produce identical outputs.
3. **Validation is layered.** Components validate at construction; actions validate at submission and again at resolution.
4. **Conflict resolution via seeded RNG.** When competing orders conflict, exactly one succeeds; all others get failure feedback.
5. **Fog of war is structural.** `VisibilityComponent.visible_to` / `revealed_to` are maintained by `VisibilitySystem` each turn; `generate_turn_summary()` filters output by these sets.

## Class size limits

Ruff enforces a god-class rule on every file in `src/` and `tests/`:

| Rule | Limit | Tightest existing class |
| --- | --- | --- |
| `PLR0904` too-many-public-methods | **14** | `TestWorldRoundTrip` — 13 methods |

(Ruff does not implement `PLR0902` too-many-instance-attributes.)

When `ruff check src/ tests/` fails, options in order of preference:

1. **Split the class.** ECS makes this natural — extract a new system, action, helper registry, or module-level functions.
2. **Refactor to reduce scope.** A class past the limit usually has two concerns mixed together.
3. **Suppress inline** with `# noqa: PLR0904` plus a comment explaining why. Use sparingly.

ECS-specific decomposition hints:

- `GameDatabase` growing → extract `OrderStore`, `EventStore`, or `SnapshotStore`
- `World` growing → extract a `ComponentIndex` or `EntityRegistry` helper
- Large `System` → split into two systems; declare the dependency via `required_prior_systems()`
- Large `Action` → extract module-level helper functions (see existing pattern in [src/game/actions.py](src/game/actions.py))

## Testing

Tests live in `tests/` with one module per source module. `conftest.py` provides shared fixtures and test-only component stubs. `stubs.py` provides `Action` stubs. The `hypothesis` library is available for property-based tests.

Key integration test modules: `test_game_integration.py` (5-turn full game simulation), `test_integration.py` (engine end-to-end), `test_cli.py` (CLI command integration).

## Development status

Phases 1–4 are complete (ECS core, persistence, turn engine, minimum playable game). Phase 5 is next: assessing extensibility and stress-testing the architecture by attempting to add a new game mechanic without modifying the engine.

Design rationale and phase-by-phase documentation live in `DESIGN.md`, `DEV_PHASES.md`, and `PHASE_*_DOCU.md`.
