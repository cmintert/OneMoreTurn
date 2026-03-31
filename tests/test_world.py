"""Tests for World class."""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from engine.ecs import SchemaError, World
from engine.events import EventBus
from tests.conftest import (
    ComponentBuilder,
    HealthComponent,
    StubOwnerComponent,
    PoisonComponent,
    StubPositionComponent,
)


@pytest.fixture
def world() -> World:
    return World()


# ---------------------------------------------------------------------------
# Entity creation
# ---------------------------------------------------------------------------


class TestCreateEntity:
    def test_create_empty(self, world: World):
        e = world.create_entity()
        assert e.alive
        assert world.get_entity(e.id) is e

    def test_create_with_components(self, world: World):
        e = world.create_entity([
            ComponentBuilder.health(),
            ComponentBuilder.position(),
        ])
        assert e.has(HealthComponent, StubPositionComponent)

    def test_create_with_specific_id(self, world: World):
        eid = uuid.uuid4()
        e = world.create_entity(entity_id=eid)
        assert e.id == eid

    def test_create_validates_dependencies(self, world: World):
        with pytest.raises(SchemaError, match="Health"):
            world.create_entity([ComponentBuilder.poison()])

    def test_create_with_deps_satisfied(self, world: World):
        e = world.create_entity([
            ComponentBuilder.health(),
            ComponentBuilder.poison(),
        ])
        assert e.has(HealthComponent, PoisonComponent)

    def test_create_validates_constraints(self, world: World):
        with pytest.raises(SchemaError):
            world.create_entity([ComponentBuilder.health(current=-1)])

    def test_create_emits_event(self, world: World):
        e = world.create_entity([ComponentBuilder.health()])
        events = world.event_bus.emitted
        assert len(events) == 1
        assert events[0].what == "EntityCreated"
        assert events[0].who == e.id


# ---------------------------------------------------------------------------
# Entity retrieval and destruction
# ---------------------------------------------------------------------------


class TestEntityLifecycle:
    def test_get_entity(self, world: World):
        e = world.create_entity()
        assert world.get_entity(e.id) is e

    def test_get_missing_raises(self, world: World):
        with pytest.raises(KeyError):
            world.get_entity(uuid.uuid4())

    def test_destroy_entity(self, world: World):
        e = world.create_entity([ComponentBuilder.health()])
        world.destroy_entity(e.id)
        with pytest.raises(KeyError):
            world.get_entity(e.id)

    def test_destroy_emits_event(self, world: World):
        e = world.create_entity()
        world.event_bus.clear()
        world.destroy_entity(e.id)
        events = world.event_bus.emitted
        assert len(events) == 1
        assert events[0].what == "EntityDestroyed"

    def test_destroy_removes_from_query(self, world: World):
        e = world.create_entity([ComponentBuilder.health()])
        world.destroy_entity(e.id)
        assert world.query(HealthComponent) == []

    def test_entities_returns_living_only(self, world: World):
        e1 = world.create_entity()
        e2 = world.create_entity()
        world.destroy_entity(e1.id)
        living = world.entities()
        assert len(living) == 1
        assert living[0].id == e2.id


# ---------------------------------------------------------------------------
# Component add/remove
# ---------------------------------------------------------------------------


class TestAddComponent:
    def test_add_component(self, world: World):
        e = world.create_entity()
        world.add_component(e.id, ComponentBuilder.health())
        assert e.has(HealthComponent)

    def test_add_validates_dependencies(self, world: World):
        e = world.create_entity()
        with pytest.raises(SchemaError, match="Health"):
            world.add_component(e.id, ComponentBuilder.poison())

    def test_add_validates_constraints(self, world: World):
        e = world.create_entity()
        with pytest.raises(SchemaError):
            world.add_component(e.id, ComponentBuilder.health(current=-5))

    def test_add_duplicate_type_raises(self, world: World):
        e = world.create_entity([ComponentBuilder.health()])
        with pytest.raises(SchemaError, match="already has"):
            world.add_component(e.id, ComponentBuilder.health(current=50))

    def test_add_emits_event(self, world: World):
        e = world.create_entity()
        world.event_bus.clear()
        world.add_component(e.id, ComponentBuilder.health())
        events = world.event_bus.emitted
        assert len(events) == 1
        assert events[0].what == "ComponentAdded"
        assert events[0].effects["component_type"] == "Health"


class TestRemoveComponent:
    def test_remove_component(self, world: World):
        e = world.create_entity([ComponentBuilder.health()])
        world.remove_component(e.id, HealthComponent)
        assert not e.has(HealthComponent)

    def test_remove_with_dependents_raises(self, world: World):
        e = world.create_entity([
            ComponentBuilder.health(),
            ComponentBuilder.poison(),
        ])
        with pytest.raises(SchemaError, match="Poison depends on it"):
            world.remove_component(e.id, HealthComponent)

    def test_remove_missing_raises(self, world: World):
        e = world.create_entity()
        with pytest.raises(KeyError):
            world.remove_component(e.id, HealthComponent)

    def test_remove_emits_event(self, world: World):
        e = world.create_entity([ComponentBuilder.health()])
        world.event_bus.clear()
        world.remove_component(e.id, HealthComponent)
        events = world.event_bus.emitted
        assert len(events) == 1
        assert events[0].what == "ComponentRemoved"

    def test_remove_updates_query(self, world: World):
        e = world.create_entity([
            ComponentBuilder.health(),
            ComponentBuilder.position(),
        ])
        world.remove_component(e.id, HealthComponent)
        assert world.query(HealthComponent) == []
        assert len(world.query(StubPositionComponent)) == 1


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_single_type(self, world: World):
        world.create_entity([ComponentBuilder.health()])
        world.create_entity([ComponentBuilder.position()])
        results = world.query(HealthComponent)
        assert len(results) == 1
        entity, health = results[0]
        assert isinstance(health, HealthComponent)

    def test_query_multiple_types(self, world: World):
        world.create_entity([ComponentBuilder.health(), ComponentBuilder.position()])
        world.create_entity([ComponentBuilder.health()])
        world.create_entity([ComponentBuilder.position()])
        results = world.query(HealthComponent, StubPositionComponent)
        assert len(results) == 1

    def test_query_no_matches(self, world: World):
        world.create_entity([ComponentBuilder.position()])
        assert world.query(HealthComponent) == []

    def test_query_empty_args(self, world: World):
        world.create_entity([ComponentBuilder.health()])
        assert world.query() == []

    def test_query_returns_correct_components(self, world: World):
        world.create_entity([
            ComponentBuilder.health(current=42),
            ComponentBuilder.position(x=10, y=20),
        ])
        results = world.query(StubPositionComponent, HealthComponent)
        entity, pos, health = results[0]
        assert pos.x == 10
        assert health.current == 42

    def test_query_deterministic_order(self, world: World):
        ids = [uuid.uuid4() for _ in range(5)]
        for eid in ids:
            world.create_entity([ComponentBuilder.health()], entity_id=eid)
        results = world.query(HealthComponent)
        result_ids = [r[0].id for r in results]
        assert result_ids == sorted(result_ids)


# ---------------------------------------------------------------------------
# Event bus integration
# ---------------------------------------------------------------------------


class TestWorldEventBus:
    def test_custom_event_bus(self):
        bus = EventBus()
        world = World(event_bus=bus)
        assert world.event_bus is bus

    def test_default_event_bus(self):
        world = World()
        assert isinstance(world.event_bus, EventBus)

    def test_current_turn_in_events(self):
        world = World()
        world.current_turn = 5
        e = world.create_entity()
        assert world.event_bus.emitted[0].when == 5


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------


@given(
    num_entities=st.integers(min_value=0, max_value=20),
    include_health=st.lists(st.booleans(), min_size=20, max_size=20),
    include_position=st.lists(st.booleans(), min_size=20, max_size=20),
)
@settings(max_examples=30)
def test_hypothesis_query_correctness(
    num_entities: int,
    include_health: list[bool],
    include_position: list[bool],
):
    world = World()
    expected_both = 0

    for i in range(num_entities):
        components = []
        has_h = include_health[i]
        has_p = include_position[i]
        if has_h:
            components.append(HealthComponent(current=50, maximum=100))
        if has_p:
            components.append(StubPositionComponent(x=i, y=i))
        if has_h and has_p:
            expected_both += 1
        world.create_entity(components)

    results = world.query(HealthComponent, StubPositionComponent)
    assert len(results) == expected_both
