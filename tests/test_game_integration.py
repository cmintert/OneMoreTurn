"""Integration tests for the full game loop via TurnManager."""

from __future__ import annotations

import uuid

import pytest

from engine.ecs import World
from engine.events import EventBus
from engine.rng import SystemRNG
from engine.turn import TurnManager
from game.actions import ColonizePlanetAction, HarvestResourcesAction, MoveFleetAction
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    Resources,
    VisibilityComponent,
)
from game.registry import game_action_registry, game_component_registry, game_systems
from game.setup import setup_game
from persistence.db import GameDatabase
from persistence.serialization import serialize_world


def _setup(seed: str = "integration") -> tuple[World, dict[str, uuid.UUID], GameDatabase]:
    """Create a world, run setup, return (world, player_ids, db)."""
    world = World(event_bus=EventBus())
    rng = SystemRNG(game_id=seed, turn_number=0, system_name="setup")
    player_ids = setup_game(world, ["Alice", "Bob"], rng)
    db = GameDatabase(":memory:")
    db.init_schema()
    registry = game_component_registry()
    db.save_snapshot(seed, 0, world, registry)
    return world, player_ids, db


def _find_entity_by_name(world: World, name: str) -> uuid.UUID:
    from engine.names import NameComponent
    for ent in world.entities():
        if ent.has(NameComponent) and ent.get(NameComponent).name == name:
            return ent.id
    raise KeyError(f"Entity '{name}' not found")


class TestFullGameResolution:
    def test_ten_turn_game_resolves(self) -> None:
        """Run 10 turns with no actions — systems alone should run without errors."""
        world, pids, db = _setup("ten-turn")
        registry = game_component_registry()
        game_id = "ten-turn"

        for turn in range(10):
            tm = TurnManager(world, game_id, db, registry, systems=game_systems())
            result = tm.resolve_turn()
            assert result.turn_number == turn
            assert world.current_turn == turn + 1

        assert world.current_turn == 10

    def test_ten_turn_game_produces_events(self) -> None:
        """Production system should emit events every turn."""
        world, pids, db = _setup("events-check")
        registry = game_component_registry()
        game_id = "events-check"

        total_events = 0
        for turn in range(10):
            tm = TurnManager(world, game_id, db, registry, systems=game_systems())
            result = tm.resolve_turn()
            total_events += len(result.events)

        # At minimum, production events for 2 planets per turn
        assert total_events > 0

    def test_production_grows_resources(self) -> None:
        """After a few turns, owned planets should have more resources."""
        world, pids, db = _setup("production")
        registry = game_component_registry()
        game_id = "production"

        alice_id = pids["Alice"]
        # Get initial resources of Alice's planet
        initial_minerals = None
        for ent, owner, pop, res in world.query(Owner, PopulationStats, Resources):
            if owner.player_id == alice_id:
                initial_minerals = res.amounts.get("minerals", 0)
                break
        assert initial_minerals is not None

        for _ in range(3):
            tm = TurnManager(world, game_id, db, registry, systems=game_systems())
            tm.resolve_turn()

        # Check resources increased
        for ent, owner, pop, res in world.query(Owner, PopulationStats, Resources):
            if owner.player_id == alice_id:
                assert res.amounts.get("minerals", 0) > initial_minerals
                break

    def test_move_fleet_and_arrive(self) -> None:
        """Submit a MoveFleet action and resolve enough turns for arrival."""
        world, pids, db = _setup("move")
        registry = game_component_registry()
        game_id = "move"
        alice_id = pids["Alice"]

        fleet_id = _find_entity_by_name(world, "Alice_Fleet1")
        target_id = _find_entity_by_name(world, "Alpha")

        # Submit move order
        tm = TurnManager(world, game_id, db, registry, systems=game_systems())
        action = MoveFleetAction(
            _player_id=alice_id,
            _order_id=uuid.uuid4(),
            fleet_id=fleet_id,
            target_system_id=target_id,
        )
        tm.submit_order(action)
        result = tm.resolve_turn()

        # Fleet should now be moving
        fleet_ent = world.get_entity(fleet_id)
        fs = fleet_ent.get(FleetStats)
        assert fs.destination_system_id == target_id

        # Resolve more turns until arrival
        for _ in range(30):
            tm = TurnManager(world, game_id, db, registry, systems=game_systems())
            tm.resolve_turn()
            fs = world.get_entity(fleet_id).get(FleetStats)
            if fs.turns_remaining == 0:
                break

        # Fleet should have arrived
        fs = world.get_entity(fleet_id).get(FleetStats)
        assert fs.turns_remaining == 0

    def test_colonize_planet(self) -> None:
        """Move fleet to neutral system, then colonize a planet."""
        world, pids, db = _setup("colonize")
        registry = game_component_registry()
        game_id = "colonize"
        alice_id = pids["Alice"]

        fleet_id = _find_entity_by_name(world, "Alice_Fleet1")
        target_system_id = _find_entity_by_name(world, "Alpha")

        # Move fleet
        tm = TurnManager(world, game_id, db, registry, systems=game_systems())
        tm.submit_order(MoveFleetAction(
            _player_id=alice_id, _order_id=uuid.uuid4(),
            fleet_id=fleet_id, target_system_id=target_system_id,
        ))
        tm.resolve_turn()

        # Resolve until arrival
        for _ in range(30):
            tm = TurnManager(world, game_id, db, registry, systems=game_systems())
            tm.resolve_turn()
            if world.get_entity(fleet_id).get(FleetStats).turns_remaining == 0:
                break

        # Find a planet in Alpha system
        planet_id = _find_entity_by_name(world, "Alpha_1")

        # Colonize
        tm = TurnManager(world, game_id, db, registry, systems=game_systems())
        tm.submit_order(ColonizePlanetAction(
            _player_id=alice_id, _order_id=uuid.uuid4(),
            fleet_id=fleet_id, planet_id=planet_id,
        ))
        result = tm.resolve_turn()

        # Planet should now be owned
        planet = world.get_entity(planet_id)
        assert planet.has(Owner)
        assert planet.get(Owner).player_id == alice_id

    def test_production_skips_unowned_planets(self) -> None:
        """Unowned planets should not produce anything."""
        world, pids, db = _setup("skip-unowned")
        registry = game_component_registry()
        game_id = "skip-unowned"

        # Find a neutral planet
        neutral_planet_id = _find_entity_by_name(world, "Alpha_1")
        planet = world.get_entity(neutral_planet_id)
        initial_res = dict(planet.get(Resources).amounts)

        for _ in range(3):
            tm = TurnManager(world, game_id, db, registry, systems=game_systems())
            tm.resolve_turn()

        # Resources should not have changed (no owner = no production)
        planet = world.get_entity(neutral_planet_id)
        assert planet.get(Resources).amounts == initial_res


class TestDeterministicReplay:
    def test_replay_from_snapshot(self) -> None:
        """Replay a turn from a snapshot and verify identical results."""
        world, pids, db = _setup("replay")
        registry = game_component_registry()
        action_reg = game_action_registry()
        game_id = "replay"
        alice_id = pids["Alice"]

        fleet_id = _find_entity_by_name(world, "Alice_Fleet1")
        target_id = _find_entity_by_name(world, "Alpha")

        # Turn 0: move fleet
        tm = TurnManager(world, game_id, db, registry, systems=game_systems())
        move = MoveFleetAction(
            _player_id=alice_id, _order_id=uuid.uuid4(),
            fleet_id=fleet_id, target_system_id=target_id,
        )
        tm.submit_order(move)
        db.save_orders(game_id, 0, [move])
        result = tm.resolve_turn()

        # Capture post-turn-0 state
        snapshot_original = serialize_world(world, game_id)

        # Replay: load turn 0 snapshot, re-submit same orders, resolve
        world_replay = db.load_snapshot(game_id, 0, registry)
        saved_actions = db.load_orders(game_id, 0, action_reg)

        db_replay = GameDatabase(":memory:")
        db_replay.init_schema()
        tm_replay = TurnManager(world_replay, game_id, db_replay, registry, systems=game_systems())
        for a in saved_actions:
            tm_replay.submit_order(a)
        tm_replay.resolve_turn()

        snapshot_replay = serialize_world(world_replay, game_id)

        # Normalize children order in Container components for comparison
        for snap in (snapshot_original, snapshot_replay):
            for ent in snap["entities"]:
                for comp in ent["components"]:
                    if comp["component_type"] == "Container" and "children" in comp["data"]:
                        comp["data"]["children"] = sorted(comp["data"]["children"])

        assert snapshot_original["entities"] == snapshot_replay["entities"]
