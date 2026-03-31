"""Tests for game archetype factory functions."""

from __future__ import annotations

import uuid

import pytest

from engine.components import ChildComponent, ContainerComponent
from engine.ecs import World
from engine.names import NameComponent
from game.archetypes import create_fleet, create_planet, create_star_system
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    Resources,
    VisibilityComponent,
)


@pytest.fixture
def world() -> World:
    return World()


class TestCreateStarSystem:
    def test_has_all_components(self, world: World):
        sys = create_star_system(world, "Sol", 10.0, 20.0)
        assert sys.has(NameComponent)
        assert sys.has(Position)
        assert sys.has(ContainerComponent)
        assert sys.has(Resources)
        assert sys.has(VisibilityComponent)

    def test_position_values(self, world: World):
        sys = create_star_system(world, "Sol", 10.0, 20.0)
        pos = sys.get(Position)
        assert pos.x == 10.0
        assert pos.y == 20.0
        assert pos.parent_system_id is None

    def test_name(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        assert sys.get(NameComponent).name == "Sol"

    def test_base_resources(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0, base_resources={"minerals": 50.0})
        assert sys.get(Resources).amounts == {"minerals": 50.0}


class TestCreatePlanet:
    def test_is_child_of_system(self, world: World):
        sys = create_star_system(world, "Sol", 10.0, 20.0)
        planet = create_planet(world, "Earth", sys)
        container = sys.get(ContainerComponent)
        assert planet.id in container.children
        assert planet.get(ChildComponent).parent_id == sys.id

    def test_inherits_parent_position(self, world: World):
        sys = create_star_system(world, "Sol", 10.0, 20.0)
        planet = create_planet(world, "Earth", sys)
        pos = planet.get(Position)
        assert pos.x == 10.0
        assert pos.y == 20.0
        assert pos.parent_system_id == sys.id

    def test_without_owner(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        planet = create_planet(world, "Mars", sys)
        assert not planet.has(Owner)

    def test_with_owner(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        planet = create_planet(world, "Earth", sys, owner_id=pid, owner_name="Alice")
        assert planet.has(Owner)
        assert planet.get(Owner).player_id == pid
        assert planet.get(Owner).player_name == "Alice"

    def test_without_population(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        planet = create_planet(world, "Mars", sys)
        assert not planet.has(PopulationStats)

    def test_with_population(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        planet = create_planet(world, "Earth", sys, population=100)
        assert planet.has(PopulationStats)
        assert planet.get(PopulationStats).size == 100


class TestCreateFleet:
    def test_has_all_components(self, world: World):
        sys = create_star_system(world, "Sol", 10.0, 20.0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        assert fleet.has(NameComponent)
        assert fleet.has(Position)
        assert fleet.has(ChildComponent)
        assert fleet.has(Owner)
        assert fleet.has(FleetStats)
        assert fleet.has(Resources)
        assert fleet.has(VisibilityComponent)

    def test_position_matches_parent(self, world: World):
        sys = create_star_system(world, "Sol", 10.0, 20.0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        pos = fleet.get(Position)
        assert pos.x == 10.0
        assert pos.y == 20.0
        assert pos.parent_system_id == sys.id

    def test_owner(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        assert fleet.get(Owner).player_id == pid
        assert fleet.get(Owner).player_name == "Alice"

    def test_fleet_stats(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys, speed=7.0)
        stats = fleet.get(FleetStats)
        assert stats.speed == 7.0
        assert stats.condition == 100.0

    def test_cargo(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(
            world, "Fleet1", pid, "Alice", sys, cargo={"minerals": 10.0}
        )
        assert fleet.get(Resources).amounts == {"minerals": 10.0}

    def test_is_child_of_system(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        container = sys.get(ContainerComponent)
        assert fleet.id in container.children
