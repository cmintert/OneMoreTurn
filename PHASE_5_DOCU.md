---
title: "Phase 5 Documentation: Assess & Extensibility Test"
status: "Complete"
date: 2026-03-31
---

# Phase 5 Documentation: Assess & Extensibility Test

## Overview

Phase 5 stress-tests the ECS architecture by answering one question: **can a meaningful
new mechanic be added to the game without touching the core engine?**

Two advances were shipped together:

1. **Decorator-based registry autodiscovery** — `src/game/registry.py` now provides
   `@component`, `@action`, and `@system` class decorators. Game classes self-register
   at import time; adding a new mechanic to `src/game/` requires touching only that file.

2. **Propulsion tech tree** — a new game mechanic (`ResearchComponent`, `ResearchSystem`,
   `StartResearchAction`, `create_civilization` archetype) that proves the extensibility
   claim. Players research propulsion technologies that permanently increase their fleet
   speeds. The mechanic was implemented with zero changes to `src/engine/`.

**Status:** Complete. 19 new tests. All 351 Phase 1–4 tests still passing.
Grand total: 370 tests. Ruff god-class checks pass. Zero engine changes.

---

## What Was Built

### Modified Files

| File | Change |
|------|--------|
| `src/game/registry.py` | Rewritten: decorator accumulators, `@component`/`@action`/`@system`, guard-import builder functions |
| `src/game/components.py` | Added `@component` to all 6 existing classes; added `ResearchComponent` |
| `src/game/actions.py` | Added `@action` to all 3 existing classes; added `StartResearchAction` |
| `src/game/systems.py` | Added `@system` to all 3 existing classes; added `PROPULSION_TECHS` and `ResearchSystem` |
| `src/game/archetypes.py` | Added `create_civilization()` factory function |
| `src/game/setup.py` | Calls `create_civilization()` for each player during map initialization |

### New Test File

| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_propulsion_tech.py` | 19 | Decorator autodiscovery, research progression, tech completion, speed bonus application, event emission, action validation, serialization round-trip |

---

## Architecture

### 1. [src/game/registry.py](src/game/registry.py) — Decorator Registry

**The problem it solves:** Previously, adding a new component, action, or system required
editing two files: the file defining the class and `registry.py` to register it. A forgotten
registration is silent at definition time and only surfaces as a `KeyError` at deserialization
— a confusing failure mode far from the source.

**The solution:** Three module-level accumulator lists and three decorator functions.

```python
_component_classes: list[type] = []
_action_classes: list[type] = []
_system_classes: list[type] = []

def component(cls): _component_classes.append(cls); return cls
def action(cls):    _action_classes.append(cls);    return cls
def system(cls):    _system_classes.append(cls);    return cls
```

Decorating a class at definition time registers it immediately and visibly at its source.
The failure mode becomes: forgot `@component` → class never appears in the registry.
The registration point and the definition point are the same line.

The builder functions use guard-imports so game modules are loaded on first call even if
the caller has not already imported them:

```python
def game_component_registry() -> ComponentRegistry:
    import game.components as _gc  # noqa: F401  ← ensures decorators fire
    ...
    reg.register(*_component_classes)
    reg.register(NameComponent, ContainerComponent, ChildComponent)  # engine types
    return reg
```

**Why engine types stay explicit:** `ContainerComponent`, `ChildComponent`, and `NameComponent`
live in `src/engine/` and `src/engine/names.py` — outside the game package. They cannot
self-register into the game registry. Three explicit lines are the right answer; no discovery
mechanism would be cleaner.

**Why not full module scanning (`pkgutil` + `inspect`):** Autodiscovery via `pkgutil.walk_packages`
and `inspect.getmembers` would silently pick up abstract base classes, test stubs, and any helper
class that happens to subclass `Component`. The decorator pattern is explicit about intent with
no scanning magic.

**Circular import avoidance:** `registry.py` has no top-level imports from `game.*`. Game modules
import `from game.registry import component` (safe — registry is a leaf in the import graph).
Builder functions perform all game-module imports inside the function body.

---

### 2. New Component: `ResearchComponent`

```python
@component
@dataclass
class ResearchComponent(Component):
    active_tech_id: str | None = None
    progress: float = 0.0
    required_progress: float = 0.0
    unlocked_techs: list[str] = field(default_factory=list)

    component_name() = "Research"
    version()        = "1.0.0"
    constraints()    = {"progress": {"min": 0}, "required_progress": {"min": 0}}
```

`ResearchComponent` is attached to a **civilization entity** — a new entity archetype that
represents a player's empire as a whole. The civilization entity carries `Owner + ResearchComponent`
and has no Position; it is not a spatial object. This design avoids mutating fleet or planet
entities to hold research state.

**Why `progress` counts in whole turns:** Research cost is specified in turns (`cost: int`).
`ResearchSystem` increments `progress` by `1.0` per turn. The mechanic is transparent to the
player: "ion drive takes 3 turns". No fractional rates, no resource costs for the prototype.

**Why `unlocked_techs` is a list of strings:** Tech IDs are lightweight, human-readable, and
serializable without a registry. The list accumulates; techs are never removed. This also makes
validation simple: `tech_id in research.unlocked_techs`.

---

### 3. New System: `ResearchSystem`

```
Phase: MAIN   Required prior: ActionSystem
Queries: (ResearchComponent, Owner)
```

```python
PROPULSION_TECHS: dict[str, dict] = {
    "ion_drive": {"cost": 3, "speed_multiplier": 1.5},
    "warp_core":  {"cost": 8, "speed_multiplier": 2.5},
}
```

Each turn, for every civilization entity with an `active_tech_id`:

1. `research.progress += 1.0`
2. If `progress >= required_progress`:
   - Append `tech_id` to `unlocked_techs`
   - Look up `speed_multiplier` from `PROPULSION_TECHS`
   - Multiply `FleetStats.speed` for **all fleets owned by that player** (query by `Owner.player_id`)
   - Clear `active_tech_id`, `progress`, `required_progress`
   - Publish `TechUnlocked` event with `visibility_scope=[player_id]`

**Why the speed bonus is baked into `FleetStats.speed`:** `MovementSystem` already reads
`FleetStats.speed` to compute travel turns. No change to `MovementSystem` is needed — it
gets faster fleets automatically. The alternative (a separate speed-bonus component read by
`MovementSystem`) would require a `MovementSystem` change, which would violate the Phase 5
goal of zero engine changes *and* unnecessary game-system coupling.

**Ordering:** `ResearchSystem` declares `required_prior_systems=[ActionSystem]`, so `StartResearchAction`
orders for the current turn are already applied before research progress is ticked. A player who
submits a `StartResearchAction` on the same turn research completes will not double-apply.

**New fleet bonus:** When tech completes, only fleets that exist at that moment receive the
multiplier. Fleets created in future turns start with the base speed. This is a deliberate
simplification deferred for Phase 6.

---

### 4. New Action: `StartResearchAction`

```python
@action
@dataclass
class StartResearchAction(Action):
    civ_entity_id: uuid.UUID
    tech_id: str

    action_type() = "StartResearch"
    conflict_key() = None   # one civ per player; no player can conflict with themselves
```

**Validate:** Entity exists, owned by player, has `ResearchComponent`, `tech_id` is in
`PROPULSION_TECHS`, `tech_id` not already in `unlocked_techs`, `active_tech_id is None`.

**Execute:** Set `active_tech_id`, `required_progress = float(tech_def["cost"])`, reset
`progress = 0.0`. Emit `ResearchStarted` event.

`PROPULSION_TECHS` is imported inside the method body (`from game.systems import PROPULSION_TECHS`)
rather than at module top level. This avoids a circular import: `actions.py` → `systems.py`
→ `actions.py` (via `ActionSystem` from the engine). The function-level import fires only on
validation/execution, by which time all modules are fully loaded.

---

### 5. New Archetype: `create_civilization()`

```python
def create_civilization(world, player_id, owner_name) -> Entity:
    return world.create_entity([
        Owner(player_id=player_id, player_name=owner_name),
        ResearchComponent(),
    ])
```

A minimal entity with no spatial presence. One per player. Created by `setup_game()` for every
player at game start. This gives each player a persistent anchor for tech state across turns,
serialized and loaded alongside all other entities.

**Why a separate entity rather than attaching to the home planet:** Planets can be lost (conquered
or destroyed). Research state belongs to the player's empire, not to any single spatial object.
A dedicated civilization entity has a fixed lifetime matching the player's participation.

---

### 6. [src/game/setup.py](src/game/setup.py) — Initialization Change

One line added per player in the setup loop:

```python
create_civilization(world, pid, pname)
```

This is the only change to `setup_game()`. All existing archetype calls are untouched. The
existing integration tests still pass because `ResearchSystem` queries `(ResearchComponent, Owner)`
— it silently skips entities that lack either, including all pre-existing entity types.

---

## Extensibility Assessment

The Phase 5 goal was: **add a new mechanic with zero changes to Phase 1–3 engine code.**

| Layer | Files changed | Notes |
|-------|--------------|-------|
| `src/engine/` | 0 | No changes |
| `src/persistence/` | 0 | Serialization handled by existing `ComponentRegistry` + `ActionRegistry` infrastructure |
| `src/game/` | 6 | All game-layer additions; no workarounds required |
| `tests/` | 1 new file | 19 tests covering new mechanic end-to-end |

The engine protocol (`Component`, `System`, `Action`, `EventBus`, `TurnManager`) absorbed the
new mechanic cleanly. Specific invariants confirmed:

- Topological sort correctly orders `ResearchSystem` after `ActionSystem` (MAIN phase,
  `required_prior_systems` declared).
- Serialization round-trips `ResearchComponent` — including `list[str]` unlocked_techs and
  `str | None` active_tech_id — without any persistence-layer changes.
- RNG seeding contract is respected: `ResearchSystem` does not use RNG (research is deterministic
  by turn count). This is consistent with the engine design.
- Fog-of-war: `TechUnlocked` events carry `visibility_scope=[player_id]` so opponents cannot
  observe another player's research progress.

**Friction points observed (deferred to Phase 6):**
- New fleets do not inherit speed bonuses applied before they were created.
- No prerequisites between techs (must research `ion_drive` before `warp_core`).
- No resource cost for research — players can always research; there is no economic tradeoff.

---

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Decorator pattern over module scanning | Explicit, visible at definition site; scanning picks up stubs and abstract classes |
| Guard-imports in builder functions | Prevents circular imports; modules load on first call to registry builders |
| Engine types registered explicitly | They live in `src/engine/`, cannot self-register into `game/` |
| Speed bonus baked into `FleetStats.speed` | `MovementSystem` unchanged; speed is the right level of abstraction |
| `ResearchComponent` on a civilization entity | Research state belongs to player's empire, not to any spatial entity |
| `PROPULSION_TECHS` defined in `systems.py` | Only consumed by `ResearchSystem` + `StartResearchAction`; owned by the layer that uses it |
| `PROPULSION_TECHS` imported inside method body in `actions.py` | Avoids circular import through `ActionSystem` |
| `conflict_key() = None` on `StartResearchAction` | One civ per player; a player can only conflict with themselves |
| Progress in whole turns (not resource cost) | Transparent to the player; no economy balance needed for prototype |

---

## Test Coverage: 19 New Tests

| Class | Tests | What is covered |
|-------|-------|-----------------|
| `TestDecoratorRegistry` | 6 | Decorators populate accumulator lists; `game_component_registry()`, `game_action_registry()`, `game_systems()` return new types |
| `TestResearchSystem` | 5 | Progress advances, tech completes + unlocks, fleet speed updated, `TechUnlocked` event emitted, idle when no active tech |
| `TestStartResearchAction` | 7 | Valid submit, execute sets fields, wrong owner rejected, unknown tech rejected, already unlocked rejected, already researching rejected |
| `TestResearchRoundTrip` | 2 | Serialize/deserialize populated `ResearchComponent`; serialize/deserialize empty `ResearchComponent` |

### Totals

| | Count |
|---|---|
| Phase 5 new tests | 19 |
| Phase 1–4 (unchanged) | 351 |
| **Grand total** | **370** |
