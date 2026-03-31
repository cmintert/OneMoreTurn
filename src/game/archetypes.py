"""Archetype factory functions for creating pre-configured game entities."""

from __future__ import annotations

import uuid

from engine.components import ChildComponent, ContainerComponent
from engine.ecs import Entity, World
from engine.names import NameComponent
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
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
            Resources(amounts=base_resources or {}, capacity=500.0),
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
        Resources(amounts=resources or {}, capacity=200.0),
        VisibilityComponent(),
    ]
    if population > 0:
        components.append(
            PopulationStats(size=population, growth_rate=0.05, morale=1.0)
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
    speed: float = 5.0,
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
            FleetStats(speed=speed, capacity=50.0, condition=100.0),
            Resources(amounts=cargo or {}, capacity=50.0),
            VisibilityComponent(),
        ]
    )
