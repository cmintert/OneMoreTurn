"""Tests for World and Component serialization round-trips."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import pytest

from engine.components import ChildComponent, Component, ContainerComponent
from engine.ecs import SchemaError, World
from persistence.serialization import (
    ComponentRegistry,
    deserialize_component,
    deserialize_world,
    serialize_component,
    serialize_world,
)

from tests.conftest import (
    ComponentBuilder,
    HealthComponent,
    OwnerComponent,
    PoisonComponent,
    PositionComponent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_registry(*classes: type[Component]) -> ComponentRegistry:
    reg = ComponentRegistry()
    reg.register(*classes)
    return reg


def standard_registry() -> ComponentRegistry:
    return make_registry(
        HealthComponent,
        PoisonComponent,
        PositionComponent,
        OwnerComponent,
        ContainerComponent,
        ChildComponent,
    )


# ---------------------------------------------------------------------------
# ComponentRegistry
# ---------------------------------------------------------------------------


class TestComponentRegistry:
    def test_register_and_get(self):
        reg = ComponentRegistry()
        reg.register(HealthComponent)
        assert reg.get("Health") is HealthComponent

    def test_get_unknown_raises(self):
        reg = ComponentRegistry()
        with pytest.raises(KeyError, match="not registered"):
            reg.get("NonExistent")

    def test_register_multiple(self):
        reg = ComponentRegistry()
        reg.register(HealthComponent, PositionComponent)
        assert reg.get("Health") is HealthComponent
        assert reg.get("Position") is PositionComponent

    def test_all_returns_copy(self):
        reg = ComponentRegistry()
        reg.register(HealthComponent)
        result = reg.all()
        result["injected"] = HealthComponent  # mutating return value
        assert "injected" not in reg.all()  # original unaffected


# ---------------------------------------------------------------------------
# serialize_component
# ---------------------------------------------------------------------------


class TestSerializeComponent:
    def test_basic_int_fields(self):
        comp = HealthComponent(current=75, maximum=100)
        record = serialize_component(comp)
        assert record["component_type"] == "Health"
        assert record["component_version"] == "1.0.0"
        assert record["data"] == {"current": 75, "maximum": 100}

    def test_uuid_field_serialized_as_string(self):
        owner_id = uuid.uuid4()
        comp = OwnerComponent(owner_id=owner_id)
        record = serialize_component(comp)
        assert record["data"]["owner_id"] == str(owner_id)
        assert isinstance(record["data"]["owner_id"], str)

    def test_container_children_serialized_as_strings(self):
        child_id = uuid.uuid4()
        comp = ContainerComponent(children=[child_id])
        record = serialize_component(comp)
        assert record["data"]["children"] == [str(child_id)]

    def test_container_allowed_child_types_serialized_as_names(self):
        comp = ContainerComponent(allowed_child_types=[HealthComponent])
        record = serialize_component(comp)
        assert record["data"]["allowed_child_types"] == ["Health"]

    def test_child_parent_id_serialized_as_string(self):
        parent_id = uuid.uuid4()
        comp = ChildComponent(parent_id=parent_id)
        record = serialize_component(comp)
        assert record["data"]["parent_id"] == str(parent_id)

    def test_result_is_json_serializable(self):
        comp = OwnerComponent(owner_id=uuid.uuid4())
        record = serialize_component(comp)
        # Must not raise
        json.dumps(record)


# ---------------------------------------------------------------------------
# deserialize_component
# ---------------------------------------------------------------------------


class TestDeserializeComponent:
    def test_basic_int_fields(self):
        reg = make_registry(HealthComponent)
        record = {
            "component_type": "Health",
            "component_version": "1.0.0",
            "data": {"current": 60, "maximum": 100},
        }
        comp = deserialize_component(record, reg)
        assert isinstance(comp, HealthComponent)
        assert comp.current == 60
        assert comp.maximum == 100

    def test_uuid_field_reconstructed(self):
        reg = make_registry(OwnerComponent)
        owner_id = uuid.uuid4()
        record = {
            "component_type": "Owner",
            "component_version": "1.0.0",
            "data": {"owner_id": str(owner_id)},
        }
        comp = deserialize_component(record, reg)
        assert isinstance(comp, OwnerComponent)
        assert comp.owner_id == owner_id
        assert isinstance(comp.owner_id, uuid.UUID)

    def test_container_allowed_child_types_reconstructed(self):
        reg = make_registry(HealthComponent, ContainerComponent)
        record = {
            "component_type": "Container",
            "component_version": "1.0.0",
            "data": {
                "allowed_child_types": ["Health"],
                "max_capacity": None,
                "children": [],
            },
        }
        comp = deserialize_component(record, reg)
        assert isinstance(comp, ContainerComponent)
        assert comp.allowed_child_types == [HealthComponent]

    def test_container_children_cleared(self):
        """Children are always cleared on deserialization; hooks rebuild them."""
        reg = make_registry(ContainerComponent)
        child_id = uuid.uuid4()
        record = {
            "component_type": "Container",
            "component_version": "1.0.0",
            "data": {
                "allowed_child_types": [],
                "max_capacity": None,
                "children": [str(child_id)],
            },
        }
        comp = deserialize_component(record, reg)
        assert isinstance(comp, ContainerComponent)
        assert comp.children == []

    def test_unknown_component_type_raises(self):
        reg = make_registry(HealthComponent)
        record = {"component_type": "Unknown", "component_version": "1.0.0", "data": {}}
        with pytest.raises(KeyError, match="not registered"):
            deserialize_component(record, reg)


# ---------------------------------------------------------------------------
# serialize_world / deserialize_world round-trips
# ---------------------------------------------------------------------------


class TestWorldRoundTrip:
    def test_empty_world(self):
        world = World()
        reg = standard_registry()
        snapshot = serialize_world(world, game_id="g1")
        restored = deserialize_world(snapshot, reg)
        assert restored.entities() == []

    def test_entity_count_preserved(self):
        world = World()
        world.create_entity([HealthComponent()])
        world.create_entity([PositionComponent(x=3, y=7)])
        reg = standard_registry()
        snapshot = serialize_world(world, game_id="g1")
        restored = deserialize_world(snapshot, reg)
        assert len(restored.entities()) == 2

    def test_entity_ids_preserved(self):
        world = World()
        e1 = world.create_entity([HealthComponent()])
        e2 = world.create_entity([PositionComponent()])
        reg = standard_registry()
        snapshot = serialize_world(world, game_id="g1")
        restored = deserialize_world(snapshot, reg)
        ids = {e.id for e in restored.entities()}
        assert e1.id in ids
        assert e2.id in ids

    def test_component_data_preserved(self):
        world = World()
        world.create_entity([HealthComponent(current=42, maximum=99)])
        reg = standard_registry()
        snapshot = serialize_world(world, game_id="g1")
        restored = deserialize_world(snapshot, reg)
        entity = restored.entities()[0]
        health = entity.get(HealthComponent)
        assert health.current == 42
        assert health.maximum == 99

    def test_uuid_field_preserved(self):
        world = World()
        owner_id = uuid.uuid4()
        world.create_entity([OwnerComponent(owner_id=owner_id)])
        reg = standard_registry()
        snapshot = serialize_world(world, game_id="g1")
        restored = deserialize_world(snapshot, reg)
        entity = restored.entities()[0]
        comp = entity.get(OwnerComponent)
        assert comp.owner_id == owner_id
        assert isinstance(comp.owner_id, uuid.UUID)

    def test_current_turn_preserved(self):
        world = World()
        world.current_turn = 5
        reg = standard_registry()
        snapshot = serialize_world(world, game_id="g1")
        restored = deserialize_world(snapshot, reg)
        assert restored.current_turn == 5

    def test_multiple_components_per_entity(self):
        world = World()
        world.create_entity([
            HealthComponent(current=50, maximum=100),
            PoisonComponent(damage_per_turn=10),
        ])
        reg = standard_registry()
        snapshot = serialize_world(world, game_id="g1")
        restored = deserialize_world(snapshot, reg)
        entity = restored.entities()[0]
        assert entity.has(HealthComponent, PoisonComponent)
        assert entity.get(PoisonComponent).damage_per_turn == 10

    def test_parent_child_relationship_preserved(self):
        world = World()
        parent = world.create_entity([ContainerComponent()])
        child = world.create_entity([
            HealthComponent(),
            ChildComponent(parent_id=parent.id),
        ])
        reg = standard_registry()
        snapshot = serialize_world(world, game_id="g1")
        restored = deserialize_world(snapshot, reg)

        restored_parent = restored.get_entity(parent.id)
        restored_child = restored.get_entity(child.id)

        container = restored_parent.get(ContainerComponent)
        assert restored_child.id in container.children

        child_comp = restored_child.get(ChildComponent)
        assert child_comp.parent_id == parent.id

    def test_world_query_works_after_restore(self):
        world = World()
        world.create_entity([HealthComponent(), PositionComponent(x=1, y=2)])
        world.create_entity([HealthComponent(current=50)])
        reg = standard_registry()
        snapshot = serialize_world(world, game_id="g1")
        restored = deserialize_world(snapshot, reg)

        results = restored.query(HealthComponent, PositionComponent)
        assert len(results) == 1
        _, health, pos = results[0]
        assert pos.x == 1

    def test_dependency_validation_on_deserialize(self):
        """A malformed snapshot missing a dependency raises SchemaError on load."""
        reg = standard_registry()
        # PoisonComponent requires HealthComponent
        world = World()
        world.create_entity([HealthComponent(), PoisonComponent()])
        snapshot = serialize_world(world, game_id="g1")

        # Corrupt: remove HealthComponent from the entity record
        for entity_record in snapshot["entities"]:
            entity_record["components"] = [
                c for c in entity_record["components"] if c["component_type"] != "Health"
            ]

        with pytest.raises(SchemaError):
            deserialize_world(snapshot, reg)

    def test_deterministic_serialization(self):
        """Same world serialized twice produces identical JSON."""
        world = World()
        owner_id = uuid.uuid4()
        world.create_entity([HealthComponent(current=80), OwnerComponent(owner_id=owner_id)])
        world.create_entity([PositionComponent(x=3, y=4)])

        reg = standard_registry()
        snap1 = json.dumps(serialize_world(world, game_id="g1"), sort_keys=True)
        snap2 = json.dumps(serialize_world(world, game_id="g1"), sort_keys=True)
        assert snap1 == snap2

    def test_snapshot_format_version_field(self):
        world = World()
        snapshot = serialize_world(world, game_id="g1", format_version="1.0.0")
        assert snapshot["format_version"] == "1.0.0"

    def test_game_id_in_snapshot(self):
        world = World()
        snapshot = serialize_world(world, game_id="my-game-42")
        assert snapshot["game_id"] == "my-game-42"
