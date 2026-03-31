"""Integration tests for cli.server — Flask HTTP API layer."""

from __future__ import annotations

import json

import pytest

from cli.json_export import create_game
from cli.server import app as flask_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture()
def game_client(tmp_path, monkeypatch):
    """Client with a pre-created game."""
    monkeypatch.chdir(tmp_path)
    create_game("srv", player1="Alice", player2="Bob")
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/games
# ---------------------------------------------------------------------------


class TestListGamesRoute:
    def test_empty_returns_list(self, client):
        resp = client.get("/api/games")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_created_game(self, game_client):
        resp = game_client.get("/api/games")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["id"] == "srv"


# ---------------------------------------------------------------------------
# POST /api/games
# ---------------------------------------------------------------------------


class TestCreateGameRoute:
    def test_creates_game(self, client):
        resp = client.post(
            "/api/games",
            data=json.dumps({"name": "web_g", "player1": "Alice", "player2": "Bob"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["game_id"] == "web_g"
        assert "Alice" in body["players"]

    def test_missing_name_returns_400(self, client):
        resp = client.post(
            "/api/games",
            data=json.dumps({"player1": "Alice"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()


# ---------------------------------------------------------------------------
# GET /api/game/<id>/state
# ---------------------------------------------------------------------------


class TestGameStateRoute:
    def test_returns_state(self, game_client):
        resp = game_client.get("/api/game/srv/state?player=Alice")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["player_name"] == "Alice"
        assert "fleets" in body
        assert "star_systems" in body

    def test_missing_player_param_returns_400(self, game_client):
        resp = game_client.get("/api/game/srv/state")
        assert resp.status_code == 400

    def test_unknown_player_returns_404(self, game_client):
        resp = game_client.get("/api/game/srv/state?player=nobody")
        assert resp.status_code == 404

    def test_unknown_game_returns_error(self, client):
        resp = client.get("/api/game/nope/state?player=Alice")
        assert resp.status_code in (404, 500)


# ---------------------------------------------------------------------------
# POST /api/game/<id>/orders
# ---------------------------------------------------------------------------


class TestSubmitOrdersRoute:
    def test_valid_order_returns_200(self, game_client):
        body = {
            "player": "Alice",
            "action_type": "MoveFleet",
            "action_data": {"fleet": "Alice_Fleet1", "target": "Alpha"},
        }
        resp = game_client.post(
            "/api/game/srv/orders",
            data=json.dumps(body),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["valid"] is True

    def test_invalid_order_returns_422(self, game_client):
        body = {
            "player": "Alice",
            "action_type": "FlyToMoon",
            "action_data": {},
        }
        resp = game_client.post(
            "/api/game/srv/orders",
            data=json.dumps(body),
            content_type="application/json",
        )
        assert resp.status_code == 422
        assert resp.get_json()["valid"] is False

    def test_missing_fields_returns_400(self, game_client):
        resp = game_client.post(
            "/api/game/srv/orders",
            data=json.dumps({"player": "Alice"}),  # missing action_type
            content_type="application/json",
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/game/<id>/resolve
# ---------------------------------------------------------------------------


class TestResolveTurnRoute:
    def test_resolve_increments_turn(self, game_client):
        resp = game_client.post("/api/game/srv/resolve")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["turn"] == 1
        assert "event_count" in body

    def test_submit_then_resolve(self, game_client):
        game_client.post(
            "/api/game/srv/orders",
            data=json.dumps({
                "player": "Alice",
                "action_type": "MoveFleet",
                "action_data": {"fleet": "Alice_Fleet1", "target": "Alpha"},
            }),
            content_type="application/json",
        )
        resp = game_client.post("/api/game/srv/resolve")
        assert resp.status_code == 200
        body = resp.get_json()
        executed = [r for r in body["action_results"] if r["status"] == "executed"]
        assert len(executed) >= 1
