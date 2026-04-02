"""Tests for the NameComponent and NameResolver."""

from __future__ import annotations

import uuid

import pytest

from engine.ecs import SchemaError, World
from engine.names import NameComponent
from cli.names import NameResolver


class TestNameComponent:
    def test_valid_name(self):
        comp = NameComponent(name="Alpha Squadron")
        assert comp.validate() == []

    def test_empty_name_fails_validation(self):
        comp = NameComponent(name="")
        errors = comp.validate()
        assert len(errors) > 0
        assert "non-empty" in errors[0].lower()

    def test_whitespace_only_fails_validation(self):
        comp = NameComponent(name="   ")
        errors = comp.validate()
        assert len(errors) > 0

    def test_component_name(self):
        assert NameComponent.component_name() == "Name"

    def test_version(self):
        assert NameComponent.version() == "1.0.0"


class TestNameResolver:
    def _make_world(self):
        world = World()
        e1 = world.create_entity([NameComponent(name="Alice")])
        e2 = world.create_entity([NameComponent(name="Bob")])
        e3 = world.create_entity([])  # no name
        return world, e1, e2, e3

    def test_resolve_existing_name(self):
        world, e1, _, _ = self._make_world()
        resolver = NameResolver(world)
        assert resolver.resolve("Alice") == e1.id

    def test_resolve_nonexistent_raises_key_error(self):
        world, _, _, _ = self._make_world()
        resolver = NameResolver(world)
        with pytest.raises(KeyError, match="Charlie"):
            resolver.resolve("Charlie")

    def test_resolve_ambiguous_raises_value_error(self):
        world = World()
        world.create_entity([NameComponent(name="Duplicate")])
        world.create_entity([NameComponent(name="Duplicate")])
        resolver = NameResolver(world)
        with pytest.raises(ValueError, match="Ambiguous"):
            resolver.resolve("Duplicate")

    def test_get_name(self):
        world, e1, _, _ = self._make_world()
        resolver = NameResolver(world)
        assert resolver.get_name(e1.id) == "Alice"

    def test_get_name_no_component_raises(self):
        world, _, _, e3 = self._make_world()
        resolver = NameResolver(world)
        with pytest.raises(KeyError):
            resolver.get_name(e3.id)

    def test_resolve_many(self):
        world, e1, e2, _ = self._make_world()
        resolver = NameResolver(world)
        ids = resolver.resolve_many(["Alice", "Bob"])
        assert ids == [e1.id, e2.id]

    def test_get_name_nonexistent_entity_raises(self):
        world, _, _, _ = self._make_world()
        resolver = NameResolver(world)
        with pytest.raises(KeyError):
            resolver.get_name(uuid.uuid4())
