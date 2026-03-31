"""Tests for Component base class and schema protocol."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from engine.components import Component
from tests.conftest import (
    ComponentBuilder,
    HealthComponent,
    StubOwnerComponent,
    PoisonComponent,
    StubPositionComponent,
)


class TestComponentABC:
    def test_cannot_instantiate_without_component_name(self):
        @dataclass
        class Incomplete(Component):
            @classmethod
            def version(cls) -> str:
                return "1.0.0"

        with pytest.raises(TypeError):
            Incomplete()

    def test_cannot_instantiate_without_version(self):
        @dataclass
        class Incomplete(Component):
            @classmethod
            def component_name(cls) -> str:
                return "Incomplete"

        with pytest.raises(TypeError):
            Incomplete()


class TestSchemaProtocol:
    def test_component_name(self):
        assert HealthComponent.component_name() == "Health"
        assert PoisonComponent.component_name() == "Poison"

    def test_version(self):
        assert HealthComponent.version() == "1.0.0"

    def test_dependencies_default_empty(self):
        assert StubPositionComponent.dependencies() == []

    def test_dependencies_declared(self):
        assert PoisonComponent.dependencies() == [HealthComponent]

    def test_constraints_default_empty(self):
        assert StubPositionComponent.constraints() == {}

    def test_constraints_declared(self):
        c = HealthComponent.constraints()
        assert "current" in c
        assert c["current"]["min"] == 0

    def test_properties_schema_introspection(self):
        schema = StubPositionComponent.properties_schema()
        assert "x" in schema
        assert "y" in schema

    def test_properties_schema_health(self):
        schema = HealthComponent.properties_schema()
        assert "current" in schema
        assert "maximum" in schema


class TestValidation:
    def test_valid_component(self):
        h = ComponentBuilder.health(current=50, maximum=100)
        assert h.validate() == []

    def test_min_constraint_violated(self):
        h = ComponentBuilder.health(current=-1, maximum=100)
        errors = h.validate()
        assert len(errors) == 1
        assert "min" in errors[0]

    def test_max_constraint(self):
        @dataclass
        class Bounded(Component):
            value: int = 5

            @classmethod
            def component_name(cls) -> str:
                return "Bounded"

            @classmethod
            def version(cls) -> str:
                return "1.0.0"

            @classmethod
            def constraints(cls) -> dict:
                return {"value": {"min": 0, "max": 10}}

        assert Bounded(value=5).validate() == []
        errors = Bounded(value=11).validate()
        assert len(errors) == 1
        assert "max" in errors[0]

    def test_multiple_constraint_violations(self):
        h = ComponentBuilder.health(current=-1, maximum=0)
        errors = h.validate()
        assert len(errors) == 2


class TestHooks:
    def test_on_add_validation_default_empty(self):
        assert HealthComponent.on_add_validation(None, None, None) == []  # type: ignore[arg-type]

    def test_on_remove_validation_default_empty(self):
        assert HealthComponent.on_remove_validation(None, None) == []  # type: ignore[arg-type]
