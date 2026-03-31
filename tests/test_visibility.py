"""Tests for game.summary — per-player fog-of-war summaries."""

from __future__ import annotations

import uuid

import pytest

from engine.ecs import World
from engine.events import Event, EventBus
from engine.names import NameComponent
from game.archetypes import create_fleet, create_star_system, create_planet
from game.components import Owner, Position, VisibilityComponent
from game.summary import generate_turn_summary, _event_visible_to_player


@pytest.fixture
def world() -> World:
    return World(event_bus=EventBus())


@pytest.fixture
def alice_id() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def bob_id() -> uuid.UUID:
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


class TestGenerateTurnSummary:
    def test_shows_own_planets(self, world: World, alice_id: uuid.UUID) -> None:
        sys = create_star_system(world, "Home", 10, 50)
        create_planet(world, "Alice_Prime", sys, {"minerals": 50.0}, 100, alice_id, "Alice")
        summary = generate_turn_summary(world, alice_id, [])
        assert "Alice_Prime" in summary
        assert "pop=100" in summary

    def test_shows_own_fleets(self, world: World, alice_id: uuid.UUID) -> None:
        sys = create_star_system(world, "Home", 10, 50)
        create_fleet(world, "Alice_F1", alice_id, "Alice", sys)
        summary = generate_turn_summary(world, alice_id, [])
        assert "Alice_F1" in summary
        assert "speed=5.0" in summary

    def test_hides_other_player_entities(self, world: World, alice_id: uuid.UUID, bob_id: uuid.UUID) -> None:
        sys = create_star_system(world, "Home", 10, 50)
        create_fleet(world, "Bob_F1", bob_id, "Bob", sys)
        summary = generate_turn_summary(world, alice_id, [])
        # Bob's fleet should not appear in "Your Fleets"
        assert "Bob_F1" not in summary.split("-- Visible Entities --")[0]

    def test_visible_entities_section(self, world: World, alice_id: uuid.UUID, bob_id: uuid.UUID) -> None:
        sys = create_star_system(world, "Neutral", 50, 50)
        fleet = create_fleet(world, "Bob_F1", bob_id, "Bob", sys)
        # Make visible to Alice
        world.remove_component(fleet.id, VisibilityComponent)
        world.add_component(fleet.id, VisibilityComponent(visible_to={alice_id, bob_id}, revealed_to=set()))
        summary = generate_turn_summary(world, alice_id, [])
        visible_section = summary.split("-- Visible Entities --")[1]
        assert "Bob_F1" in visible_section

    def test_stale_entities_marked(self, world: World, alice_id: uuid.UUID, bob_id: uuid.UUID) -> None:
        sys = create_star_system(world, "Far", 90, 90)
        fleet = create_fleet(world, "Bob_F1", bob_id, "Bob", sys)
        world.remove_component(fleet.id, VisibilityComponent)
        world.add_component(fleet.id, VisibilityComponent(visible_to=set(), revealed_to={alice_id}))
        summary = generate_turn_summary(world, alice_id, [])
        assert "[stale]" in summary

    def test_no_own_entities_in_visible_section(self, world: World, alice_id: uuid.UUID) -> None:
        sys = create_star_system(world, "Home", 10, 50)
        fleet = create_fleet(world, "Alice_F1", alice_id, "Alice", sys)
        summary = generate_turn_summary(world, alice_id, [])
        visible_section = summary.split("-- Visible Entities --")[1].split("-- Events --")[0]
        assert "Alice_F1" not in visible_section


class TestEventVisibility:
    def test_event_with_visibility_scope_includes_player(self, world: World, alice_id: uuid.UUID) -> None:
        ev = Event(who="system", what="Test", when=1, why="test", effects={},
                   visibility_scope=[str(alice_id)])
        assert _event_visible_to_player(ev, alice_id, world) is True

    def test_event_with_visibility_scope_excludes_player(self, world: World, alice_id: uuid.UUID, bob_id: uuid.UUID) -> None:
        ev = Event(who="system", what="Test", when=1, why="test", effects={},
                   visibility_scope=[str(bob_id)])
        assert _event_visible_to_player(ev, alice_id, world) is False

    def test_event_entity_owner_matches(self, world: World, alice_id: uuid.UUID) -> None:
        sys = create_star_system(world, "S", 10, 10)
        fleet = create_fleet(world, "Alice_F", alice_id, "Alice", sys)
        ev = Event(who=str(fleet.id), what="Moved", when=1, why="move", effects={})
        assert _event_visible_to_player(ev, alice_id, world) is True

    def test_event_entity_owner_no_match(self, world: World, alice_id: uuid.UUID, bob_id: uuid.UUID) -> None:
        sys = create_star_system(world, "S", 10, 10)
        fleet = create_fleet(world, "Bob_F", bob_id, "Bob", sys)
        ev = Event(who=str(fleet.id), what="Moved", when=1, why="move", effects={})
        assert _event_visible_to_player(ev, alice_id, world) is False

    def test_event_in_summary(self, world: World, alice_id: uuid.UUID) -> None:
        events = [
            Event(who="system", what="ProductionCompleted", when=1, why="production",
                  effects={"minerals": 5.0}, visibility_scope=[str(alice_id)])
        ]
        summary = generate_turn_summary(world, alice_id, events)
        assert "ProductionCompleted" in summary
