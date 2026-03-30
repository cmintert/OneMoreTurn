"""Tests for MigrationRegistry snapshot versioning."""

from __future__ import annotations

import pytest

from persistence.migrations import CURRENT_FORMAT_VERSION, MigrationError, MigrationRegistry


def _snapshot(version: str = CURRENT_FORMAT_VERSION, **extra) -> dict:
    """Build a minimal snapshot dict for testing."""
    return {"format_version": version, "entities": [], **extra}


class TestMigrationRegistry:
    def test_current_version_passthrough(self):
        """Snapshot already at current version is returned unchanged."""
        reg = MigrationRegistry()
        snap = _snapshot(CURRENT_FORMAT_VERSION)
        result = reg.apply(snap)
        assert result is snap  # same object, no copy needed

    def test_missing_format_version_raises(self):
        reg = MigrationRegistry()
        with pytest.raises(MigrationError, match="format_version"):
            reg.apply({"entities": []})

    def test_unknown_version_raises(self):
        reg = MigrationRegistry()
        snap = _snapshot("0.0.1")
        with pytest.raises(MigrationError):
            reg.apply(snap)

    def test_single_hop_migration(self):
        """A snapshot at v0.9.0 is upgraded to v1.0.0 via one migration."""
        reg = MigrationRegistry()

        def upgrade(snap: dict) -> dict:
            snap = dict(snap)
            snap["format_version"] = "1.0.0"
            snap["added_by_migration"] = True
            return snap

        reg.register("0.9.0", "1.0.0", upgrade)
        snap = _snapshot("0.9.0")
        result = reg.apply(snap)
        assert result["format_version"] == CURRENT_FORMAT_VERSION
        assert result["added_by_migration"] is True

    def test_chain_migration(self):
        """v0.8.0 → v0.9.0 → v1.0.0 applied in order."""
        reg = MigrationRegistry()
        calls: list[str] = []

        def v08_to_v09(snap: dict) -> dict:
            calls.append("v08→v09")
            snap = dict(snap)
            snap["format_version"] = "0.9.0"
            return snap

        def v09_to_v10(snap: dict) -> dict:
            calls.append("v09→v10")
            snap = dict(snap)
            snap["format_version"] = "1.0.0"
            return snap

        reg.register("0.8.0", "0.9.0", v08_to_v09)
        reg.register("0.9.0", "1.0.0", v09_to_v10)

        snap = _snapshot("0.8.0")
        result = reg.apply(snap)
        assert result["format_version"] == CURRENT_FORMAT_VERSION
        assert calls == ["v08→v09", "v09→v10"]

    def test_idempotent_migration(self):
        """Applying the same migration twice gives the same result."""
        reg = MigrationRegistry()

        def upgrade(snap: dict) -> dict:
            snap = dict(snap)
            snap["format_version"] = "1.0.0"
            snap["x"] = 42
            return snap

        reg.register("0.9.0", "1.0.0", upgrade)

        snap = _snapshot("0.9.0")
        result1 = reg.apply(snap)
        # result1 is now at CURRENT_FORMAT_VERSION; applying again is a no-op
        result2 = reg.apply(result1)
        assert result1["format_version"] == result2["format_version"]
        assert result1.get("x") == result2.get("x")

    def test_migration_that_forgets_version_raises(self):
        """Migration function that drops format_version raises MigrationError."""
        reg = MigrationRegistry()

        def bad_migration(snap: dict) -> dict:
            snap = dict(snap)
            del snap["format_version"]  # Bug: forgot to set new version
            return snap

        reg.register("0.9.0", "1.0.0", bad_migration)
        with pytest.raises(MigrationError, match="format_version"):
            reg.apply(_snapshot("0.9.0"))

    def test_field_rename_migration(self):
        """Rename a component field in all entities during migration."""
        reg = MigrationRegistry()

        def rename_damage_to_strength(snap: dict) -> dict:
            """v0.9.0 → v1.0.0: rename PoisonComponent.damage → strength."""
            snap = dict(snap)
            updated_entities = []
            for entity in snap.get("entities", []):
                entity = dict(entity)
                updated_comps = []
                for comp in entity.get("components", []):
                    comp = dict(comp)
                    if comp["component_type"] == "Poison":
                        data = dict(comp["data"])
                        if "damage" in data:
                            data["strength"] = data.pop("damage")
                        comp["data"] = data
                    updated_comps.append(comp)
                entity["components"] = updated_comps
                updated_entities.append(entity)
            snap["entities"] = updated_entities
            snap["format_version"] = "1.0.0"
            return snap

        reg.register("0.9.0", "1.0.0", rename_damage_to_strength)

        old_snapshot = {
            "format_version": "0.9.0",
            "entities": [
                {
                    "entity_id": "abc",
                    "alive": True,
                    "components": [
                        {
                            "component_type": "Poison",
                            "component_version": "0.9.0",
                            "data": {"damage": 15},
                        }
                    ],
                }
            ],
        }

        result = reg.apply(old_snapshot)
        assert result["format_version"] == "1.0.0"
        comp_data = result["entities"][0]["components"][0]["data"]
        assert "strength" in comp_data
        assert "damage" not in comp_data
        assert comp_data["strength"] == 15
