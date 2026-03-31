"""Per-player fog-of-war turn summary."""

from __future__ import annotations

import uuid

from engine.ecs import World
from engine.events import Event
from engine.names import NameComponent
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    Resources,
    VisibilityComponent,
)


def _entity_name(ent) -> str:
    return ent.get(NameComponent).name if ent.has(NameComponent) else str(ent.id)


def generate_turn_summary(
    world: World,
    player_id: uuid.UUID,
    events: list[Event],
) -> str:
    """Build a text summary of the turn from a single player's perspective."""
    lines: list[str] = []
    lines.append(f"=== Turn {world.current_turn} Summary ===")
    lines.append("")

    # -- Your Planets --
    lines.append("-- Your Planets --")
    planets = world.query(Owner, PopulationStats, Resources)
    own_planets = [
        (ent, owner, pop, res)
        for ent, owner, pop, res in planets
        if owner.player_id == player_id
    ]
    if not own_planets:
        lines.append("  (none)")
    for ent, owner, pop, res in own_planets:
        name = _entity_name(ent)
        lines.append(f"  {name}: pop={pop.size}, morale={pop.morale:.1f}, resources={res.amounts}")
    lines.append("")

    # -- Your Fleets --
    lines.append("-- Your Fleets --")
    fleets = world.query(Owner, FleetStats, Position)
    own_fleets = [
        (ent, owner, fs, pos)
        for ent, owner, fs, pos in fleets
        if owner.player_id == player_id
    ]
    if not own_fleets:
        lines.append("  (none)")
    for ent, owner, fs, pos in own_fleets:
        name = _entity_name(ent)
        if fs.turns_remaining > 0:
            status = f"moving ({fs.turns_remaining} turns remaining)"
        else:
            status = f"at ({pos.x:.0f}, {pos.y:.0f})"
        lines.append(f"  {name}: speed={fs.speed}, {status}")
    lines.append("")

    # -- Visible Entities --
    lines.append("-- Visible Entities --")
    vis_entities = world.query(VisibilityComponent)
    visible_others = []
    for ent, vis in vis_entities:
        if ent.has(Owner) and ent.get(Owner).player_id == player_id:
            continue
        if player_id in vis.visible_to:
            visible_others.append((ent, "current"))
        elif player_id in vis.revealed_to:
            visible_others.append((ent, "stale"))
    if not visible_others:
        lines.append("  (none)")
    for ent, freshness in visible_others:
        name = _entity_name(ent)
        tag = " [stale]" if freshness == "stale" else ""
        lines.append(f"  {name}{tag}")
    lines.append("")

    # -- Events --
    lines.append("-- Events --")
    visible_events = [e for e in events if _event_visible_to_player(e, player_id, world)]
    if not visible_events:
        lines.append("  (none)")
    for ev in visible_events:
        lines.append(f"  {ev.what}: {ev.effects}")

    return "\n".join(lines)


def _event_visible_to_player(
    event: Event,
    player_id: uuid.UUID,
    world: World,
) -> bool:
    """Determine if an event is visible to a player."""
    # Check explicit visibility_scope first
    if event.visibility_scope is not None:
        return str(player_id) in event.visibility_scope

    # If event.who is a UUID-like string, check the entity's ownership/visibility
    if event.who is not None:
        try:
            entity_id = uuid.UUID(str(event.who))
            entity = world.get_entity(entity_id)
            if entity.has(Owner):
                return entity.get(Owner).player_id == player_id
            if entity.has(VisibilityComponent):
                vis = entity.get(VisibilityComponent)
                return player_id in vis.visible_to or player_id in vis.revealed_to
        except (ValueError, KeyError):
            pass

    return False
