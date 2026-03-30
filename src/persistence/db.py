"""SQLite-backed persistence for game state."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid

from engine.ecs import World
from engine.events import Event
from persistence.migrations import MigrationRegistry
from persistence.serialization import ComponentRegistry, deserialize_world, serialize_world


class GameDatabase:
    """SQLite-backed store for world snapshots, entity components, and event logs.

    Pass ``db_path=":memory:"`` for in-memory databases (tests). Pass a file
    path for durable storage (e.g. ``"games/mygame/mygame.db"``).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        """Create all tables if they do not already exist.

        Safe to call multiple times (uses CREATE TABLE IF NOT EXISTS).
        """
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entity_components (
                entity_id      TEXT NOT NULL,
                component_type TEXT NOT NULL,
                component_data TEXT NOT NULL,
                PRIMARY KEY (entity_id, component_type)
            );

            CREATE TABLE IF NOT EXISTS turns (
                turn_id        TEXT PRIMARY KEY,
                game_id        TEXT NOT NULL,
                turn_number    INTEGER NOT NULL,
                state_snapshot TEXT NOT NULL,
                format_version TEXT NOT NULL,
                resolved_at    REAL NOT NULL,
                UNIQUE (game_id, turn_number)
            );

            CREATE TABLE IF NOT EXISTS event_log (
                log_id      TEXT PRIMARY KEY,
                game_id     TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                timestamp   REAL NOT NULL,
                severity    TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                system_name TEXT,
                entity_id   TEXT,
                order_id    TEXT,
                context     TEXT,
                message     TEXT NOT NULL
            );
            """
        )

    def save_snapshot(
        self,
        game_id: str,
        turn_number: int,
        world: World,
        registry: ComponentRegistry,
        format_version: str = "1.0.0",
    ) -> None:
        """Serialize world and persist to turns and entity_components tables.

        Both writes happen in a single transaction. Raises
        ``sqlite3.IntegrityError`` if a snapshot for (game_id, turn_number)
        already exists.
        """
        snapshot = serialize_world(world, game_id=game_id, format_version=format_version)
        snapshot_json = json.dumps(snapshot, sort_keys=True)

        component_rows = [
            (
                entity_record["entity_id"],
                comp_record["component_type"],
                json.dumps(comp_record["data"], sort_keys=True),
            )
            for entity_record in snapshot["entities"]
            for comp_record in entity_record["components"]
        ]

        turn_id = str(uuid.uuid4())
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO turns
                    (turn_id, game_id, turn_number, state_snapshot, format_version, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (turn_id, game_id, turn_number, snapshot_json, format_version, time.time()),
            )
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO entity_components
                    (entity_id, component_type, component_data)
                VALUES (?, ?, ?)
                """,
                component_rows,
            )

    def load_snapshot(
        self,
        game_id: str,
        turn_number: int,
        registry: ComponentRegistry,
        migrations: MigrationRegistry | None = None,
    ) -> World:
        """Load and deserialize the snapshot for (game_id, turn_number).

        If a ``MigrationRegistry`` is provided, migrations are applied before
        deserialization.

        Raises ``KeyError`` if no snapshot exists for the given game and turn.
        """
        row = self._conn.execute(
            "SELECT state_snapshot FROM turns WHERE game_id = ? AND turn_number = ?",
            (game_id, turn_number),
        ).fetchone()

        if row is None:
            raise KeyError(
                f"No snapshot found for game_id={game_id!r}, turn_number={turn_number}"
            )

        snapshot = json.loads(row["state_snapshot"])

        if migrations is not None:
            snapshot = migrations.apply(snapshot)

        return deserialize_world(snapshot, registry)

    def log_event(
        self,
        game_id: str,
        turn_number: int,
        event: Event,
        severity: str = "INFO",
        system_name: str | None = None,
        order_id: str | None = None,
        context: dict | None = None,
    ) -> None:
        """Insert one structured row into the event_log table."""
        entity_id = str(event.who) if event.who is not None else None
        message = f"{event.what}: {event.effects}"
        context_json = json.dumps(context, sort_keys=True) if context is not None else None

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO event_log
                    (log_id, game_id, turn_number, timestamp, severity, event_type,
                     system_name, entity_id, order_id, context, message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    game_id,
                    turn_number,
                    event.timestamp,
                    severity,
                    event.what,
                    system_name,
                    entity_id,
                    order_id,
                    context_json,
                    message,
                ),
            )

    def get_turn_events(self, game_id: str, turn_number: int) -> list[dict]:
        """Return all event_log rows for (game_id, turn_number), ordered by timestamp."""
        rows = self._conn.execute(
            """
            SELECT * FROM event_log
            WHERE game_id = ? AND turn_number = ?
            ORDER BY timestamp
            """,
            (game_id, turn_number),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
