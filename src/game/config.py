"""Game configuration loader.

Reads TOML files from data/ at import time and exposes validated, typed config
objects as module-level singletons.  Systems, archetypes, setup, and actions
import these singletons rather than using magic numbers.

To change a value: edit the relevant ``data/*.toml`` file — no Python changes needed.

Config files each carry a ``schema_version`` field.  Breaking changes bump the
version and are handled by a migration chain (same pattern as
``persistence.migrations.MigrationRegistry``).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent.parent / "data"

# ---------------------------------------------------------------------------
# Pydantic models — balance.toml
# ---------------------------------------------------------------------------


class ProductionConfig(BaseModel):
    """Production rates and resource split fractions for colonized planets."""

    base_rate: float = Field(gt=0.0, le=10.0)
    mineral_split: float = Field(ge=0.0, le=1.0)
    energy_split: float = Field(ge=0.0, le=1.0)
    food_split: float = Field(ge=0.0, le=1.0)
    min_growth: int = Field(ge=1)

    @model_validator(mode="after")
    def splits_sum_to_one(self) -> "ProductionConfig":
        """Reject configs where the three resource splits don't add up to 1.0."""
        total = self.mineral_split + self.energy_split + self.food_split
        if abs(total - 1.0) >= 1e-9:
            raise ValueError(
                f"mineral_split + energy_split + food_split must equal 1.0, got {total:.6f}"
            )
        return self


class VisibilityConfig(BaseModel):
    """Fog-of-war observation parameters."""

    observation_range: float = Field(gt=0.0, le=1000.0)


class BalanceConfig(BaseModel):
    """Top-level model for data/balance.toml."""

    schema_version: str
    production: ProductionConfig
    visibility: VisibilityConfig


# ---------------------------------------------------------------------------
# Pydantic models — archetypes.toml
# ---------------------------------------------------------------------------


class StarSystemArchetype(BaseModel):
    """Default component values for star system entities."""

    resource_capacity: float = Field(gt=0.0)


class PlanetArchetype(BaseModel):
    """Default component values for planet entities."""

    resource_capacity: float = Field(gt=0.0)
    default_growth_rate: float = Field(ge=0.0, le=1.0)
    default_morale: float = Field(ge=0.0, le=2.0)
    colonize_population: int = Field(ge=1)
    colonize_growth_rate: float = Field(ge=0.0, le=1.0)
    colonize_morale: float = Field(ge=0.0, le=2.0)


class FleetArchetype(BaseModel):
    """Default component values for fleet entities."""

    speed: float = Field(gt=0.0)
    capacity: float = Field(gt=0.0)
    condition: float = Field(gt=0.0, le=100.0)


class ArchetypesConfig(BaseModel):
    """Top-level model for data/archetypes.toml."""

    schema_version: str
    star_system: StarSystemArchetype
    planet: PlanetArchetype
    fleet: FleetArchetype


# ---------------------------------------------------------------------------
# Pydantic models — tech_tree.toml
# ---------------------------------------------------------------------------


class TechConfig(BaseModel):
    """A single researchable technology."""

    id: str
    cost: int = Field(ge=1)
    speed_multiplier: float = Field(gt=1.0)


class TechTreeConfig(BaseModel):
    """Top-level model for data/tech_tree.toml."""

    schema_version: str
    tech: list[TechConfig]

    def as_dict(self) -> dict[str, dict]:
        """Return techs as a plain dict compatible with PROPULSION_TECHS usage."""
        return {
            t.id: {"cost": t.cost, "speed_multiplier": t.speed_multiplier}
            for t in self.tech
        }


# ---------------------------------------------------------------------------
# Pydantic models — map.toml
# ---------------------------------------------------------------------------


class HomeWorldsConfig(BaseModel):
    """Starting resources, population, and positions for player home worlds."""

    starting_minerals: float
    starting_energy: float
    starting_food: float
    starting_population: int = Field(ge=1)
    fleet_minerals: float = Field(ge=0.0)
    fleet_energy: float = Field(ge=0.0)
    positions: list[list[float]]


class NeutralSystem(BaseModel):
    """Name and coordinates for a neutral star system."""

    name: str
    x: float
    y: float


class NeutralPlanetResources(BaseModel):
    """RNG ranges for resources on procedurally generated neutral planets."""

    mineral_range: list[float]
    energy_range: list[float]
    food_range: list[float]
    planets_per_system: list[int]


class MapConfig(BaseModel):
    """Top-level model for data/map.toml."""

    schema_version: str
    home_worlds: HomeWorldsConfig
    neutral_system: list[NeutralSystem]
    neutral_planet_resources: NeutralPlanetResources


# ---------------------------------------------------------------------------
# Migration scaffolding
# ---------------------------------------------------------------------------

_MigrationFn = Callable[[dict], dict]

_BALANCE_MIGRATIONS: dict[tuple[str, str], _MigrationFn] = {
    # placeholder: ("1", "2"): lambda d: {**d, ...},
}

_ARCHETYPES_MIGRATIONS: dict[tuple[str, str], _MigrationFn] = {}
_TECH_TREE_MIGRATIONS: dict[tuple[str, str], _MigrationFn] = {}
_MAP_MIGRATIONS: dict[tuple[str, str], _MigrationFn] = {}


def _migrate(
    data: dict,
    migrations: dict[tuple[str, str], _MigrationFn],
    target: str,
) -> dict:
    """Walk the migration chain from data['schema_version'] up to target."""
    current = data.get("schema_version", "1")
    seen: set[str] = set()
    while current != target:
        if current in seen:
            raise ValueError(f"Cycle detected in migration chain at version {current!r}")
        seen.add(current)
        next_ver = str(int(current) + 1)
        key = (current, next_ver)
        if key not in migrations:
            break
        data = migrations[key](data)
        data["schema_version"] = current = next_ver
    return data


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

_CURRENT_BALANCE_VERSION = "1"
_CURRENT_ARCHETYPES_VERSION = "1"
_CURRENT_TECH_TREE_VERSION = "1"
_CURRENT_MAP_VERSION = "1"


def _load(model: type, path: Path, migrations: dict, target_version: str):
    """Read a TOML file, migrate if needed, then validate with Pydantic."""
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    raw = _migrate(raw, migrations, target_version)
    return model.model_validate(raw)


# ---------------------------------------------------------------------------
# Module-level singletons — loaded once at import time
# ---------------------------------------------------------------------------

BALANCE: BalanceConfig = _load(
    BalanceConfig, DATA_DIR / "balance.toml", _BALANCE_MIGRATIONS, _CURRENT_BALANCE_VERSION
)

ARCHETYPES: ArchetypesConfig = _load(
    ArchetypesConfig,
    DATA_DIR / "archetypes.toml",
    _ARCHETYPES_MIGRATIONS,
    _CURRENT_ARCHETYPES_VERSION,
)

TECH_TREE: TechTreeConfig = _load(
    TechTreeConfig,
    DATA_DIR / "tech_tree.toml",
    _TECH_TREE_MIGRATIONS,
    _CURRENT_TECH_TREE_VERSION,
)

MAP: MapConfig = _load(
    MapConfig, DATA_DIR / "map.toml", _MAP_MIGRATIONS, _CURRENT_MAP_VERSION
)
