---
title: "Phase 1 Documentation: ECS Core Engine"
status: "Complete"
date: 2026-03-30
---

# Phase 1 Documentation: ECS Core Engine

## Overview

Phase 1 implements the **ECS (Entity-Component-System) core engine** for OneMoreTurn—a pure Python,
zero-dependency foundation for a PBEM 4X strategy game. This is the hardest phase to get right and
the most important: everything else in Phases 2–5 depends on it.

**Status:** Complete. All 124 tests passing. Exit criteria met.

---

## What Was Built

### Core Architecture: 5 Engine Modules

#### 1. [src/engine/events.py](src/engine/events.py) — Event System

**What it does:**
- Immutable record of state changes during turn resolution
- Pub/sub event bus with type-based routing and wildcards
- Complete audit trail for replay and debugging

**Key Classes:**

```python
@dataclass(frozen=True)
class Event:
    who: str | UUID           # entity or system that caused it
    what: str                 # event type (e.g., "ComponentAdded")
    when: int                 # turn number
    why: str                  # order ID or reason
    effects: dict[str, Any]   # serializable change data
    visibility_scope: list[UUID] | None  # for fog of war (Phase 4)
    timestamp: float          # wall-clock for within-turn ordering

class EventBus:
    subscribe(event_type: str, handler)  # type-specific subscription
    subscribe_all(handler)                # wildcard subscription
    publish(event)                        # dispatch to all handlers
    emitted: list[Event]                  # complete history
    clear()                               # reset history
```

**Why this design:**
- **Frozen Event:** Immutable after creation; no silent mutations in replay
- **Complete context:** who/what/when/why/effects encode full change semantics
- **visibility_scope:** Field exists (None for now) for Phase 4's fog of war system
- **Ordered history:** `emitted` list enables deterministic replay and testing assertions
- **Type-based routing:** Subscribers filter by event type; wildcard subscribers catch all

**Where it's used:**
- `World` publishes events for all mutations (EntityCreated, ComponentAdded, etc.)
- `SystemExecutor` publishes SystemStarted/SystemCompleted for profiling
- Tests assert on event sequences to validate observable behavior
- Phase 2: serialized to database per turn
- Phase 4: filtered by visibility_scope to generate per-player turn reports

---

#### 2. [src/engine/rng.py](src/engine/rng.py) — Deterministic RNG

**What it does:**
- Provides seeded, deterministic randomness per system per turn
- Ensures identical game states when replayed with same inputs
- Critical for PBEM: turns must be reproducible for disputed outcomes

**Key Class:**

```python
class SystemRNG:
    def __init__(self, game_id: UUID, turn_number: int, system_name: str):
        # Seed = SHA-256(f"{game_id}:{turn_number}:{system_name}")
        # Instance-based random.Random (not module-level globals)

    random() -> float         # [0.0, 1.0)
    randint(a, b) -> int      # [a, b]
    choice(seq) -> T          # random element
    shuffle(seq) -> None      # in-place shuffle
    seed: int                 # computed seed (for logging)
```

**Why this design:**
- **Per-system RNG:** Each system gets its own seeded instance. Adding/removing systems
  doesn't change other systems' random sequences → safe extensibility
- **Deterministic seed:** Hash of (game_id, turn_number, system_name) ensures reproducibility
- **Instance-based:** Wraps `random.Random(seed)`, not module-level `random` functions
  (which share global state and are non-deterministic across runs)

**Where it's used:**
- `SystemExecutor` creates one per system during `execute_all()`
- Passed to `System.update(world, rng)` for all random decisions
- Tests verify identical seeds produce identical sequences (12 tests)
- Phase 3: conflict resolution uses RNG to break ties (seeded with game_id + turn + conflict_id)

---

#### 3. [src/engine/components.py](src/engine/components.py) — Component Schema System

**What it does:**
- Defines the component schema protocol: every component declares what it needs, what it contains,
  and how it behaves
- Base class for all game attributes (Position, Owner, Resources, etc.)
- Validation hooks enable extensibility: `ContainerComponent` and `ChildComponent` enforce
  cross-entity constraints without World knowing about them

**Key Classes:**

```python
class Component(ABC):
    @classmethod
    @abstractmethod
    def component_name(cls) -> str:        # unique identifier

    @classmethod
    @abstractmethod
    def version(cls) -> str:               # semver (for migrations)

    @classmethod
    def dependencies(cls) -> list[type]:   # components that must coexist

    @classmethod
    def properties_schema(cls) -> dict:    # field → type mapping

    @classmethod
    def constraints(cls) -> dict:          # validation rules (min, max, etc.)

    def validate(self) -> list[str]:       # check constraints on instance

    # Validation hooks for cross-entity constraints:
    @classmethod
    def on_add_validation(cls, world, entity_id, component) -> list[str]:
        """Called before adding; return error messages."""

    @classmethod
    def on_remove_validation(cls, world, entity_id) -> list[str]:
        """Called before removing; check dependents."""

    @classmethod
    def on_added(cls, world, entity_id, component) -> None:
        """Called after successful add; update bookkeeping."""

    @classmethod
    def on_removed(cls, world, entity_id, component) -> None:
        """Called after successful remove; cleanup."""


@dataclass
class ContainerComponent(Component):
    """Allows entity to hold children."""
    allowed_child_types: list[type] = []  # permitted child component types
    max_capacity: int | None = None       # None = unlimited
    children: list[UUID] = []             # child entity IDs


@dataclass
class ChildComponent(Component):
    """Marks entity as contained by parent."""
    parent_id: UUID = None                # reference to parent entity
    # on_add_validation: verify parent exists, has ContainerComponent,
    #   allowed types match, capacity not exceeded
    # on_added: append self.entity_id to parent.children
    # on_removed: remove from parent.children
```

**Why this design:**
- **Mandatory schemas:** No implicit relationships. Every component declares what it needs and what
  it provides. Catches bugs at creation time
- **Validation hooks:** Instead of hardcoding container logic in World, validation is delegated to
  the component itself. This keeps World generic and enables new component types without
  modifying engine code (extensibility goal per DESIGN.md)
- **Constraints as data:** Min/max/custom rules are declarative, validated generically by World
- **properties_schema introspection:** Automatically extract field types from dataclass fields
- **Versioning:** Component version field (not used in Phase 1) prepares for Phase 2 migrations

**Where it's used:**
- World calls component hooks before/after all mutations
- Tests create 4 test components: HealthComponent, PoisonComponent, PositionComponent, OwnerComponent
- Phase 4: Position, Owner, Resources, FleetStats, PopulationStats, VisibilityComponent
- Phase 5: extensibility proof—new mechanics add new components without core engine changes

---

#### 4. [src/engine/ecs.py](src/engine/ecs.py) — Entity & World

**What it does:**
- **Entity:** UUID-keyed component container with lifecycle (alive flag)
- **World:** Central registry managing all entities, components, and queries with full validation

**Key Classes:**

```python
class Entity:
    id: UUID                           # globally unique identifier
    alive: bool                        # False after destroy()

    has(*component_types) -> bool      # check for components
    get(component_type) -> Component   # retrieve component (KeyError if missing)
    components() -> MappingProxyType   # read-only view of all components


class World:
    # Entity lifecycle
    create_entity(components=None, entity_id=None) -> Entity
        """Create with optional initial components.
        Validates dependencies & constraints before adding any."""

    destroy_entity(entity_id)
        """Mark dead, remove from indices, emit event."""

    get_entity(entity_id) -> Entity
        """Lookup by ID (KeyError if missing or destroyed)."""

    # Component mutations
    add_component(entity_id, component)
        """Add with validation: check deps, constraints, hooks."""

    remove_component(entity_id, component_type)
        """Remove with validation: check dependents."""

    # Queries
    query(*component_types) -> list[tuple[Entity, *Components]]
        """Return entities with ALL specified types.
        Returns (entity, comp1, comp2, ...) tuples for ergonomic unpacking."""

    entities() -> list[Entity]
        """All living entities (excludes destroyed)."""

    # State
    event_bus: EventBus
    current_turn: int


class SchemaError(Exception):
    """Raised when component schema constraint violated."""
```

**Why this design:**
- **All mutations through World:** Single point of truth per DESIGN.md. No side effects hidden in
  Entity or System methods
- **Query returns tuples:** `for entity, pos, owner in world.query(Position, Owner)` is ergonomic
  and avoids repeated `entity.get(Type)` calls in system code
- **Component index:** `dict[type, set[UUID]]` for O(min set) intersection queries
- **Validation before mutation:** Dependencies checked across full initial component set; constraints
  validated on instances; hooks allow cross-entity validation (containment)
- **Dead entities removed from indices:** `query()` never returns destroyed entities
- **current_turn:** Set by SystemExecutor; included in all emitted events

**Where it's used:**
- Center of all gameplay logic (systems query and mutate via World methods)
- Tests validate schema enforcement (33 tests on World)
- Phase 2: World state serialized to SQLite per turn
- Phase 3: Turn loop receives orders, validates via actions, executes them through World

---

#### 5. [src/engine/systems.py](src/engine/systems.py) — System Execution

**What it does:**
- Defines how game mechanics (production, movement, combat) are organized and executed
- Declarative dependencies: systems declare what they need; engine builds execution order
- Topological sort detects cycles and ensures deterministic ordering
- Executor manages per-turn system lifecycle

**Key Classes & Functions:**

```python
class System(ABC):
    @classmethod
    @abstractmethod
    def system_name(cls) -> str:
        """Unique identifier (e.g., "Production")."""

    @classmethod
    def phase(cls) -> str:
        """Execution phase: "PRE_TURN", "MAIN", "POST_TURN", "CLEANUP".
        Default: "MAIN"."""

    @classmethod
    def required_components(cls) -> list[type[Component]]:
        """Component types this system operates on. Default: []."""

    @classmethod
    def required_prior_systems(cls) -> list[type[System]]:
        """Systems that must run before this one. Default: []."""

    @classmethod
    def skip_if_missing(cls) -> bool:
        """If True, silently skip when no matching entities exist.
        If False, raise MissingEntitiesError. Default: True."""

    @abstractmethod
    def update(self, world: World, rng: SystemRNG) -> None:
        """Execute this system's logic for current turn."""


def topological_sort(systems: list[type[System]]) -> list[type[System]]:
    """Sort by phase, then dependency order within phase.
    Uses Kahn's algorithm with alphabetical tiebreaker for determinism.
    Raises CycleDetectedError if circular dependencies exist."""


class SystemExecutor:
    """Manages system registration, sorting, and execution."""

    def __init__(self, world: World, game_id: UUID, turn_number: int = 0):
        pass

    def register(self, system: System) -> None:
        """Register a system instance."""

    def execute_all(self) -> None:
        """Sort systems, then run each in order:
        - Check component requirements (skip or error per skip_if_missing)
        - Create per-system RNG
        - Emit SystemStarted/SystemCompleted events
        - Call system.update(world, rng)"""

    @property
    def execution_order(self) -> list[type[System]]:
        """Resolved execution order (cached, re-sorted if new systems added)."""


class CycleDetectedError(Exception):
    """Raised when system dependencies form a cycle."""
```

**Why this design:**
- **Declarative over imperative:** Systems declare what they need; engine handles ordering.
  Adding a new system doesn't require rewriting the turn loop
- **Phase grouping:** PRE_TURN, MAIN, POST_TURN, CLEANUP ensure natural game flow
- **Topological sort (Kahn's algorithm):** Naturally detects cycles. Alphabetical tiebreaker
  (for systems with no dependency relationship) ensures deterministic, reproducible ordering
- **Per-system RNG:** Executor creates `SystemRNG(game_id, turn, system_name)` so each system
  gets deterministic seeded randomness independent of others
- **SystemStarted/Completed events:** Enable profiling, logging, and debugging
- **skip_if_missing flag:** Most systems gracefully skip when no matching entities exist;
  some (strict requirements) raise errors for validation

**Where it's used:**
- Phase 1: Integration tests prove 2 systems sort and execute correctly
- Phase 3: Full turn loop receives orders, ActionSystem runs first, then production/movement/etc.
- Phase 4: Real game systems (ProductionSystem, MovementSystem, VisibilitySystem)
- Phase 5: extensibility proof—add new system type without touching engine

---

### Test Coverage: 8 Test Files, 124 Tests

| File | Tests | Coverage |
|------|-------|----------|
| test_events.py | 14 | Event immutability, EventBus pub/sub, ordering |
| test_rng.py | 12 | Determinism, seed derivation, independence |
| test_components.py | 16 | Schema protocol, validation, constraints, hooks |
| test_entity.py | 12 | UUID, lifecycle, component bag, read-only view |
| test_world.py | 33 | Create/destroy, add/remove, queries, validation, events |
| test_systems.py | 19 | ABC, topological sort, cycle detection, executor |
| test_containment.py | 14 | Container/child relationships, capacity, types, nesting |
| test_integration.py | 4 | Exit criteria (3 entities, 2 components, 2 systems) + determinism |

**Test Philosophy (per DESIGN.md):**
- **Isolated:** Each test creates fresh World and entities; no shared state
- **Order-independent:** Tests pass in any order; no side effects between tests
- **Event-driven assertions:** Validate via event sequences, not just state inspection
- **Determinism:** Property-based tests (hypothesis) prove identical seeds → identical results
- **Factories:** ComponentBuilder, WorldBuilder in conftest for ergonomic test setup

---

## Why This Design

### Principle 1: Extensibility Through Schema & Hooks

The engine does not hardcode knowledge of game-specific components. Instead:
- Components declare schemas (dependencies, constraints)
- Components provide validation hooks (on_add_validation, on_remove_validation, etc.)
- World calls these hooks generically; new components work without core changes

**Example:** ContainerComponent and ChildComponent enforce parent-child constraints via hooks.
When Phase 4 adds VisibilityComponent, no World code changes.

### Principle 2: All Mutations Through World

No side effects hidden in Entity or System methods. World is the single point of truth:
- Validates against component schemas
- Updates indices for efficient queries
- Emits events for every change
- Transactional: validation must pass completely before any mutation

### Principle 3: Determinism for PBEM

Turn resolution must be reproducible:
- Seeded RNG per system per turn
- Events ordered by timestamp
- Topological sort is deterministic (alphabetical tiebreaker)
- Same input → same output (proven by hypothesis tests)

Critical for PBEM: disputed turns can be replayed and verified.

### Principle 4: Events as First-Class Citizens

Every state change is an event:
- Complete audit trail (who, what, when, why, effects)
- Enables debugging ("what happened to ship X")
- Enables player reports (filter events by visibility)
- Enables replay (serialize events per turn, replay to reconstruct state)

### Principle 5: Declarative Execution Order

Systems declare dependencies; engine builds the graph. Benefits:
- Self-documenting execution order
- New systems integrate without rewriting turn loop
- Cycle detection catches configuration errors
- Deterministic ordering for reproducibility

---

## Where The Code Lives

```
src/engine/
├── __init__.py             Public API re-exports
├── events.py               Event + EventBus (~60 lines)
├── rng.py                  SystemRNG (~50 lines)
├── components.py           Component ABC + Container/Child (~170 lines)
├── ecs.py                  Entity + World (~270 lines)
└── systems.py              System ABC + topological sort + executor (~180 lines)

tests/
├── conftest.py             Test components + factories (~80 lines)
├── test_events.py          EventBus tests (14 tests)
├── test_rng.py             RNG determinism (12 tests)
├── test_components.py      Schema protocol (16 tests)
├── test_entity.py          Entity lifecycle (12 tests)
├── test_world.py           World queries & mutations (33 tests)
├── test_systems.py         System execution & sorting (19 tests)
├── test_containment.py     Container/child constraints (14 tests)
└── test_integration.py     Exit criteria (4 tests)

Configuration:
├── pyproject.toml          Build config, pytest settings
├── .gitignore              Standard Python ignores
└── src/engine/__init__.py  Public API exports
```

---

## Exit Criteria: Met ✓

Phase 1 exit criteria (per DEV_PHASES.md):
> All tests pass. A `World` with 3 entities, 2 component types, and 2 systems
> resolves in declared order and emits events.

**Verification:**
- ✓ All 124 tests pass
- ✓ `test_integration.py::TestExitCriteria::test_three_entities_two_components_two_systems`
  creates 3 entities with 2 component types (Counter, Tag)
- ✓ Registers 2 systems (IncrementSystem in MAIN, LabelSystem in POST_TURN)
- ✓ Systems execute in declared order (MAIN before POST_TURN)
- ✓ Systems process correct entities (IncrementSystem runs on entities with Counter)
- ✓ Events emitted for all operations (SystemStarted/SystemCompleted per system)
- ✓ Determinism proven: identical inputs → identical outputs (test_identical_inputs_identical_outputs)

---

## What's Next: Phase 2

Phase 2 (Persistence Layer) builds on this solid foundation:

**Will depend on Phase 1:**
- World queries and component validation
- Event bus for turn snapshot audit trail
- Deterministic RNG (already handles seed derivation)

**Will add:**
- SQLite integration with tall table schema
- World → DB serialization (dump all entities + components)
- DB → World deserialization (reconstruct from snapshots)
- Migration registry for schema evolution (component version field used here)
- Turn snapshot storage with format versioning

**No changes to Phase 1:** The ECS engine is stable. Phase 2 doesn't modify any
core classes—it only extends them (e.g., adding `Saveable` mixin or serialization methods).

---

## Deferred Decisions

These are explicitly deferred per DEV_PHASES.md and addressed in later phases:

| Decision | Phase | Notes |
|----------|-------|-------|
| Movement model (travel time formula) | Phase 4 | Turn-based discrete movement; design needed |
| Conflict resolution formula | Phase 4 | Unit modifiers (speed, type); RNG seeding ready |
| Multi-turn actions (queued construction) | Phase 4 | Represented as component state + ActionSystem |
| Combat mechanics | Phase 5 | Extensibility test; may add CombatSystem |
| Diplomacy / faction relations | Phase 5 | New components + systems |
| Victory conditions | Phase 4+ | Game balance, tuning |

---

## Testing Strategy Rationale

**Function-scoped fixtures:** Every test gets a fresh World and EventBus. No shared mutable state.
Ensures tests pass in any order.

**Event assertions:** Tests assert on `world.event_bus.emitted` sequences, not just component state.
This validates the observable behavior contract and catches silent state corruption.

**Hypothesis property tests:** For ECS invariants (query correctness, determinism), property-based
tests with `hypothesis` library prove the property across hundreds of random inputs.

**Layered factories:** ComponentBuilder (single component), WorldBuilder (minimal world for a test)
keep test setup minimal and focused. Prevents tight coupling to game structure.

**Determinism tests:** Run identical scenarios twice; assert identical event sequences and final state.
This is critical for PBEM: replayed turns must produce identical outcomes.

---

## Lessons & Architecture Notes

**Why Kahn's algorithm for topological sort?**
- Naturally detects cycles (remaining nodes after BFS = cycle)
- Supports deterministic ordering via sorted queue
- More efficient than DFS-based toposort for large graphs
- Well-understood, straightforward to implement correctly

**Why component validation hooks instead of hardcoded logic?**
- Keeps World generic; doesn't need to know about specific component types
- Enables new components to declare their own validation rules
- Supports arbitrary nesting depth (containers can contain containers)
- Aligns with ECS philosophy: data + behavior colocated in components

**Why immutable Event dataclass?**
- Prevents accidental mutation during replay/debugging
- Frozen dataclass is hashable (can be stored in sets, dicts if needed)
- Cheap copy-on-write semantics via frozen=True

**Why per-system RNG instead of global?**
- Adding/removing systems doesn't change others' random sequences
- Each system is independently reproducible
- Extensibility goal: new systems don't cause non-determinism side effects

---

## Summary

Phase 1 is a **solid, well-tested, extensible ECS engine** that meets all requirements:

1. ✓ Zero external dependencies; pure Python 3.11+
2. ✓ Full test coverage; 124 tests; all passing
3. ✓ Deterministic turn resolution (seeded RNG, topological sort)
4. ✓ Complete event audit trail (who/what/when/why/effects)
5. ✓ Extensible architecture (validation hooks, schema protocols)
6. ✓ PBEM-ready (reproducible, order-independent, deterministic)

Phases 2–5 build on this foundation without modifying core engine code.

---

*End of Phase 1 documentation.*
