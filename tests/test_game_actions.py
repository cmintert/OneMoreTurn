"""Tests for game actions: MoveFleet, ColonizePlanet, HarvestResources."""

from __future__ import annotations

import math
import uuid

import pytest

from engine.components import ChildComponent, ContainerComponent
from engine.ecs import World
from game.actions import (
    ColonizePlanetAction,
    HarvestResourcesAction,
    MoveFleetAction,
)
from game.archetypes import create_fleet, create_planet, create_star_system
from game.components import FleetStats, Owner, PopulationStats, Position, Resources


@pytest.fixture
def world() -> World:
    return World()


# ---------------------------------------------------------------------------
# MoveFleetAction
# ---------------------------------------------------------------------------


class TestMoveFleetAction:
    def test_valid_move(self, world: World):
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 25, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src)

        action = MoveFleetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, target_system_id=tgt.id,
        )
        result = action.validate(world)
        assert result.valid

    def test_wrong_owner_rejected(self, world: World):
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 25, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src)

        action = MoveFleetAction(
            _player_id=uuid.uuid4(), _order_id=uuid.uuid4(),
            fleet_id=fleet.id, target_system_id=tgt.id,
        )
        result = action.validate(world)
        assert not result.valid
        assert any("not owned" in e for e in result.errors)

    def test_nonexistent_system_rejected(self, world: World):
        src = create_star_system(world, "Source", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src)

        action = MoveFleetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, target_system_id=uuid.uuid4(),
        )
        result = action.validate(world)
        assert not result.valid
        assert any("not found" in e for e in result.errors)

    def test_already_moving_rejected(self, world: World):
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 25, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src)
        fleet.get(FleetStats).turns_remaining = 3

        action = MoveFleetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, target_system_id=tgt.id,
        )
        result = action.validate(world)
        assert not result.valid
        assert any("already moving" in e for e in result.errors)

    def test_execute_sets_destination(self, world: World):
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 25, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src, speed=5.0)

        action = MoveFleetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, target_system_id=tgt.id,
        )
        events = action.execute(world)

        fs = fleet.get(FleetStats)
        assert fs.destination_x == 25.0
        assert fs.destination_y == 0.0
        assert fs.destination_system_id == tgt.id
        assert fs.turns_remaining == math.ceil(25.0 / 5.0)
        assert fleet.get(Position).parent_system_id is None
        assert len(events) == 1
        assert events[0].what == "FleetDeparted"

    def test_execute_removes_child_component(self, world: World):
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 25, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src)

        action = MoveFleetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, target_system_id=tgt.id,
        )
        action.execute(world)

        assert not fleet.has(ChildComponent)
        assert fleet.id not in src.get(ContainerComponent).children


# ---------------------------------------------------------------------------
# ColonizePlanetAction
# ---------------------------------------------------------------------------


class TestColonizePlanetAction:
    def test_valid_colonize(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        planet = create_planet(world, "Mars", sys)

        action = ColonizePlanetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, planet_id=planet.id,
        )
        result = action.validate(world)
        assert result.valid

    def test_already_owned_rejected(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        planet = create_planet(
            world, "Earth", sys, owner_id=uuid.uuid4(), owner_name="Bob"
        )

        action = ColonizePlanetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, planet_id=planet.id,
        )
        result = action.validate(world)
        assert not result.valid
        assert any("already colonized" in e for e in result.errors)

    def test_different_system_rejected(self, world: World):
        sys1 = create_star_system(world, "S1", 0, 0)
        sys2 = create_star_system(world, "S2", 50, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys1)
        planet = create_planet(world, "Mars", sys2)

        action = ColonizePlanetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, planet_id=planet.id,
        )
        result = action.validate(world)
        assert not result.valid
        assert any("not at same" in e for e in result.errors)

    def test_execute_adds_owner_and_population(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        planet = create_planet(world, "Mars", sys)

        action = ColonizePlanetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, planet_id=planet.id,
        )
        events = action.execute(world)

        assert planet.has(Owner)
        assert planet.get(Owner).player_id == pid
        assert planet.get(Owner).player_name == "Alice"
        assert planet.has(PopulationStats)
        assert planet.get(PopulationStats).size == 10
        assert len(events) == 1
        assert events[0].what == "PlanetColonized"

    def test_conflict_key(self):
        pid = uuid.uuid4()
        planet_id = uuid.uuid4()
        action = ColonizePlanetAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=uuid.uuid4(), planet_id=planet_id,
        )
        assert action.conflict_key() == f"colonize:{planet_id}"


# ---------------------------------------------------------------------------
# HarvestResourcesAction
# ---------------------------------------------------------------------------


class TestHarvestResourcesAction:
    def test_valid_harvest(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        planet = create_planet(
            world, "Earth", sys,
            resources={"minerals": 50.0}, owner_id=pid, owner_name="Alice",
        )

        action = HarvestResourcesAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, planet_id=planet.id,
            resource_type="minerals", amount=10.0,
        )
        result = action.validate(world)
        assert result.valid

    def test_unowned_planet_rejected(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        planet = create_planet(world, "Mars", sys, resources={"minerals": 50.0})

        action = HarvestResourcesAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, planet_id=planet.id,
            resource_type="minerals", amount=10.0,
        )
        result = action.validate(world)
        assert not result.valid

    def test_not_enough_resources_rejected(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        planet = create_planet(
            world, "Earth", sys,
            resources={"minerals": 5.0}, owner_id=pid, owner_name="Alice",
        )

        action = HarvestResourcesAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, planet_id=planet.id,
            resource_type="minerals", amount=10.0,
        )
        result = action.validate(world)
        assert not result.valid

    def test_fleet_capacity_exceeded_rejected(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(
            world, "Fleet1", pid, "Alice", sys,
            cargo={"minerals": 45.0},
        )
        planet = create_planet(
            world, "Earth", sys,
            resources={"minerals": 50.0}, owner_id=pid, owner_name="Alice",
        )

        action = HarvestResourcesAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, planet_id=planet.id,
            resource_type="minerals", amount=10.0,
        )
        result = action.validate(world)
        assert not result.valid
        assert any("capacity" in e for e in result.errors)

    def test_execute_transfers_resources(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)
        planet = create_planet(
            world, "Earth", sys,
            resources={"minerals": 50.0}, owner_id=pid, owner_name="Alice",
        )

        action = HarvestResourcesAction(
            _player_id=pid, _order_id=uuid.uuid4(),
            fleet_id=fleet.id, planet_id=planet.id,
            resource_type="minerals", amount=20.0,
        )
        events = action.execute(world)

        assert planet.get(Resources).amounts["minerals"] == 30.0
        assert fleet.get(Resources).amounts["minerals"] == 20.0
        assert len(events) == 1
        assert events[0].what == "ResourcesHarvested"
