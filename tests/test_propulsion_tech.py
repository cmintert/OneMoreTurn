"""Tests for Phase 5: propulsion tech tree and decorator-based registry."""

from __future__ import annotations

import uuid

import pytest

from engine.ecs import World
from engine.events import EventBus
from engine.rng import SystemRNG
from game.actions import StartResearchAction
from game.archetypes import create_civilization, create_fleet, create_star_system
from game.components import FleetStats, Owner, ResearchComponent
from game.registry import (
    _action_classes,
    _component_classes,
    _system_classes,
    game_action_registry,
    game_component_registry,
    game_systems,
)
from game.systems import PROPULSION_TECHS, ResearchSystem
from persistence.serialization import (
    deserialize_component,
    serialize_component,
)


def _rng(name: str = "test") -> SystemRNG:
    return SystemRNG("test-game", 0, name)


@pytest.fixture
def world() -> World:
    return World(event_bus=EventBus())


# ---------------------------------------------------------------------------
# Decorator registry
# ---------------------------------------------------------------------------


class TestDecoratorRegistry:
    def test_components_include_research(self):
        assert ResearchComponent in _component_classes

    def test_actions_include_start_research(self):
        assert StartResearchAction in _action_classes

    def test_systems_include_research(self):
        assert ResearchSystem in _system_classes

    def test_game_component_registry_has_research(self):
        reg = game_component_registry()
        assert reg.get("Research") is ResearchComponent

    def test_game_action_registry_has_start_research(self):
        reg = game_action_registry()
        assert reg.get("StartResearch") is StartResearchAction

    def test_game_systems_includes_research(self):
        systems = game_systems()
        names = [s.system_name() for s in systems]
        assert "Research" in names


# ---------------------------------------------------------------------------
# ResearchSystem
# ---------------------------------------------------------------------------


class TestResearchSystem:
    def test_research_advances_each_turn(self, world: World):
        sys = create_star_system(world, "Sol", 0, 0)
        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")
        research = civ.get(ResearchComponent)
        research.active_tech_id = "ion_drive"
        research.required_progress = 3.0

        ResearchSystem().update(world, _rng("Research"))

        assert research.progress == 1.0
        assert research.active_tech_id == "ion_drive"

    def test_research_completes_and_unlocks(self, world: World):
        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")
        research = civ.get(ResearchComponent)
        research.active_tech_id = "ion_drive"
        research.required_progress = 3.0
        research.progress = 2.0  # will reach 3.0 this turn

        ResearchSystem().update(world, _rng("Research"))

        assert "ion_drive" in research.unlocked_techs
        assert research.active_tech_id is None
        assert research.progress == 0.0

    def test_research_applies_speed_bonus(self, world: World):
        pid = uuid.uuid4()
        sys = create_star_system(world, "Sol", 0, 0)
        fleet = create_fleet(world, "Fleet1", pid, "Alice", sys, speed=5.0)
        civ = create_civilization(world, pid, "Alice")
        research = civ.get(ResearchComponent)
        research.active_tech_id = "ion_drive"
        research.required_progress = 1.0  # completes this turn

        ResearchSystem().update(world, _rng("Research"))

        assert fleet.get(FleetStats).speed == pytest.approx(5.0 * 1.5)

    def test_research_emits_tech_unlocked_event(self, world: World):
        captured: list = []
        world.event_bus.subscribe("TechUnlocked", captured.append)

        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")
        research = civ.get(ResearchComponent)
        research.active_tech_id = "ion_drive"
        research.required_progress = 1.0

        ResearchSystem().update(world, _rng("Research"))

        assert len(captured) == 1
        assert captured[0].effects["tech_id"] == "ion_drive"

    def test_idle_when_no_active_tech(self, world: World):
        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")

        ResearchSystem().update(world, _rng("Research"))

        research = civ.get(ResearchComponent)
        assert research.progress == 0.0
        assert research.unlocked_techs == []


# ---------------------------------------------------------------------------
# StartResearchAction
# ---------------------------------------------------------------------------


class TestStartResearchAction:
    def test_valid_start_research(self, world: World):
        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")

        action = StartResearchAction(
            _player_id=pid,
            _order_id=uuid.uuid4(),
            civ_entity_id=civ.id,
            tech_id="ion_drive",
        )
        result = action.validate(world)
        assert result.valid

    def test_execute_sets_active_tech(self, world: World):
        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")

        action = StartResearchAction(
            _player_id=pid,
            _order_id=uuid.uuid4(),
            civ_entity_id=civ.id,
            tech_id="ion_drive",
        )
        events = action.execute(world)

        research = civ.get(ResearchComponent)
        assert research.active_tech_id == "ion_drive"
        assert research.required_progress == 3.0
        assert research.progress == 0.0
        assert len(events) == 1
        assert events[0].what == "ResearchStarted"

    def test_wrong_owner_rejected(self, world: World):
        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")

        action = StartResearchAction(
            _player_id=uuid.uuid4(),  # different player
            _order_id=uuid.uuid4(),
            civ_entity_id=civ.id,
            tech_id="ion_drive",
        )
        result = action.validate(world)
        assert not result.valid
        assert any("not owned" in e for e in result.errors)

    def test_unknown_tech_rejected(self, world: World):
        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")

        action = StartResearchAction(
            _player_id=pid,
            _order_id=uuid.uuid4(),
            civ_entity_id=civ.id,
            tech_id="hyperdrive_9000",
        )
        result = action.validate(world)
        assert not result.valid
        assert any("Unknown" in e for e in result.errors)

    def test_already_unlocked_rejected(self, world: World):
        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")
        civ.get(ResearchComponent).unlocked_techs.append("ion_drive")

        action = StartResearchAction(
            _player_id=pid,
            _order_id=uuid.uuid4(),
            civ_entity_id=civ.id,
            tech_id="ion_drive",
        )
        result = action.validate(world)
        assert not result.valid
        assert any("already unlocked" in e for e in result.errors)

    def test_already_researching_rejected(self, world: World):
        pid = uuid.uuid4()
        civ = create_civilization(world, pid, "Alice")
        civ.get(ResearchComponent).active_tech_id = "warp_core"

        action = StartResearchAction(
            _player_id=pid,
            _order_id=uuid.uuid4(),
            civ_entity_id=civ.id,
            tech_id="ion_drive",
        )
        result = action.validate(world)
        assert not result.valid
        assert any("Already researching" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


class TestResearchRoundTrip:
    def test_serialize_deserialize_research_component(self):
        comp = ResearchComponent(
            active_tech_id="warp_core",
            progress=4.0,
            required_progress=8.0,
            unlocked_techs=["ion_drive"],
        )
        record = serialize_component(comp)
        registry = game_component_registry()
        restored = deserialize_component(record, registry)

        assert isinstance(restored, ResearchComponent)
        assert restored.active_tech_id == "warp_core"
        assert restored.progress == 4.0
        assert restored.required_progress == 8.0
        assert restored.unlocked_techs == ["ion_drive"]

    def test_serialize_empty_research_component(self):
        comp = ResearchComponent()
        record = serialize_component(comp)
        registry = game_component_registry()
        restored = deserialize_component(record, registry)

        assert isinstance(restored, ResearchComponent)
        assert restored.active_tech_id is None
        assert restored.unlocked_techs == []
