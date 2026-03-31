"""Registry construction helpers for the game.

Game components, actions, and systems self-register via decorators defined
here.  Engine types (ContainerComponent, ChildComponent, NameComponent) live
outside the game package and are registered explicitly.
"""

from __future__ import annotations

from typing import TypeVar

from persistence.serialization import ActionRegistry, ComponentRegistry

_T = TypeVar("_T")

# Accumulator lists populated by the decorators below.
_component_classes: list[type] = []
_action_classes: list[type] = []
_system_classes: list[type] = []


def component(cls: type[_T]) -> type[_T]:
    """Class decorator: register a Component subclass for serialization."""
    _component_classes.append(cls)
    return cls


def action(cls: type[_T]) -> type[_T]:
    """Class decorator: register an Action subclass for serialization."""
    _action_classes.append(cls)
    return cls


def system(cls: type[_T]) -> type[_T]:
    """Class decorator: register a System subclass for turn resolution."""
    _system_classes.append(cls)
    return cls


def game_component_registry() -> ComponentRegistry:
    """Build a ComponentRegistry with all game and engine components registered."""
    # Guard-imports ensure game modules are loaded (decorators fire on import).
    import game.components as _gc  # noqa: F401
    from engine.components import ChildComponent, ContainerComponent
    from engine.names import NameComponent

    reg = ComponentRegistry()
    reg.register(*_component_classes)
    # Engine types live outside game/ — register explicitly.
    reg.register(NameComponent, ContainerComponent, ChildComponent)
    return reg


def game_action_registry() -> ActionRegistry:
    """Build an ActionRegistry with all game actions registered."""
    import game.actions as _ga  # noqa: F401

    reg = ActionRegistry()
    reg.register(*_action_classes)
    return reg


def game_systems() -> list:
    """Return instantiated game systems for turn resolution."""
    import game.systems as _gs  # noqa: F401

    return [cls() for cls in _system_classes]
