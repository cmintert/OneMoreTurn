"""Component base class with schema protocol and validation."""

from __future__ import annotations

import dataclasses
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.ecs import World


class Component(ABC):
    """Base class for all components. Enforces the schema protocol.

    Subclasses must be dataclasses and implement component_name() and version().
    """

    @classmethod
    @abstractmethod
    def component_name(cls) -> str:
        """Unique identifier for this component type."""

    @classmethod
    @abstractmethod
    def version(cls) -> str:
        """Semver string for this component schema."""

    @classmethod
    def dependencies(cls) -> list[type[Component]]:
        """Component types that must also exist on the same entity. Default: none."""
        return []

    @classmethod
    def properties_schema(cls) -> dict[str, type]:
        """Name -> type mapping of component fields. Introspected from dataclass."""
        if not dataclasses.is_dataclass(cls):
            return {}
        return {f.name: f.type for f in dataclasses.fields(cls)}

    @classmethod
    def constraints(cls) -> dict[str, dict[str, Any]]:
        """Validation rules per property. E.g., {"health": {"min": 0}}. Default: none."""
        return {}

    def validate(self) -> list[str]:
        """Validate this instance against its constraints. Returns error messages."""
        errors = []
        for field_name, rules in self.constraints().items():
            value = getattr(self, field_name, None)
            if value is None:
                continue
            if "min" in rules and value < rules["min"]:
                errors.append(
                    f"{self.component_name()}.{field_name}: "
                    f"{value} < min {rules['min']}"
                )
            if "max" in rules and value > rules["max"]:
                errors.append(
                    f"{self.component_name()}.{field_name}: "
                    f"{value} > max {rules['max']}"
                )
        return errors

    @classmethod
    def on_add_validation(
        cls,
        world: World,
        entity_id: uuid.UUID,
        component: Component,
    ) -> list[str]:
        """Called by World before adding this component. Return error messages."""
        return []

    @classmethod
    def on_remove_validation(
        cls,
        world: World,
        entity_id: uuid.UUID,
    ) -> list[str]:
        """Called by World before removing this component. Return error messages."""
        return []

    @classmethod
    def on_added(
        cls,
        world: World,
        entity_id: uuid.UUID,
        component: Component,
    ) -> None:
        """Called by World after this component is successfully added."""

    @classmethod
    def on_removed(
        cls,
        world: World,
        entity_id: uuid.UUID,
        component: Component,
    ) -> None:
        """Called by World after this component is successfully removed."""


# ---------------------------------------------------------------------------
# Containment components
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ContainerComponent(Component):
    """Allows an entity to hold child entities."""

    allowed_child_types: list[type[Component]] = dataclasses.field(
        default_factory=list
    )
    max_capacity: int | None = None
    children: list[uuid.UUID] = dataclasses.field(default_factory=list)

    @classmethod
    def component_name(cls) -> str:
        """Registry key used by serialization to identify this component type."""
        return "Container"

    @classmethod
    def version(cls) -> str:
        """Schema version; increment when field names or types change."""
        return "1.0.0"

    @classmethod
    def on_remove_validation(
        cls, world: World, entity_id: uuid.UUID
    ) -> list[str]:
        """Prevent removal while the container still holds children.

        Enforces the invariant that a container must be emptied before it (or
        its entity) can be removed.  This guards against orphaned entities whose
        parent_id would point to a non-existent entity.

        Args:
            world: The current game world.
            entity_id: ID of the entity the component will be removed from.

        Returns:
            list[str]: Error messages; empty if removal is safe.
        """
        entity = world.get_entity(entity_id)
        if not entity.has(ContainerComponent):
            return []
        container = entity.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)
        if container.children:
            return [
                f"Cannot remove/destroy Container: "
                f"still has {len(container.children)} children"
            ]
        return []


@dataclasses.dataclass
class ChildComponent(Component):
    """Marks an entity as contained by a parent entity."""

    parent_id: uuid.UUID = dataclasses.field(default_factory=uuid.uuid4)

    @classmethod
    def component_name(cls) -> str:
        """Registry key used by serialization to identify this component type."""
        return "Child"

    @classmethod
    def version(cls) -> str:
        """Schema version; increment when field names or types change."""
        return "1.0.0"

    @classmethod
    def on_add_validation(
        cls, world: World, entity_id: uuid.UUID, component: Component
    ) -> list[str]:
        """Verify the parent exists, has a ContainerComponent, and can accept children.

        Checks: parent entity existence, parent has ContainerComponent,
        child entity has one of the allowed child types (if restricted), and
        the container is not already at capacity.

        Args:
            world: The current game world.
            entity_id: ID of the entity being given a ChildComponent.
            component: The ChildComponent instance being added.

        Returns:
            list[str]: Error messages; empty if validation passes.
        """
        assert isinstance(component, ChildComponent)
        errors: list[str] = []

        # Parent must exist
        try:
            parent = world.get_entity(component.parent_id)
        except KeyError:
            return [f"Parent entity {component.parent_id} does not exist"]

        # Parent must have ContainerComponent
        if not parent.has(ContainerComponent):
            return [f"Parent entity does not have ContainerComponent"]

        container = parent.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)

        # Check allowed types
        if container.allowed_child_types:
            child_entity = world.get_entity(entity_id)
            has_allowed = any(
                child_entity.has(ct)
                for ct in container.allowed_child_types
            )
            if not has_allowed:
                allowed_names = [
                    ct.component_name() for ct in container.allowed_child_types
                ]
                errors.append(
                    f"Child does not have any of the allowed types: "
                    f"{allowed_names}"
                )

        # Check capacity
        if (
            container.max_capacity is not None
            and len(container.children) >= container.max_capacity
        ):
            errors.append(
                f"Container at capacity ({container.max_capacity})"
            )

        return errors

    @classmethod
    def on_added(
        cls, world: World, entity_id: uuid.UUID, component: Component
    ) -> None:
        """Register this entity in the parent container's children list.

        Called by World after the ChildComponent is successfully added.  This
        is the authoritative way the parent container learns about new children
        — the children list on ContainerComponent is never set directly.

        Args:
            world: The current game world.
            entity_id: ID of the child entity.
            component: The ChildComponent instance that was just added.
        """
        assert isinstance(component, ChildComponent)
        parent = world.get_entity(component.parent_id)
        container = parent.get(ContainerComponent)
        assert isinstance(container, ContainerComponent)
        container.children.append(entity_id)

    @classmethod
    def on_remove_validation(
        cls, world: World, entity_id: uuid.UUID
    ) -> list[str]:
        """Always permit removal of ChildComponent.

        Unlike ContainerComponent, a child can always be detached from its
        parent (e.g. when a fleet departs a system mid-flight).

        Returns:
            list[str]: Always empty.
        """
        return []  # Always allow removal

    @classmethod
    def on_removed(
        cls, world: World, entity_id: uuid.UUID, component: Component
    ) -> None:
        """Deregister this entity from the parent container's children list.

        Called by World after ChildComponent is removed.  Handles the case
        where the parent was already destroyed (e.g. star system wiped) by
        silently returning rather than raising.

        Args:
            world: The current game world.
            entity_id: ID of the child entity being detached.
            component: The ChildComponent instance that was just removed.
        """
        assert isinstance(component, ChildComponent)
        try:
            parent = world.get_entity(component.parent_id)
        except KeyError:
            return  # Parent already destroyed
        if parent.has(ContainerComponent):
            container = parent.get(ContainerComponent)
            assert isinstance(container, ContainerComponent)
            if entity_id in container.children:
                container.children.remove(entity_id)
