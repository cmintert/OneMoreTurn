"""JSON export functions for the Phase 6 web UI.

All functions are module-level and stateless: open a DB, read what is needed,
close the DB, return a plain dict.  No HTTP concerns live here.
"""

from __future__ import annotations

import pathlib
import uuid

from engine.components import ChildComponent, ContainerComponent
from engine.ecs import World
from engine.names import NameComponent, NameResolver
from engine.rng import SystemRNG
from engine.turn import TurnManager
from game.actions import ColonizePlanetAction, HarvestResourcesAction, MoveFleetAction
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    ResearchComponent,
    Resources,
    VisibilityComponent,
)
from game.registry import game_action_registry, game_component_registry, game_systems
from game.setup import setup_game
from game.summary import _event_visible_to_player
from persistence.db import GameDatabase


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _db_path(game_id: str) -> pathlib.Path:
    return pathlib.Path("games") / game_id / f"{game_id}.db"


def _entity_name(ent) -> str:
    return ent.get(NameComponent).name if ent.has(NameComponent) else str(ent.id)


def _resolve_player_id(world: World, player_name: str) -> uuid.UUID | None:
    for _, owner in world.query(Owner):
        if owner.player_name == player_name:
            return owner.player_id
    return None


def _sys_name(world: World, sys_id: uuid.UUID | None) -> str:
    if sys_id is None:
        return ""
    try:
        return _entity_name(world.get_entity(sys_id))
    except KeyError:
        return str(sys_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_games() -> list[dict]:
    """Return metadata for all available games, sorted by name."""
    games_dir = pathlib.Path("games")
    if not games_dir.exists():
        return []

    result = []
    for game_dir in sorted(games_dir.iterdir()):
        if not game_dir.is_dir():
            continue
        db_path = game_dir / f"{game_dir.name}.db"
        if not db_path.exists():
            continue
        try:
            db = GameDatabase(str(db_path))
            registry = game_component_registry()
            turn = db.latest_turn(game_dir.name)
            world = db.load_snapshot(game_dir.name, turn, registry)
            db.close()
            players = sorted({owner.player_name for _, owner in world.query(Owner)})
            result.append(
                {"id": game_dir.name, "name": game_dir.name, "turn": turn, "players": players}
            )
        except Exception:  # noqa: BLE001 — skip corrupt/unreadable games
            continue
    return result


def create_game(
    name: str,
    player1: str = "Player1",
    player2: str = "Player2",
    seed: str = "",
) -> dict:
    """Create a new 2-player game. Returns {game_id, players, turn}."""
    game_dir = pathlib.Path("games") / name
    game_dir.mkdir(parents=True, exist_ok=True)
    db_path = game_dir / f"{name}.db"

    db = GameDatabase(str(db_path))
    db.init_schema()
    registry = game_component_registry()

    world = World()
    rng_seed = seed if seed else name
    rng = SystemRNG(game_id=rng_seed, turn_number=0, system_name="setup")
    player_ids = setup_game(world, [player1, player2], rng)

    db.save_snapshot(name, 0, world, registry)
    db.close()

    return {
        "game_id": name,
        "players": {pname: str(pid) for pname, pid in player_ids.items()},
        "turn": 0,
    }


def export_game_state(game_id: str, player_name: str) -> dict:
    """Return game state visible to player_name with fog-of-war applied.

    Enemy entities outside observation range are absent from the response
    entirely — not nulled or redacted.  Stale entities (once seen, now
    out-of-range) appear in visible_entities with stale=True.
    """
    db = GameDatabase(str(_db_path(game_id)))
    registry = game_component_registry()
    turn = db.latest_turn(game_id)
    world = db.load_snapshot(game_id, turn, registry)
    events = db.load_events(game_id, turn)
    db.close()

    player_id = _resolve_player_id(world, player_name)
    if player_id is None:
        raise KeyError(f"Player '{player_name}' not found in game '{game_id}'")

    # -- Own fleets -----------------------------------------------------------
    fleets = []
    for ent, owner, fs, pos in world.query(Owner, FleetStats, Position):
        if owner.player_id != player_id:
            continue
        fleet_res = ent.get(Resources).amounts if ent.has(Resources) else {}
        fleets.append(
            {
                "id": str(ent.id),
                "name": _entity_name(ent),
                "position_x": pos.x,
                "position_y": pos.y,
                "system_id": str(pos.parent_system_id) if pos.parent_system_id else None,
                "system_name": _sys_name(world, pos.parent_system_id),
                "destination_id": (
                    str(fs.destination_system_id) if fs.destination_system_id else None
                ),
                "destination_name": _sys_name(world, fs.destination_system_id),
                "turns_remaining": fs.turns_remaining,
                "speed": fs.speed,
                "resources": fleet_res,
            }
        )

    # -- Own planets ----------------------------------------------------------
    planets = []
    for ent, owner, pop, res in world.query(Owner, PopulationStats, Resources):
        if owner.player_id != player_id:
            continue
        pos = ent.get(Position) if ent.has(Position) else None
        planets.append(
            {
                "id": str(ent.id),
                "name": _entity_name(ent),
                "system_id": (
                    str(pos.parent_system_id) if pos and pos.parent_system_id else None
                ),
                "system_name": _sys_name(world, pos.parent_system_id if pos else None),
                "position_x": pos.x if pos else 0.0,
                "position_y": pos.y if pos else 0.0,
                "resources": res.amounts,
                "population": pop.size,
                "morale": pop.morale,
                "growth_rate": pop.growth_rate,
            }
        )

    # -- Star systems (always visible on the map) ----------------------------
    star_systems = []
    for ent, _container, pos in world.query(ContainerComponent, Position):
        planet_ids = [
            str(e.id)
            for e, child in world.query(ChildComponent)
            if child.parent_id == ent.id
        ]
        star_systems.append(
            {
                "id": str(ent.id),
                "name": _entity_name(ent),
                "position_x": pos.x,
                "position_y": pos.y,
                "planet_ids": planet_ids,
            }
        )

    # -- Visible other entities (fog-of-war filtered) ------------------------
    visible_entities = []
    for ent, vis in world.query(VisibilityComponent):
        # Skip own entities — they're in fleets/planets above
        if ent.has(Owner) and ent.get(Owner).player_id == player_id:
            continue
        # Star systems are in star_systems list; don't duplicate
        if ent.has(ContainerComponent):
            continue
        if player_id in vis.visible_to:
            stale = False
        elif player_id in vis.revealed_to:
            stale = True
        else:
            continue  # not visible at all — omit entirely
        pos = ent.get(Position) if ent.has(Position) else None
        if ent.has(FleetStats):
            etype = "fleet"
        elif ent.has(PopulationStats):
            etype = "planet"
        else:
            etype = "unknown"
        visible_entities.append(
            {
                "id": str(ent.id),
                "name": _entity_name(ent),
                "type": etype,
                "position_x": pos.x if pos else 0.0,
                "position_y": pos.y if pos else 0.0,
                "stale": stale,
            }
        )

    # -- Events (fog-of-war filtered) ----------------------------------------
    filtered_events = [
        {
            "type": ev.what,
            "description": str(ev.effects),
            "entity_name": ev.who or "",
        }
        for ev in events
        if _event_visible_to_player(ev, player_id, world)
    ]

    # -- Research (if civ entity exists for this player) ---------------------
    research = None
    for ent, owner, rc in world.query(Owner, ResearchComponent):
        if owner.player_id == player_id:
            research = {
                "active_tech": rc.active_tech_id,
                "progress": rc.progress,
                "required_progress": rc.required_progress,
                "unlocked": list(rc.unlocked_techs),
            }
            break

    return {
        "turn": turn,
        "game_id": game_id,
        "player_name": player_name,
        "player_id": str(player_id),
        "fleets": fleets,
        "planets": planets,
        "star_systems": star_systems,
        "visible_entities": visible_entities,
        "events": filtered_events,
        "research": research,
    }


def submit_action(
    game_id: str,
    player_name: str,
    action_type: str,
    action_data: dict,
) -> dict:
    """Validate and queue one action. Returns {valid, errors, warnings}."""
    db = GameDatabase(str(_db_path(game_id)))
    registry = game_component_registry()
    turn = db.latest_turn(game_id)
    world = db.load_snapshot(game_id, turn, registry)
    resolver = NameResolver(world)

    player_id = _resolve_player_id(world, player_name)
    if player_id is None:
        db.close()
        return {
            "valid": False,
            "errors": [f"Player '{player_name}' not found"],
            "warnings": [],
        }

    action = _build_action({"action_type": action_type, **action_data}, player_id, resolver)
    if action is None:
        db.close()
        return {
            "valid": False,
            "errors": [f"Unknown action_type '{action_type}'"],
            "warnings": [],
        }

    tm = TurnManager(world, game_id, db, registry, systems=game_systems())
    result = tm.submit_order(action)
    if result.valid:
        db.save_orders(game_id, turn, tm.get_all_orders())
    db.close()
    return {"valid": result.valid, "errors": result.errors, "warnings": result.warnings}


def resolve_turn(game_id: str) -> dict:
    """Resolve the current turn. Returns {turn, action_results, event_count}."""
    db = GameDatabase(str(_db_path(game_id)))
    registry = game_component_registry()
    action_reg = game_action_registry()

    turn = db.latest_turn(game_id)
    world = db.load_snapshot(game_id, turn, registry)

    tm = TurnManager(world, game_id, db, registry, systems=game_systems())
    for action in db.load_orders(game_id, turn, action_reg):
        tm.submit_order(action)

    result = tm.resolve_turn()
    db.close()
    return {
        "turn": result.turn_number + 1,  # new current turn after resolution
        "action_results": [
            {"action_type": r.action_type, "status": r.status, "errors": r.errors}
            for r in result.results
        ],
        "event_count": len(result.events),
    }


# ---------------------------------------------------------------------------
# Internal action builder (mirrors cli/main.py _build_action)
# ---------------------------------------------------------------------------


def _build_action(order_dict: dict, player_id: uuid.UUID, resolver: NameResolver):
    """Construct a typed Action from a name-keyed order dict."""
    atype = order_dict.get("action_type", "")
    oid = uuid.uuid4()

    if atype == "MoveFleet":
        return MoveFleetAction(
            _player_id=player_id,
            _order_id=oid,
            fleet_id=resolver.resolve(order_dict["fleet"]),
            target_system_id=resolver.resolve(order_dict["target"]),
        )
    if atype == "ColonizePlanet":
        return ColonizePlanetAction(
            _player_id=player_id,
            _order_id=oid,
            fleet_id=resolver.resolve(order_dict["fleet"]),
            planet_id=resolver.resolve(order_dict["planet"]),
        )
    if atype == "HarvestResources":
        return HarvestResourcesAction(
            _player_id=player_id,
            _order_id=oid,
            fleet_id=resolver.resolve(order_dict["fleet"]),
            planet_id=resolver.resolve(order_dict["planet"]),
            resource_type=order_dict["resource_type"],
            amount=float(order_dict["amount"]),
        )
    return None
