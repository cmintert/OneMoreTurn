
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

## ARCHITECTURE — Extensibility & Abstraction Layer

The core engine must support adding new mechanics—units, spells, factions, resources—without
modifying existing systems. This requires three foundational abstractions:

1. **Component Metadata:** Components know what they need and what they do.
2. **System Dependencies:** Systems declare what they need to run; execution order emerges
   automatically.
3. **Action Protocol:** All player actions follow a single interface; new action types require
   no core changes.

### 1. Component Metadata & Validation

Each component class carries metadata describing:

- **What it is:** Name, human-readable description.
- **What it needs:** Which other components must exist on the same entity.
- **What it contains:** Type definitions for all properties (not instances).
- **How it behaves:** Whether changes trigger events, validation rules, constraints.

Examples:

- A `Health` component requires an `Owner` component (health only makes sense on owned entities).
- A `Poison` component can only exist on entities with `Health`; if `Health` is removed, `Poison`
  is invalid.
- A `Mana` component has a capacity constraint (`max_mana ≥ current_mana` always).

**Benefits:**

- **Validation at creation:** "Create ship" fails early if the archetype is missing a required
  component.
- **Smart querying:** "Give me all entities with [Health AND Owner]" becomes a schema query,
  not manual iteration.
- **Safe removal:** Before removing a component, check what depends on it.
- **Extensibility:** New component? New schema. Nothing breaks.
- **Version safety:** Schemas can define migrations ("if Health v1 exists but not Health v2,
  transform it").

**Implementation:** Each component declares a schema—a structured description of its
dependencies, properties, and constraints. The system validates entities against their component
set before turn resolution.

### 2. System Dependencies & Execution Order

Each system declares:

- **What it does:** Descriptive name.
- **When it runs:** Execution phase (PRE_TURN, MAIN, POST_TURN, CLEANUP).
- **What it needs:** Which systems must run before it, which components it requires.
- **Whether it can skip:** If required components are missing, can it safely skip?

Examples:

- A `MovementSystem` says: "I run in the MAIN phase, after `ActionSystem` (actions might spawn
  movement), and I need `Position` and `Owner` components."
- A `PoisonDamageSystem` says: "I run in POST_TURN, after all combat, and I need `Health` and
  `Poison` components. If an entity has `Poison` but no `Health`, I skip it."
- A `SpellCastingSystem` says: "I run in MAIN, after `ActionSystem`, before `MovementSystem`,
  and I need `Mana` and `Owner`."

**Benefits:**

- **Automatic ordering:** The engine builds a dependency graph and executes in correct order.
- **No surprises:** If a system can't run (missing required components), it says so and skips
  gracefully.
- **Easy extension:** Adding a new system is declaring its dependencies, not rewriting the
  execution loop.
- **Debuggability:** Logs show the exact order systems ran, why some skipped, and where time
  was spent.

**Implementation:** Systems are registered with metadata about their phase and dependencies.
Before turn resolution, the engine topologically sorts systems and executes them in order. If a
system's requirements aren't met, it's logged and skipped.

### 3. Action Protocol & Universal Processing

All player actions—Move, Build, CastSpell, TradeWith, SetTax—implement a single contract:

- **Validation:** "Can this action run right now?"
  (Check orders, resources, prerequisites, target validity.)
- **Execution:** "Run the action and emit events describing what happened."

The core engine has a single `ActionSystem` that:

- Receives all actions from all players.
- Validates each one.
- Executes valid ones in a deterministic order.
- Emits events for every outcome.

Examples:

- A `MoveAction` validates: "Does the entity exist? Is it owned by the player? Can it move
  (movement_points > 0)?" Then executes: move the entity, deduct movement points, emit a
  `UnitMoved` event.
- A `CastSpellAction` validates: "Does the caster have mana? Does the spell exist? Is the
  target valid for this spell?" Then executes: deduct mana, apply spell effects, emit spell
  events.
- A `BuildStructureAction` validates: "Does the player own the location? Do they have resources?
  Is the structure available?" Then executes: deduct resources, create the structure entity,
  emit building events.

**Benefits:**

- **New mechanics are new Action classes:** Adding a spell system means writing a `CastSpell`
  action. No changes to core.
- **Validation is consistent:** Every action validates itself; the engine doesn't need to know
  about specifics.
- **Deterministic:** Actions execute in order with seeded RNG; replays work.
- **Observable:** Every action emits events; logs and replays are straightforward.
- **Testable:** New action types are testable in isolation (given a world state, does this
  action validate/execute correctly?).

**Implementation:** Actions are objects with `validate()` and `execute()` methods. The
`ActionSystem` iterates over them, calls `validate()` on each, executes valid ones, and collects
events. Everything else subscribes to events.

### 4. Containment as a Pattern, Not Special Logic

Containment is expressed via components:

- **ContainerComponent:** "I can hold other entities." It declares capacity, what kinds of
  children are allowed, and how the relationship works. A star system has this; a fleet has
  this; an inventory has this.
- **ChildComponent:** "I am contained by a parent." It knows its parent ID and can navigate up.

Both are optional. An entity either can contain or cannot; that's explicit.

Examples:

- A star system contains planets (spatial containment).
- A fleet contains ships (command hierarchy).
- A caravan contains goods (inventory).
- A population has a workforce (composition).

**Benefits:**

- **Clear semantics:** You don't need to guess what `parent_id` means on a ship vs. a planet.
- **Constraints are data:** A fleet might hold up to 12 ships; that's declared in its
  `ContainerComponent`.
- **Querying is simple:** "Give me all ships in fleet X" is a query on
  `ChildComponent.parent_id == X`.
- **Hierarchy depth is arbitrary:** Fleets can contain fleets; no special logic needed.
- **Extensibility:** New container types just define a new `ContainerComponent` flavor; nothing
  breaks.

**Implementation:** `ContainerComponent` and `ChildComponent` are ordinary components with metadata.
Systems that care about containment (like logistics or movement) query these components. No special
spatial logic; it's all through the component system.

### 5. Events as First-Class Citizens

Events are the record of truth for what happened during a turn. Every state change is
described by an event.

Event properties:

- **Who:** Which entity or system caused it.
- **What:** What changed (Health decreased, Position changed, Resource produced).
- **When:** Turn number and timestamp.
- **Why:** Order ID or action that triggered it.
- **Effects:** Serializable data about the change.

Systems emit events when they do work. The `EventBus` collects them. Subscribers (logger, UI,
replay system) consume them.

**Benefits:**

- **Complete audit trail:** Every turn is a sequence of events; nothing is implicit.
- **Deterministic replay:** Replay turn by replaying events, not re-running systems.
- **Debugging:** Query "what happened to ship X" by filtering events.
- **Player reporting:** Turn summary is auto-generated from events.
- **Extensibility:** New event types are new event classes; observers subscribe to what they
  care about.

**Implementation:** All systems emit structured events (not log strings). Events have types
(UnitMoved, ResourceProduced, SpellCast). `EventBus` dispatches them to subscribers. Subscribers
(Logger, TurnSummary, Replay) consume the streams they care about.

### 6. World State as a Queryable Database

The `World` provides a simple, composable query interface:

- **Get all entities with these components:** Query by component types. The engine returns
  matching entities efficiently.
- **Get entity by ID:** Direct lookup.
- **Get entities where component property X = Y:** Filter by component data.
- **Add/remove component:** Safe mutation with validation against schemas.

All systems use the same interface. No hidden magic.

**Benefits:**

- **Consistency:** Everyone queries the same way.
- **Efficiency:** Query logic is optimized in one place.
- **Testability:** Easy to set up test worlds with specific configurations.
- **Extensibility:** New systems don't invent their own queries.

**Implementation:** `World` provides methods like `query(ComponentType1, ComponentType2)` returning
entities, `add_component()`, `remove_component()`. No magic; just declarative, composable queries.

### 7. Fog of War & Visibility

Visibility is a core mechanic in 4X games. The event and state system must
anticipate it from the start.

**Visibility Model:**

- Every entity has a visibility scope: which players can see it and what information
  they receive.
- Events are labeled with visibility metadata: `visibility_scope: [player_ids]`.
- When generating turn reports or state snapshots for a player, filter events and
  state to only what that player can observe.
- Entities outside a player's visibility are either hidden or shown with stale
  (last-seen) data.

**Implementation:**

- Add `VisibilityComponent` with fields: `visible_to: [player_ids]`, `revealed_to:
  [player_ids]` (for fog of war vs. fog of knowledge).
- Events carry `visibility_scope` field; subscribers filter before emitting to
  players.
- `World.query()` accepts a `visible_to_player` parameter; by default, returns all
  entities (unfiltered for admin/replay). Player-facing queries are filtered.
- Turn reports are generated per-player by filtering events through visibility.

**Benefits:**

- Visibility is explicit and queryable, not an afterthought.
- Events serve dual purpose: game log (admin/replay sees all) and player report
  (filtered to visibility).
- Enables fog of war mechanics without special casing.

### 8. Putting It Together: The Turn Loop

A turn resolves like this:

1. **Receive Orders:** All players submit actions.
2. **Validate Orders:** Each action validates itself against the world state. Invalid orders are
   rejected with clear feedback.
3. **Execute Actions:** `ActionSystem` runs all valid actions in order. Each action emits events
   describing its outcome.
4. **Run Systems:** Remaining systems (Production, Movement, Decay, etc.) execute in dependency
   order. Each system checks its requirements; if they're met, it processes entities and emits
   events. If not, it skips and logs why.
5. **Collect Events:** All events (from actions and systems) are accumulated.
6. **Log & Snapshot:** Events are written to the database. A full JSON snapshot of the world
   state is stored for replay/debugging.
7. **Emit to Subscribers:** Event subscribers (UI updates, player notifications, stats
   tracking) consume the event stream.

Key properties:

- **Deterministic:** Same input (seed, orders, world state) always produces the same output.
- **Observable:** Every change is an event; nothing is implicit.
- **Extensible:** New actions, systems, and components don't require core changes.
- **Testable:** Each component, action, and system can be tested in isolation.

### 9. Design Constraints & Decisions

#### Component Metadata Is Mandatory

Every component class must declare a schema. No implicit relationships. This costs a bit of
upfront definition but saves enormous debugging pain later.

#### Systems Are Explicit About Dependencies

No magic ordering. Systems declare what they need; the engine ensures they run when safe.

#### All Mutations Go Through World

No side effects hidden in systems. All state changes go through `World` methods, which validate
against component schemas.

#### Actions Are Synchronous

An action validates and executes atomically. Complex behaviors (multi-turn spells, queued
construction) are represented as state (a `Spell` component tracking remaining duration) plus
an action system that processes that state each turn.

#### Events Are Immutable & Detailed

Once emitted, an event cannot be changed. Events contain all context needed to understand what
happened without looking elsewhere.

### 10. Extensibility Examples

#### Adding a New Unit Type (e.g., Mage)

- Define new components: `Mana`, `SpellList`.
- Create `CastSpell` action class (if not already exists).
- Define spell templates (fire bolt, heal, etc.).
- Everything else works. The `ActionSystem` processes `CastSpell` like any other action.

No changes to core engine.

#### Adding a Faction System

- Define `Faction` and `FactionRelation` components.
- Create systems: `DiplomacySystem` (processes trade agreements), `ReputationSystem`
  (updates relations based on actions).
- Define new actions: `ProposeAlliance`, `DeclareTax`.
- Systems run in main loop; actions work like everything else.

No changes to core engine.

#### Adding a Tech Tree

- Define `ResearchQueue` and `TechnologyUnlocked` components.
- Create `ResearchSystem` that progresses research each turn.
- Create `UnlockTechnology` action.
- Integrate with validation: certain structures require certain techs (checked in action
  validate).

No changes to core engine.

### 11. This Layer in the Development Plan

#### Phase 1 Extensions

In Phase 1 (Foundation), build the core abstractions:

- Component schema system with validation.
- System dependency declaration and topological sorting.
- Action protocol and `ActionSystem`.
- `World` query interface.
- Event types and `EventBus`.

Implement one complete example cycle: a `Produce` action (validates resources, executes, emits
`ProductionEvent`) + a `ProductionSystem` (processes produce actions via events).

#### Phase 2 Integration

In Phase 2 (Turn Loop), use these abstractions to build the full loop. Everything snaps into
place cleanly.

#### Phase 3+ Extensibility Test

In Phase 3 (Assess), add a second mechanic (spell system, faction diplomacy, etc.) without
touching the core engine. If it works cleanly, the abstraction is sound.

## Summary of ARCHITECTURE Layer

The engine needs three core abstractions:

- **Components know what they need** (schemas, validation).
- **Systems know what they need** (dependencies, phases).
- **Actions are a protocol** (validate, execute, emit).

Combined with a queryable `World` and an event-driven architecture, these let you add new
mechanics indefinitely without refactoring the core. Everything is explicit, testable, and
observable.

This isn't overengineering for a 4X game. It's the minimum needed to avoid the "we have to
rewrite this" moment at scale.

---

### Player API Abstraction

- **UUIDs are internal only.** Players never see, reference, or type UUIDs.
- **Players work with names.** All player-facing API uses human-readable names for entities.
- **Name-to-UUID mapping is transparent.** The system translates player names to entity IDs
  internally; the translation is invisible to the player.

Example: A player submits an order like `"move fleet 'Alpha Squadron' to system 'Sirius'"`.
Internally, the system resolves `'Alpha Squadron'` to its UUID and `'Sirius'` to its UUID,
then executes the action. The player never types or sees a UUID.

**Benefits:**

- **Lower cognitive load:** Players focus on strategy, not administrative bookkeeping.
- **Better UX:** Names are memorable; UUIDs are not.
- **Flexibility:** Systems can be renamed without breaking player workflows.
- **Consistency:** All player actions use consistent naming conventions.

### Entity Model

- **Flat storage, hierarchical querying:** All entities are stored flat (no nested
  objects). Relationships are expressed via component references (`parent_id`).
- **Arbitrary nesting:** Entities reference their parent/container via `parent_id`
  (or multiple parents via `ChildComponent`). No depth limit.
- **Containment is explicit:** Only entities with `ContainerComponent` can contain
  children. Only entities with `ChildComponent` are contained.

Example: a ship has `parent_id = <fleet_id>` (not embedded in the fleet); a fleet
has `parent_id = <sector_id>` (not embedded in the sector).

Query pattern example:

```text
Give me all entities where parent_id == X AND ChildComponent exists
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

- **Decision:** Declarative dependencies with topological sorting
  (see ARCHITECTURE section below for details).
- **Rationale:** Self-documenting execution order; new systems integrate without core changes.
        Systems declare dependencies; engine builds and executes the graph automatically.

### Determinism & RNG

- **Decision:** Seeded RNG per system per turn. Seed = `(game_id, turn_number,
  system_name)`.
- **Rationale:** Reproducible turn resolution for PBEM. Each system gets its own RNG
  state so that execution order is part of the determinism contract. Adding new
  systems does not cause non-deterministic behavior due to RNG state consumption by
  earlier systems.
- **Important Note:** When multiple systems call RNG in the same turn, the order in
  which systems execute affects outcomes. This is intentional and documented as part
  of the determinism guarantee.

### Save Format Versioning & Migrations

- **Decision:** Every saved game state includes a `format_version` field (semantic
  versioning: "1.0.0"). Component schemas include their own version. Migrations are
  chainable functions stored in a registry.
- **Mechanism:**
  1. On save: include `format_version` in the root JSON snapshot and component
     schema versions in each component's metadata.
  2. On load: read `format_version`, look up migration chain from registry, apply
     migrations in order to transform the snapshot to current format.
  3. Migrations are idempotent: applying the same migration twice produces the same
     result.
  4. Migration registry: `migrations = {("1.0.0" -> "1.1.0"): migration_fn, ...}`.
     Engine applies them in dependency order.
- **Rationale:** Supports iterative schema evolution without breaking old saves.
  Backward compatibility guaranteed; forward compatibility rejected (can't load from
  future versions). Clear audit trail of what changed and why.

**Example:**

```text
v1.0.0: ResourceComponent has {amount, capacity}
v1.1.0: Split capacity -> max_storage (for inventory), max_energy (for power)
Migration: if ResourceComponent exists, create separate components or split fields
v1.2.0: Rename Component.owner_id -> Component.controller_id
Migration: ResourceComponent.owner_id -> ResourceComponent.controller_id
```

On load, engine checks version, applies migrations in order, validates result
against current schemas.

### Conflict Resolution & Order Precedence

- **Decision:** When multiple orders conflict (e.g., two players building on the same location),
  resolution uses seeded RNG with unit modifiers.
- **Mechanism:** Identify conflict, seed RNG with `(game_id, turn_number, system_name, conflict_id)`,
  select winner based on unit modifiers (e.g., speed, type). One order succeeds; the other fails
  with clear feedback to the player.
- **Rationale:** Fair resolution independent of submission order. Unit composition becomes strategically
  relevant (investing in fast units provides advantage in contention scenarios).
- **Deferred:** Exact modifier formula (speed, type, combination). Determined in Phase 2 based on
  playtesting and game balance goals.

### Turn Submission & Validation

- **Decision:** Per-order validation; invalid orders are rejected individually with
  clear feedback. Valid orders proceed; invalid ones are reported to the player but
  do not block the submission.
- **Rationale:** Better UX — one typo doesn't cost a player the entire turn.
  Validation happens at submission time and again at turn resolution (redundant
  validation is safe).

### Order Submission Window

- **Decision:** Orders can be submitted and updated until the turn is evaluated
  (resolved).
- **Rationale:** Allows players to revise orders before the turn lock without
  explicit amendment logic. On evaluation, only the current state of each order is
  processed.

### Spatial Hierarchy & Containment

- **Decision:** Arbitrary nesting via `ContainerComponent` and `ChildComponent`.
  No depth limit. All spatial relationships expressed as parent-child references.
- **Rationale:** Supports 4X domain naturally (galaxy > system > planet > surface slot;
  fleet > subfleet > ship). Containment constraints are declared per component, not
  hardcoded. Queries remain simple: "get all entities where parent_id == X".

### Testing Strategy

- **Decision:** Isolated, order-independent tests using function-scoped fixtures, layered
  factories, and event-based assertions.

#### Core Principles

- **Isolation:** Every test creates its own `World` instance. No shared mutable state between
  tests. A test that passes in isolation must pass in any order.
- **No filesystem:** Use in-memory SQLite (`:memory:`) per test. No test touches the real DB
  or leaves files behind.
- **Function-scoped fixtures only:** `pytest` fixtures default to function scope. Never use
  module- or session-scoped fixtures for mutable state (game world, DB, event bus).
- **Fixed seeds:** All RNG-dependent tests pin seed inputs explicitly. Tests are deterministic
  by construction.

#### Assert on Events, Not Just State

The event bus is the record of truth. Prefer asserting on emitted events over inspecting
component state directly. This validates the observable behavior contract and catches silent
state corruption.

```python
events = world.event_bus.emitted
assert any(e.type == "UnitMoved" and e.entity_id == ship_id for e in events)
```

State assertions are still valid for verifying the final world, but events should be the
primary signal for what *happened*.

#### Layered Test Factories

Tests need different levels of setup depending on what they are testing:

- **`ComponentBuilder`** — construct a single component with specific field values; for
  testing validation rules and schema constraints in isolation.
- **`EntityBuilder`** — create an entity with an explicit set of components; for testing
  actions and systems against minimal world state.
- **`WorldBuilder`** — compose a `World` with only the entities and components a given system
  or action needs; avoids coupling tests to full game setup.
- **`ScenarioBuilder`** — full seeded game state (players, map, orders) for integration tests
  and replay validation.

```python
# Unit: test a single action against minimal state
world = WorldBuilder().with_entity(ship_id, [PositionComponent(...), OwnerComponent(...)]).build()

# Integration: full seeded scenario
scenario = ScenarioBuilder.create_game_with_players(2, seed=42)
```

#### Test Layers

Each layer tests a distinct scope and should not reach into lower layers unnecessarily:

| Layer | Scope | Tools |
| --- | --- | --- |
| **Component** | Validation rules, schema constraints, migrations | `ComponentBuilder` |
| **Action** | `validate()` and `execute()` given a world state | `EntityBuilder` |
| **System** | Entities with required components → events + state | `WorldBuilder` |
| **Turn loop** | Full resolution: orders in → events + snapshot out | `ScenarioBuilder` |

#### Determinism Tests

The determinism contract is itself a testable property. Maintain a dedicated suite that:

1. Resolves a seeded turn once and captures the output snapshot.
2. Resolves the same turn again (same seed, same orders, same state).
3. Asserts the two outputs are byte-for-byte identical.

This guards against accidental RNG state leakage, non-deterministic iteration order (dict
ordering, set ordering), and system execution order regressions.

#### Invariant / Property-Based Tests

Use `hypothesis` to verify ECS invariants that must hold across arbitrary world states:

- An entity with `Poison` always has `Health`.
- `ContainerComponent` capacity is never exceeded.
- Removing a required component from an entity raises a validation error.
- Every event has `who`, `what`, `turn_number`, and `why` fields populated.

These tests complement example-based tests by exploring edge cases automatically.

#### What Not to Test

- Internal ECS bookkeeping (entity UUID generation, index structures) — test the interface,
  not the implementation.
- Log formatting — logs are for humans; assert on structured event data instead.
- Migration correctness by re-running production migrations — use dedicated migration unit
  tests with synthetic old-format fixtures.

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
