"""Game components for the OneMoreTurn space 4X game."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from engine.components import Component


@dataclass
class Position(Component):
    """Location in 2D space with optional parent star system reference.

    Tracks both absolute coordinates for distance calculations and a
    parent_system_id foreign key so queries can group entities by system
    without a containment walk.
    """

    x: float = 0.0
    y: float = 0.0
    parent_system_id: uuid.UUID | None = None

    @classmethod
    def component_name(cls) -> str:
        """Registry key used by serialization to identify this component type."""
        return "Position"

    @classmethod
    def version(cls) -> str:
        """Schema version; increment when field names or types change."""
        return "1.0.0"


@dataclass
class Owner(Component):
    """Marks an entity as owned by a player.

    Used by systems and actions to enforce ownership rules and filter
    per-player visibility. player_name is denormalised here so summaries
    can display it without an extra registry lookup.
    """

    player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    player_name: str = ""

    @classmethod
    def component_name(cls) -> str:
        """Registry key used by serialization to identify this component type."""
        return "Owner"

    @classmethod
    def version(cls) -> str:
        """Schema version; increment when field names or types change."""
        return "1.0.0"


@dataclass
class Resources(Component):
    """Resource stockpile with a named-type dict and a shared capacity ceiling.

    Using a dict keyed on resource type (e.g. 'minerals', 'energy', 'food')
    means new resource types can be added in game/systems.py without schema
    changes to this component.
    """

    amounts: dict[str, float] = field(default_factory=dict)
    capacity: float = 100.0

    @classmethod
    def component_name(cls) -> str:
        """Registry key used by serialization to identify this component type."""
        return "Resources"

    @classmethod
    def version(cls) -> str:
        """Schema version; increment when field names or types change."""
        return "1.0.0"

    @classmethod
    def constraints(cls) -> dict[str, dict[str, Any]]:
        """Numeric bounds enforced by the base validate() loop.

        Returns:
            dict: Mapping of field name to constraint rules.
        """
        return {"capacity": {"min": 0}}

    def total(self) -> float:
        """Sum of all stored resource amounts across all types.

        Used to check whether the stockpile is at or over capacity before
        adding more resources.

        Returns:
            float: Total units currently stored.
        """
        return sum(self.amounts.values())

    def validate(self) -> list[str]:
        """Check that total stockpile does not exceed capacity.

        Extends base constraint validation with a cross-field check: the
        sum of all resource types must not exceed capacity.

        Returns:
            list[str]: Validation error messages; empty if valid.
        """
        errors = super().validate()
        if self.total() > self.capacity:
            errors.append(
                f"Resources.total ({self.total()}) exceeds capacity ({self.capacity})"
            )
        return errors


@dataclass
class FleetStats(Component):
    """Movement and cargo state for a fleet entity.

    destination_* fields are set by MoveFleetAction and consumed by
    MovementSystem each turn until turns_remaining reaches zero.  Keeping
    them on the component (rather than in a separate 'order' component)
    lets the persistence layer snapshot in-flight movement transparently.
    """

    speed: float = 1.0
    capacity: float = 50.0
    condition: float = 100.0
    destination_x: float | None = None
    destination_y: float | None = None
    destination_system_id: uuid.UUID | None = None
    turns_remaining: int = 0

    @classmethod
    def component_name(cls) -> str:
        """Registry key used by serialization to identify this component type."""
        return "FleetStats"

    @classmethod
    def version(cls) -> str:
        """Schema version; increment when field names or types change."""
        return "1.0.0"

    @classmethod
    def constraints(cls) -> dict[str, dict[str, Any]]:
        """Numeric bounds enforced by the base validate() loop.

        Returns:
            dict: Mapping of field name to constraint rules.
        """
        return {"speed": {"min": 0}, "condition": {"min": 0, "max": 100}}


@dataclass
class PopulationStats(Component):
    """Population metrics for a colonized planet.

    Added when ColonizePlanetAction succeeds.  ProductionSystem reads these
    values each turn to calculate resource output and apply population growth.
    morale acts as a productivity multiplier clamped to [0, 2].
    """

    size: int = 0
    growth_rate: float = 0.05
    morale: float = 1.0

    @classmethod
    def component_name(cls) -> str:
        """Registry key used by serialization to identify this component type."""
        return "PopulationStats"

    @classmethod
    def version(cls) -> str:
        """Schema version; increment when field names or types change."""
        return "1.0.0"

    @classmethod
    def constraints(cls) -> dict[str, dict[str, Any]]:
        """Numeric bounds enforced by the base validate() loop.

        Returns:
            dict: Mapping of field name to constraint rules.
        """
        return {"size": {"min": 0}, "morale": {"min": 0, "max": 2}}


@dataclass
class VisibilityComponent(Component):
    """Fog-of-war state for a single entity.

    visible_to holds the set of player UUIDs that can see this entity *this
    turn* (recomputed by VisibilitySystem each POST_TURN phase).
    revealed_to is the cumulative set — once seen, always on the map.
    generate_turn_summary() reads both sets to filter what each player sees.
    """

    visible_to: set[uuid.UUID] = field(default_factory=set)
    revealed_to: set[uuid.UUID] = field(default_factory=set)

    @classmethod
    def component_name(cls) -> str:
        """Registry key used by serialization to identify this component type."""
        return "Visibility"

    @classmethod
    def version(cls) -> str:
        """Schema version; increment when field names or types change."""
        return "1.0.0"
