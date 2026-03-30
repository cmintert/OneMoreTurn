"""Core ECS classes: Entity and World."""

from __future__ import annotations

import uuid
from types import MappingProxyType
from typing import Any

from engine.components import Component
from engine.events import Event, EventBus


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------


class Entity:
    """An entity is a UUID with a bag of components."""

    def __init__(self, entity_id: uuid.UUID | None = None) -> None:
        self._id = entity_id or uuid.uuid4()
        self._components: dict[type[Component], Component] = {}
        self._alive = True

    @property
    def id(self) -> uuid.UUID:
        return self._id

    @property
    def alive(self) -> bool:
        return self._alive

    def has(self, *component_types: type[Component]) -> bool:
        """True if entity has ALL specified component types."""
        return all(ct in self._components for ct in component_types)

    def get(self, component_type: type[Component]) -> Component:
        """Get component by type. Raises KeyError if missing."""
        return self._components[component_type]

    def components(self) -> MappingProxyType[type[Component], Component]:
        """Read-only view of all components."""
        return MappingProxyType(self._components)

    def destroy(self) -> None:
        """Mark entity as destroyed."""
        self._alive = False

    # -- Internal methods used by World --

    def _add_component(self, component: Component) -> None:
        self._components[type(component)] = component

    def _remove_component(self, component_type: type[Component]) -> Component:
        return self._components.pop(component_type)


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


class SchemaError(Exception):
    """Raised when a component schema constraint is violated."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class World:
    """Central registry. All entity/component mutations go through World."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._entities: dict[uuid.UUID, Entity] = {}
        self._event_bus = event_bus or EventBus()
        self._component_index: dict[type[Component], set[uuid.UUID]] = {}
        self.current_turn: int = 0

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    # -- Entity lifecycle --

    def create_entity(
        self,
        components: list[Component] | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> Entity:
        """Create an entity, optionally with initial components.

        Validates all dependency and constraint requirements across the full
        initial component set before adding any.
        """
        entity = Entity(entity_id)
        components = components or []

        # Collect types in the initial set for dependency checking
        initial_types = {type(c) for c in components}

        # Validate dependencies: each component's deps must be in the initial set
        errors: list[str] = []
        for comp in components:
            for dep in type(comp).dependencies():
                if dep not in initial_types:
                    errors.append(
                        f"{type(comp).component_name()} requires "
                        f"{dep.component_name()} but it is not present"
                    )

        # Validate constraints
        for comp in components:
            errors.extend(comp.validate())

        if errors:
            raise SchemaError(errors)

        # Add components to entity and index
        for comp in components:
            entity._add_component(comp)
            self._index_add(type(comp), entity.id)

        # Run on_add_validation hooks (need entity in world first for
        # cross-entity checks like containment)
        self._entities[entity.id] = entity
        hook_errors: list[str] = []
        for comp in components:
            hook_errors.extend(
                type(comp).on_add_validation(self, entity.id, comp)
            )

        if hook_errors:
            # Roll back: remove from storage and indices
            del self._entities[entity.id]
            for comp in components:
                self._index_remove(type(comp), entity.id)
            raise SchemaError(hook_errors)

        # Run on_added hooks
        for comp in components:
            type(comp).on_added(self, entity.id, comp)

        self._event_bus.publish(Event(
            who=entity.id,
            what="EntityCreated",
            when=self.current_turn,
            why="create_entity",
            effects={"component_types": [type(c).component_name() for c in components]},
        ))
        return entity

    def destroy_entity(self, entity_id: uuid.UUID) -> None:
        """Destroy entity. Removes from indices and emits event."""
        entity = self.get_entity(entity_id)

        # Check if any hook vetoes destruction (e.g., container with children)
        errors: list[str] = []
        for comp_type in list(entity.components()):
            errors.extend(comp_type.on_remove_validation(self, entity_id))
        if errors:
            raise SchemaError(errors)

        # Snapshot components before removal for on_removed hooks
        components_snapshot = dict(entity.components())

        # Remove from indices
        for comp_type in list(components_snapshot):
            self._index_remove(comp_type, entity_id)

        # Run on_removed hooks with the actual component instances
        for comp_type, comp in components_snapshot.items():
            comp_type.on_removed(self, entity_id, comp)

        entity.destroy()
        del self._entities[entity_id]

        self._event_bus.publish(Event(
            who=entity_id,
            what="EntityDestroyed",
            when=self.current_turn,
            why="destroy_entity",
            effects={},
        ))

    def get_entity(self, entity_id: uuid.UUID) -> Entity:
        """Get entity by ID. Raises KeyError if not found."""
        try:
            entity = self._entities[entity_id]
        except KeyError:
            raise KeyError(f"Entity {entity_id} not found") from None
        return entity

    # -- Component mutations --

    def add_component(self, entity_id: uuid.UUID, component: Component) -> None:
        """Add a component to an entity with full validation."""
        entity = self.get_entity(entity_id)
        comp_type = type(component)

        if entity.has(comp_type):
            raise SchemaError(
                [f"Entity already has {comp_type.component_name()}"]
            )

        # Check dependencies
        errors: list[str] = []
        for dep in comp_type.dependencies():
            if not entity.has(dep):
                errors.append(
                    f"{comp_type.component_name()} requires "
                    f"{dep.component_name()}"
                )

        # Validate constraints
        errors.extend(component.validate())

        # Hook validation
        errors.extend(comp_type.on_add_validation(self, entity_id, component))

        if errors:
            raise SchemaError(errors)

        entity._add_component(component)
        self._index_add(comp_type, entity_id)
        comp_type.on_added(self, entity_id, component)

        self._event_bus.publish(Event(
            who=entity_id,
            what="ComponentAdded",
            when=self.current_turn,
            why="add_component",
            effects={"component_type": comp_type.component_name()},
        ))

    def remove_component(
        self, entity_id: uuid.UUID, component_type: type[Component]
    ) -> None:
        """Remove a component from an entity. Checks dependents."""
        entity = self.get_entity(entity_id)

        if not entity.has(component_type):
            raise KeyError(
                f"Entity does not have {component_type.component_name()}"
            )

        # Check if other components on this entity depend on this one
        errors: list[str] = []
        for other_type in entity.components():
            if other_type is component_type:
                continue
            if component_type in other_type.dependencies():
                errors.append(
                    f"Cannot remove {component_type.component_name()}: "
                    f"{other_type.component_name()} depends on it"
                )

        # Hook validation
        errors.extend(
            component_type.on_remove_validation(self, entity_id)
        )

        if errors:
            raise SchemaError(errors)

        removed = entity._remove_component(component_type)
        self._index_remove(component_type, entity_id)
        component_type.on_removed(self, entity_id, removed)

        self._event_bus.publish(Event(
            who=entity_id,
            what="ComponentRemoved",
            when=self.current_turn,
            why="remove_component",
            effects={"component_type": component_type.component_name()},
        ))

    # -- Queries --

    def query(self, *component_types: type[Component]) -> list[tuple[Any, ...]]:
        """Return entities that have ALL specified component types.

        Returns list of (entity, comp1, comp2, ...) tuples.
        """
        if not component_types:
            return []

        # Intersect index sets, starting with the smallest
        sets = []
        for ct in component_types:
            ids = self._component_index.get(ct, set())
            sets.append(ids)
        sets.sort(key=len)

        matching_ids = sets[0].copy()
        for s in sets[1:]:
            matching_ids &= s

        results = []
        for eid in matching_ids:
            entity = self._entities[eid]
            row = (entity, *(entity.get(ct) for ct in component_types))
            results.append(row)

        # Deterministic order by entity ID
        results.sort(key=lambda r: r[0].id)
        return results

    def entities(self) -> list[Entity]:
        """Return all living entities."""
        return [e for e in self._entities.values() if e.alive]

    # -- Internal index management --

    def _index_add(self, comp_type: type[Component], entity_id: uuid.UUID) -> None:
        if comp_type not in self._component_index:
            self._component_index[comp_type] = set()
        self._component_index[comp_type].add(entity_id)

    def _index_remove(self, comp_type: type[Component], entity_id: uuid.UUID) -> None:
        if comp_type in self._component_index:
            self._component_index[comp_type].discard(entity_id)
