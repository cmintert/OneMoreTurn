---
title: "Phase 4 Documentation: Minimum Playable Game"
status: "Complete"
date: 2026-03-31
---

# Phase 4 Documentation: Minimum Playable Game

## Overview

Phase 4 transforms the ECS engine into a **minimum playable 2-player space 4X game**. Where
Phases 1–3 built the engine infrastructure (ECS core, persistence, turn loop), Phase 4 fills it
with real game content: star systems, planets, fleets, three player actions, three game systems,
fog of war, and a turn summary report.

**Status:** Complete. 104 new tests. All 247 Phase 1–3 tests still passing. Grand total: 351 tests.

---

## What Was Built

### New Package: `src/game/`

| File | Purpose |
|------|---------|
| `src/game/__init__.py` | Package init |
| `src/game/components.py` | 6 game components |
| `src/game/actions.py` | 3 player actions |
| `src/game/systems.py` | 3 game systems |
| `src/game/archetypes.py` | Entity factory functions |
| `src/game/setup.py` | Map generation and game initialization |
| `src/game/registry.py` | Registry construction helpers |
| `src/game/summary.py` | Per-player fog-of-war turn summary |

### Modified Files

| File | Change |
|------|--------|
| `src/persistence/db.py` | Added `events` table, `save_events()`, `load_events()` |
| `src/engine/turn.py` | `resolve_turn()` now calls `save_events()` after each turn |
| `src/cli/main.py` | Rewritten with game content: 5 commands, player visibility filter |
| `pyproject.toml` | Added `src/game` to wheel packages |
| `tests/conftest.py` | Renamed `PositionComponent` → `StubPositionComponent`, `OwnerComponent` → `StubOwnerComponent` to avoid name conflicts with game components |
| 7 existing test files | Updated for conftest rename (`StubPosition`, `StubOwner`) |

---

## Architecture

### 1. [src/game/components.py](src/game/components.py) — Game Components

Six domain components describe all game state. All are standard Component subclasses, serializable via the Phase 2 registry.

| Component | Fields | Notes |
|-----------|--------|-------|
| `Position` | `x, y: float`, `parent_system_id: UUID \| None` | 2D coordinate + parent reference |
| `Owner` | `player_id: UUID`, `player_name: str` | Who controls this entity |
| `Resources` | `amounts: dict[str, float]`, `capacity: float` | Generic resource stockpile; validates `total() ≤ capacity` |
| `FleetStats` | `speed, capacity, condition: float`, `destination_x/y, destination_system_id, turns_remaining` | Movement state; destination fields `None` when idle |
| `PopulationStats` | `size: int`, `growth_rate: float`, `morale: float` | Planet population; drives production volume |
| `VisibilityComponent` | `visible_to: list[UUID]`, `revealed_to: list[UUID]` | Fog of war; `visible_to` = currently seen, `revealed_to` = ever seen (stale) |

**Why `Resources` uses a dict:**
A `dict[str, float]` holds any resource type (`minerals`, `energy`, `food`, or future types) without schema changes. The only constraint is `total() ≤ capacity`. This is explicitly extensible per DESIGN.md.

**Why VisibilityComponent tracks both lists:**
`visible_to` is rebuilt every turn by `VisibilitySystem`. `revealed_to` is additive and never cleared, giving players a persistent "fog of war" map of systems they've scouted.

---

### 2. [src/game/archetypes.py](src/game/archetypes.py) — Entity Factories

Three factory functions encapsulate the multi-component entity creation patterns that occur both in setup and in tests:

```python
create_star_system(world, name, x, y, base_resources=None) -> Entity
    # Adds: NameComponent, Position, ContainerComponent, Resources(capacity=500),
    #        VisibilityComponent

create_planet(world, name, parent_system, resources=None, population=0,
              owner_id=None, owner_name="") -> Entity
    # Adds: NameComponent, Position (inherits parent x/y), ChildComponent,
    #        Resources(capacity=200), VisibilityComponent
    # Conditionally adds: PopulationStats (if population > 0), Owner (if owner_id given)

create_fleet(world, name, owner_id, owner_name, parent_system,
             speed=5.0, cargo=None) -> Entity
    # Adds: NameComponent, Position (inherits parent x/y), ChildComponent,
    #        Owner, FleetStats(speed, capacity=50), Resources (cargo, capacity=50),
    #        VisibilityComponent
```

The parent system's position is fetched at creation time so planets and fleets start at the same coordinates as their containing system. ContainerComponent validates child additions; ChildComponent's `on_added` hook registers them into the parent's `children` list.

---

### 3. [src/game/systems.py](src/game/systems.py) — Game Systems

All three systems follow the Phase 3 pattern: MAIN-phase systems declare `required_prior_systems=[ActionSystem]` so they run after player actions are applied.

#### ProductionSystem

```
Phase: MAIN   Required prior: ActionSystem
Queries: (PopulationStats, Resources, Owner)
```

Each owned planet produces per turn:

```
production = pop.size × pop.morale × 0.1
  minerals += production × 0.4   (capped at Resources.capacity)
  energy   += production × 0.3   (capped)
  food     += production × 0.3   (capped)
  pop.size += max(int(size × growth_rate × morale), 1)
```

Emits `ProductionCompleted` event with `visibility_scope=[str(owner.player_id)]` so only the owner sees this event in their turn summary.

**Why skip unowned planets:** The query requires `Owner` — neutral planets don't match and are silently skipped, giving the colonization mechanic value.

#### MovementSystem

```
Phase: MAIN   Required prior: ActionSystem
Queries: (FleetStats, Position)
```

Each in-transit fleet moves `speed` distance units per turn:

```
Euclidean distance from current position to destination.
Progress per turn = speed / total_distance.
Position moves along the direct vector.
On final turn (turns_remaining == 1): snap to exact destination coordinates,
  set destination fields to None, add ChildComponent(parent_id=target_system).
Emits FleetArrived event on arrival.
```

MoveFleetAction (executed by ActionSystem first) removes the fleet's ChildComponent and sets the destination fields. MovementSystem then advances it each turn. The separation of "order" (action) from "movement" (system) means the fleet is parentless while in transit — it belongs to no star system.

#### VisibilitySystem

```
Phase: POST_TURN   Required prior: none
Queries: (Owner, Position), then (VisibilityComponent, Position)
OBSERVATION_RANGE = 10.0 distance units
```

1. Builds `observer_positions: dict[UUID, (x, y)]` — one entry per owned entity with a Position.
2. For every entity with VisibilityComponent + Position: compute distance to each observer's position. If distance ≤ 10.0, add observer's player_id to `visible_to`. Add to `revealed_to` if not already there.
3. Clears `visible_to` each turn and rebuilds from scratch. `revealed_to` is cumulative.

**Runs POST_TURN** (not MAIN) so visibility reflects moved fleets' arrival positions at end of turn rather than departure positions.

---

### 4. [src/game/actions.py](src/game/actions.py) — Player Actions

Three actions cover the core 4X loop: explore (movement), expand (colonize), exploit (harvest).

#### MoveFleetAction

```python
MoveFleetAction(player_id, order_id, fleet_id, target_system_id)
action_type() = "MoveFleet"
conflict_key() = None   # fleets don't conflict with each other
```

**Validate:** Fleet exists, owned by player, has FleetStats, not already moving (turns_remaining == 0), target system exists and has Position.

**Execute:** Compute Euclidean distance; `turns_remaining = ceil(distance / speed)`; set `destination_x/y/system_id`; update `parent_system_id = None`; remove ChildComponent from current parent; emit `FleetDeparted`.

#### ColonizePlanetAction

```python
ColonizePlanetAction(player_id, order_id, fleet_id, planet_id)
action_type() = "ColonizePlanet"
conflict_key() = f"colonize:{planet_id}"   # two players can't colonize same planet
```

**Validate:** Fleet exists + owned by player, planet exists, fleet and planet share same `parent_system_id`, planet has no Owner.

**Execute:** Add Owner(player_id, player_name) to planet. Add PopulationStats(size=10) if absent. Emit `PlanetColonized` with visibility_scope for the player.

**Why conflict_key on planet_id:** Two players could legitimately both arrive at a neutral system in the same turn. The Phase 3 conflict resolution mechanism (deterministic weighted RNG) automatically handles the race condition.

#### HarvestResourcesAction

```python
HarvestResourcesAction(player_id, order_id, fleet_id, planet_id, resource_type, amount)
action_type() = "HarvestResources"
conflict_key() = None
```

**Validate:** Fleet exists + owned, planet exists + owned by same player, fleet and planet in same system, planet has enough of `resource_type`, fleet has cargo capacity for `amount`.

**Execute:** Subtract `amount` from planet's resources; add to fleet's resources. Emit `ResourcesHarvested`.

---

### 5. [src/game/setup.py](src/game/setup.py) — Map Generation

```python
setup_game(world: World, player_names: list[str], rng: SystemRNG) -> dict[str, UUID]
```

Returns `{player_name: player_id}`. Creates the full starting map:

| What | Count | Details |
|------|-------|---------|
| Home systems | 2 | Positions (10, 50) and (90, 50) |
| Home planets | 2 | pop=100, resources {minerals:50, energy:30, food:40}, capacity=200 |
| Home fleets | 2 | speed=5.0, cargo {minerals:10, energy:5} |
| Neutral systems | 5 | Fixed positions: (30,30), (50,50), (70,70), (50,20), (40,60) |
| Neutral planets | 5–10 | 1–2 per neutral system, rng-varied resources |

Player IDs are generated deterministically from the RNG, so `setup_game(world, names, rng)` with the same seed produces identical UUIDs and entity layouts every time.

---

### 6. [src/game/registry.py](src/game/registry.py) — Registry Helpers

Three convenience functions for constructing fully-populated registries:

```python
game_component_registry() -> ComponentRegistry
    # Registers: Position, Owner, Resources, FleetStats, PopulationStats,
    #             VisibilityComponent, NameComponent, ContainerComponent, ChildComponent

game_action_registry() -> ActionRegistry
    # Registers: MoveFleetAction, ColonizePlanetAction, HarvestResourcesAction

game_systems() -> list[System]
    # Returns instantiated: [ProductionSystem(), MovementSystem(), VisibilitySystem()]
```

CLI commands and TurnManager both call these helpers. Tests use them directly.

---

### 7. [src/game/summary.py](src/game/summary.py) — Turn Summary

```python
generate_turn_summary(world: World, player_id: UUID, events: list[Event]) -> str
```

Produces a four-section per-player text report:

1. **Your Planets** — entities matching `(Owner, PopulationStats, Resources)` filtered to `owner.player_id == player_id`. Shows name, population, morale, resource amounts.
2. **Your Fleets** — entities matching `(Owner, FleetStats, Position)` filtered to player. Shows speed, current position or transit status.
3. **Visible Entities** — all entities with `VisibilityComponent` where player_id appears in `visible_to` or `revealed_to`, excluding own entities. Stale entries (revealed but no longer visible) are tagged `[stale]`.
4. **Events** — turn events filtered through `_event_visible_to_player()`.

#### Fog of War: `_event_visible_to_player(event, player_id, world) -> bool`

Resolution order:
1. If `event.visibility_scope` is set: check if `str(player_id)` appears in it.
2. If `event.who` is a UUID: fetch entity from World; if it has Owner, check ownership match; if it has VisibilityComponent, check `visible_to`/`revealed_to`.
3. Otherwise: hidden (return False).

This means system events (who = "system" string) are hidden unless they explicitly set a visibility_scope. Production events set `visibility_scope=[str(owner.player_id)]` so only the producing player sees them.

---

### 8. DB: Events Table ([src/persistence/db.py](src/persistence/db.py))

A new `events` table enables full Event round-trip persistence for replay and the `turn-summary` CLI command:

```sql
CREATE TABLE IF NOT EXISTS events (
    game_id     TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    event_index INTEGER NOT NULL,
    event_json  TEXT NOT NULL,
    PRIMARY KEY (game_id, turn_number, event_index)
);
```

```python
GameDatabase.save_events(game_id, turn_number, events: list[Event]) -> None
    # Serializes each Event to JSON: who/what/when/why/effects/visibility_scope/timestamp
    # visibility_scope: list[str] (UUIDs as strings) or null

GameDatabase.load_events(game_id, turn_number) -> list[Event]
    # Loads rows ordered by event_index, deserializes back to Event instances
```

`TurnManager.resolve_turn()` now calls `save_events()` after each turn alongside the existing `save_snapshot()` and `save_orders()` calls. This makes the `events` table the authoritative per-turn event log, separate from the `event_log` table (which records diagnostic metadata).

---

### 9. CLI ([src/cli/main.py](src/cli/main.py))

The CLI was rewritten to use game content. Phase 3 stub imports are gone.

| Command | Change from Phase 3 |
|---------|---------------------|
| `create-game` | `--player1/--player2/--seed` options; calls `setup_game()` instead of manual entity creation |
| `submit-orders` | `_resolve_player_id()` scans Owner components instead of PlayerComponent; handles MoveFleet/ColonizePlanet/HarvestResources |
| `resolve-turn` | Passes `game_systems()` to TurnManager |
| `query-state` | New `--player` option: hides entities not in player's `visible_to`/`revealed_to`; marks stale entries `[stale]` |
| `turn-summary` | **New command.** Loads snapshot + events for a turn, calls `generate_turn_summary()`, prints result |

---

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Phase 4 stubs renamed to `Stub*` in conftest | `PositionComponent` and `OwnerComponent` would collide with game components of the same `component_name()`. Renamed to `StubPosition`/`StubOwner` to avoid pytest collection warnings and serialization conflicts. |
| `Resources` uses `dict[str, float]` | Extensible without schema migration. Constraint validates total ≤ capacity. |
| `VisibilitySystem` runs POST_TURN | Ensures visibility reflects end-of-turn positions (fleets that arrived this turn are visible). |
| `MovementSystem` removes ChildComponent on departure | Fleet belongs to no system while in transit; parent-child integrity is maintained (you can't have both). |
| Children list ordering in Container | `ContainerComponent.children` is append-ordered. When comparing replay snapshots, children lists must be sorted before equality check (order is insertion-dependent, not semantically significant). |
| Separate `events` table from `event_log` | `event_log` is a structured diagnostic log (severity, system_name, etc.). The new `events` table stores full JSON for lossless round-trip deserialization needed by `turn-summary` and replay. |
| Player IDs generated by RNG in `setup_game()` | Deterministic given a seed. Same player names + same seed = same UUIDs in all tests and replays. |
| `game_systems()` returns new instances each call | `TurnManager` is stateless across CLI invocations; a new instance per turn-resolution is the correct pattern. |

---

## Test Coverage: 104 New Tests

### New Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_game_components.py` | 26 | Instantiation, validation, constraints, serialization round-trips for `dict[str,float]` and `list[UUID]` |
| `tests/test_game_archetypes.py` | 16 | Entity creation, component presence, containment setup, parent position inheritance |
| `tests/test_game_systems.py` | 19 | Production amounts/capacity/growth, movement/arrival/reparenting, visibility range/persistence/fog |
| `tests/test_game_actions.py` | 16 | Validation errors (missing entity, wrong owner, already moving, unowned planet), execute effects, conflict keys |
| `tests/test_game_setup.py` | 7 | Entity counts, home systems/planets/fleets per player, neutral systems, determinism |
| `tests/test_game_integration.py` | 7 | 10-turn resolution, event production, resource growth, fleet movement+arrival, colonization, unowned skip, deterministic replay |
| `tests/test_visibility.py` | 11 | Own planets/fleets visible, opponent entities hidden/visible/stale, event scope filtering |

### Modified Test Files (net change)

| File | Before | After | Delta |
|------|--------|-------|-------|
| `tests/test_cli.py` | 13 | 11 | −2 (rewrote for game content) |
| `tests/test_persistence.py` | 19 | 23 | +4 (`TestEventRoundTrip`) |

### Totals

| | Count |
|---|---|
| Phase 4 new tests | 104 |
| Phase 1–3 (unchanged) | 247 |
| **Grand total** | **351** |

---

## Test Philosophy

Consistent with prior phases:

- **Isolated:** Every test creates a fresh `World(event_bus=EventBus())`. No shared mutable state.
- **Tuple destructuring:** `world.query()` returns `(entity, comp1, comp2, ...)` tuples; tests destructure explicitly.
- **Event assertions:** Integration tests count events per turn; system tests assert specific `event.what` values.
- **Determinism:** `setup_game()` and replay tests use fixed seeds and verify identical UUIDs / entity states.
- **Fixture IDs:** `alice_id` and `bob_id` in visibility tests are fixed UUIDs to make test expectations readable.

---

## Where the Code Lives

```
src/game/
├── __init__.py             Package init
├── components.py           6 game components (~100 lines)
├── actions.py              3 player actions (~180 lines)
├── systems.py              3 game systems (~130 lines)
├── archetypes.py           Entity factory functions (~80 lines)
├── setup.py                Map generation (~80 lines)
├── registry.py             Registry construction helpers (~50 lines)
└── summary.py              Per-player fog-of-war summary (~100 lines)

src/persistence/db.py       Added: events table, save_events(), load_events()
src/engine/turn.py          Modified: resolve_turn() calls save_events()
src/cli/main.py             Rewritten with game content (5 commands)
pyproject.toml              src/game added to wheel packages

tests/
├── conftest.py             StubPositionComponent, StubOwnerComponent
├── test_game_components.py 26 tests
├── test_game_archetypes.py 16 tests
├── test_game_systems.py    19 tests
├── test_game_actions.py    16 tests
├── test_game_setup.py       7 tests
├── test_game_integration.py 7 tests
└── test_visibility.py      11 tests
```

---

## Exit Criteria: Met ✓

Phase 4 exit criteria (per DEV_PHASES.md):
> A 2-player game starts, runs for 10 turns via TurnManager with no errors, and produces
> per-player turn summaries. Fog of war hides opponent entities outside observation range.

**Verification:**
- ✓ `test_ten_turn_game_resolves` — 10 turns resolve with no exceptions
- ✓ `test_ten_turn_game_produces_events` — systems emit events each turn
- ✓ `test_production_grows_resources` — owned planets grow after 3 turns
- ✓ `test_move_fleet_and_arrive` — MoveFleetAction + MovementSystem moves fleet to target
- ✓ `test_colonize_planet` — fleet arrives, ColonizePlanetAction adds Owner to unowned planet
- ✓ `test_production_skips_unowned_planets` — neutral planets' resources unchanged after 3 turns
- ✓ `test_replay_from_snapshot` — identical entity state when replaying turn from snapshot
- ✓ `test_hides_other_player_entities` / `test_visible_entities_section` — fog of war enforced in summary
- ✓ All 247 Phase 1–3 tests still passing (351 total)

---

## What's Next: Phase 5

Phase 5 (Extensibility & Polish) will demonstrate that the engine can be extended without modifying core code:

**Will build on Phase 4:**
- New component and system types added to `src/game/` with no engine changes
- Migration round-trip for a renamed component field
- Turn summary extended with new event types

**Envisioned additions:**
- Combat system (fleet vs. fleet encounters, using conflict resolution RNG)
- Technology/research component (passive unlocks per turn)
- Diplomacy events (alliance, war declaration)
- CLI `history` command (replay event log across multiple turns)
- Hypothesis property-based tests proving full-game determinism
