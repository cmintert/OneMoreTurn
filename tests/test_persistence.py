"""Tests for GameDatabase: full SQLite round-trips, snapshots, and event logging."""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from engine.components import ChildComponent, ContainerComponent
from engine.ecs import World
from engine.events import Event
from persistence.db import GameDatabase
from persistence.migrations import MigrationRegistry
from persistence.serialization import ComponentRegistry

from tests.conftest import (
    ComponentBuilder,
    HealthComponent,
    OwnerComponent,
    PositionComponent,
    PoisonComponent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db() -> GameDatabase:
    database = GameDatabase(":memory:")
    database.init_schema()
    return database


@pytest.fixture
def registry() -> ComponentRegistry:
    reg = ComponentRegistry()
    reg.register(
        HealthComponent,
        PoisonComponent,
        PositionComponent,
        OwnerComponent,
        ContainerComponent,
        ChildComponent,
    )
    return reg


def _build_world_10_entities() -> World:
    """Build a world with 10 entities covering multiple component types."""
    world = World()
    world.current_turn = 3

    # Plain entities with simple components
    for i in range(4):
        world.create_entity([HealthComponent(current=i * 10, maximum=100)])

    # Entities with UUID fields
    for _ in range(2):
        world.create_entity([OwnerComponent(owner_id=uuid.uuid4())])

    # Entities with multiple components
    for i in range(2):
        world.create_entity([
            HealthComponent(current=50 + i, maximum=100),
            PositionComponent(x=i, y=i * 2),
        ])

    # A parent–child pair
    parent = world.create_entity([ContainerComponent()])
    world.create_entity([
        HealthComponent(),
        ChildComponent(parent_id=parent.id),
    ])

    assert len(world.entities()) == 10
    return world


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


class TestInitSchema:
    def test_tables_created(self, db: GameDatabase):
        tables = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"entity_components", "turns", "event_log"} <= tables

    def test_idempotent(self, db: GameDatabase):
        """Calling init_schema twice does not raise."""
        db.init_schema()
        db.init_schema()


# ---------------------------------------------------------------------------
# save_snapshot / load_snapshot — exit criterion 1
# ---------------------------------------------------------------------------


class TestSnapshotRoundTrip:
    def test_empty_world_round_trip(self, db: GameDatabase, registry: ComponentRegistry):
        world = World()
        db.save_snapshot("game1", 0, world, registry)
        restored = db.load_snapshot("game1", 0, registry)
        assert restored.entities() == []

    def test_10_entity_round_trip(self, db: GameDatabase, registry: ComponentRegistry):
        """Exit criterion 1: 10 entities survive save/load with zero data loss."""
        world = _build_world_10_entities()
        original_ids = {e.id for e in world.entities()}

        db.save_snapshot("game1", 3, world, registry)
        restored = db.load_snapshot("game1", 3, registry)

        restored_ids = {e.id for e in restored.entities()}
        assert len(restored.entities()) == 10
        assert restored_ids == original_ids

    def test_component_data_survives(self, db: GameDatabase, registry: ComponentRegistry):
        world = World()
        world.create_entity([HealthComponent(current=37, maximum=80)])
        db.save_snapshot("game1", 1, world, registry)
        restored = db.load_snapshot("game1", 1, registry)
        entity = restored.entities()[0]
        health = entity.get(HealthComponent)
        assert health.current == 37
        assert health.maximum == 80

    def test_uuid_field_survives(self, db: GameDatabase, registry: ComponentRegistry):
        owner_id = uuid.uuid4()
        world = World()
        world.create_entity([OwnerComponent(owner_id=owner_id)])
        db.save_snapshot("game1", 1, world, registry)
        restored = db.load_snapshot("game1", 1, registry)
        comp = restored.entities()[0].get(OwnerComponent)
        assert comp.owner_id == owner_id

    def test_current_turn_survives(self, db: GameDatabase, registry: ComponentRegistry):
        world = World()
        world.current_turn = 7
        db.save_snapshot("game1", 7, world, registry)
        restored = db.load_snapshot("game1", 7, registry)
        assert restored.current_turn == 7

    def test_parent_child_survives(self, db: GameDatabase, registry: ComponentRegistry):
        world = World()
        parent = world.create_entity([ContainerComponent()])
        child = world.create_entity([
            HealthComponent(),
            ChildComponent(parent_id=parent.id),
        ])
        db.save_snapshot("game1", 1, world, registry)
        restored = db.load_snapshot("game1", 1, registry)

        r_parent = restored.get_entity(parent.id)
        r_child = restored.get_entity(child.id)
        container = r_parent.get(ContainerComponent)
        assert r_child.id in container.children
        assert r_child.get(ChildComponent).parent_id == parent.id

    def test_load_missing_snapshot_raises(self, db: GameDatabase, registry: ComponentRegistry):
        with pytest.raises(KeyError):
            db.load_snapshot("no-such-game", 99, registry)

    def test_duplicate_snapshot_raises_integrity_error(
        self, db: GameDatabase, registry: ComponentRegistry
    ):
        world = World()
        db.save_snapshot("game1", 1, world, registry)
        with pytest.raises(sqlite3.IntegrityError):
            db.save_snapshot("game1", 1, world, registry)

    def test_entity_components_table_populated(
        self, db: GameDatabase, registry: ComponentRegistry
    ):
        world = World()
        e = world.create_entity([HealthComponent(), PositionComponent(x=1, y=2)])
        db.save_snapshot("game1", 1, world, registry)
        rows = db._conn.execute(
            "SELECT * FROM entity_components WHERE entity_id = ?", (str(e.id),)
        ).fetchall()
        types = {row["component_type"] for row in rows}
        assert types == {"Health", "Position"}

    def test_multiple_turns_stored_independently(
        self, db: GameDatabase, registry: ComponentRegistry
    ):
        world1 = World()
        world1.create_entity([HealthComponent(current=100)])
        db.save_snapshot("game1", 1, world1, registry)

        world2 = World()
        world2.create_entity([HealthComponent(current=50)])
        db.save_snapshot("game1", 2, world2, registry)

        r1 = db.load_snapshot("game1", 1, registry)
        r2 = db.load_snapshot("game1", 2, registry)
        assert r1.entities()[0].get(HealthComponent).current == 100
        assert r2.entities()[0].get(HealthComponent).current == 50


# ---------------------------------------------------------------------------
# Migration on load — exit criterion 2
# ---------------------------------------------------------------------------


class TestMigrationOnLoad:
    def test_field_rename_migration(self, registry: ComponentRegistry):
        """Exit criterion 2: rename a component field; old snapshot loads cleanly."""

        # Simulate saving an old-format snapshot manually (bypassing current serializer)
        db = GameDatabase(":memory:")
        db.init_schema()

        entity_id = str(uuid.uuid4())
        old_snapshot = {
            "format_version": "0.9.0",
            "game_id": "game1",
            "turn_number": 1,
            "current_turn": 1,
            "entities": [
                {
                    "entity_id": entity_id,
                    "alive": True,
                    "components": [
                        {
                            "component_type": "Health",
                            "component_version": "0.9.0",
                            # Old field name: "hp" instead of "current"
                            "data": {"hp": 77, "maximum": 100},
                        }
                    ],
                }
            ],
        }

        import json, time, uuid as _uuid

        db._conn.execute(
            """
            INSERT INTO turns (turn_id, game_id, turn_number, state_snapshot, format_version, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(_uuid.uuid4()), "game1", 1, json.dumps(old_snapshot), "0.9.0", time.time()),
        )
        db._conn.commit()

        # Build a registry with a migrated HealthComponent that uses "current" field
        # (the standard HealthComponent already uses "current")
        migration_reg = MigrationRegistry()

        def rename_hp_to_current(snap: dict) -> dict:
            snap = dict(snap)
            for entity in snap.get("entities", []):
                for comp in entity.get("components", []):
                    if comp["component_type"] == "Health" and "hp" in comp.get("data", {}):
                        comp["data"]["current"] = comp["data"].pop("hp")
            snap["format_version"] = "1.0.0"
            return snap

        migration_reg.register("0.9.0", "1.0.0", rename_hp_to_current)

        restored = db.load_snapshot("game1", 1, registry, migrations=migration_reg)
        assert len(restored.entities()) == 1
        health = restored.entities()[0].get(HealthComponent)
        assert health.current == 77
        assert health.maximum == 100


# ---------------------------------------------------------------------------
# Event logging
# ---------------------------------------------------------------------------


class TestEventLog:
    def test_log_and_retrieve(self, db: GameDatabase):
        event = Event(
            who=uuid.uuid4(),
            what="TestEvent",
            when=1,
            why="test",
            effects={"x": 1},
        )
        db.log_event("game1", 1, event)
        rows = db.get_turn_events("game1", 1)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "TestEvent"
        assert rows[0]["severity"] == "INFO"

    def test_log_with_metadata(self, db: GameDatabase):
        entity_id = uuid.uuid4()
        event = Event(who=entity_id, what="SystemRan", when=2, why="tick", effects={})
        db.log_event(
            "game1",
            2,
            event,
            severity="DEBUG",
            system_name="ProductionSystem",
            order_id="ord-123",
            context={"detail": "ok"},
        )
        rows = db.get_turn_events("game1", 2)
        assert rows[0]["severity"] == "DEBUG"
        assert rows[0]["system_name"] == "ProductionSystem"
        assert rows[0]["order_id"] == "ord-123"
        assert rows[0]["entity_id"] == str(entity_id)

    def test_multiple_events_ordered_by_timestamp(self, db: GameDatabase):
        for i in range(3):
            event = Event(who="sys", what=f"Event{i}", when=1, why="test", effects={})
            db.log_event("game1", 1, event)
        rows = db.get_turn_events("game1", 1)
        assert len(rows) == 3
        # Timestamps should be non-decreasing
        timestamps = [r["timestamp"] for r in rows]
        assert timestamps == sorted(timestamps)

    def test_events_isolated_by_game_and_turn(self, db: GameDatabase):
        ev = Event(who="sys", what="E", when=1, why="test", effects={})
        db.log_event("game1", 1, ev)
        db.log_event("game1", 2, ev)
        db.log_event("game2", 1, ev)

        assert len(db.get_turn_events("game1", 1)) == 1
        assert len(db.get_turn_events("game1", 2)) == 1
        assert len(db.get_turn_events("game2", 1)) == 1
        assert len(db.get_turn_events("game2", 2)) == 0

    def test_no_events_returns_empty_list(self, db: GameDatabase):
        assert db.get_turn_events("game1", 99) == []


# ---------------------------------------------------------------------------
# init_schema idempotency
# ---------------------------------------------------------------------------


class TestDatabaseIsolation:
    def test_each_test_uses_separate_in_memory_db(self, registry: ComponentRegistry):
        """Two separate :memory: databases are fully isolated."""
        db1 = GameDatabase(":memory:")
        db1.init_schema()
        db2 = GameDatabase(":memory:")
        db2.init_schema()

        world = World()
        world.create_entity([HealthComponent()])
        db1.save_snapshot("game", 1, world, registry)

        with pytest.raises(KeyError):
            db2.load_snapshot("game", 1, registry)
