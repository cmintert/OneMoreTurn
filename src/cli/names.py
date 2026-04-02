"""Name-to-UUID resolution for the CLI and server layers."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from engine.names import NameComponent

if TYPE_CHECKING:
    from engine.ecs import World


class NameResolver:
    """Translates human-readable entity names to/from UUIDs.

    Queries the World for entities with NameComponent. Players never see
    UUIDs — this class bridges the gap.
    """

    def __init__(self, world: World) -> None:
        """Bind the resolver to a specific world instance.

        The resolver queries the world on every call rather than caching,
        so it always reflects the current entity state without needing
        explicit cache invalidation.

        Args:
            world: The game world to resolve names against.
        """
        self._world = world

    def resolve(self, name: str) -> uuid.UUID:
        """Resolve a name to an entity UUID.

        Raises KeyError if no entity has this name.
        Raises ValueError if multiple entities share the name.
        """
        matches = [
            entity
            for entity, name_comp in self._world.query(NameComponent)
            if name_comp.name == name
        ]
        if not matches:
            raise KeyError(f"No entity found with name '{name}'")
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous name '{name}': matches {len(matches)} entities"
            )
        return matches[0].id

    def resolve_many(self, names: list[str]) -> list[uuid.UUID]:
        """Resolve multiple names to UUIDs. Same error semantics as resolve()."""
        return [self.resolve(name) for name in names]

    def get_name(self, entity_id: uuid.UUID) -> str:
        """Look up the name of an entity. Raises KeyError if not found."""
        entity = self._world.get_entity(entity_id)
        if not entity.has(NameComponent):
            raise KeyError(f"Entity {entity_id} has no NameComponent")
        name_comp = entity.get(NameComponent)
        assert isinstance(name_comp, NameComponent)
        return name_comp.name
