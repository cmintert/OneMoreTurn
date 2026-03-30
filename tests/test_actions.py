"""Tests for the Action protocol and ActionSystem."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from engine.actions import Action, ActionResult, ActionSystem, ValidationResult
from engine.ecs import World
from engine.events import Event
from engine.rng import SystemRNG
from engine.systems import SystemExecutor

from stubs import (
    ClaimAction,
    ClaimableComponent,
    IncrementScoreAction,
    PlayerComponent,
    ScoreComponent,
)


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_valid_result_is_truthy(self):
        result = ValidationResult(valid=True)
        assert result
        assert result.valid is True

    def test_invalid_result_is_falsy(self):
        result = ValidationResult(valid=False, errors=["bad"])
        assert not result
        assert result.valid is False

    def test_errors_and_warnings(self):
        result = ValidationResult(
            valid=True, errors=[], warnings=["heads up"]
        )
        assert result.warnings == ["heads up"]

    def test_defaults_to_empty_lists(self):
        result = ValidationResult(valid=True)
        assert result.errors == []
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Action ABC
# ---------------------------------------------------------------------------


class TestActionABC:
    def test_cannot_instantiate_without_implementing(self):
        with pytest.raises(TypeError):
            Action()

    def test_conflict_key_defaults_to_none(self):
        pid = uuid.uuid4()
        oid = uuid.uuid4()
        tid = uuid.uuid4()
        action = IncrementScoreAction(
            _player_id=pid, _order_id=oid, target_id=tid
        )
        assert action.conflict_key() is None

    def test_conflict_weight_defaults_to_one(self):
        pid = uuid.uuid4()
        oid = uuid.uuid4()
        tid = uuid.uuid4()
        action = IncrementScoreAction(
            _player_id=pid, _order_id=oid, target_id=tid
        )
        assert action.conflict_weight() == 1.0

    def test_claim_action_has_conflict_key(self):
        pid = uuid.uuid4()
        oid = uuid.uuid4()
        tid = uuid.uuid4()
        action = ClaimAction(_player_id=pid, _order_id=oid, target_id=tid)
        assert action.conflict_key() == f"claim:{tid}"


# ---------------------------------------------------------------------------
# Single action validation & execution
# ---------------------------------------------------------------------------


class TestSingleAction:
    def _make_player_world(self):
        """World with one player entity (Player + Score) and one claimable entity."""
        world = World()
        pid = uuid.uuid4()
        player_entity = world.create_entity([
            PlayerComponent(name="Alice", player_id=pid),
            ScoreComponent(score=0),
        ])
        claimable_entity = world.create_entity([ClaimableComponent()])
        return world, player_entity, claimable_entity, pid

    def test_increment_validates_success(self):
        world, player_entity, _, pid = self._make_player_world()
        action = IncrementScoreAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=player_entity.id
        )
        result = action.validate(world)
        assert result.valid

    def test_increment_validates_missing_entity(self):
        world, _, _, pid = self._make_player_world()
        action = IncrementScoreAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=uuid.uuid4()
        )
        result = action.validate(world)
        assert not result.valid
        assert "not found" in result.errors[0].lower()

    def test_increment_validates_wrong_player(self):
        world, player_entity, _, _ = self._make_player_world()
        other_pid = uuid.uuid4()
        action = IncrementScoreAction(
            _player_id=other_pid, _order_id=uuid.uuid4(), target_id=player_entity.id
        )
        result = action.validate(world)
        assert not result.valid
        assert "not your" in result.errors[0].lower()

    def test_increment_executes_and_emits_event(self):
        world, player_entity, _, pid = self._make_player_world()
        action = IncrementScoreAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=player_entity.id, amount=5
        )
        events = action.execute(world)
        assert len(events) == 1
        assert events[0].what == "ScoreIncremented"
        assert events[0].effects["new_score"] == 5
        assert player_entity.get(ScoreComponent).score == 5

    def test_claim_validates_success(self):
        world, _, claimable_entity, pid = self._make_player_world()
        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimable_entity.id
        )
        result = action.validate(world)
        assert result.valid

    def test_claim_validates_already_claimed(self):
        world, _, claimable_entity, pid = self._make_player_world()
        claimable_entity.get(ClaimableComponent).claimed_by = uuid.uuid4()
        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimable_entity.id
        )
        result = action.validate(world)
        assert not result.valid
        assert "already claimed" in result.errors[0].lower()

    def test_claim_executes(self):
        world, _, claimable_entity, pid = self._make_player_world()
        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimable_entity.id
        )
        events = action.execute(world)
        assert len(events) == 1
        assert events[0].what == "EntityClaimed"
        assert claimable_entity.get(ClaimableComponent).claimed_by == pid


# ---------------------------------------------------------------------------
# ActionSystem
# ---------------------------------------------------------------------------


class TestActionSystem:
    def _build_game(self, n_players=2, n_claimable=2):
        """Build a world with N players and M claimable entities."""
        world = World()
        game_id = uuid.uuid4()
        players = []
        for i in range(n_players):
            pid = uuid.uuid4()
            entity = world.create_entity([
                PlayerComponent(name=f"Player{i}", player_id=pid),
                ScoreComponent(score=0),
            ])
            players.append((entity, pid))
        claimables = []
        for _ in range(n_claimable):
            entity = world.create_entity([ClaimableComponent()])
            claimables.append(entity)
        return world, game_id, players, claimables

    def test_empty_actions_is_noop(self):
        world, game_id, _, _ = self._build_game()
        system = ActionSystem()
        system.set_actions([])
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)
        assert system.results == []

    def test_single_valid_action_executes(self):
        world, game_id, players, claimables = self._build_game()
        _, pid = players[0]
        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        system = ActionSystem()
        system.set_actions([action])
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)

        results = system.results
        assert len(results) == 1
        assert results[0].status == "executed"
        assert claimables[0].get(ClaimableComponent).claimed_by == pid

    def test_invalid_action_rejected_with_feedback(self):
        world, game_id, players, _ = self._build_game()
        _, pid = players[0]
        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=uuid.uuid4()
        )
        system = ActionSystem()
        system.set_actions([action])
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)

        results = system.results
        assert len(results) == 1
        assert results[0].status == "rejected"
        assert len(results[0].errors) > 0

    def test_invalid_does_not_block_valid(self):
        """DEV_PHASES exit test: invalid order in batch does not block valid ones."""
        world, game_id, players, claimables = self._build_game()
        _, pid_a = players[0]
        _, pid_b = players[1]

        invalid = IncrementScoreAction(
            _player_id=pid_a, _order_id=uuid.uuid4(), target_id=uuid.uuid4()
        )
        valid = ClaimAction(
            _player_id=pid_b, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        system = ActionSystem()
        system.set_actions([invalid, valid])
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)

        results = {r.status: r for r in system.results}
        assert "rejected" in results
        assert "executed" in results
        assert claimables[0].get(ClaimableComponent).claimed_by == pid_b

    def test_conflict_one_wins_one_loses(self):
        """DEV_PHASES exit test: two conflicting orders → one succeeds, one fails."""
        world, game_id, players, claimables = self._build_game()
        _, pid_a = players[0]
        _, pid_b = players[1]
        target = claimables[0]

        action_a = ClaimAction(
            _player_id=pid_a, _order_id=uuid.uuid4(), target_id=target.id
        )
        action_b = ClaimAction(
            _player_id=pid_b, _order_id=uuid.uuid4(), target_id=target.id
        )
        system = ActionSystem()
        system.set_actions([action_a, action_b])
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)

        results = system.results
        statuses = [r.status for r in results]
        assert "executed" in statuses
        assert "conflict_lost" in statuses
        # Exactly one winner
        assert statuses.count("executed") == 1
        assert statuses.count("conflict_lost") == 1

    def test_conflict_loser_gets_feedback(self):
        """Conflict loser gets ActionConflictLost event with details."""
        world, game_id, players, claimables = self._build_game()
        _, pid_a = players[0]
        _, pid_b = players[1]
        target = claimables[0]

        action_a = ClaimAction(
            _player_id=pid_a, _order_id=uuid.uuid4(), target_id=target.id
        )
        action_b = ClaimAction(
            _player_id=pid_b, _order_id=uuid.uuid4(), target_id=target.id
        )
        system = ActionSystem()
        system.set_actions([action_a, action_b])
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)

        conflict_events = [
            e for e in world.event_bus.emitted if e.what == "ActionConflictLost"
        ]
        assert len(conflict_events) == 1
        assert "conflict_key" in conflict_events[0].effects

    def test_conflict_resolution_determinism(self):
        """DEV_PHASES exit test: same seed produces same winner every time."""
        game_id = uuid.uuid4()
        target_id = uuid.uuid4()
        pid_a = uuid.uuid4()
        pid_b = uuid.uuid4()

        winners = []
        for _ in range(10):
            world = World()
            world.create_entity([
                PlayerComponent(name="A", player_id=pid_a),
                ScoreComponent(score=0),
            ])
            world.create_entity([
                PlayerComponent(name="B", player_id=pid_b),
                ScoreComponent(score=0),
            ])
            world.create_entity([ClaimableComponent()], entity_id=target_id)

            action_a = ClaimAction(
                _player_id=pid_a, _order_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                target_id=target_id,
            )
            action_b = ClaimAction(
                _player_id=pid_b, _order_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                target_id=target_id,
            )
            system = ActionSystem()
            system.set_actions([action_a, action_b])
            rng = SystemRNG(game_id, 0, "ActionSystem")
            system.update(world, rng)

            executed = [r for r in system.results if r.status == "executed"]
            winners.append(executed[0].player_id)

        # All runs produce the same winner
        assert len(set(winners)) == 1

    def test_non_conflicting_all_execute(self):
        world, game_id, players, claimables = self._build_game()
        _, pid_a = players[0]
        _, pid_b = players[1]

        # Each claims a different target
        action_a = ClaimAction(
            _player_id=pid_a, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        action_b = ClaimAction(
            _player_id=pid_b, _order_id=uuid.uuid4(), target_id=claimables[1].id
        )
        system = ActionSystem()
        system.set_actions([action_a, action_b])
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)

        assert all(r.status == "executed" for r in system.results)
        assert claimables[0].get(ClaimableComponent).claimed_by == pid_a
        assert claimables[1].get(ClaimableComponent).claimed_by == pid_b

    def test_deterministic_execution_order(self):
        """Actions execute in deterministic (action_type, order_id) order."""
        world, game_id, players, claimables = self._build_game(n_players=1, n_claimable=2)
        player_entity, pid = players[0]

        oid1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
        oid2 = uuid.UUID("00000000-0000-0000-0000-000000000002")

        actions = [
            ClaimAction(_player_id=pid, _order_id=oid2, target_id=claimables[1].id),
            ClaimAction(_player_id=pid, _order_id=oid1, target_id=claimables[0].id),
        ]
        system = ActionSystem()
        system.set_actions(actions)
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)

        executed = [r for r in system.results if r.status == "executed"]
        assert len(executed) == 2
        # oid1 should execute before oid2 (sorted by order_id)
        assert executed[0].order_id == oid1
        assert executed[1].order_id == oid2

    def test_action_executed_events_published(self):
        world, game_id, players, claimables = self._build_game()
        _, pid = players[0]
        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        system = ActionSystem()
        system.set_actions([action])
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)

        event_types = [e.what for e in world.event_bus.emitted]
        assert "EntityClaimed" in event_types
        assert "ActionExecuted" in event_types

    def test_action_rejected_events_published(self):
        world, game_id, players, _ = self._build_game()
        _, pid = players[0]
        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=uuid.uuid4()
        )
        system = ActionSystem()
        system.set_actions([action])
        rng = SystemRNG(game_id, 0, "ActionSystem")
        system.update(world, rng)

        event_types = [e.what for e in world.event_bus.emitted]
        assert "ActionRejected" in event_types

    def test_action_system_integrates_with_executor(self):
        """ActionSystem works within SystemExecutor as a regular system."""
        world, game_id, players, claimables = self._build_game()
        _, pid = players[0]

        action = ClaimAction(
            _player_id=pid, _order_id=uuid.uuid4(), target_id=claimables[0].id
        )
        action_system = ActionSystem()
        action_system.set_actions([action])

        executor = SystemExecutor(world, game_id, turn_number=0)
        executor.register(action_system)
        executor.execute_all()

        assert claimables[0].get(ClaimableComponent).claimed_by == pid
        assert any(e.what == "ActionExecuted" for e in world.event_bus.emitted)
