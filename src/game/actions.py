"""Game actions: MoveFleetAction, ColonizePlanetAction, HarvestResourcesAction."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from engine.actions import Action, ValidationResult
from engine.components import ChildComponent
from engine.events import Event
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    ResearchComponent,
    Resources,
)
from game.registry import action


def _check_fleet_ownership(fleet, player_id: uuid.UUID, errors: list[str]) -> None:
    """Append errors if the fleet is not owned by player_id."""
    if not fleet.has(Owner):
        errors.append("Fleet has no Owner")
    elif fleet.get(Owner).player_id != player_id:
        errors.append("Fleet not owned by player")


def _check_same_system(fleet, planet, errors: list[str]) -> None:
    """Append errors if fleet and planet are not in the same star system."""
    if not fleet.has(Position) or not planet.has(Position):
        errors.append("Missing Position component")
    elif fleet.get(Position).parent_system_id != planet.get(Position).parent_system_id:
        errors.append("Fleet and planet not at same star system")


@action
@dataclass
class MoveFleetAction(Action):
    """Order a fleet to move to a target star system.

    Sets the fleet's destination on FleetStats and calculates turns_remaining
    based on Euclidean distance / speed.  Movement is then executed
    incrementally by MovementSystem each turn until the fleet arrives.
    """

    _player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    fleet_id: uuid.UUID = field(default_factory=uuid.uuid4)
    target_system_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def action_type(cls) -> str:
        """Registry key identifying this action type for serialization."""
        return "MoveFleet"

    @property
    def player_id(self) -> uuid.UUID:
        """UUID of the player who issued this order."""
        return self._player_id

    @property
    def order_id(self) -> uuid.UUID:
        """Unique identifier for this order; used for replacement and tracking."""
        return self._order_id

    def validate(self, world) -> ValidationResult:
        """Check that the fleet exists, is owned by this player, and is not already moving.

        Also verifies that the target system exists and has a Position.

        Args:
            world: Current game world.

        Returns:
            ValidationResult: valid=True if all checks pass; errors otherwise.
        """
        errors: list[str] = []

        try:
            fleet = world.get_entity(self.fleet_id)
        except KeyError:
            return ValidationResult(valid=False, errors=["Fleet not found"])

        _check_fleet_ownership(fleet, self._player_id, errors)

        if not fleet.has(FleetStats):
            errors.append("Fleet has no FleetStats")
        elif fleet.get(FleetStats).turns_remaining > 0:
            errors.append("Fleet is already moving")

        try:
            target = world.get_entity(self.target_system_id)
        except KeyError:
            errors.append("Target system not found")
        else:
            if not target.has(Position):
                errors.append("Target system has no Position")

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def execute(self, world) -> list[Event]:
        """Set destination on FleetStats and detach fleet from its current system.

        Computes turns_remaining as ceil(distance / speed).  Removes the
        fleet's ChildComponent so it is no longer counted as being in the
        origin system while in transit.  Publishes a ``FleetDeparted`` event.

        Args:
            world: Current game world (mutated in-place).

        Returns:
            list[Event]: Single FleetDeparted event.
        """
        fleet = world.get_entity(self.fleet_id)
        target = world.get_entity(self.target_system_id)

        fleet_pos = fleet.get(Position)
        target_pos = target.get(Position)
        fleet_stats = fleet.get(FleetStats)

        dx = target_pos.x - fleet_pos.x
        dy = target_pos.y - fleet_pos.y
        distance = math.sqrt(dx * dx + dy * dy)

        fleet_stats.destination_x = target_pos.x
        fleet_stats.destination_y = target_pos.y
        fleet_stats.destination_system_id = self.target_system_id
        fleet_stats.turns_remaining = max(math.ceil(distance / fleet_stats.speed), 1)

        fleet_pos.parent_system_id = None

        if fleet.has(ChildComponent):
            world.remove_component(fleet.id, ChildComponent)

        return [
            Event(
                who=fleet.id,
                what="FleetDeparted",
                when=world.current_turn,
                why=str(self._order_id),
                effects={
                    "target_system": str(self.target_system_id),
                    "turns": fleet_stats.turns_remaining,
                },
                visibility_scope=[str(self._player_id)],
            )
        ]


@action
@dataclass
class ColonizePlanetAction(Action):
    """Colonize an unowned planet using a fleet at the same star system.

    Adds an Owner component to the planet and seeds it with an initial
    PopulationStats if none exists.  Multiple players racing to colonize
    the same planet are subject to conflict resolution via conflict_key().
    """

    _player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    fleet_id: uuid.UUID = field(default_factory=uuid.uuid4)
    planet_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def action_type(cls) -> str:
        """Registry key identifying this action type for serialization."""
        return "ColonizePlanet"

    @property
    def player_id(self) -> uuid.UUID:
        """UUID of the player who issued this order."""
        return self._player_id

    @property
    def order_id(self) -> uuid.UUID:
        """Unique identifier for this order; used for replacement and tracking."""
        return self._order_id

    def validate(self, world) -> ValidationResult:
        """Check that the fleet exists and is at the same system as the target planet.

        Also verifies that the planet is not already colonized.

        Args:
            world: Current game world.

        Returns:
            ValidationResult: valid=True if all checks pass; errors otherwise.
        """
        errors: list[str] = []

        try:
            fleet = world.get_entity(self.fleet_id)
        except KeyError:
            return ValidationResult(valid=False, errors=["Fleet not found"])

        _check_fleet_ownership(fleet, self._player_id, errors)

        try:
            planet = world.get_entity(self.planet_id)
        except KeyError:
            return ValidationResult(valid=False, errors=["Planet not found"])

        _check_same_system(fleet, planet, errors)

        if planet.has(Owner):
            errors.append("Planet already colonized")

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def execute(self, world) -> list[Event]:
        """Transfer ownership to the colonizing player and seed initial population.

        Adds Owner to the planet mirroring the fleet's owner, and adds a
        default PopulationStats if the planet doesn't already have one.
        Publishes a ``PlanetColonized`` event.

        Args:
            world: Current game world (mutated in-place).

        Returns:
            list[Event]: Single PlanetColonized event.
        """
        fleet = world.get_entity(self.fleet_id)
        planet = world.get_entity(self.planet_id)

        owner = fleet.get(Owner)
        world.add_component(
            planet.id,
            Owner(player_id=owner.player_id, player_name=owner.player_name),
        )
        if not planet.has(PopulationStats):
            world.add_component(
                planet.id,
                PopulationStats(size=10, growth_rate=0.05, morale=1.0),
            )

        return [
            Event(
                who=planet.id,
                what="PlanetColonized",
                when=world.current_turn,
                why=str(self._order_id),
                effects={
                    "colonized_by": str(owner.player_id),
                    "player_name": owner.player_name,
                },
                visibility_scope=[str(owner.player_id)],
            )
        ]

    def conflict_key(self) -> str | None:
        """Group all colonize orders targeting the same planet for conflict resolution.

        When multiple players issue ColonizePlanetAction for the same planet in
        the same turn, only one can win.  ActionSystem uses this key to identify
        the competing group and resolves it via seeded RNG.

        Returns:
            str: Conflict key scoped to this planet.
        """
        return f"colonize:{self.planet_id}"


@action
@dataclass
class HarvestResourcesAction(Action):
    """Transfer resources from an owned planet to a fleet at the same system.

    Validates that the planet has sufficient resources and the fleet has
    enough remaining cargo capacity before executing.  This is a one-shot
    transfer; the full requested amount is moved in a single turn.
    """

    _player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    fleet_id: uuid.UUID = field(default_factory=uuid.uuid4)
    planet_id: uuid.UUID = field(default_factory=uuid.uuid4)
    resource_type: str = ""
    amount: float = 0.0

    @classmethod
    def action_type(cls) -> str:
        """Registry key identifying this action type for serialization."""
        return "HarvestResources"

    @property
    def player_id(self) -> uuid.UUID:
        """UUID of the player who issued this order."""
        return self._player_id

    @property
    def order_id(self) -> uuid.UUID:
        """Unique identifier for this order; used for replacement and tracking."""
        return self._order_id

    def validate(self, world) -> ValidationResult:
        """Check ownership, co-location, available resources, and fleet capacity.

        Ensures the player owns both the fleet and the planet, both are in the
        same star system, the planet has enough of the requested resource type,
        and the fleet has sufficient remaining cargo capacity.

        Args:
            world: Current game world.

        Returns:
            ValidationResult: valid=True if all checks pass; errors otherwise.
        """
        errors: list[str] = []

        try:
            fleet = world.get_entity(self.fleet_id)
        except KeyError:
            return ValidationResult(valid=False, errors=["Fleet not found"])

        _check_fleet_ownership(fleet, self._player_id, errors)

        try:
            planet = world.get_entity(self.planet_id)
        except KeyError:
            return ValidationResult(valid=False, errors=["Planet not found"])

        if not planet.has(Owner):
            errors.append("Planet has no Owner")
        elif planet.get(Owner).player_id != self._player_id:
            errors.append("Planet not owned by player")

        _check_same_system(fleet, planet, errors)

        if planet.has(Resources):
            available = planet.get(Resources).amounts.get(self.resource_type, 0.0)
            if available < self.amount:
                errors.append(
                    f"Planet has {available} {self.resource_type}, need {self.amount}"
                )

        if fleet.has(Resources):
            fleet_res = fleet.get(Resources)
            remaining_capacity = fleet_res.capacity - fleet_res.total()
            if remaining_capacity < self.amount:
                errors.append(
                    f"Fleet cargo capacity insufficient ({remaining_capacity} free)"
                )

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def execute(self, world) -> list[Event]:
        """Move the requested amount from the planet's stockpile to the fleet.

        Directly adjusts the amounts dicts on both Resources components.
        Publishes a ``ResourcesHarvested`` event visible only to the acting player.

        Args:
            world: Current game world (mutated in-place).

        Returns:
            list[Event]: Single ResourcesHarvested event.
        """
        fleet = world.get_entity(self.fleet_id)
        planet = world.get_entity(self.planet_id)

        planet_res = planet.get(Resources)
        fleet_res = fleet.get(Resources)

        planet_res.amounts[self.resource_type] = (
            planet_res.amounts.get(self.resource_type, 0.0) - self.amount
        )
        fleet_res.amounts[self.resource_type] = (
            fleet_res.amounts.get(self.resource_type, 0.0) + self.amount
        )

        return [
            Event(
                who=fleet.id,
                what="ResourcesHarvested",
                when=world.current_turn,
                why=str(self._order_id),
                effects={
                    "resource": self.resource_type,
                    "amount": self.amount,
                    "from_planet": str(planet.id),
                },
                visibility_scope=[str(self._player_id)],
            )
        ]


@action
@dataclass
class StartResearchAction(Action):
    """Begin researching a propulsion technology.

    The player specifies which civilization entity to research with and
    which tech_id to research.  The tech must exist in PROPULSION_TECHS,
    must not already be unlocked, and the civ must not be mid-research.
    """

    _player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    civ_entity_id: uuid.UUID = field(default_factory=uuid.uuid4)
    tech_id: str = ""

    @classmethod
    def action_type(cls) -> str:
        """Registry key identifying this action type for serialization."""
        return "StartResearch"

    @property
    def player_id(self) -> uuid.UUID:
        """UUID of the player who issued this order."""
        return self._player_id

    @property
    def order_id(self) -> uuid.UUID:
        """Unique identifier for this order; used for replacement and tracking."""
        return self._order_id

    def validate(self, world) -> ValidationResult:
        """Check entity exists, is owned, has ResearchComponent, tech is valid."""
        from game.systems import PROPULSION_TECHS

        errors: list[str] = []

        try:
            civ = world.get_entity(self.civ_entity_id)
        except KeyError:
            return ValidationResult(valid=False, errors=["Civilization entity not found"])

        if not civ.has(Owner):
            errors.append("Entity has no Owner")
        elif civ.get(Owner).player_id != self._player_id:
            errors.append("Entity not owned by player")

        if not civ.has(ResearchComponent):
            errors.append("Entity has no ResearchComponent")
        else:
            research = civ.get(ResearchComponent)
            if research.active_tech_id is not None:
                errors.append("Already researching a technology")
            if self.tech_id in research.unlocked_techs:
                errors.append(f"Technology '{self.tech_id}' already unlocked")

        if self.tech_id not in PROPULSION_TECHS:
            errors.append(f"Unknown technology '{self.tech_id}'")

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def execute(self, world) -> list[Event]:
        """Set active research on the civilization entity."""
        from game.systems import PROPULSION_TECHS

        civ = world.get_entity(self.civ_entity_id)
        research = civ.get(ResearchComponent)
        tech_def = PROPULSION_TECHS[self.tech_id]

        research.active_tech_id = self.tech_id
        research.progress = 0.0
        research.required_progress = float(tech_def["cost"])

        return [
            Event(
                who=civ.id,
                what="ResearchStarted",
                when=world.current_turn,
                why=str(self._order_id),
                effects={
                    "tech_id": self.tech_id,
                    "turns_required": tech_def["cost"],
                },
                visibility_scope=[str(self._player_id)],
            )
        ]
