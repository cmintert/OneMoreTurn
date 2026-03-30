"""Component and World serialization for persistence."""

from __future__ import annotations

import dataclasses
import types as _builtin_types
import typing
import uuid
from typing import Any

from engine.components import Component
from engine.ecs import World


class ComponentRegistry:
    """Maps component_name() strings to component classes for deserialization."""

    def __init__(self) -> None:
        self._registry: dict[str, type[Component]] = {}

    def register(self, *component_classes: type[Component]) -> None:
        """Register one or more component classes."""
        for cls in component_classes:
            self._registry[cls.component_name()] = cls

    def get(self, name: str) -> type[Component]:
        """Look up a class by component_name(). Raises KeyError if not registered."""
        if name not in self._registry:
            raise KeyError(f"Component '{name}' not registered in ComponentRegistry")
        return self._registry[name]

    def all(self) -> dict[str, type[Component]]:
        """Return a copy of the full registry."""
        return dict(self._registry)


# ---------------------------------------------------------------------------
# Value serialization helpers
# ---------------------------------------------------------------------------


def _serialize_value(value: Any) -> Any:
    """Convert a field value to a JSON-serializable form."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, type) and hasattr(value, "component_name"):
        return value.component_name()
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


def _get_type_hints_safe(cls: type) -> dict[str, Any]:
    """Get resolved type hints for a dataclass. Falls back to raw field types."""
    try:
        return typing.get_type_hints(cls)
    except Exception:
        return {f.name: f.type for f in dataclasses.fields(cls)}


def _is_union_type(type_hint: Any) -> bool:
    """True if type_hint is a Union or new-style (int | None) union."""
    origin = typing.get_origin(type_hint)
    if origin is typing.Union:
        return True
    if hasattr(_builtin_types, "UnionType") and isinstance(
        type_hint, _builtin_types.UnionType
    ):
        return True
    return False


def _deserialize_value(value: Any, type_hint: Any, registry: ComponentRegistry) -> Any:
    """Reconstruct a field value from its JSON-serialized form."""
    if value is None:
        return None

    # Union / Optional — take the first non-None arg
    if _is_union_type(type_hint):
        args = typing.get_args(type_hint)
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _deserialize_value(value, non_none[0], registry)
        return value

    # Direct UUID
    if type_hint is uuid.UUID:
        return uuid.UUID(str(value))

    # Parameterized generic (list[X], etc.)
    origin = typing.get_origin(type_hint)
    args = typing.get_args(type_hint)

    if origin is list and args:
        item_hint = args[0]
        item_origin = typing.get_origin(item_hint)
        item_args = typing.get_args(item_hint)

        if item_hint is uuid.UUID:
            return [uuid.UUID(str(item)) for item in value]

        # list[type[Component]] → list of class objects from registry
        if item_origin is type and item_args:
            return [registry.get(item) for item in value]

        return list(value)

    return value


# ---------------------------------------------------------------------------
# Component serialization
# ---------------------------------------------------------------------------


def serialize_component(component: Component) -> dict:
    """Serialize a component instance to a JSON-compatible dict."""
    cls = type(component)
    if dataclasses.is_dataclass(component):
        data = {
            f.name: _serialize_value(getattr(component, f.name))
            for f in dataclasses.fields(component)
        }
    else:
        data = {}
    return {
        "component_type": cls.component_name(),
        "component_version": cls.version(),
        "data": data,
    }


def deserialize_component(record: dict, registry: ComponentRegistry) -> Component:
    """Reconstruct a Component from its serialized dict record.

    For ContainerComponent, the ``children`` field is cleared — it will be
    repopulated by ChildComponent.on_added hooks during world deserialization.
    """
    cls = registry.get(record["component_type"])
    data = dict(record.get("data", {}))

    if dataclasses.is_dataclass(cls):
        hints = _get_type_hints_safe(cls)
        for field_name in list(data):
            hint = hints.get(field_name)
            if hint is not None:
                data[field_name] = _deserialize_value(data[field_name], hint, registry)

    # ContainerComponent.children is rebuilt by ChildComponent.on_added hooks.
    # Clear it here to avoid duplicates when the hook fires during create_entity.
    if record["component_type"] == "Container" and "children" in data:
        data["children"] = []

    return cls(**data)


# ---------------------------------------------------------------------------
# World serialization
# ---------------------------------------------------------------------------


def serialize_world(world: World, game_id: str, format_version: str = "1.0.0") -> dict:
    """Serialize an entire World to a JSON-compatible snapshot dict.

    Entities are written in stable UUID order for deterministic output.
    """
    entity_records = []
    for entity in sorted(world.entities(), key=lambda e: e.id):
        component_records = [
            serialize_component(comp) for comp in entity.components().values()
        ]
        entity_records.append(
            {
                "entity_id": str(entity.id),
                "alive": entity.alive,
                "components": component_records,
            }
        )

    return {
        "format_version": format_version,
        "game_id": game_id,
        "turn_number": world.current_turn,
        "current_turn": world.current_turn,
        "entities": entity_records,
    }


def _has_child_component(entity_record: dict) -> bool:
    return any(c["component_type"] == "Child" for c in entity_record["components"])


def deserialize_world(snapshot: dict, registry: ComponentRegistry) -> World:
    """Reconstruct a World from a snapshot dict.

    Entities without ChildComponent are created first so that parent entities
    exist before ChildComponent.on_add_validation runs.
    """
    world = World()
    world.current_turn = snapshot.get("current_turn", snapshot.get("turn_number", 0))

    records = snapshot.get("entities", [])
    # Parents first, children second
    ordered = [r for r in records if not _has_child_component(r)] + [
        r for r in records if _has_child_component(r)
    ]

    for record in ordered:
        entity_id = uuid.UUID(record["entity_id"])
        components = [
            deserialize_component(c, registry) for c in record["components"]
        ]
        world.create_entity(components, entity_id=entity_id)

    return world
