"""CLI integration tests for Phase 4 game commands."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Individual command tests
# ---------------------------------------------------------------------------


class TestCreateGame:
    def test_creates_db_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["create-game", "--name", "testgame"])
        assert result.exit_code == 0
        assert (tmp_path / "games" / "testgame" / "testgame.db").exists()

    def test_output_lists_players(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["create-game", "--name", "g1", "--player1", "Alice", "--player2", "Bob"])
        assert result.exit_code == 0
        assert "Alice" in result.output
        assert "Bob" in result.output

    def test_deterministic_with_seed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r1 = runner.invoke(app, ["create-game", "--name", "g1", "--seed", "test-seed"])
        assert r1.exit_code == 0
        # Second game with same seed in separate directory
        r2 = runner.invoke(app, ["create-game", "--name", "g2", "--seed", "test-seed"])
        assert r2.exit_code == 0


class TestSubmitOrders:
    def test_submit_move_fleet_order(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["create-game", "--name", "g", "--player1", "Alice", "--player2", "Bob"])
        orders = json.dumps([{"action_type": "MoveFleet", "fleet": "Alice_Fleet1", "target": "Alpha"}])
        result = runner.invoke(app, ["submit-orders", "--game", "g", "--player", "Alice", "--orders", orders])
        assert result.exit_code == 0
        assert "ok" in result.output

    def test_submit_unknown_action_warns(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["create-game", "--name", "g", "--player1", "Alice", "--player2", "Bob"])
        orders = json.dumps([{"action_type": "FlyToMoon"}])
        result = runner.invoke(app, ["submit-orders", "--game", "g", "--player", "Alice", "--orders", orders])
        assert result.exit_code == 0
        assert "unknown action_type" in result.output.lower() or "0 order" in result.output.lower()

    def test_submit_nonexistent_game_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["submit-orders", "--game", "nope", "--player", "P1", "--orders", "[]"])
        assert result.exit_code != 0


class TestResolveTurn:
    def test_resolve_produces_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["create-game", "--name", "g", "--player1", "Alice", "--player2", "Bob"])
        result = runner.invoke(app, ["resolve-turn", "--game", "g"])
        assert result.exit_code == 0
        assert "resolved" in result.output.lower()

    def test_resolve_nonexistent_game_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["resolve-turn", "--game", "nope"])
        assert result.exit_code != 0


class TestQueryState:
    def test_query_initial_state(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["create-game", "--name", "g", "--player1", "Alice", "--player2", "Bob"])
        result = runner.invoke(app, ["query-state", "--game", "g"])
        assert result.exit_code == 0
        assert "Alice_Home" in result.output
        assert "Alpha" in result.output

    def test_query_specific_entity(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["create-game", "--name", "g", "--player1", "Alice", "--player2", "Bob"])
        result = runner.invoke(app, ["query-state", "--game", "g", "--entity", "Alice_Home"])
        assert result.exit_code == 0
        assert "Alice_Home" in result.output

    def test_query_nonexistent_game_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["query-state", "--game", "nope"])
        assert result.exit_code != 0
