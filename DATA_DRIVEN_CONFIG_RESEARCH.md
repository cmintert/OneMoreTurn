# Data-Driven Game Configuration: Research & Recommendation

> Research conducted 2026-03-31. Covers industry practices for externalizing game balance
> values from code into designer-editable config files.

---

## Problem Statement

OneMoreTurn currently has **35+ hardcoded constants** scattered across 5 Python files:

| File | Examples |
|------|---------|
| `src/game/components.py` | `capacity=100.0`, `speed=1.0`, `growth_rate=0.05` |
| `src/game/systems.py` | `base_rate=0.1`, `OBSERVATION_RANGE=10.0`, `PROPULSION_TECHS` dict |
| `src/game/archetypes.py` | `capacity=500.0`, `speed=5.0`, starting inventories |
| `src/game/setup.py` | Home positions, neutral system coordinates, resource ranges |
| `src/game/actions.py` | `population=10` on colonize, `growth_rate=0.05` |

Editing any of these requires Python knowledge, a dev environment, and a code change.

---

## Industry Approaches

### File Formats

| Format | Used By | Pros | Cons |
|--------|---------|------|------|
| **TOML** | Python ecosystem (`pyproject.toml`), indie games | Typed, comments, no coercion, built into Python 3.11+ | Awkward for deeply nested structures |
| **YAML** | Most Python projects, Kubernetes, CI configs | Human-readable, comments, wide VS Code support | Silent type coercion bugs (`NO`/`yes` → boolean) |
| **JSON** | APIs, mobile live-ops, Unity | Universal, no surprises | No comments, verbose |
| **Lua tables** | Factorio | Full scripting power, patchable, loops/conditionals | Requires Lua runtime |
| **SQLite + SQL** | Civilization VI | Relational constraints, foreign keys, mod patches via SQL | Heavy — overkill for small projects |
| **Clausewitz DSL** | Stellaris, CK3, EU4 | Patch/override system, good for mods | Proprietary, no standard tooling |
| **Token text files** | Dwarf Fortress | Simple, moddable via `SELECT`/`CUT` | No structure, verbose |

### The Designer Workflow (Spreadsheet Pipeline)

Most studios with dedicated designers use a **spreadsheet-first pipeline**:

1. **Google Sheets as source of truth** — designers use formulas (not hardcoded values),
   expose a small set of global variables that fan out through derived cells
2. **Auto-export to JSON** via Google Apps Script on save, committed to Git as a diff
3. **Game reads JSON** on startup — zero engineer handoff for pure-number tweaks

This means a balance change is: edit spreadsheet → diff in Git → game updated. No Python required.

### ECS-Specific Patterns

- **Archetypes as config files** — entity templates declare which components + initial property values in `.ron` / `.yaml` / `.json`; code only reads the file
- **Component schemas as validators** — the `properties_schema()` / `constraints()` pattern already in OneMoreTurn maps directly to Pydantic model validation
- **Hot-swapping** — Bevy fires `AssetEvent` when a file changes on disk; systems re-spawn entities from updated definitions without restart

### Notable Game Examples

**Factorio — Lua `data.raw`**
```lua
data:extend({
  { type = "item", name = "iron-plate", stack_size = 100 }
})
-- Mods patch existing entries:
data.raw["item"]["coal"].stack_size = 1000
```
Three-phase load: settings → data → control. Each mod gets three passes (`-updates.lua`, `-final-fixes.lua`). Entire `data.raw` is dumpable to JSON for external tooling.

**Civilization VI — SQLite**
```sql
UPDATE Units SET Cost = 1;
UPDATE Buildings SET Cost = Cost * 3
WHERE PrereqTech IN (
    SELECT TechnologyType FROM Technologies WHERE EraType = 'ERA_ANCIENT'
);
```
Relational model enforces cross-entity constraints via foreign keys. Mods write SQL `INSERT`/`UPDATE` statements.

**Stellaris — Clausewitz DSL**
```
capital_scope = {
    every_deposit = {
        limit = { category = deposit_cat_blockers }
        remove_deposit = yes
    }
}
```
Key-value/block format, `#` comments, duplicate keys stored as lists. CWTools provides parsing + IDE language services.

---

## Recommendation: TOML + Pydantic

### Why TOML

- `tomllib` is **built into Python 3.11+** — zero new dependencies
- Strongly typed (no silent `ON`/`OFF` → boolean coercion unlike YAML)
- Designed for humans to author, not for machines to generate
- Already used in this repo via `pyproject.toml`

### Why Pydantic

- OneMoreTurn's `Component` already has `properties_schema()` and `constraints()` — Pydantic formalizes this existing pattern
- Generates **JSON Schema automatically** → VS Code gives designers autocomplete + inline validation for free
- Consistent with the existing `MigrationRegistry` versioning pattern

---

## Proposed File Structure

```
data/
├── balance.toml      # production rates, growth, morale, observation range
├── map.toml          # spawn positions, neutral systems, resource ranges
├── tech_tree.toml    # research costs and speed multipliers
└── archetypes.toml   # fleet/planet/star system defaults
```

### `data/balance.toml`
```toml
schema_version = "1"

[production]
base_rate     = 0.1    # population × morale × this = output/turn
mineral_split = 0.40   # fraction of output → minerals
energy_split  = 0.30
food_split    = 0.30
min_growth    = 1      # minimum pop increase per turn

[visibility]
observation_range = 10.0   # max distance to see another entity
```

### `data/tech_tree.toml`
```toml
schema_version = "1"

[[tech]]
id               = "ion_drive"
cost             = 3        # turns to research
speed_multiplier = 1.5

[[tech]]
id               = "warp_core"
cost             = 8
speed_multiplier = 2.5
```

### `data/archetypes.toml`
```toml
schema_version = "1"

[star_system]
resource_capacity = 500.0

[planet]
resource_capacity = 200.0
default_growth_rate = 0.05
default_morale      = 1.0
colonize_population = 10    # starting pop when a player colonizes

[fleet]
speed    = 5.0
capacity = 50.0
condition = 100.0
```

### `data/map.toml`
```toml
schema_version = "1"

[home_worlds]
starting_minerals = 50.0
starting_energy   = 30.0
starting_food     = 40.0
starting_population = 100
fleet_starting_cargo = { minerals = 10.0, energy = 5.0 }
positions = [[10.0, 50.0], [90.0, 50.0]]

[[neutral_system]]
name = "Alpha"
x = 30.0
y = 30.0

[[neutral_system]]
name = "Beta"
x = 50.0
y = 50.0

# ... etc

[neutral_planet_resources]
mineral_range = [10.0, 60.0]
energy_range  = [5.0,  40.0]
food_range    = [5.0,  30.0]
planets_per_system = [1, 2]
```

---

## Implementation Pattern

### `src/game/config.py` (new file)
```python
import tomllib
from pathlib import Path
from pydantic import BaseModel, Field

DATA_DIR = Path(__file__).parent.parent.parent / "data"

class ProductionConfig(BaseModel):
    base_rate:     float = Field(gt=0.0)
    mineral_split: float = Field(ge=0.0, le=1.0)
    energy_split:  float = Field(ge=0.0, le=1.0)
    food_split:    float = Field(ge=0.0, le=1.0)
    min_growth:    int   = Field(ge=1)

class VisibilityConfig(BaseModel):
    observation_range: float = Field(gt=0.0)

class BalanceConfig(BaseModel):
    schema_version: str
    production: ProductionConfig
    visibility:  VisibilityConfig

def load_balance(path: Path = DATA_DIR / "balance.toml") -> BalanceConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return BalanceConfig.model_validate(raw)

BALANCE = load_balance()
```

### Usage in systems (before → after)
```python
# Before — magic number
production = pop.size * pop.morale * 0.1

# After — named, externally tunable, validated
from game.config import BALANCE
production = pop.size * pop.morale * BALANCE.production.base_rate
```

---

## Config Versioning

Embed `schema_version` in every config file and maintain a migration chain — the same
pattern already used by `MigrationRegistry` in `src/persistence/migrations.py`:

```python
MIGRATIONS = {
    ("1", "2"): lambda d: {**d, "visibility": {"observation_range": d.pop("observation_range")}},
}

def migrate(data: dict, target: str) -> dict:
    current = data.get("schema_version", "1")
    while current != target:
        key = (current, str(int(current) + 1))
        data = MIGRATIONS[key](data)
        data["schema_version"] = current = key[1]
    return data
```

---

## Upgrade Path

| Phase | What | Benefit |
|-------|------|---------|
| **1 — Now** | TOML files in `data/`, Pydantic loader in `src/game/config.py` | No Python needed to tune balance |
| **2 — Near** | Expose config via existing Flask API (`GET /config`, `PUT /config`) | Edit in browser, no file system access needed |
| **3 — Later** | Google Sheets → export script → `data/*.toml` commit | Non-technical designers iterate independently |

---

## Sources

- [Data-Driven Design: Leveraging Lessons from Game Development](https://dev.to/methodox/data-driven-design-leveraging-lessons-from-game-development-in-everyday-software-5512)
- [My Approach to Economy Balancing Using Spreadsheets — Game Developer](https://www.gamedeveloper.com/design/my-approach-to-economy-balancing-using-spreadsheets)
- [For the love of spreadsheets — Hutch Games](https://www.hutch.io/blog/tech/tech-blog-game-changer/)
- [Factorio Data Lifecycle — Official Auxiliary Docs](https://lua-api.factorio.com/latest/auxiliary/data-lifecycle.html)
- [A Tour of PDS Clausewitz Syntax — PDX Tools](https://pdx.tools/blog/a-tour-of-pds-clausewitz-syntax)
- [Civilization VI SQLite Modding Guide — Steam](https://steamcommunity.com/sharedfiles/filedetails/?id=1968580787)
- [ECS FAQ — Sander Mertens (GitHub)](https://github.com/SanderMertens/ecs-faq)
- [Bevy Hot-Reloading Assets — Unofficial Cheat Book](https://bevy-cheatbook.github.io/assets/hot-reload.html)
- [How to Build a Config System with Hot Reload in Python — OneUptime Blog](https://oneuptime.com/blog/post/2026-01-22-config-hot-reload-python/view)
- [pydantic-yaml on PyPI](https://pypi.org/project/pydantic-yaml/)
- [watchdog on PyPI](https://pypi.org/project/watchdog/)
- [importlib.reload is not thread-safe — CPython Issue #126548](https://github.com/python/cpython/issues/126548)
- [Beyond Scriptable Objects: Unity Data Management with CastleDB — Game Developer](https://www.gamedeveloper.com/programming/beyond-scriptable-objects-unity-data-management-with-castledb)
