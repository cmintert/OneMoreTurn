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

## Phase 6+ — TBD

Determined by Phase 5 assessment. Likely candidates:

- FastAPI backend (turn submission over HTTP, player auth, game hosting).
- Web frontend (vanilla HTML/CSS/JS, calls FastAPI, visualizes state).
- Additional game mechanics (based on playtesting feedback).
- Postgres migration (when SQLite per-game-file becomes a limitation).
- Multiplayer infrastructure (notification emails, PBEM file exchange).

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

*End of development phases.*
