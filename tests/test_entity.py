"""Tests for Entity class."""

from __future__ import annotations

import uuid

import pytest

from engine.ecs import Entity
from tests.conftest import (
    ComponentBuilder,
    HealthComponent,
    StubPositionComponent,
)


class TestEntityCreation:
    def test_auto_uuid(self):
        e = Entity()
        assert isinstance(e.id, uuid.UUID)

    def test_provided_uuid(self):
        eid = uuid.uuid4()
        e = Entity(entity_id=eid)
        assert e.id == eid

    def test_alive_by_default(self):
        e = Entity()
        assert e.alive is True


class TestComponentBag:
    def test_has_component_after_add(self):
        e = Entity()
        e._add_component(ComponentBuilder.health())
        assert e.has(HealthComponent)

    def test_has_missing_component(self):
        e = Entity()
        assert e.has(HealthComponent) is False

    def test_has_multiple_components(self):
        e = Entity()
        e._add_component(ComponentBuilder.health())
        e._add_component(ComponentBuilder.position())
        assert e.has(HealthComponent, StubPositionComponent)

    def test_has_multiple_partial(self):
        e = Entity()
        e._add_component(ComponentBuilder.health())
        assert e.has(HealthComponent, StubPositionComponent) is False

    def test_get_component(self):
        e = Entity()
        h = ComponentBuilder.health(current=42)
        e._add_component(h)
        assert e.get(HealthComponent) is h
        assert e.get(HealthComponent).current == 42

    def test_get_missing_raises(self):
        e = Entity()
        with pytest.raises(KeyError):
            e.get(HealthComponent)

    def test_components_readonly(self):
        e = Entity()
        e._add_component(ComponentBuilder.health())
        view = e.components()
        with pytest.raises(TypeError):
            view[StubPositionComponent] = ComponentBuilder.position()  # type: ignore[index]


class TestLifecycle:
    def test_destroy(self):
        e = Entity()
        assert e.alive is True
        e.destroy()
        assert e.alive is False

    def test_remove_component(self):
        e = Entity()
        e._add_component(ComponentBuilder.health())
        removed = e._remove_component(HealthComponent)
        assert isinstance(removed, HealthComponent)
        assert e.has(HealthComponent) is False
