"""Shared test components, factories, and fixtures."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from engine.components import Component
from engine.events import EventBus


# ---------------------------------------------------------------------------
# Test components (Phase 1)
# ---------------------------------------------------------------------------


@dataclass
class HealthComponent(Component):
    current: int = 100
    maximum: int = 100

    @classmethod
    def component_name(cls) -> str:
        return "Health"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"

    @classmethod
    def constraints(cls) -> dict:
        return {"current": {"min": 0}, "maximum": {"min": 1}}


@dataclass
class PoisonComponent(Component):
    damage_per_turn: int = 5

    @classmethod
    def component_name(cls) -> str:
        return "Poison"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"

    @classmethod
    def dependencies(cls) -> list[type[Component]]:
        return [HealthComponent]


@dataclass
class StubPositionComponent(Component):
    x: int = 0
    y: int = 0

    @classmethod
    def component_name(cls) -> str:
        return "StubPosition"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"


@dataclass
class StubOwnerComponent(Component):
    owner_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def component_name(cls) -> str:
        return "StubOwner"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


class ComponentBuilder:
    @staticmethod
    def health(current: int = 100, maximum: int = 100) -> HealthComponent:
        return HealthComponent(current=current, maximum=maximum)

    @staticmethod
    def poison(damage_per_turn: int = 5) -> PoisonComponent:
        return PoisonComponent(damage_per_turn=damage_per_turn)

    @staticmethod
    def position(x: int = 0, y: int = 0) -> StubPositionComponent:
        return StubPositionComponent(x=x, y=y)

    @staticmethod
    def owner(owner_id: uuid.UUID | None = None) -> StubOwnerComponent:
        return StubOwnerComponent(owner_id=owner_id or uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()
