
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

### 7. Putting It Together: The Turn Loop

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

### 8. Design Constraints & Decisions

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

### 9. Extensibility Examples

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

### 10. This Layer in the Development Plan

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

- **Decision:** Declarative dependencies with topological sorting
  (see ARCHITECTURE section below for details).
- **Rationale:** Self-documenting execution order; new systems integrate without core changes.
        Systems declare dependencies; engine builds and executes the graph automatically.

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
