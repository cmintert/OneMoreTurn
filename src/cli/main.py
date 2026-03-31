"""OneMoreTurn CLI — thin orchestration layer over the Turn Engine.

Commands:
    create-game    Create a new 2-player game with star systems and fleets.
    submit-orders  Submit player orders (JSON).
    resolve-turn   Resolve the current turn.
    query-state    Display game state for a given turn.
    turn-summary   Per-player fog-of-war turn summary.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import uuid

import typer

from engine.ecs import World
from engine.names import NameComponent, NameResolver
from engine.rng import SystemRNG
from engine.turn import TurnManager
from game.actions import ColonizePlanetAction, HarvestResourcesAction, MoveFleetAction
from game.components import Owner, Position, VisibilityComponent
from game.registry import game_action_registry, game_component_registry, game_systems
from game.setup import setup_game
from game.summary import generate_turn_summary
from persistence.db import GameDatabase

app = typer.Typer(name="onemoreturn", help="OneMoreTurn PBEM 4X turn engine CLI.")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def create_game(
    name: str = typer.Option(..., help="Game name (also used for DB filename)."),
    player1: str = typer.Option("Player1", help="Name for player 1."),
    player2: str = typer.Option("Player2", help="Name for player 2."),
    seed: str = typer.Option("", help="Deterministic seed (default: game name)."),
) -> None:
    """Create a new 2-player game with star systems and fleets."""
    game_dir = pathlib.Path("games") / name
    game_dir.mkdir(parents=True, exist_ok=True)
    db_path = game_dir / f"{name}.db"

    db = GameDatabase(str(db_path))
    db.init_schema()
    registry = game_component_registry()

    world = World()
    game_id = name
    rng_seed = seed if seed else name
    rng = SystemRNG(game_id=rng_seed, turn_number=0, system_name="setup")

    player_ids = setup_game(world, [player1, player2], rng)

    db.save_snapshot(game_id, 0, world, registry)
    db.close()

    typer.echo(f"Game '{game_id}' created at {db_path}")
    for pname, pid in player_ids.items():
        typer.echo(f"  {pname}: {pid}")


@app.command()
def submit_orders(
    game: str = typer.Option(..., help="Game name."),
    player: str = typer.Option(..., help="Player name."),
    orders: str = typer.Option(..., help="JSON string with list of order dicts."),
) -> None:
    """Submit player orders for the current turn.

    Each order dict needs: action_type, and action-specific fields.
    Entity references use human-readable names (resolved via NameResolver).

    Example orders JSON:
        '[{"action_type": "MoveFleet", "fleet": "Alice_Fleet1", "target": "Alpha"}]'
    """
    db_path = pathlib.Path("games") / game / f"{game}.db"
    if not db_path.exists():
        typer.echo(f"Error: game '{game}' not found at {db_path}", err=True)
        raise typer.Exit(1)

    db = GameDatabase(str(db_path))
    registry = game_component_registry()

    turn_number = db.latest_turn(game)
    world = db.load_snapshot(game, turn_number, registry)
    resolver = NameResolver(world)

    # Find player_id from owner components
    pid = _resolve_player_id(world, player)
    if pid is None:
        typer.echo(f"Error: player '{player}' not found.", err=True)
        db.close()
        raise typer.Exit(1)

    tm = TurnManager(world, game, db, registry, systems=game_systems())
    action_list = json.loads(orders)

    for order_dict in action_list:
        action = _build_action(order_dict, pid, resolver)
        if action is None:
            typer.echo(f"Warning: unknown action_type '{order_dict.get('action_type')}'", err=True)
            continue
        result = tm.submit_order(action)
        status = "ok" if result.valid else f"invalid ({', '.join(result.errors)})"
        typer.echo(f"  Order {action.order_id}: {action.action_type()} -> {status}")

    all_orders = tm.get_all_orders()
    if all_orders:
        db.save_orders(game, turn_number, all_orders)
    db.close()
    typer.echo(f"Submitted {len(action_list)} order(s) for {player} (turn {turn_number}).")


@app.command()
def resolve_turn(
    game: str = typer.Option(..., help="Game name."),
) -> None:
    """Resolve the current turn: validate, execute actions, run systems, save snapshot."""
    db_path = pathlib.Path("games") / game / f"{game}.db"
    if not db_path.exists():
        typer.echo(f"Error: game '{game}' not found at {db_path}", err=True)
        raise typer.Exit(1)

    db = GameDatabase(str(db_path))
    registry = game_component_registry()
    action_reg = game_action_registry()

    turn_number = db.latest_turn(game)
    world = db.load_snapshot(game, turn_number, registry)

    tm = TurnManager(world, game, db, registry, systems=game_systems())

    saved_actions = db.load_orders(game, turn_number, action_reg)
    for action in saved_actions:
        tm.submit_order(action)

    result = tm.resolve_turn()

    typer.echo(f"Turn {result.turn_number} resolved.")
    typer.echo(f"  Events: {len(result.events)}")
    for r in result.results:
        typer.echo(f"  [{r.status}] {r.action_type} (order {r.order_id})")
    typer.echo(f"  Snapshot saved: {result.snapshot_id}")


@app.command()
def query_state(
    game: str = typer.Option(..., help="Game name."),
    turn: int = typer.Option(-1, help="Turn number (-1 = latest)."),
    entity: str = typer.Option("", help="Filter by entity name (optional)."),
    player: str = typer.Option("", help="Filter by player visibility (optional)."),
) -> None:
    """Display game state for a given turn."""
    db_path = pathlib.Path("games") / game / f"{game}.db"
    if not db_path.exists():
        typer.echo(f"Error: game '{game}' not found at {db_path}", err=True)
        raise typer.Exit(1)

    db = GameDatabase(str(db_path))
    registry = game_component_registry()

    turn_number = turn if turn >= 0 else db.latest_turn(game)
    world = db.load_snapshot(game, turn_number, registry)

    # Resolve player filter
    player_id: uuid.UUID | None = None
    if player:
        player_id = _resolve_player_id(world, player)
        if player_id is None:
            typer.echo(f"Error: player '{player}' not found.", err=True)
            db.close()
            raise typer.Exit(1)

    typer.echo(f"Game: {game}  Turn: {turn_number}")
    typer.echo("-" * 40)

    for ent in sorted(world.entities(), key=lambda e: e.id):
        ent_name = ent.get(NameComponent).name if ent.has(NameComponent) else str(ent.id)

        if entity and ent_name != entity:
            continue

        # Player visibility filter
        if player_id is not None and ent.has(VisibilityComponent):
            vis = ent.get(VisibilityComponent)
            if player_id not in vis.visible_to and player_id not in vis.revealed_to:
                continue
            stale = player_id in vis.revealed_to and player_id not in vis.visible_to
        else:
            stale = False

        label = " [stale]" if stale else ""
        typer.echo(f"\n{ent_name} ({ent.id}){label}")
        for comp in ent.components().values():
            typer.echo(f"  {comp.component_name()}: {_comp_summary(comp)}")

    db.close()


@app.command()
def turn_summary(
    game: str = typer.Option(..., help="Game name."),
    player: str = typer.Option(..., help="Player name."),
    turn: int = typer.Option(-1, help="Turn number (-1 = latest)."),
) -> None:
    """Show per-player fog-of-war turn summary."""
    db_path = pathlib.Path("games") / game / f"{game}.db"
    if not db_path.exists():
        typer.echo(f"Error: game '{game}' not found at {db_path}", err=True)
        raise typer.Exit(1)

    db = GameDatabase(str(db_path))
    registry = game_component_registry()

    turn_number = turn if turn >= 0 else db.latest_turn(game)
    world = db.load_snapshot(game, turn_number, registry)

    player_id = _resolve_player_id(world, player)
    if player_id is None:
        typer.echo(f"Error: player '{player}' not found.", err=True)
        db.close()
        raise typer.Exit(1)

    events = db.load_events(game, turn_number)
    summary = generate_turn_summary(world, player_id, events)
    typer.echo(summary)
    db.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_player_id(world: World, player_name: str) -> uuid.UUID | None:
    """Find a player_id by scanning Owner components for matching player_name."""
    for ent, owner in world.query(Owner):
        if owner.player_name == player_name:
            return owner.player_id
    return None


def _build_action(
    order_dict: dict,
    player_id: uuid.UUID,
    resolver: NameResolver,
) -> MoveFleetAction | ColonizePlanetAction | HarvestResourcesAction | None:
    """Build an Action from a user-supplied dict. Returns None if unknown type."""
    atype = order_dict.get("action_type", "")
    oid = uuid.uuid4()

    if atype == "MoveFleet":
        fleet_id = resolver.resolve(order_dict["fleet"])
        target_id = resolver.resolve(order_dict["target"])
        return MoveFleetAction(
            _player_id=player_id,
            _order_id=oid,
            fleet_id=fleet_id,
            target_system_id=target_id,
        )
    elif atype == "ColonizePlanet":
        fleet_id = resolver.resolve(order_dict["fleet"])
        planet_id = resolver.resolve(order_dict["planet"])
        return ColonizePlanetAction(
            _player_id=player_id,
            _order_id=oid,
            fleet_id=fleet_id,
            planet_id=planet_id,
        )
    elif atype == "HarvestResources":
        fleet_id = resolver.resolve(order_dict["fleet"])
        planet_id = resolver.resolve(order_dict["planet"])
        return HarvestResourcesAction(
            _player_id=player_id,
            _order_id=oid,
            fleet_id=fleet_id,
            planet_id=planet_id,
            resource_type=order_dict["resource_type"],
            amount=float(order_dict["amount"]),
        )
    return None


def _comp_summary(comp) -> str:
    """One-line summary of a component's data fields."""
    if dataclasses.is_dataclass(comp):
        parts = []
        for f in dataclasses.fields(comp):
            parts.append(f"{f.name}={getattr(comp, f.name)!r}")
        return ", ".join(parts)
    return str(comp)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind to."),
    port: int = typer.Option(8000, help="Port to listen on."),
    debug: bool = typer.Option(False, help="Enable Flask debug mode."),
) -> None:
    """Start the web UI server at http://<host>:<port>/"""
    from cli.server import run_server  # deferred to keep Flask optional

    typer.echo(f"Starting OneMoreTurn web UI at http://{host}:{port}/")
    run_server(host=host, port=port, debug=debug)


if __name__ == "__main__":
    app()
