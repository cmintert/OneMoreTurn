"""Name-to-UUID resolution for player-facing API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.components import Component

if TYPE_CHECKING:
    from engine.ecs import World


# ---------------------------------------------------------------------------
# NameComponent
# ---------------------------------------------------------------------------


@dataclass
class NameComponent(Component):
    """Human-readable name for an entity. Used by CLI and player-facing API."""

    name: str = ""

    @classmethod
    def component_name(cls) -> str:
        """Registry key used by serialization to identify this component type."""
        return "Name"

    @classmethod
    def version(cls) -> str:
        """Schema version; increment when field names or types change."""
        return "1.0.0"

    @classmethod
    def constraints(cls) -> dict:
        """Require a non-empty name string; enforced structurally by validate()."""
        return {"name": {"min_length": 1}}

    def validate(self) -> list[str]:
        """Reject blank or whitespace-only names.

        The base class constraint loop does not handle string length, so this
        override adds the specific check needed for NameComponent.

        Returns:
            list[str]: Validation error messages; empty if the name is valid.
        """
        errors = []
        if not self.name or not self.name.strip():
            errors.append("Name.name: must be non-empty")
        return errors
