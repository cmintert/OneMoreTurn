"""Registry construction helpers for the game."""

from __future__ import annotations

from engine.components import ChildComponent, ContainerComponent
from engine.names import NameComponent
from game.actions import (
    ColonizePlanetAction,
    HarvestResourcesAction,
    MoveFleetAction,
)
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    Resources,
    VisibilityComponent,
)
from game.systems import MovementSystem, ProductionSystem, VisibilitySystem
from persistence.serialization import ActionRegistry, ComponentRegistry


def game_component_registry() -> ComponentRegistry:
    """Build a ComponentRegistry with all game components registered."""
    reg = ComponentRegistry()
    reg.register(
        Position,
        Owner,
        Resources,
        FleetStats,
        PopulationStats,
        VisibilityComponent,
        NameComponent,
        ContainerComponent,
        ChildComponent,
    )
    return reg


def game_action_registry() -> ActionRegistry:
    """Build an ActionRegistry with all game actions registered."""
    reg = ActionRegistry()
    reg.register(MoveFleetAction, ColonizePlanetAction, HarvestResourcesAction)
    return reg


def game_systems() -> list:
    """Return instantiated game systems for turn resolution."""
    return [ProductionSystem(), MovementSystem(), VisibilitySystem()]
