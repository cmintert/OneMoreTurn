"""Archetype factory functions for creating pre-configured game entities."""

from __future__ import annotations

import uuid

from engine.components import ChildComponent, ContainerComponent
from engine.ecs import Entity, World
from engine.names import NameComponent
from game.config import ARCHETYPES
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    ResearchComponent,
    Resources,
    VisibilityComponent,
)


def create_star_system(
    world: World,
    name: str,
    x: float,
    y: float,
    base_resources: dict[str, float] | None = None,
) -> Entity:
    """Create a star system entity with Position, Container, Resources, Name, Visibility."""
    return world.create_entity(
        [
            NameComponent(name=name),
            Position(x=x, y=y, parent_system_id=None),
            ContainerComponent(),
            Resources(amounts=base_resources or {}, capacity=ARCHETYPES.star_system.resource_capacity),
            VisibilityComponent(),
        ]
    )


def create_planet(
    world: World,
    name: str,
    parent_system: Entity,
    resources: dict[str, float] | None = None,
    population: int = 0,
    owner_id: uuid.UUID | None = None,
    owner_name: str = "",
) -> Entity:
    """Create a planet as a child of a star system."""
    sys_pos = parent_system.get(Position)
    components = [
        NameComponent(name=name),
        Position(x=sys_pos.x, y=sys_pos.y, parent_system_id=parent_system.id),
        ChildComponent(parent_id=parent_system.id),
        Resources(amounts=resources or {}, capacity=ARCHETYPES.planet.resource_capacity),
        VisibilityComponent(),
    ]
    if population > 0:
        components.append(
            PopulationStats(
                size=population,
                growth_rate=ARCHETYPES.planet.default_growth_rate,
                morale=ARCHETYPES.planet.default_morale,
            )
        )
    if owner_id is not None:
        components.append(Owner(player_id=owner_id, player_name=owner_name))
    return world.create_entity(components)


def create_fleet(
    world: World,
    name: str,
    owner_id: uuid.UUID,
    owner_name: str,
    parent_system: Entity,
    speed: float = ARCHETYPES.fleet.speed,
    cargo: dict[str, float] | None = None,
) -> Entity:
    """Create a fleet docked at a star system."""
    sys_pos = parent_system.get(Position)
    return world.create_entity(
        [
            NameComponent(name=name),
            Position(x=sys_pos.x, y=sys_pos.y, parent_system_id=parent_system.id),
            ChildComponent(parent_id=parent_system.id),
            Owner(player_id=owner_id, player_name=owner_name),
            FleetStats(speed=speed, capacity=ARCHETYPES.fleet.capacity, condition=ARCHETYPES.fleet.condition),
            Resources(amounts=cargo or {}, capacity=ARCHETYPES.fleet.capacity),
            VisibilityComponent(),
        ]
    )


def create_civilization(
    world: World,
    player_id: uuid.UUID,
    player_name: str,
) -> Entity:
    """Create a civilization entity that tracks per-player research state."""
    return world.create_entity(
        [
            Owner(player_id=player_id, player_name=player_name),
            ResearchComponent(),
        ]
    )
