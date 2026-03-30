---
title: "Phase 2 Documentation: Persistence Layer"
status: "Complete"
date: 2026-03-30
---

# Phase 2 Documentation: Persistence Layer

## Overview

Phase 2 implements the **persistence layer** for OneMoreTurn—SQLite-backed serialization of the ECS
World, deterministic snapshots per turn, and a migration framework for schema evolution. This
phase is the foundation for PBEM: without reliable save/load, turns cannot be replayed,
disputed outcomes cannot be verified, and old games cannot be loaded after code changes.

**Status:** Complete. All 55 new tests passing. Both exit criteria met. All 124 Phase 1 tests still passing (179 total).

---

## What Was Built

### Persistence Architecture: 3 Core Modules + Registry

#### 1. [src/persistence/serialization.py](src/persistence/serialization.py) — Component & World Serialization

**What it does:**
- Converts Component instances to/from JSON-compatible dicts
- Serializes entire World to snapshot dicts (full entity+component state)
- Deserializes snapshots back to World with full validation
- Handles UUID fields and lists of UUIDs transparently
- Orders entities during deserialization (parents before children) to avoid broken references

**Key Classes & Functions:**

```python
class ComponentRegistry:
    """Maps component_name() strings to component classes."""
    register(*component_classes) -> None
        """Register one or more component classes for deserialization."""
    get(name: str) -> type[Component]
        """Look up class by component_name(). Raises KeyError if not registered."""
    all() -> dict[str, type[Component]]
        """Return copy of full registry."""


def serialize_component(component: Component) -> dict:
    """component → {"component_type": ..., "component_version": ..., "data": {...}}
    All UUID fields in data are converted to strings.
    Lists of UUIDs (e.g. ContainerComponent.children) → lists of strings."""


def deserialize_component(record: dict, registry: ComponentRegistry) -> Component:
    """Inverse of serialize_component. Strings for UUID fields → UUID objects.
    Looks up class via registry.get(record["component_type"]).
    Reconstructs via class(**data_dict)."""


def serialize_world(world: World, game_id: str, format_version: str = "1.0.0") -> dict:
    """World → full snapshot dict. Iterates world.entities() in stable order."""


def deserialize_world(snapshot: dict, registry: ComponentRegistry) -> World:
    """Snapshot dict → World. Creates entities with parents first, children second
    to avoid broken parent_id references during validation."""
```

**Snapshot JSON Format:**

```json
{
  "format_version": "1.0.0",
  "game_id": "uuid-string",
  "turn_number": 3,
  "current_turn": 3,
  "entities": [
    {
      "entity_id": "uuid-string",
      "alive": true,
      "components": [
        {
          "component_type": "Health",
          "component_version": "1.0.0",
          "data": { "current": 100, "maximum": 100 }
        }
      ]
    }
  ]
}
```

**Why this design:**
- **ComponentRegistry:** Explicit, testable registration (no auto-discovery magic). Caller controls what
  components are available for deserialization
- **Separate serialize/deserialize functions:** Symmetric, testable separately. Pure functions with no
  side effects
- **UUID handling:** UUIDs serialize to strings (JSON-compatible), deserialize back to UUID objects.
  Handles `parent_id`, `owner_id`, `children` lists transparently
- **Parent-before-child ordering:** During deserialization, entities without ChildComponent are created
  first. Ensures parent exists before child's `on_add_validation` hook runs. Avoids broken
  `parent_id` references
- **Deterministic serialization:** Stable entity ordering + sorted JSON keys = byte-identical snapshots
  for identical worlds

**Where it's used:**
- Phase 2: Core of save/load workflow
- `GameDatabase.save_snapshot()` calls `serialize_world()` to generate JSON
- `GameDatabase.load_snapshot()` calls `deserialize_world()` after loading from DB
- Tests verify 10-entity round-trips with zero data loss (exit criterion 1)
- Phase 3: Turn snapshots enable replay for debugging

---

#### 2. [src/persistence/migrations.py](src/persistence/migrations.py) — Migration Registry

**What it does:**
- Manages chainable snapshot format migrations for schema evolution
- Applies migration chain from any old version to current CURRENT_FORMAT_VERSION
- Detects unsupported versions and cycles in migration chains
- Enforces idempotency: same migration applied twice = same result

**Key Classes & Constants:**

```python
CURRENT_FORMAT_VERSION = "1.0.0"


class MigrationError(Exception):
    """Raised when snapshot cannot be migrated to current format."""


class MigrationRegistry:
    """Registry of snapshot migration functions."""

    def register(self, from_version: str, to_version: str,
                 fn: Callable[[dict], dict]) -> None:
        """Register a migration function from one version to another.
        Migration function is pure: receives snapshot dict, returns transformed copy."""

    def apply(self, snapshot: dict) -> dict:
        """Apply all needed migrations to bring snapshot to CURRENT_FORMAT_VERSION.
        Walks the registered chain from snapshot["format_version"] to current,
        applying each function in order."""
```

**Migration Function Signature:**

```python
def migration_v10_to_v11(snapshot: dict) -> dict:
    """Pure function: receives snapshot dict, returns transformed copy.
    Must set snapshot["format_version"] = "1.1.0" before returning.

    Example: rename a component field
    """
    snapshot = dict(snapshot)  # Copy top level (mutations are okay on copy)
    for entity in snapshot.get("entities", []):
        for comp in entity.get("components", []):
            if comp["component_type"] == "Health" and "hp" in comp.get("data", {}):
                comp["data"]["current"] = comp["data"].pop("hp")
    snapshot["format_version"] = "1.1.0"
    return snapshot
```

**Why this design:**
- **Chainable migrations:** v0.8.0 → v0.9.0 → v1.0.0 applied in order. Supports gradual schema
  evolution without giant jump from old to new
- **Idempotency:** Migrations are pure functions with no side effects. Applying same migration twice
  is safe (needed for re-running migrations if they fail halfway)
- **Cycle detection:** Detects if migration chain loops (would cause infinite loop)
- **Clear error messages:** If snapshot version has no migration path, error states exactly what
  version is unsupported
- **Format version enforcement:** Each migration must update `snapshot["format_version"]`. Catches
  bugs where migration forgets to set the version

**Where it's used:**
- `GameDatabase.load_snapshot()` optionally applies migrations before deserialization
- Tests verify single hop, chains, field renames, idempotency (exit criterion 2)
- Phase 3+: When component schema changes (e.g., split Resources into Inventory + Energy), migration
  transforms old snapshots automatically

---

#### 3. [src/persistence/db.py](src/persistence/db.py) — SQLite Database Integration

**What it does:**
- Opens SQLite connection (`:memory:` for tests, file path for production)
- Manages three tables: `entity_components`, `turns`, `event_log`
- Provides methods to save/load world snapshots atomically
- Provides methods to log and retrieve events per turn

**Database Schema:**

```sql
-- Tall component table (for diffing/debugging; not used for queries)
CREATE TABLE IF NOT EXISTS entity_components (
    entity_id       TEXT NOT NULL,
    component_type  TEXT NOT NULL,
    component_data  TEXT NOT NULL,   -- JSON
    PRIMARY KEY (entity_id, component_type)
);

-- Full JSON snapshot per turn (primary persistence unit)
CREATE TABLE IF NOT EXISTS turns (
    turn_id         TEXT PRIMARY KEY,   -- UUID
    game_id         TEXT NOT NULL,
    turn_number     INTEGER NOT NULL,
    state_snapshot  TEXT NOT NULL,      -- Full JSON
    format_version  TEXT NOT NULL,
    resolved_at     REAL NOT NULL,      -- Unix timestamp
    UNIQUE (game_id, turn_number)
);

-- Event log
CREATE TABLE IF NOT EXISTS event_log (
    log_id          TEXT PRIMARY KEY,   -- UUID
    game_id         TEXT NOT NULL,
    turn_number     INTEGER NOT NULL,
    timestamp       REAL NOT NULL,
    severity        TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    system_name     TEXT,
    entity_id       TEXT,
    order_id        TEXT,
    context         TEXT,               -- JSON (arbitrary metadata)
    message         TEXT NOT NULL
);
```

**Key Class:**

```python
class GameDatabase:
    """SQLite-backed store for world snapshots and event logs."""

    def __init__(self, db_path: str = ":memory:") -> None:
        """Open connection. Use ":memory:" for tests."""

    def init_schema(self) -> None:
        """Create all tables if not exist. Safe to call multiple times."""

    def save_snapshot(
        self, game_id: str, turn_number: int, world: World,
        registry: ComponentRegistry, format_version: str = "1.0.0"
    ) -> None:
        """Serialize world → snapshot JSON.
        Write to turns table + entity_components table. Transactional."""

    def load_snapshot(
        self, game_id: str, turn_number: int, registry: ComponentRegistry,
        migrations: MigrationRegistry | None = None
    ) -> World:
        """Load snapshot from turns table. Apply migrations if provided.
        Deserialize → World."""

    def log_event(
        self, game_id: str, turn_number: int, event: Event,
        severity: str = "INFO", system_name: str | None = None,
        order_id: str | None = None, context: dict | None = None
    ) -> None:
        """Insert one row into event_log."""

    def get_turn_events(self, game_id: str, turn_number: int) -> list[dict]:
        """Return all event_log rows for (game_id, turn_number), ordered by timestamp."""

    def close(self) -> None:
        """Close SQLite connection."""
```

**Why this design:**
- **Tall table schema (`entity_components`):** Adding new component types requires no schema migration.
  Existing rows unaffected; just insert new (entity_id, component_type, data) rows. Per DESIGN.md rationale
- **Full JSON snapshots (`turns`):** Store complete World state per turn as JSON. Enables debugging
  (can read snapshot and see what game state was). Enables replay (load snapshot, run systems from it,
  compare with original)
- **Event log:** Structured storage of all events per turn. Enables audit trail, per-player reports
  (filter by visibility_scope in Phase 4), and debugging ("what systems ran on turn 5")
- **Transactional save:** Both `turns` and `entity_components` written in single transaction. If either
  fails, both rollback. Ensures consistent DB state
- **UNIQUE constraint on (game_id, turn_number):** Prevents accidental overwrites. Raising `IntegrityError`
  is safer than silent data loss
- **`:memory:` for tests:** Each test uses isolated in-memory database. No filesystem, no cross-test
  contamination

**Where it's used:**
- Phase 2: Save/load loop for persistence
- Tests verify 10-entity round-trip, migration on load, event logging (55 tests)
- Phase 3: Turn resolution saves snapshot after executing all systems
- Phase 4+: Loading old games, replaying turns for disputed resolution

---

### Test Coverage: 3 Test Files, 55 Tests

| File | Tests | Coverage |
|------|-------|----------|
| test_serialization.py | 28 | ComponentRegistry, serialize/deserialize component, World round-trips, UUID handling, determinism |
| test_migrations.py | 8 | Identity passthrough, single hop, chains, idempotency, field renames, cycle detection |
| test_persistence.py | 19 | Schema init, 10-entity round-trip, migrations on load, event logging, isolation |

**Test Philosophy (per DESIGN.md):**
- **In-memory databases:** Every test uses `GameDatabase(":memory:")` for isolation
- **Exit criterion tests:** Two explicit tests for the two exit criteria
  - `test_10_entity_round_trip`: 10 entities (mix of types, parent-child pairs) survive save/load
  - `test_field_rename_migration`: v0.9.0 snapshot with old field name loads with migration
- **Determinism:** Serialize same world twice, assert byte-identical JSON
- **Round-trip validation:** Save → load → assert state identical (component data, UUIDs, current_turn)
- **Event isolation:** Events are isolated by (game_id, turn_number)

---

## Why This Design

### Principle 1: Snapshot-Based Persistence Over Incremental

Store complete World state per turn as JSON, not a stream of mutations.

**Benefits:**
- **Debuggability:** Can inspect snapshot and see exact world state at turn N
- **Replay:** Load snapshot N, run systems again, compare results
- **Simplicity:** No need to track "what changed"; just dump everything
- **Extensibility:** Adding new components doesn't require migration of the mutation log

**Trade-off:** Snapshots are larger on disk than delta logs, but debuggability and simplicity win
for Phase 2. Optimization to delta logs deferred to Phase 6+ if needed.

### Principle 2: Tall Component Table for Schema Flexibility

`entity_components` table stores one row per component per entity. Adding components requires no
schema migration.

**Example:** Phase 4 adds VisibilityComponent. Existing rows in the table are untouched. Just
insert new (entity_id, "Visibility", {...}) rows.

**Why not wide tables?** Wide tables (one column per component type) require `ALTER TABLE` every
time a new component is added. That's slow and error-prone. Tall tables naturally support
extensibility.

### Principle 3: Chainable Migrations for Evolution

Snapshots include a format version. When loading an old snapshot, migrations walk a chain from
old to new version, transforming the JSON document.

**Benefits:**
- **Gradual evolution:** Each migration is small and testable
- **Idempotency:** Safe to re-run migrations if they fail halfway
- **Clear error messages:** If no migration path exists, user knows exactly which version is unsupported
- **Audit trail:** Migration chain is explicit; changes are documented

**Why not ad-hoc deserialization?** Ad-hoc deserialization (checking version inline in `deserialize_world`)
gets messy fast. Chainable migrations keep migration logic separate and composable.

### Principle 4: Transactional Save

`save_snapshot()` writes both `turns` and `entity_components` in a single transaction.

**Benefits:**
- **Consistency:** If save fails halfway, database is rolled back. No partial saves
- **Data integrity:** UNIQUE constraint on (game_id, turn_number) prevents overwrites

### Principle 5: No Changes to Phase 1

Phase 1 ECS code is untouched. Phase 2 adds new modules without modifying engine classes.

**Benefits:**
- **Stability:** Phase 1 tests continue to pass
- **Separation of concerns:** Persistence is separate from core ECS logic
- **Extensibility:** Other phases can build on Phase 1 without serialization coupling them together

---

## Where The Code Lives

```
src/persistence/
├── __init__.py              Public API re-exports
├── serialization.py         ComponentRegistry + serialize/deserialize (~230 lines)
├── migrations.py            MigrationRegistry + CURRENT_FORMAT_VERSION (~90 lines)
└── db.py                    GameDatabase + schema (~220 lines)

tests/
├── test_serialization.py    Round-trips, UUID handling, determinism (28 tests)
├── test_migrations.py       Chain application, idempotency, field renames (8 tests)
└── test_persistence.py      SQLite round-trips, snapshots, events (19 tests)
```

---

## Exit Criteria: Met ✓

Phase 2 exit criteria (per DEV_PHASES.md):
> A world with 10 entities survives save/load with zero data loss. An intentional schema change
> (rename one component field) migrates an old snapshot cleanly.

**Verification:**

**Exit Criterion 1: 10-Entity Round-Trip**
- Test: `test_persistence.py::TestSnapshotRoundTrip::test_10_entity_round_trip`
- Creates world with 10 entities: 4 with HealthComponent, 2 with OwnerComponent (UUID fields), 2 with
  both Health+Position, 1 parent+1 child (ContainerComponent + ChildComponent)
- Saves to SQLite via `GameDatabase.save_snapshot()`
- Loads via `GameDatabase.load_snapshot()`
- Asserts: entity count = 10, entity IDs identical, component data identical, UUIDs preserved,
  parent-child relationships intact

**Exit Criterion 2: Field-Rename Migration**
- Test: `test_persistence.py::TestMigrationOnLoad::test_field_rename_migration`
- Simulates old v0.9.0 snapshot with field `hp` (old name)
- Registers migration v0.9.0 → v1.0.0 that renames `hp` → `current` in HealthComponent
- Loads snapshot with migration registry
- Asserts: result has `current` field (not `hp`), value preserved (77 = 77)

---

## What's Next: Phase 3

Phase 3 (Turn Engine) builds on this persistence foundation:

**Will depend on Phase 2:**
- Save snapshots per turn
- Load snapshots for replay
- Migrations for schema changes
- Event logging for audit trail

**Will add:**
- Action protocol: validate() and execute() interface
- ActionSystem: receives all orders, validates, executes in deterministic order
- Conflict resolution: RNG seeding with game_id + turn + conflict_id
- Full turn loop: receive orders → validate → execute → run systems → snapshot → emit events
- CLI commands: create_game, submit_orders, resolve_turn, query_state

**No changes to Phase 2:** Persistence layer is stable. Phase 3 doesn't modify database schema
(assumes no new component types yet). Snapshots get larger with more entities, but table structure
unchanged.

---

## Deferred Decisions

These are explicitly deferred per DEV_PHASES.md and addressed in later phases:

| Decision | Phase | Notes |
|----------|-------|-------|
| Postgres migration | Phase 6+ | Start with SQLite; migrate when multiplayer requires central DB |
| Backup/restore utilities | Phase 3+ | Phase 3 will add CLI commands that use GameDatabase |
| Delta compression | Phase 6+ | Snapshots can be large; defer optimization until scale matters |
| GameLogger auto-subscription | Phase 3 | Phase 3 introduces turn loop; will auto-subscribe to EventBus for logging |

---

## Testing Strategy Rationale

**In-memory SQLite per test:** `:memory:` databases are fully isolated. Tests don't interfere with
each other. No filesystem operations, no cleanup needed.

**Exit criterion tests first:** Both `test_10_entity_round_trip` and `test_field_rename_migration`
are priority tests. If these fail, phase is incomplete.

**Determinism assertion:** Serialize same world twice, assert JSON is byte-identical. Catches
non-deterministic iteration order (e.g., dict/set ordering bugs).

**Transactional verification:** `test_duplicate_snapshot_raises_integrity_error` verifies that
UNIQUE constraint catches accidental overwrites.

**Parent-before-child ordering:** `test_parent_child_survives` verifies that parent-child relationships
survive round-trip. Tests both loading order (parent created first) and validation hooks (children
have correct parent_id).

---

## Lessons & Architecture Notes

**Why JSON snapshots instead of binary format?**
- **Debuggability:** Can read snapshot as text, inspect game state
- **Compatibility:** JSON works across languages (Python now, maybe Rust later)
- **Simplicity:** No custom binary serialization, no version negotiation

**Why not store raw Component objects (pickle)?**
- **Safety:** Pickle can execute arbitrary code. Not safe for loading untrusted saves
- **Portability:** Pickle is Python-specific; future ports to other languages would break
- **Clarity:** JSON schema is explicit; pickle is black box

**Why migration functions return copies instead of mutating?**
- **Idempotency:** Pure function applied twice = same result
- **Testability:** Input is not modified; can verify migration in isolation
- **Clarity:** No hidden side effects

**Why UNIQUE(game_id, turn_number) instead of INSERT OR REPLACE?**
- **Safety:** Raising IntegrityError is safer than silent overwrites
- **Explicitness:** Caller must decide whether to retry, overwrite, or save to different turn number
- **Debugging:** Explicit errors are easier to trace than silent data loss

---

## Summary

Phase 2 is a **complete, tested persistence layer** that enables PBEM saves, loads, and migrations:

1. ✓ ComponentRegistry for explicit deserialization
2. ✓ Serialization functions (world ↔ JSON) with UUID handling
3. ✓ Deserialization with parent-before-child ordering
4. ✓ MigrationRegistry for chainable schema evolution
5. ✓ GameDatabase with SQLite backend
6. ✓ Both exit criteria met (10-entity round-trip + field-rename migration)
7. ✓ 55 tests; all passing
8. ✓ No changes to Phase 1 code

Phases 3–5 build on this persistence foundation without modifying database schema or core
serialization logic.

---

*End of Phase 2 documentation.*
