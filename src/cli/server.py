"""Flask HTTP server for the OneMoreTurn web UI.

Routes:
    GET  /                                     Serve index.html
    GET  /assets/<path>                        Serve Vite-built assets
    GET  /api/games                            list_games()
    POST /api/games                            create_game()
    GET  /api/game/<game_id>/state?player=...  export_game_state()
    POST /api/game/<game_id>/orders            submit_action()
    POST /api/game/<game_id>/resolve           resolve_turn()
    GET  /api/metrics?format=json|csv          metrics export
    POST /api/telemetry                        client telemetry ingest
"""

from __future__ import annotations

import pathlib

from flask import Flask, Response, jsonify, request, send_from_directory

from cli.json_export import (
    create_game,
    export_game_state,
    list_games,
    resolve_turn,
    submit_action,
)
from cli.metrics import MetricsStore, RequestRecord, TelemetryEvent

_WEB_DIR = pathlib.Path(__file__).parent.parent / "web"
_DIST_DIR = _WEB_DIR / "dist"

app = Flask(__name__)
metrics = MetricsStore()
_telemetry_enabled = True


# ---------------------------------------------------------------------------
# Request middleware — X-Request-ID + timing
# ---------------------------------------------------------------------------


@app.before_request
def _before_request():
    rid = request.headers.get("X-Request-ID") or MetricsStore.generate_request_id()
    request._request_id = rid  # type: ignore[attr-defined]
    request._start_time = MetricsStore.perf_now()  # type: ignore[attr-defined]


@app.after_request
def _after_request(response):
    rid = getattr(request, "_request_id", "")
    response.headers["X-Request-ID"] = rid

    if _telemetry_enabled:
        start = getattr(request, "_start_time", None)
        duration_ms = (MetricsStore.perf_now() - start) * 1000 if start else 0.0
        metrics.record_request(
            RequestRecord(
                request_id=rid,
                route=request.path,
                method=request.method,
                status=response.status_code,
                duration_ms=round(duration_ms, 2),
                ts=MetricsStore.wall_now(),
            )
        )
    return response


# ---------------------------------------------------------------------------
# Static file serving — serves Vite build output (web/dist/) or legacy (web/)
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    if (_DIST_DIR / "index.html").exists():
        return send_from_directory(_DIST_DIR, "index.html")
    return send_from_directory(_WEB_DIR, "index.html")


@app.route("/assets/<path:filename>")
def assets_static(filename):
    return send_from_directory(_DIST_DIR / "assets", filename)


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
# Metrics & telemetry routes
# ---------------------------------------------------------------------------


@app.route("/api/metrics", methods=["GET"])
def api_metrics():
    fmt = request.args.get("format", "json").lower()
    if fmt == "csv":
        return Response(metrics.export_csv(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=metrics.csv"})
    return jsonify(metrics.export_json())


@app.route("/api/telemetry", methods=["POST"])
def api_telemetry():
    if not _telemetry_enabled:
        return jsonify({"accepted": 0}), 200
    body = request.get_json(silent=True)
    if not isinstance(body, list):
        body = [body] if body else []
    count = 0
    for item in body[:100]:  # cap batch size to prevent abuse
        if not isinstance(item, dict):
            continue
        metrics.record_telemetry(
            TelemetryEvent(
                request_id=item.get("request_id", ""),
                event_type=item.get("event_type", ""),
                ts_ms=item.get("ts_ms", 0),
                data=item.get("data", {}),
            )
        )
        count += 1
    return jsonify({"accepted": count}), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    debug: bool = False,
    telemetry: bool = True,
) -> None:
    """Start the Flask development server."""
    global _telemetry_enabled  # noqa: PLW0603
    _telemetry_enabled = telemetry
    app.run(host=host, port=port, debug=debug)
