"""Game components for the OneMoreTurn space 4X game."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from engine.components import Component


@dataclass
class Position(Component):
    """Location in 2D space with optional parent star system reference."""

    x: float = 0.0
    y: float = 0.0
    parent_system_id: uuid.UUID | None = None

    @classmethod
    def component_name(cls) -> str:
        return "Position"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"


@dataclass
class Owner(Component):
    """Marks an entity as owned by a player."""

    player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    player_name: str = ""

    @classmethod
    def component_name(cls) -> str:
        return "Owner"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"


@dataclass
class Resources(Component):
    """Resource stockpile. Generic dict-based for extensibility."""

    amounts: dict[str, float] = field(default_factory=dict)
    capacity: float = 100.0

    @classmethod
    def component_name(cls) -> str:
        return "Resources"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"

    @classmethod
    def constraints(cls) -> dict[str, dict[str, Any]]:
        return {"capacity": {"min": 0}}

    def total(self) -> float:
        return sum(self.amounts.values())

    def validate(self) -> list[str]:
        errors = super().validate()
        if self.total() > self.capacity:
            errors.append(
                f"Resources.total ({self.total()}) exceeds capacity ({self.capacity})"
            )
        return errors


@dataclass
class FleetStats(Component):
    """Fleet movement and state. Drives multi-turn travel."""

    speed: float = 1.0
    capacity: float = 50.0
    condition: float = 100.0
    destination_x: float | None = None
    destination_y: float | None = None
    destination_system_id: uuid.UUID | None = None
    turns_remaining: int = 0

    @classmethod
    def component_name(cls) -> str:
        return "FleetStats"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"

    @classmethod
    def constraints(cls) -> dict[str, dict[str, Any]]:
        return {"speed": {"min": 0}, "condition": {"min": 0, "max": 100}}


@dataclass
class PopulationStats(Component):
    """Population on a colonized planet."""

    size: int = 0
    growth_rate: float = 0.05
    morale: float = 1.0

    @classmethod
    def component_name(cls) -> str:
        return "PopulationStats"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"

    @classmethod
    def constraints(cls) -> dict[str, dict[str, Any]]:
        return {"size": {"min": 0}, "morale": {"min": 0, "max": 2}}


@dataclass
class VisibilityComponent(Component):
    """Fog of war tracking per entity."""

    visible_to: set[uuid.UUID] = field(default_factory=set)
    revealed_to: set[uuid.UUID] = field(default_factory=set)

    @classmethod
    def component_name(cls) -> str:
        return "Visibility"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"
