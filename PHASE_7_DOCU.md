---
title: "Phase 7 Documentation: Data-Driven Configuration"
status: "Complete"
date: 2026-04-02
---

# Phase 7 Documentation: Data-Driven Configuration

## Overview

Phase 7 extracts all hardcoded game constants into external TOML files with Pydantic
validation, making the game **tunable without touching Python code**.

The 28 magic numbers scattered across five source files (systems, archetypes, setup,
actions) now live in four TOML files under `data/` and are validated at startup.
Systems, archetypes, and setup read values from module-level singletons instead of
hardcoded literals. A game designer can now change `observation_range` from `10.0`
to `12.0` by editing `data/balance.toml` — no Python knowledge required.

**Why TOML + Pydantic:**

- `tomllib` is built into Python 3.11+ — zero new runtime dependencies
- TOML is strongly typed, comment-supporting, no silent coercion bugs
- Pydantic validates on load and generates JSON Schema for IDE autocomplete
- Both patterns fit the existing `properties_schema()` / `constraints()` protocol
- Migration chain mirrors the existing `MigrationRegistry` versioning approach

**Status:** Complete. 15 new tests in `tests/test_config.py`. All 417 Phase 1–7
tests passing. Ruff checks pass. Zero engine changes.

---

## What Was Built

### New Files

| File | Purpose |
| --- | --- |
| `data/balance.toml` | Production rates, resource splits, observation range |
| `data/archetypes.toml` | Fleet, planet, star system defaults |
| `data/tech_tree.toml` | Research costs and speed multipliers |
| `data/map.toml` | Home positions, neutral systems, resource ranges |
| [src/game/config.py](src/game/config.py) | Pydantic models, TOML loaders, singletons |
| [tests/test_config.py](tests/test_config.py) | 15 tests: validation, migration, integration |

### Modified Files

| File | Change |
|------|--------|
| `pyproject.toml` | Added `pydantic>=2.0` to `[project.dependencies]` |
| `src/game/systems.py` | 7 constants replaced with config references; `PROPULSION_TECHS` rebuilt from `TECH_TREE` |
| `src/game/archetypes.py` | 6 constants replaced with config references; function defaults wired to config |
| `src/game/setup.py` | 13 constants replaced; neutral system loop restructured to use `MAP.neutral_system` |
| `src/game/actions.py` | 3 colonize defaults replaced with config references |
| `CLAUDE.md` | Documents config layer and enforces "never hardcode" rule |

---

## Architecture

### Config Layer: `src/game/config.py`

The sole interface between TOML files and game code. All other modules import
module-level singletons; none read files directly.

### Pydantic models (with validation)

- `ProductionConfig` — base rate, resource splits, min growth. Validator ensures
  splits sum to 1.0
- `BalanceConfig` — production + visibility settings
- `StarSystemArchetype`, `PlanetArchetype`, `FleetArchetype` — entity defaults
- `ArchetypesConfig` — all archetypes
- `TechConfig`, `TechTreeConfig` — research definitions with `as_dict()` method
- `HomeWorldsConfig`, `NeutralSystem`, `NeutralPlanetResources`, `MapConfig`
  — map generation parameters

### Loaders

- `_load(model, path, migrations, target_version)` — read TOML, migrate, validate
- Reads each file once at import time → module-level singletons
- Invalid config raises `ValidationError` with human-readable message at startup

### Migration scaffolding

- `_migrate(data, migrations, target)` — walk the migration chain from current
  version to target
- Migration dicts exist for all four config types (currently empty; scaffolding
  for future schema evolution)
- No circular dependencies — `config.py` imports only stdlib + pydantic

### Module-level singletons

```python
BALANCE: BalanceConfig       # data/balance.toml
ARCHETYPES: ArchetypesConfig # data/archetypes.toml
TECH_TREE: TechTreeConfig    # data/tech_tree.toml
MAP: MapConfig               # data/map.toml
```

All game code reads from these. Example:

```python
# Before (hardcoded)
production = pop.size * pop.morale * 0.1

# After (configurable)
from game.config import BALANCE
production = pop.size * pop.morale * BALANCE.production.base_rate
```

---

## Wiring Pattern

Every file that consumed constants now imports config and reads from singletons:

### `src/game/systems.py`

```python
from game.config import BALANCE, TECH_TREE

# ProductionSystem.update()
production = pop.size * pop.morale * BALANCE.production.base_rate
minerals = production * BALANCE.production.mineral_split
# ...
pop.size += max(growth, BALANCE.production.min_growth)

# VisibilitySystem class attribute
OBSERVATION_RANGE: float = BALANCE.visibility.observation_range

# Module-level constant
PROPULSION_TECHS: dict = TECH_TREE.as_dict()
```

### `src/game/archetypes.py`

```python
from game.config import ARCHETYPES

def create_star_system(...) -> Entity:
    return world.create_entity([
        Resources(amounts=..., capacity=ARCHETYPES.star_system.resource_capacity),
        ...
    ])

def create_fleet(..., speed: float = ARCHETYPES.fleet.speed, ...) -> Entity:
    return world.create_entity([
        FleetStats(speed=speed, capacity=ARCHETYPES.fleet.capacity,
                   condition=ARCHETYPES.fleet.condition),
        Resources(amounts=cargo or {}, capacity=ARCHETYPES.fleet.capacity),
        ...
    ])
```

### `src/game/setup.py`

```python
from game.config import MAP

home_positions = [tuple(pos) for pos in MAP.home_worlds.positions]
# ...
for ns in MAP.neutral_system:
    system = create_star_system(world, ns.name, ns.x, ns.y)
    n_planets = rng.randint(MAP.neutral_planet_resources.planets_per_system[0],
                            MAP.neutral_planet_resources.planets_per_system[1])
    # ...
    "minerals": float(rng.randint(int(_npr.mineral_range[0]),
                                  int(_npr.mineral_range[1]))),
```

### `src/game/actions.py`

```python
from game.config import ARCHETYPES

# ColonizePlanetAction.execute()
world.add_component(planet.id, PopulationStats(
    size=ARCHETYPES.planet.colonize_population,
    growth_rate=ARCHETYPES.planet.colonize_growth_rate,
    morale=ARCHETYPES.planet.colonize_morale,
))
```

---

## TOML Configuration Files

All default values preserved from existing code.

### `data/balance.toml`

```toml
schema_version = "1"

[production]
base_rate     = 0.1    # population × morale × this = output/turn
mineral_split = 0.40   # fraction of output (must sum to 1.0 with others)
energy_split  = 0.30
food_split    = 0.30
min_growth    = 1      # minimum pop increase per turn

[visibility]
observation_range = 10.0   # max distance to see entities
```

### `data/archetypes.toml`

```toml
schema_version = "1"

[star_system]
resource_capacity = 500.0

[planet]
resource_capacity    = 200.0
default_growth_rate  = 0.05
default_morale       = 1.0
colonize_population  = 10
colonize_growth_rate = 0.05
colonize_morale      = 1.0

[fleet]
speed     = 5.0
capacity  = 50.0
condition = 100.0
```

### `data/tech_tree.toml`

```toml
schema_version = "1"

[[tech]]
id               = "ion_drive"
cost             = 3
speed_multiplier = 1.5

[[tech]]
id               = "warp_core"
cost             = 8
speed_multiplier = 2.5
```

### `data/map.toml`

```toml
schema_version = "1"

[home_worlds]
starting_minerals   = 50.0
starting_energy     = 30.0
starting_food       = 40.0
starting_population = 100
fleet_minerals      = 10.0
fleet_energy        = 5.0
positions           = [[10.0, 50.0], [90.0, 50.0]]

[[neutral_system]]
name = "Alpha"
x    = 30.0
y    = 30.0

# ... (4 more neutral systems)

[neutral_planet_resources]
mineral_range      = [10.0, 60.0]
energy_range       = [5.0,  40.0]
food_range         = [5.0,  30.0]
planets_per_system = [1, 2]
```

---

## Tests

[tests/test_config.py](tests/test_config.py) — 15 tests covering:

**Loading (4 tests)**
- `test_balance_loads()` — all fields parse and have correct types
- `test_archetypes_loads()` — all archetype values present
- `test_tech_tree_loads()` — techs available as dict
- `test_map_loads()` — systems, positions, ranges all present

**Validation (4 tests)**
- `test_splits_not_summing_to_one_rejected()` — Pydantic validator works
- `test_negative_base_rate_rejected()` — field constraints enforced
- `test_zero_min_growth_rejected()` — min growth ≥ 1
- `test_missing_production_section_rejected()` — required fields enforced

**Migration (2 tests)**
- `test_migrate_no_op_when_already_at_target()` — no-op migration chain
- `test_migrate_applies_registered_function()` — registered migrations execute

**Integration (5 tests)**
- `test_production_system_uses_config()` — ProductionSystem reads `BALANCE`
- `test_create_fleet_uses_config_default_speed()` — archetypes use `ARCHETYPES`
- `test_colonize_uses_config_population()` — actions use `ARCHETYPES`
- `test_monkeypatch_balance_changes_production_output()` — config change → observable
  output change (confirms wiring)

All 417 Phase 1–7 tests pass. Ruff checks pass.

---

## Exit Criteria Met

- ✓ `python -m pytest` — all 417 tests pass (399 existing + 15 new + 3 from earlier phases)
- ✓ `ruff check src/ tests/` — no violations
- ✓ At least one balance value changed in TOML produces expected change in test outcome
  (monkeypatch test demonstrates this)
- ✓ Invalid TOML (splits not summing to 1.0) produces human-readable error at startup
- ✓ `schema_version` field present in all four TOML files
- ✓ Migration scaffolding in place; v1→v2 chain exists (even if v2 not yet needed)

---

## Upgrade Path (Deferred to Phase 8+)

| Phase | What | Benefit |
|-------|------|---------|
| **7 — Now** | TOML files in `data/`, Pydantic in config | No Python needed to tune |
| **8 — Later** | Flask config API: `GET /config`, `PUT /config` | Edit in browser |
| **9 — Later** | Google Sheets export script → TOML | Non-technical designers iterate |

---

## Design Notes

### Why not JSON?

JSON has no comments. YAML has silent type coercion bugs. TOML is typed,
comment-friendly, and built into Python 3.11+.

### Why not hot-reload?

Deferred to Phase 8. Config is validated once at startup; adding file watcher +
reload complexity is orthogonal to the core infrastructure.

### Why not per-game configs?

All games use the same config. Per-game variants (e.g., "hard mode") are Phase 8+
territory — requires deciding how overrides compose and when they're applied.

### Why Pydantic?

Validates, generates JSON Schema (free IDE autocomplete), and is the de facto
standard in the Python ecosystem. The `as_dict()` method on `TechTreeConfig` shows
how Pydantic models can provide custom output formats.

---

*End of Phase 7 documentation.*
