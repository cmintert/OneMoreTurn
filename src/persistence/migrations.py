"""Migration registry for snapshot format versioning."""

from __future__ import annotations

from typing import Callable

CURRENT_FORMAT_VERSION = "1.0.0"


class MigrationError(Exception):
    """Raised when a snapshot cannot be migrated to the current format version."""


class MigrationRegistry:
    """Registry of snapshot migration functions.

    Migration functions are pure: they receive a snapshot dict and return a
    transformed copy. They must be idempotent — applying the same migration
    twice produces the same result.

    Usage::

        registry = MigrationRegistry()

        def v10_to_v11(snapshot: dict) -> dict:
            # rename a field, etc.
            snapshot = dict(snapshot)
            snapshot["format_version"] = "1.1.0"
            return snapshot

        registry.register("1.0.0", "1.1.0", v10_to_v11)
        migrated = registry.apply(old_snapshot)
    """

    def __init__(self) -> None:
        """Initialise the registry with an empty migration chain."""
        self._migrations: dict[tuple[str, str], Callable[[dict], dict]] = {}

    def register(
        self,
        from_version: str,
        to_version: str,
        fn: Callable[[dict], dict],
    ) -> None:
        """Register a migration function from one version to another."""
        self._migrations[(from_version, to_version)] = fn

    def apply(self, snapshot: dict) -> dict:
        """Apply all needed migrations to bring snapshot to CURRENT_FORMAT_VERSION.

        Walks the registered chain from ``snapshot["format_version"]`` to
        ``CURRENT_FORMAT_VERSION``, applying each function in order.

        Raises MigrationError if:
        - ``format_version`` is missing from the snapshot
        - no chain exists from the snapshot version to the current version
        - a cycle is detected in the chain
        - a migration function does not update ``format_version``
        """
        if "format_version" not in snapshot:
            raise MigrationError("Snapshot has no 'format_version' field")

        if snapshot["format_version"] == CURRENT_FORMAT_VERSION:
            return snapshot

        result = dict(snapshot)
        visited: set[str] = set()

        while result["format_version"] != CURRENT_FORMAT_VERSION:
            current = result["format_version"]

            if current in visited:
                raise MigrationError(
                    f"Cycle detected in migration chain at version {current!r}"
                )
            visited.add(current)

            # Find the registered step starting from current
            next_step: tuple[str, str] | None = None
            for key in self._migrations:
                if key[0] == current:
                    next_step = key
                    break

            if next_step is None:
                raise MigrationError(
                    f"No migration registered from version {current!r}; "
                    f"cannot reach {CURRENT_FORMAT_VERSION!r}"
                )

            fn = self._migrations[next_step]
            result = fn(result)

            if "format_version" not in result:
                raise MigrationError(
                    f"Migration {next_step[0]!r} → {next_step[1]!r} "
                    f"did not set 'format_version' on the returned snapshot"
                )

        return result
