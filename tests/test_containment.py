"""Tests for ContainerComponent and ChildComponent."""

from __future__ import annotations

import uuid

import pytest

from engine.components import ChildComponent, ContainerComponent
from engine.ecs import SchemaError, World
from tests.conftest import ComponentBuilder, HealthComponent, PositionComponent


@pytest.fixture
def world() -> World:
    return World()


def _make_container(
    world: World,
    allowed: list[type] | None = None,
    max_capacity: int | None = None,
) -> uuid.UUID:
    """Create a container entity and return its ID."""
    container_comp = ContainerComponent(
        allowed_child_types=allowed or [],
        max_capacity=max_capacity,
    )
    entity = world.create_entity([container_comp])
    return entity.id


def _make_child(world: World, parent_id: uuid.UUID, components: list | None = None) -> uuid.UUID:
    """Create a child entity and return its ID."""
    child_comp = ChildComponent(parent_id=parent_id)
    all_components = (components or []) + [child_comp]
    entity = world.create_entity(all_components)
    return entity.id


class TestAddChild:
    def test_add_child_to_container(self, world: World):
        parent_id = _make_container(world)
        child_id = _make_child(world, parent_id)

        parent = world.get_entity(parent_id)
        container = parent.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)
        assert child_id in container.children

        child = world.get_entity(child_id)
        child_comp = child.get(ChildComponent)
        assert isinstance(child_comp, ChildComponent)
        assert child_comp.parent_id == parent_id

    def test_child_without_container_parent_raises(self, world: World):
        # Create a non-container entity
        parent = world.create_entity([ComponentBuilder.health()])
        with pytest.raises(SchemaError, match="ContainerComponent"):
            _make_child(world, parent.id)

    def test_child_with_nonexistent_parent_raises(self, world: World):
        fake_id = uuid.uuid4()
        with pytest.raises(SchemaError, match="does not exist"):
            _make_child(world, fake_id)


class TestCapacity:
    def test_capacity_enforced(self, world: World):
        parent_id = _make_container(world, max_capacity=2)
        _make_child(world, parent_id)
        _make_child(world, parent_id)
        with pytest.raises(SchemaError, match="capacity"):
            _make_child(world, parent_id)

    def test_unlimited_capacity(self, world: World):
        parent_id = _make_container(world, max_capacity=None)
        for _ in range(10):
            _make_child(world, parent_id)
        parent = world.get_entity(parent_id)
        container = parent.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)
        assert len(container.children) == 10


class TestAllowedTypes:
    def test_allowed_types_enforced(self, world: World):
        parent_id = _make_container(world, allowed=[HealthComponent])
        # Child without Health — should fail
        with pytest.raises(SchemaError, match="allowed types"):
            _make_child(world, parent_id, [ComponentBuilder.position()])

    def test_allowed_types_pass(self, world: World):
        parent_id = _make_container(world, allowed=[HealthComponent])
        child_id = _make_child(world, parent_id, [ComponentBuilder.health()])
        parent = world.get_entity(parent_id)
        container = parent.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)
        assert child_id in container.children

    def test_empty_allowed_types_permits_all(self, world: World):
        parent_id = _make_container(world, allowed=[])
        child_id = _make_child(world, parent_id, [ComponentBuilder.position()])
        parent = world.get_entity(parent_id)
        container = parent.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)
        assert child_id in container.children


class TestNavigation:
    def test_parent_child_navigation(self, world: World):
        parent_id = _make_container(world)
        child_id = _make_child(world, parent_id)

        # Navigate child -> parent
        child = world.get_entity(child_id)
        child_comp = child.get(ChildComponent)
        assert isinstance(child_comp, ChildComponent)
        parent = world.get_entity(child_comp.parent_id)
        assert parent.id == parent_id

        # Navigate parent -> children
        container = parent.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)
        assert child_id in container.children

    def test_nested_containment(self, world: World):
        """Entity can be both container and child (fleet in system containing ships)."""
        system_id = _make_container(world)
        # Fleet is child of system AND container for ships
        fleet = world.create_entity([
            ChildComponent(parent_id=system_id),
            ContainerComponent(max_capacity=5),
        ])
        ship_id = _make_child(world, fleet.id)

        # Verify nesting
        system_entity = world.get_entity(system_id)
        sys_container = system_entity.get(ContainerComponent)
        assert isinstance(sys_container, ContainerComponent)
        assert fleet.id in sys_container.children

        fleet_container = fleet.get(ContainerComponent)
        assert isinstance(fleet_container, ContainerComponent)
        assert ship_id in fleet_container.children


class TestRemoval:
    def test_remove_child_component_updates_parent(self, world: World):
        parent_id = _make_container(world)
        child_id = _make_child(world, parent_id)

        world.remove_component(child_id, ChildComponent)

        parent = world.get_entity(parent_id)
        container = parent.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)
        assert child_id not in container.children

    def test_destroy_child_updates_parent(self, world: World):
        parent_id = _make_container(world)
        child_id = _make_child(world, parent_id)

        world.destroy_entity(child_id)

        parent = world.get_entity(parent_id)
        container = parent.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)
        assert child_id not in container.children

    def test_destroy_container_with_children_raises(self, world: World):
        parent_id = _make_container(world)
        _make_child(world, parent_id)

        with pytest.raises(SchemaError, match="children"):
            world.destroy_entity(parent_id)

    def test_destroy_empty_container_ok(self, world: World):
        parent_id = _make_container(world)
        world.destroy_entity(parent_id)
        with pytest.raises(KeyError):
            world.get_entity(parent_id)
