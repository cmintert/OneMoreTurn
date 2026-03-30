"""OneMoreTurn CLI — thin orchestration layer over the Turn Engine.

Commands:
    create-game   Create a new game with stub components.
    submit-orders Submit player orders (JSON).
    resolve-turn  Resolve the current turn.
    query-state   Display game state for a given turn.
"""

from __future__ import annotations

import json
import pathlib
import uuid

import typer

from engine.ecs import World
from engine.names import NameComponent, NameResolver
from engine.turn import TurnManager
from persistence.db import GameDatabase
from persistence.serialization import ActionRegistry, ComponentRegistry

# Stub components/actions/systems — Phase 3 test content only.
# A real game would register its own domain types.
from stubs import (
    ClaimAction,
    ClaimableComponent,
    IncrementScoreAction,
    PlayerComponent,
    ScoreBonusSystem,
    ScoreComponent,
)

app = typer.Typer(name="onemoreturn", help="OneMoreTurn PBEM 4X turn engine CLI.")


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def _component_registry() -> ComponentRegistry:
    reg = ComponentRegistry()
    reg.register(PlayerComponent, ScoreComponent, ClaimableComponent, NameComponent)
    return reg


def _action_registry() -> ActionRegistry:
    reg = ActionRegistry()
    reg.register(IncrementScoreAction, ClaimAction)
    return reg


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def create_game(
    name: str = typer.Option(..., help="Game name (also used for DB filename)."),
    players: int = typer.Option(2, help="Number of players."),
    claimables: int = typer.Option(3, help="Number of claimable entities."),
) -> None:
    """Create a new game with player and claimable entities."""
    game_dir = pathlib.Path("games") / name
    game_dir.mkdir(parents=True, exist_ok=True)
    db_path = game_dir / f"{name}.db"

    db = GameDatabase(str(db_path))
    db.init_schema()
    registry = _component_registry()

    world = World()
    game_id = name

    # Create player entities
    player_names: list[str] = []
    for i in range(1, players + 1):
        pname = f"Player{i}"
        pid = uuid.uuid4()
        world.create_entity([
            NameComponent(name=pname),
            PlayerComponent(name=pname, player_id=pid),
            ScoreComponent(score=0),
        ])
        player_names.append(pname)

    # Create claimable entities
    claim_names: list[str] = []
    for i in range(1, claimables + 1):
        cname = f"Resource{i}"
        world.create_entity([
            NameComponent(name=cname),
            ClaimableComponent(),
        ])
        claim_names.append(cname)

    # Save turn-0 snapshot
    db.save_snapshot(game_id, 0, world, registry)
    db.close()

    typer.echo(f"Game '{game_id}' created at {db_path}")
    typer.echo(f"Players: {', '.join(player_names)}")
    typer.echo(f"Claimables: {', '.join(claim_names)}")


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
        '[{"action_type": "Claim", "target": "Resource1"}]'
    """
    db_path = pathlib.Path("games") / game / f"{game}.db"
    if not db_path.exists():
        typer.echo(f"Error: game '{game}' not found at {db_path}", err=True)
        raise typer.Exit(1)

    db = GameDatabase(str(db_path))
    registry = _component_registry()

    # Find latest turn
    turn_number = _latest_turn(db, game)
    world = db.load_snapshot(game, turn_number, registry)
    resolver = NameResolver(world)

    # Resolve player name → player entity UUID + player_id
    try:
        player_entity_id = resolver.resolve(player)
    except KeyError:
        typer.echo(f"Error: player '{player}' not found.", err=True)
        db.close()
        raise typer.Exit(1)

    player_entity = world.get_entity(player_entity_id)
    player_comp = player_entity.get(PlayerComponent)
    pid = player_comp.player_id

    tm = TurnManager(world, game, db, registry, systems=[ScoreBonusSystem()])
    action_list = json.loads(orders)

    for order_dict in action_list:
        action = _build_action(order_dict, pid, resolver)
        if action is None:
            typer.echo(f"Warning: unknown action_type '{order_dict.get('action_type')}'", err=True)
            continue
        result = tm.submit_order(action)
        status = "ok" if result.valid else f"invalid ({', '.join(result.errors)})"
        typer.echo(f"  Order {action.order_id}: {action.action_type()} -> {status}")

    # Persist orders to DB for later resolution
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
    registry = _component_registry()
    action_reg = _action_registry()

    turn_number = _latest_turn(db, game)
    world = db.load_snapshot(game, turn_number, registry)

    tm = TurnManager(world, game, db, registry, systems=[ScoreBonusSystem()])

    # Load persisted orders for this turn
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
) -> None:
    """Display game state for a given turn."""
    db_path = pathlib.Path("games") / game / f"{game}.db"
    if not db_path.exists():
        typer.echo(f"Error: game '{game}' not found at {db_path}", err=True)
        raise typer.Exit(1)

    db = GameDatabase(str(db_path))
    registry = _component_registry()

    turn_number = turn if turn >= 0 else _latest_turn(db, game)
    world = db.load_snapshot(game, turn_number, registry)
    resolver = NameResolver(world)

    typer.echo(f"Game: {game}  Turn: {turn_number}")
    typer.echo("-" * 40)

    for ent in sorted(world.entities(), key=lambda e: e.id):
        if ent.has(NameComponent):
            ent_name = ent.get(NameComponent).name
        else:
            ent_name = str(ent.id)

        if entity and ent_name != entity:
            continue

        typer.echo(f"\n{ent_name} ({ent.id})")
        for comp in ent.components().values():
            typer.echo(f"  {comp.component_name()}: {_comp_summary(comp)}")

    db.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _latest_turn(db: GameDatabase, game_id: str) -> int:
    """Find the highest turn_number persisted for a game."""
    row = db._conn.execute(
        "SELECT MAX(turn_number) AS max_turn FROM turns WHERE game_id = ?",
        (game_id,),
    ).fetchone()
    if row is None or row["max_turn"] is None:
        return 0
    return int(row["max_turn"])


def _build_action(
    order_dict: dict,
    player_id: uuid.UUID,
    resolver: NameResolver,
) -> Action | None:
    """Build an Action from a user-supplied dict. Returns None if unknown type."""
    from engine.actions import Action

    atype = order_dict.get("action_type", "")
    oid = uuid.uuid4()

    if atype == "IncrementScore":
        target_name = order_dict.get("target", "")
        target_id = resolver.resolve(target_name)
        return IncrementScoreAction(
            _player_id=player_id,
            _order_id=oid,
            target_id=target_id,
            amount=order_dict.get("amount", 1),
        )
    elif atype == "Claim":
        target_name = order_dict.get("target", "")
        target_id = resolver.resolve(target_name)
        return ClaimAction(
            _player_id=player_id,
            _order_id=oid,
            target_id=target_id,
        )
    return None


def _comp_summary(comp) -> str:
    """One-line summary of a component's data fields."""
    import dataclasses

    if dataclasses.is_dataclass(comp):
        parts = []
        for f in dataclasses.fields(comp):
            parts.append(f"{f.name}={getattr(comp, f.name)!r}")
        return ", ".join(parts)
    return str(comp)


if __name__ == "__main__":
    app()
