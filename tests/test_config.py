"""Tests for src/game/config.py — loading, validation, migration, and wiring."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from game.config import (
    ARCHETYPES,
    BALANCE,
    MAP,
    TECH_TREE,
    BalanceConfig,
    _migrate,
    _BALANCE_MIGRATIONS,
    _CURRENT_BALANCE_VERSION,
)


# ---------------------------------------------------------------------------
# Singletons load without error
# ---------------------------------------------------------------------------


def test_balance_loads():
    assert BALANCE.production.base_rate == pytest.approx(0.1)
    assert BALANCE.production.mineral_split == pytest.approx(0.4)
    assert BALANCE.production.energy_split == pytest.approx(0.3)
    assert BALANCE.production.food_split == pytest.approx(0.3)
    assert BALANCE.production.min_growth == 1
    assert BALANCE.visibility.observation_range == pytest.approx(10.0)


def test_archetypes_loads():
    assert ARCHETYPES.star_system.resource_capacity == pytest.approx(500.0)
    assert ARCHETYPES.planet.resource_capacity == pytest.approx(200.0)
    assert ARCHETYPES.planet.default_growth_rate == pytest.approx(0.05)
    assert ARCHETYPES.planet.default_morale == pytest.approx(1.0)
    assert ARCHETYPES.planet.colonize_population == 10
    assert ARCHETYPES.fleet.speed == pytest.approx(5.0)
    assert ARCHETYPES.fleet.capacity == pytest.approx(50.0)
    assert ARCHETYPES.fleet.condition == pytest.approx(100.0)


def test_tech_tree_loads():
    techs = TECH_TREE.as_dict()
    assert "ion_drive" in techs
    assert "warp_core" in techs
    assert techs["ion_drive"]["cost"] == 3
    assert techs["ion_drive"]["speed_multiplier"] == pytest.approx(1.5)
    assert techs["warp_core"]["cost"] == 8
    assert techs["warp_core"]["speed_multiplier"] == pytest.approx(2.5)


def test_map_loads():
    assert len(MAP.home_worlds.positions) == 2
    assert MAP.home_worlds.starting_minerals == pytest.approx(50.0)
    assert MAP.home_worlds.starting_population == 100
    assert len(MAP.neutral_system) == 5
    assert MAP.neutral_system[0].name == "Alpha"
    _npr = MAP.neutral_planet_resources
    assert _npr.mineral_range[0] < _npr.mineral_range[1]
    assert _npr.planets_per_system[0] <= _npr.planets_per_system[1]


# ---------------------------------------------------------------------------
# Pydantic validation rejects bad configs
# ---------------------------------------------------------------------------


def _base_balance_data(**overrides) -> dict:
    data = {
        "schema_version": "1",
        "production": {
            "base_rate": 0.1,
            "mineral_split": 0.40,
            "energy_split": 0.30,
            "food_split": 0.30,
            "min_growth": 1,
        },
        "visibility": {"observation_range": 10.0},
    }
    data["production"].update(overrides)
    return data


def test_splits_not_summing_to_one_rejected():
    bad = _base_balance_data(mineral_split=0.50)  # 0.50 + 0.30 + 0.30 = 1.10
    with pytest.raises(ValidationError, match="must equal 1.0"):
        BalanceConfig.model_validate(bad)


def test_negative_base_rate_rejected():
    bad = _base_balance_data(base_rate=-0.1)
    with pytest.raises(ValidationError):
        BalanceConfig.model_validate(bad)


def test_zero_min_growth_rejected():
    bad = _base_balance_data(min_growth=0)
    with pytest.raises(ValidationError):
        BalanceConfig.model_validate(bad)


def test_missing_production_section_rejected():
    bad = {"schema_version": "1", "visibility": {"observation_range": 10.0}}
    with pytest.raises(ValidationError):
        BalanceConfig.model_validate(bad)


# ---------------------------------------------------------------------------
# tech_tree.as_dict() contract
# ---------------------------------------------------------------------------


def test_tech_tree_as_dict_structure():
    d = TECH_TREE.as_dict()
    for tech_id, entry in d.items():
        assert isinstance(tech_id, str)
        assert "cost" in entry
        assert "speed_multiplier" in entry
        assert entry["speed_multiplier"] > 1.0


# ---------------------------------------------------------------------------
# Migration scaffolding
# ---------------------------------------------------------------------------


def test_migrate_no_op_when_already_at_target():
    data = {"schema_version": "1", "production": {}}
    result = _migrate(data, _BALANCE_MIGRATIONS, _CURRENT_BALANCE_VERSION)
    assert result["schema_version"] == "1"


def test_migrate_applies_registered_function():
    migrations = {("1", "2"): lambda d: {**d, "new_field": "added"}}
    data = {"schema_version": "1"}
    result = _migrate(data, migrations, "2")
    assert result["schema_version"] == "2"
    assert result["new_field"] == "added"


# ---------------------------------------------------------------------------
# Integration: systems and archetypes actually use config values
# ---------------------------------------------------------------------------


def test_production_system_uses_config(tmp_path):
    """ProductionSystem output must match BALANCE.production math."""
    from engine.ecs import World
    from engine.rng import SystemRNG
    from game.archetypes import create_star_system, create_planet
    from game.systems import ProductionSystem

    world = World()
    pid = uuid.uuid4()
    system = create_star_system(world, "Sol", 0.0, 0.0)
    planet = create_planet(
        world, "Earth", system, resources={}, population=100,
        owner_id=pid, owner_name="Alice"
    )

    rng = SystemRNG("test-game", 1, "Production")
    ProductionSystem().update(world, rng)

    from game.components import Resources
    res = planet.get(Resources)
    expected_production = 100 * 1.0 * BALANCE.production.base_rate
    assert res.amounts.get("minerals", 0) == pytest.approx(
        expected_production * BALANCE.production.mineral_split
    )
    assert res.amounts.get("energy", 0) == pytest.approx(
        expected_production * BALANCE.production.energy_split
    )
    assert res.amounts.get("food", 0) == pytest.approx(
        expected_production * BALANCE.production.food_split
    )


def test_create_fleet_uses_config_default_speed():
    """create_fleet() with no explicit speed argument uses ARCHETYPES.fleet.speed."""
    from engine.ecs import World
    from game.archetypes import create_star_system, create_fleet
    from game.components import FleetStats

    world = World()
    pid = uuid.uuid4()
    system = create_star_system(world, "Sol", 0.0, 0.0)
    fleet = create_fleet(world, "F1", pid, "Alice", system)

    assert fleet.get(FleetStats).speed == pytest.approx(ARCHETYPES.fleet.speed)
    assert fleet.get(FleetStats).capacity == pytest.approx(ARCHETYPES.fleet.capacity)
    assert fleet.get(FleetStats).condition == pytest.approx(ARCHETYPES.fleet.condition)


def test_colonize_uses_config_population():
    """ColonizePlanetAction seeds population from ARCHETYPES.planet config."""
    from engine.ecs import World
    from game.archetypes import create_star_system, create_fleet, create_planet
    from game.actions import ColonizePlanetAction
    from game.components import PopulationStats

    world = World()
    pid = uuid.uuid4()
    system = create_star_system(world, "Sol", 0.0, 0.0)
    fleet = create_fleet(world, "F1", pid, "Alice", system)
    planet = create_planet(world, "P1", system, resources={})

    action = ColonizePlanetAction(
        _player_id=pid, fleet_id=fleet.id, planet_id=planet.id
    )
    action.execute(world)

    pop = planet.get(PopulationStats)
    assert pop.size == ARCHETYPES.planet.colonize_population
    assert pop.growth_rate == pytest.approx(ARCHETYPES.planet.colonize_growth_rate)
    assert pop.morale == pytest.approx(ARCHETYPES.planet.colonize_morale)


def test_monkeypatch_balance_changes_production_output(monkeypatch):
    """Overriding BALANCE in game.systems changes ProductionSystem output."""
    import game.systems as systems_mod
    from game.config import BalanceConfig, ProductionConfig, VisibilityConfig
    from engine.ecs import World
    from engine.rng import SystemRNG
    from game.archetypes import create_star_system, create_planet
    from game.components import Resources

    custom_balance = BalanceConfig(
        schema_version="1",
        production=ProductionConfig(
            base_rate=1.0,         # 10× the default
            mineral_split=0.5,
            energy_split=0.3,
            food_split=0.2,
            min_growth=1,
        ),
        visibility=VisibilityConfig(observation_range=10.0),
    )
    monkeypatch.setattr(systems_mod, "BALANCE", custom_balance)

    world = World()
    pid = uuid.uuid4()
    system = create_star_system(world, "Sol", 0.0, 0.0)
    planet = create_planet(
        world, "Earth", system, resources={}, population=100,
        owner_id=pid, owner_name="Alice"
    )

    from game.systems import ProductionSystem
    rng = SystemRNG("test-game", 1, "Production")
    ProductionSystem().update(world, rng)

    res = planet.get(Resources)
    # With base_rate=1.0 and mineral_split=0.5: minerals = 100 * 1.0 * 1.0 * 0.5 = 50
    assert res.amounts.get("minerals", 0) == pytest.approx(50.0)
