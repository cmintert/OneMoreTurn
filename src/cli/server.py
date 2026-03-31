"""Flask HTTP server for the Phase 6 web UI.

Routes:
    GET  /                                     Serve index.html
    GET  /web/<path>                           Serve static files from src/web/
    GET  /api/games                            list_games()
    POST /api/games                            create_game()
    GET  /api/game/<game_id>/state?player=...  export_game_state()
    POST /api/game/<game_id>/orders            submit_action()
    POST /api/game/<game_id>/resolve           resolve_turn()
"""

from __future__ import annotations

import pathlib

from flask import Flask, jsonify, request, send_from_directory

from cli.json_export import (
    create_game,
    export_game_state,
    list_games,
    resolve_turn,
    submit_action,
)

_WEB_DIR = pathlib.Path(__file__).parent.parent / "web"

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return send_from_directory(_WEB_DIR, "index.html")


@app.route("/web/<path:filename>")
def web_static(filename):
    return send_from_directory(_WEB_DIR, filename)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.route("/api/games", methods=["GET"])
def api_list_games():
    try:
        return jsonify(list_games())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/games", methods=["POST"])
def api_create_game():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    player1 = body.get("player1", "Player1")
    player2 = body.get("player2", "Player2")
    seed = body.get("seed", "")
    try:
        result = create_game(name, player1=player1, player2=player2, seed=seed)
        return jsonify(result), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/game/<game_id>/state", methods=["GET"])
def api_game_state(game_id: str):
    player = request.args.get("player", "").strip()
    if not player:
        return jsonify({"error": "player query parameter is required"}), 400
    try:
        state = export_game_state(game_id, player)
        return jsonify(state)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/game/<game_id>/orders", methods=["POST"])
def api_submit_orders(game_id: str):
    body = request.get_json(silent=True) or {}
    player = body.get("player", "").strip()
    action_type = body.get("action_type", "").strip()
    action_data = body.get("action_data", {})
    if not player or not action_type:
        return jsonify({"error": "player and action_type are required"}), 400
    try:
        result = submit_action(game_id, player, action_type, action_data)
        status_code = 200 if result["valid"] else 422
        return jsonify(result), status_code
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/game/<game_id>/resolve", methods=["POST"])
def api_resolve_turn(game_id: str):
    try:
        result = resolve_turn(game_id)
        return jsonify(result)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_server(host: str = "127.0.0.1", port: int = 8000, debug: bool = False) -> None:
    """Start the Flask development server."""
    app.run(host=host, port=port, debug=debug)
