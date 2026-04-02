"""Live smoke tests against a running Flask server on 127.0.0.1:8000.

Run with:
    python tests/smoke_api.py
"""
from __future__ import annotations

import json
import pathlib
import shutil
import urllib.request

BASE = "http://127.0.0.1:8000"
GAME = "smoketest"


def get(path: str, rid: str = "smoke-get") -> tuple[int, str, object]:
    req = urllib.request.Request(
        f"{BASE}{path}", headers={"X-Request-ID": rid}
    )
    with urllib.request.urlopen(req) as r:
        return r.status, r.headers.get("X-Request-ID", ""), json.loads(r.read())


def post(path: str, body: object, rid: str = "smoke-post") -> tuple[int, str, object]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json", "X-Request-ID": rid},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return r.status, r.headers.get("X-Request-ID", ""), json.loads(r.read())


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {label}")
    else:
        print(f"FAIL  {label}  {detail}")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# 1. Games list — empty
# ---------------------------------------------------------------------------
s, rid, body = get("/api/games", "smoke-001")
check("GET /api/games (empty)", s == 200 and isinstance(body, list) and rid == "smoke-001")

# ---------------------------------------------------------------------------
# 2. Create game
# ---------------------------------------------------------------------------
s, rid, body = post(
    "/api/games", {"name": GAME, "player1": "Alice", "player2": "Bob"}, "smoke-002"
)
check("POST /api/games (create)", s == 201 and body["game_id"] == GAME)  # type: ignore[index]

# ---------------------------------------------------------------------------
# 3. List — now contains game
# ---------------------------------------------------------------------------
s, _, body = get("/api/games")
ids = [g["id"] for g in body]  # type: ignore[union-attr]
check("GET /api/games (lists new game)", GAME in ids)

# ---------------------------------------------------------------------------
# 4. Game state
# ---------------------------------------------------------------------------
s, _, state = get(f"/api/game/{GAME}/state?player=Alice")
check(
    "GET /api/game/<id>/state",
    s == 200
    and state["player_name"] == "Alice"  # type: ignore[index]
    and "fleets" in state  # type: ignore[operator]
    and "star_systems" in state,  # type: ignore[operator]
)

# ---------------------------------------------------------------------------
# 5. Submit order
# ---------------------------------------------------------------------------
fleets = state["fleets"]  # type: ignore[index]
systems = state["star_systems"]  # type: ignore[index]
fleet_name = fleets[0]["name"] if fleets else "Alice_Fleet1"
current_sys = fleets[0]["system_id"] if fleets else None
dest_sys = next((sys["name"] for sys in systems if sys["id"] != current_sys), systems[0]["name"])

s, _, result = post(
    f"/api/game/{GAME}/orders",
    {"player": "Alice", "action_type": "MoveFleet",
     "action_data": {"fleet": fleet_name, "target": dest_sys}},
)
check(
    f"POST /api/game/<id>/orders (MoveFleet {fleet_name} -> {dest_sys})",
    s == 200 and result["valid"] is True,  # type: ignore[index]
    str(result),
)

# ---------------------------------------------------------------------------
# 6. Resolve turn
# ---------------------------------------------------------------------------
s, _, resolved = post(f"/api/game/{GAME}/resolve", {})
turn = resolved["turn"]  # type: ignore[index]
events = resolved["event_count"]  # type: ignore[index]
check(f"POST /api/game/<id>/resolve (turn={turn}, events={events})", s == 200 and turn == 1)

# ---------------------------------------------------------------------------
# 7. Metrics JSON
# ---------------------------------------------------------------------------
s, _, metrics = get("/api/metrics")
route_names = [r["route"] for r in metrics["routes"]]  # type: ignore[index]
check(
    f"GET /api/metrics (routes={route_names})",
    s == 200 and len(route_names) > 0,
)

# ---------------------------------------------------------------------------
# 8. Metrics CSV
# ---------------------------------------------------------------------------
req = urllib.request.Request(f"{BASE}/api/metrics?format=csv")
with urllib.request.urlopen(req) as r:
    csv_text = r.read().decode()
check("GET /api/metrics?format=csv", "route,method,count" in csv_text)

# ---------------------------------------------------------------------------
# 9. Telemetry ingest
# ---------------------------------------------------------------------------
s, _, t = post(
    "/api/telemetry",
    [{"request_id": "r1", "event_type": "smoke_test", "ts_ms": 1000, "data": {"ok": True}}],
)
check("POST /api/telemetry", s == 200 and t["accepted"] == 1)  # type: ignore[index]

# ---------------------------------------------------------------------------
# 10. X-Request-ID echo
# ---------------------------------------------------------------------------
req = urllib.request.Request(f"{BASE}/api/games", headers={"X-Request-ID": "my-custom-id"})
with urllib.request.urlopen(req) as r:
    echo = r.headers.get("X-Request-ID")
check("X-Request-ID echoed in response", echo == "my-custom-id", f"got {echo!r}")

# ---------------------------------------------------------------------------
print()
print("All 10 smoke tests passed.")

# Cleanup
shutil.rmtree(pathlib.Path("games") / GAME, ignore_errors=True)
