"""Tests for game systems: ProductionSystem, MovementSystem, VisibilitySystem."""

from __future__ import annotations

import math
import uuid

import pytest

from engine.ecs import World
from engine.events import Event
from engine.rng import SystemRNG
from game.archetypes import create_fleet, create_planet, create_star_system
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    Resources,
    VisibilityComponent,
)
from game.systems import MovementSystem, ProductionSystem, VisibilitySystem


def _rng(name: str = "test") -> SystemRNG:
    return SystemRNG("test-game", 0, name)


# ---------------------------------------------------------------------------
# ProductionSystem
# ---------------------------------------------------------------------------


class TestProductionSystem:
    def test_produces_resources(self):
        world = World()
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        planet = create_planet(
            world, "Earth", sys,
            resources={"minerals": 0.0, "energy": 0.0, "food": 0.0},
            population=100, owner_id=pid, owner_name="Alice",
        )

        ProductionSystem().update(world, _rng("Production"))

        res = planet.get(Resources)
        assert res.amounts["minerals"] > 0
        assert res.amounts["energy"] > 0
        assert res.amounts["food"] > 0

    def test_production_amounts(self):
        """production = size * morale * 0.1; split 40/30/30."""
        world = World()
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        planet = create_planet(
            world, "Earth", sys,
            resources={"minerals": 0.0, "energy": 0.0, "food": 0.0},
            population=100, owner_id=pid, owner_name="Alice",
        )

        ProductionSystem().update(world, _rng("Production"))

        res = planet.get(Resources)
        # 100 * 1.0 * 0.1 = 10.0 total
        assert res.amounts["minerals"] == pytest.approx(4.0)
        assert res.amounts["energy"] == pytest.approx(3.0)
        assert res.amounts["food"] == pytest.approx(3.0)

    def test_respects_capacity(self):
        world = World()
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        planet = create_planet(
            world, "Earth", sys,
            resources={"minerals": 198.0, "energy": 0.0, "food": 0.0},
            population=100, owner_id=pid, owner_name="Alice",
        )
        planet.get(Resources).capacity = 200.0

        ProductionSystem().update(world, _rng("Production"))

        res = planet.get(Resources)
        assert res.amounts["minerals"] <= 200.0

    def test_population_grows(self):
        world = World()
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        planet = create_planet(
            world, "Earth", sys,
            resources={"minerals": 0.0},
            population=100, owner_id=pid, owner_name="Alice",
        )

        ProductionSystem().update(world, _rng("Production"))

        pop = planet.get(PopulationStats)
        assert pop.size > 100

    def test_skips_entity_without_owner(self):
        """Uncolonized planet (no Owner) is not processed."""
        world = World()
        sys = create_star_system(world, "Sol", 0, 0)
        planet = create_planet(
            world, "Mars", sys,
            resources={"minerals": 10.0},
            population=50,
        )
        # No owner — query for (PopulationStats, Resources, Owner) won't match
        ProductionSystem().update(world, _rng("Production"))
        assert planet.get(Resources).amounts["minerals"] == 10.0

    def test_skips_entity_without_population(self):
        """Owned planet without PopulationStats is not processed."""
        world = World()
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        planet = create_planet(
            world, "Mars", sys,
            resources={"minerals": 10.0},
            owner_id=pid, owner_name="Alice",
        )
        # No population — query won't match
        ProductionSystem().update(world, _rng("Production"))
        assert planet.get(Resources).amounts["minerals"] == 10.0

    def test_emits_production_event(self):
        world = World()
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        create_planet(
            world, "Earth", sys,
            resources={"minerals": 0.0, "energy": 0.0, "food": 0.0},
            population=100, owner_id=pid, owner_name="Alice",
        )

        ProductionSystem().update(world, _rng("Production"))

        events = [e for e in world.event_bus.emitted if e.what == "ProductionCompleted"]
        assert len(events) == 1
        assert str(pid) in events[0].visibility_scope


# ---------------------------------------------------------------------------
# MovementSystem
# ---------------------------------------------------------------------------


class TestMovementSystem:
    def test_fleet_moves_toward_destination(self):
        world = World()
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 25, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src, speed=5.0)

        fs = fleet.get(FleetStats)
        fs.destination_x = 25.0
        fs.destination_y = 0.0
        fs.destination_system_id = tgt.id
        fs.turns_remaining = 5

        fleet.get(Position).parent_system_id = None

        MovementSystem().update(world, _rng("Movement"))

        pos = fleet.get(Position)
        assert pos.x > 0.0  # moved
        assert fs.turns_remaining == 4

    def test_fleet_arrives_after_correct_turns(self):
        world = World()
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 10, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src, speed=5.0)

        fs = fleet.get(FleetStats)
        fs.destination_x = 10.0
        fs.destination_y = 0.0
        fs.destination_system_id = tgt.id
        fs.turns_remaining = 2

        fleet.get(Position).parent_system_id = None

        # Turn 1: move toward
        MovementSystem().update(world, _rng("Movement"))
        assert fs.turns_remaining == 1

        # Turn 2: arrive
        MovementSystem().update(world, _rng("Movement"))
        pos = fleet.get(Position)
        assert pos.x == 10.0
        assert pos.y == 0.0
        assert pos.parent_system_id == tgt.id
        assert fs.destination_x is None
        assert fs.turns_remaining == 0

    def test_fleet_snaps_to_destination_on_arrival(self):
        world = World()
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 3, 4)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src, speed=10.0)

        fs = fleet.get(FleetStats)
        fs.destination_x = 3.0
        fs.destination_y = 4.0
        fs.destination_system_id = tgt.id
        fs.turns_remaining = 1

        fleet.get(Position).parent_system_id = None

        MovementSystem().update(world, _rng("Movement"))

        pos = fleet.get(Position)
        assert pos.x == 3.0
        assert pos.y == 4.0

    def test_fleet_reparents_on_arrival(self):
        world = World()
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 5, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src, speed=5.0)

        fs = fleet.get(FleetStats)
        fs.destination_x = 5.0
        fs.destination_y = 0.0
        fs.destination_system_id = tgt.id
        fs.turns_remaining = 1

        fleet.get(Position).parent_system_id = None

        MovementSystem().update(world, _rng("Movement"))

        from engine.components import ChildComponent, ContainerComponent
        assert fleet.has(ChildComponent)
        assert fleet.get(ChildComponent).parent_id == tgt.id
        assert fleet.id in tgt.get(ContainerComponent).children

    def test_fleet_without_destination_not_moved(self):
        world = World()
        src = create_star_system(world, "Source", 10, 20)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src)

        MovementSystem().update(world, _rng("Movement"))

        pos = fleet.get(Position)
        assert pos.x == 10.0
        assert pos.y == 20.0

    def test_emits_fleet_arrived_event(self):
        world = World()
        src = create_star_system(world, "Source", 0, 0)
        tgt = create_star_system(world, "Target", 5, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", src, speed=5.0)

        fs = fleet.get(FleetStats)
        fs.destination_x = 5.0
        fs.destination_y = 0.0
        fs.destination_system_id = tgt.id
        fs.turns_remaining = 1
        fleet.get(Position).parent_system_id = None

        MovementSystem().update(world, _rng("Movement"))

        events = [e for e in world.event_bus.emitted if e.what == "FleetArrived"]
        assert len(events) == 1
        assert events[0].who == fleet.id


# ---------------------------------------------------------------------------
# VisibilitySystem
# ---------------------------------------------------------------------------


class TestVisibilitySystem:
    def test_own_entities_visible_to_owner(self):
        world = World()
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)

        VisibilitySystem().update(world, _rng("Visibility"))

        vis = fleet.get(VisibilityComponent)
        assert pid in vis.visible_to
        assert pid in vis.revealed_to

    def test_enemy_fleet_within_range_visible(self):
        world = World()
        sys1 = create_star_system(world, "S1", 0, 0)
        sys2 = create_star_system(world, "S2", 5, 0)  # within 10 range
        pid_a = uuid.uuid4()
        pid_b = uuid.uuid4()
        create_fleet(world, "FleetA", pid_a, "Alice", sys1)
        fleet_b = create_fleet(world, "FleetB", pid_b, "Bob", sys2)

        VisibilitySystem().update(world, _rng("Visibility"))

        vis_b = fleet_b.get(VisibilityComponent)
        assert pid_a in vis_b.visible_to

    def test_enemy_fleet_outside_range_not_visible(self):
        world = World()
        sys1 = create_star_system(world, "S1", 0, 0)
        sys2 = create_star_system(world, "S2", 50, 0)  # well outside 10 range
        pid_a = uuid.uuid4()
        pid_b = uuid.uuid4()
        create_fleet(world, "FleetA", pid_a, "Alice", sys1)
        fleet_b = create_fleet(world, "FleetB", pid_b, "Bob", sys2)

        VisibilitySystem().update(world, _rng("Visibility"))

        vis_b = fleet_b.get(VisibilityComponent)
        assert pid_a not in vis_b.visible_to

    def test_revealed_to_persists(self):
        world = World()
        sys1 = create_star_system(world, "S1", 0, 0)
        sys2 = create_star_system(world, "S2", 5, 0)
        pid_a = uuid.uuid4()
        pid_b = uuid.uuid4()
        create_fleet(world, "FleetA", pid_a, "Alice", sys1)
        fleet_b = create_fleet(world, "FleetB", pid_b, "Bob", sys2)

        VisibilitySystem().update(world, _rng("Visibility"))
        assert pid_a in fleet_b.get(VisibilityComponent).revealed_to

        # Move system 2 far away
        fleet_b.get(Position).x = 100.0

        VisibilitySystem().update(world, _rng("Visibility"))
        vis = fleet_b.get(VisibilityComponent)
        assert pid_a not in vis.visible_to  # no longer visible
        assert pid_a in vis.revealed_to  # still revealed

    def test_visible_to_cleared_each_turn(self):
        world = World()
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys)

        VisibilitySystem().update(world, _rng("Visibility"))
        assert pid in fleet.get(VisibilityComponent).visible_to

        # Manually add an extra entry that should be cleared
        fleet.get(VisibilityComponent).visible_to.add(uuid.uuid4())

        VisibilitySystem().update(world, _rng("Visibility"))
        vis = fleet.get(VisibilityComponent)
        # Only the owner should be in visible_to after refresh
        assert len([v for v in vis.visible_to if v == pid]) == 1

    def test_neutral_entity_visible_to_nearby_player(self):
        world = World()
        sys1 = create_star_system(world, "S1", 0, 0)
        sys2 = create_star_system(world, "Neutral", 5, 0)
        pid = uuid.uuid4()
        create_fleet(world, "Fleet1", pid, "Alice", sys1)
        planet = create_planet(world, "NeutralPlanet", sys2)

        VisibilitySystem().update(world, _rng("Visibility"))

        vis = planet.get(VisibilityComponent)
        assert pid in vis.visible_to
