"""Tests for game.setup — map generation and starting positions."""

from __future__ import annotations

import uuid

import pytest

from engine.components import ChildComponent, ContainerComponent
from engine.ecs import World
from engine.events import EventBus
from engine.rng import SystemRNG
from game.archetypes import create_star_system
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    Resources,
)
from game.setup import setup_game


@pytest.fixture
def world() -> World:
    return World(event_bus=EventBus())


@pytest.fixture
def rng() -> SystemRNG:
    return SystemRNG(game_id="test-game", turn_number=0, system_name="setup")


class TestSetupGame:
    def test_returns_player_ids(self, world: World, rng: SystemRNG) -> None:
        result = setup_game(world, ["Alice", "Bob"], rng)
        assert set(result.keys()) == {"Alice", "Bob"}
        assert all(isinstance(v, uuid.UUID) for v in result.values())

    def test_creates_home_systems(self, world: World, rng: SystemRNG) -> None:
        setup_game(world, ["Alice", "Bob"], rng)
        systems = world.query(ContainerComponent, Position)
        home = [
            (ent, cc, pos) for ent, cc, pos in systems
            if pos.x in (10.0, 90.0) and pos.y == 50.0
        ]
        assert len(home) == 2

    def test_creates_home_planets(self, world: World, rng: SystemRNG) -> None:
        ids = setup_game(world, ["Alice", "Bob"], rng)
        owned = world.query(Owner, PopulationStats, Resources)
        assert len(owned) == 2
        for ent, owner, pop, res in owned:
            assert owner.player_id in ids.values()
            assert pop.size == 100

    def test_creates_home_fleets(self, world: World, rng: SystemRNG) -> None:
        ids = setup_game(world, ["Alice", "Bob"], rng)
        fleets = world.query(FleetStats, Owner)
        assert len(fleets) == 2
        for ent, fs, owner in fleets:
            assert owner.player_id in ids.values()
            assert fs.speed == 5.0

    def test_creates_neutral_systems(self, world: World, rng: SystemRNG) -> None:
        setup_game(world, ["Alice", "Bob"], rng)
        all_systems = world.query(ContainerComponent, Position)
        # 2 home + 5 neutral = 7
        assert len(all_systems) == 7

    def test_neutral_systems_have_planets(self, world: World, rng: SystemRNG) -> None:
        setup_game(world, ["Alice", "Bob"], rng)
        unowned_planets = [
            ent for ent, res, child in world.query(Resources, ChildComponent)
            if not ent.has(Owner)
        ]
        # 5 systems, each 1-2 planets → 5 to 10
        assert 5 <= len(unowned_planets) <= 10

    def test_deterministic(self, world: World) -> None:
        rng1 = SystemRNG(game_id="seed-A", turn_number=0, system_name="setup")
        rng2 = SystemRNG(game_id="seed-A", turn_number=0, system_name="setup")
        w2 = World(event_bus=EventBus())
        ids1 = setup_game(world, ["Alice", "Bob"], rng1)
        ids2 = setup_game(w2, ["Alice", "Bob"], rng2)
        assert ids1 == ids2
