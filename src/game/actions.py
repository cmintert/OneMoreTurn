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
    Resources,
)


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


@dataclass
class MoveFleetAction(Action):
    """Order a fleet to move to a target star system."""

    _player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    fleet_id: uuid.UUID = field(default_factory=uuid.uuid4)
    target_system_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def action_type(cls) -> str:
        return "MoveFleet"

    @property
    def player_id(self) -> uuid.UUID:
        return self._player_id

    @property
    def order_id(self) -> uuid.UUID:
        return self._order_id

    def validate(self, world) -> ValidationResult:
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


@dataclass
class ColonizePlanetAction(Action):
    """Colonize an unowned planet using a fleet at the same star system."""

    _player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    fleet_id: uuid.UUID = field(default_factory=uuid.uuid4)
    planet_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def action_type(cls) -> str:
        return "ColonizePlanet"

    @property
    def player_id(self) -> uuid.UUID:
        return self._player_id

    @property
    def order_id(self) -> uuid.UUID:
        return self._order_id

    def validate(self, world) -> ValidationResult:
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
        return f"colonize:{self.planet_id}"


@dataclass
class HarvestResourcesAction(Action):
    """Transfer resources from an owned planet to a fleet at the same system."""

    _player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    fleet_id: uuid.UUID = field(default_factory=uuid.uuid4)
    planet_id: uuid.UUID = field(default_factory=uuid.uuid4)
    resource_type: str = ""
    amount: float = 0.0

    @classmethod
    def action_type(cls) -> str:
        return "HarvestResources"

    @property
    def player_id(self) -> uuid.UUID:
        return self._player_id

    @property
    def order_id(self) -> uuid.UUID:
        return self._order_id

    def validate(self, world) -> ValidationResult:
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
