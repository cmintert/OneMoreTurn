"""Tests for the TurnManager and turn resolution loop."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from engine.actions import ActionSystem, ValidationResult
from engine.ecs import World
from engine.names import NameComponent
from engine.turn import TurnError, TurnManager, TurnResult, TurnState
from persistence.db import GameDatabase
from persistence.serialization import ComponentRegistry

from stubs import (
    ClaimAction,
    ClaimableComponent,
    IncrementScoreAction,
    PlayerComponent,
    ScoreBonusSystem,
    ScoreComponent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry():
    """ComponentRegistry with all stub components registered."""
    reg = ComponentRegistry()
    reg.register(
        PlayerComponent, ScoreComponent, ClaimableComponent, NameComponent
    )
    return reg


@pytest.fixture
def db():
    """In-memory database for tests."""
    database = GameDatabase(":memory:")
    database.init_schema()
    return database


def _build_game(db, registry, n_players=2, n_claimable=2):
    """Build a world with players and claimable entities, save turn 0."""
    world = World()
    game_id = str(uuid.uuid4())
    players = []
    for i in range(n_players):
        pid = uuid.uuid4()
        entity = world.create_entity([
            PlayerComponent(name=f"Player{i}", player_id=pid),
            ScoreComponent(score=0),
            NameComponent(name=f"Player{i}"),
        ])
        players.append((entity, pid))
    claimables = []
    for i in range(n_claimable):
        entity = world.create_entity([
            ClaimableComponent(),
            NameComponent(name=f"Target{i}"),
        ])
        claimables.append(entity)

    # Save initial snapshot (turn 0)
    db.save_snapshot(game_id, 0, world, registry)
    return world, game_id, players, claimables


# ---------------------------------------------------------------------------
# TurnState
# ---------------------------------------------------------------------------


class TestTurnState:
    def test_initial_state_is_orders_open(self, db, registry):
        world, game_id, _, _ = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        assert tm.state == TurnState.ORDERS_OPEN

    def test_current_turn_matches_world(self, db, registry):
        world, game_id, _, _ = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        assert tm.current_turn == world.current_turn


# ---------------------------------------------------------------------------
# Order submission
# ---------------------------------------------------------------------------


class TestOrderSubmission:
    def test_submit_valid_order_returns_valid(self, db, registry):
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        result = tm.submit_order(action)
        assert result.valid

    def test_submit_invalid_order_returns_errors(self, db, registry):
        world, game_id, players, _ = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=uuid.uuid4()
        )
        result = tm.submit_order(action)
        assert not result.valid
        assert len(result.errors) > 0

    def test_get_orders_returns_submitted(self, db, registry):
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        tm.submit_order(action)
        orders = tm.get_orders(pid)
        assert len(orders) == 1

    def test_replace_order_supersedes_original(self, db, registry):
        """DEV_PHASES exit test: replacement order supersedes original."""
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]
        oid = uuid.uuid4()

        original = ClaimAction(
            _player_id=pid, _order_id=oid, target_id=claimables[0].id
        )
        tm.submit_order(original)

        replacement = ClaimAction(
            _player_id=pid, _order_id=oid, target_id=claimables[1].id
        )
        tm.replace_order(oid, replacement)

        orders = tm.get_orders(pid)
        assert len(orders) == 1
        assert orders[0].target_id == claimables[1].id

    def test_remove_order(self, db, registry):
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]
        oid = uuid.uuid4()

        action = ClaimAction(
            _player_id=pid, _order_id=oid, target_id=claimables[0].id
        )
        tm.submit_order(action)
        tm.remove_order(pid, oid)
        assert tm.get_orders(pid) == []


# ---------------------------------------------------------------------------
# Turn resolution
# ---------------------------------------------------------------------------


class TestTurnResolution:
    def test_resolve_returns_turn_result(self, db, registry):
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        tm.submit_order(action)
        result = tm.resolve_turn()

        assert isinstance(result, TurnResult)
        assert result.turn_number == 0
        assert len(result.events) > 0
        assert result.snapshot_id != ""

    def test_resolve_saves_snapshot_to_db(self, db, registry):
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        tm.submit_order(action)
        tm.resolve_turn()

        # Snapshot for turn 1 should exist (post-resolution state)
        loaded = db.load_snapshot(game_id, 1, registry)
        assert len(loaded.entities()) > 0

    def test_resolve_saves_events_to_db(self, db, registry):
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        tm.submit_order(action)
        tm.resolve_turn()

        events = db.get_turn_events(game_id, 0)
        assert len(events) > 0

    def test_resolve_advances_turn(self, db, registry):
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        tm.submit_order(action)
        tm.resolve_turn()
        assert tm.current_turn == 1

    def test_resolve_clears_orders(self, db, registry):
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        tm.submit_order(action)
        tm.resolve_turn()
        assert tm.get_orders(pid) == []

    def test_state_returns_to_open_after_resolve(self, db, registry):
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(world, game_id, db, registry)
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        tm.submit_order(action)
        tm.resolve_turn()
        assert tm.state == TurnState.ORDERS_OPEN

    def test_resolve_with_extra_system(self, db, registry):
        """Systems beyond ActionSystem run during resolution."""
        world, game_id, players, claimables = _build_game(db, registry)
        tm = TurnManager(
            world, game_id, db, registry,
            systems=[ScoreBonusSystem()],
        )
        _, pid_a = players[0]
        _, pid_b = players[1]

        action = ClaimAction(
            _player_id=pid_a, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        tm.submit_order(action)
        tm.resolve_turn()

        # ScoreBonusSystem awards +1 to players who own something claimed
        player_a_entity = players[0][0]
        assert player_a_entity.get(ScoreComponent).score == 1


# ---------------------------------------------------------------------------
# Multi-turn
# ---------------------------------------------------------------------------


class TestMultiTurn:
    def test_three_turns_accumulate_state(self, db, registry):
        """DEV_PHASES exit: 3 turns resolve correctly with state accumulation."""
        world, game_id, players, claimables = _build_game(
            db, registry, n_players=2, n_claimable=3
        )
        tm = TurnManager(world, game_id, db, registry)
        _, pid_a = players[0]
        _, pid_b = players[1]
        player_a = players[0][0]

        # Turn 0: player A claims target 0
        tm.submit_order(ClaimAction(
            _player_id=pid_a, _order_id=uuid.uuid4(), target_id=claimables[0].id
        ))
        tm.resolve_turn()
        assert claimables[0].get(ClaimableComponent).claimed_by == pid_a

        # Turn 1: player A increments score
        tm.submit_order(IncrementScoreAction(
            _player_id=pid_a, _order_id=uuid.uuid4(),
            target_id=player_a.id, amount=10,
        ))
        tm.resolve_turn()
        assert player_a.get(ScoreComponent).score == 10

        # Turn 2: player B claims target 1
        tm.submit_order(ClaimAction(
            _player_id=pid_b, _order_id=uuid.uuid4(), target_id=claimables[1].id
        ))
        tm.resolve_turn()
        assert claimables[1].get(ClaimableComponent).claimed_by == pid_b
        assert tm.current_turn == 3


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_replay_from_snapshot_produces_identical_state(self, db, registry):
        """DEV_PHASES exit: turn resolved twice from same snapshot = identical output."""
        world, game_id, players, claimables = _build_game(db, registry)
        _, pid_a = players[0]
        _, pid_b = players[1]
        player_a = players[0][0]

        # Turn 0: claim + increment
        tm = TurnManager(world, game_id, db, registry)
        tm.submit_order(ClaimAction(
            _player_id=pid_a,
            _order_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            target_id=claimables[0].id,
        ))
        tm.submit_order(IncrementScoreAction(
            _player_id=pid_a,
            _order_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            target_id=player_a.id, amount=5,
        ))
        result1 = tm.resolve_turn()

        # Replay: load turn 0 snapshot and re-run with same orders
        world2 = db.load_snapshot(game_id, 0, registry)
        # Use a fresh db to avoid UNIQUE constraint on save
        db2 = GameDatabase(":memory:")
        db2.init_schema()
        db2.save_snapshot(game_id, 0, world2, registry)

        tm2 = TurnManager(world2, game_id, db2, registry)
        tm2.submit_order(ClaimAction(
            _player_id=pid_a,
            _order_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            target_id=claimables[0].id,
        ))
        tm2.submit_order(IncrementScoreAction(
            _player_id=pid_a,
            _order_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            target_id=player_a.id, amount=5,
        ))
        result2 = tm2.resolve_turn()

        # Compare: same event types in same order
        assert [e.what for e in result1.events] == [e.what for e in result2.events]
        assert result1.turn_number == result2.turn_number

        # Compare final world state
        for entity2 in world2.entities():
            if entity2.has(ScoreComponent):
                score2 = entity2.get(ScoreComponent).score
                # Find corresponding entity in world1
                entity1 = world.get_entity(entity2.id)
                score1 = entity1.get(ScoreComponent).score
                assert score1 == score2

            if entity2.has(ClaimableComponent):
                claim2 = entity2.get(ClaimableComponent).claimed_by
                entity1 = world.get_entity(entity2.id)
                claim1 = entity1.get(ClaimableComponent).claimed_by
                assert claim1 == claim2
