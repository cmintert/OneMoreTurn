"""Game systems: ProductionSystem, MovementSystem, VisibilitySystem."""

from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING

from engine.actions import ActionSystem
from engine.components import ChildComponent
from engine.events import Event
from engine.rng import SystemRNG
from engine.systems import System
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    Resources,
    VisibilityComponent,
)

if TYPE_CHECKING:
    from engine.ecs import World


class ProductionSystem(System):
    """Generates resources and grows population on all colonized planets each turn.

    Runs in the MAIN phase after ActionSystem so that any player actions
    which alter planet state (e.g. harvesting) are already resolved before
    production is calculated.
    """

    @classmethod
    def system_name(cls) -> str:
        """Identifier used in logging, RNG seeding, and dependency graphs."""
        return "Production"

    @classmethod
    def phase(cls) -> str:
        """MAIN phase: runs after PRE_TURN setup and alongside other core systems."""
        return "MAIN"

    @classmethod
    def required_components(cls) -> list:
        """Entities must have all three components to receive production."""
        return [PopulationStats, Resources, Owner]

    @classmethod
    def required_prior_systems(cls) -> list:
        """Run after ActionSystem so harvesting and building orders are resolved first."""
        return [ActionSystem]

    def update(self, world: World, rng: SystemRNG) -> None:
        """Calculate and apply per-planet resource production and population growth.

        For each planet with population, computes a production value scaled by
        population size and morale, splits it into minerals/energy/food, and
        clamps each to the resource capacity.  Also increments population by at
        least 1 per turn.  Publishes a ``ProductionCompleted`` event visible only
        to the planet's owner.

        Args:
            world: The current game world.
            rng: Seeded RNG for this system and turn (not used; reserved for
                future random events).
        """
        for entity, pop, resources, owner in world.query(
            PopulationStats, Resources, Owner
        ):
            base_rate = 0.1
            production = pop.size * pop.morale * base_rate

            minerals = production * 0.4
            energy = production * 0.3
            food = production * 0.3

            for rtype, amount in [
                ("minerals", minerals),
                ("energy", energy),
                ("food", food),
            ]:
                current = resources.amounts.get(rtype, 0.0)
                resources.amounts[rtype] = min(current + amount, resources.capacity)

            growth = int(pop.size * pop.growth_rate * pop.morale)
            pop.size += max(growth, 1)

            world.event_bus.publish(
                Event(
                    who=entity.id,
                    what="ProductionCompleted",
                    when=world.current_turn,
                    why="ProductionSystem",
                    effects={
                        "minerals": minerals,
                        "energy": energy,
                        "food": food,
                    },
                    visibility_scope=[str(owner.player_id)],
                )
            )


class MovementSystem(System):
    """Advances in-transit fleets toward their destinations each turn.

    Runs in MAIN phase after ActionSystem so that newly issued MoveFleet
    orders are already applied to FleetStats before movement is computed.
    Each turn the fleet moves up to fleet.speed units; when turns_remaining
    reaches 1 the fleet snaps exactly to its destination and transfers its
    ChildComponent to the new star system.
    """

    @classmethod
    def system_name(cls) -> str:
        """Identifier used in logging, RNG seeding, and dependency graphs."""
        return "Movement"

    @classmethod
    def phase(cls) -> str:
        """MAIN phase: runs alongside other core systems after action resolution."""
        return "MAIN"

    @classmethod
    def required_components(cls) -> list:
        """Entities must have both FleetStats and Position to be moved."""
        return [FleetStats, Position]

    @classmethod
    def required_prior_systems(cls) -> list:
        """Run after ActionSystem so new MoveFleet orders are accounted for."""
        return [ActionSystem]

    def update(self, world: World, rng: SystemRNG) -> None:
        """Move each in-transit fleet one step closer to its destination.

        Fleets with no destination (destination_x is None) are skipped.  When
        turns_remaining > 1 the fleet moves proportionally along the vector;
        on the final turn it snaps to the exact destination coordinates and
        updates its ChildComponent to the new parent system.  Publishes a
        ``FleetArrived`` event on completion.

        Args:
            world: The current game world.
            rng: Seeded RNG for this system and turn (unused; reserved for
                future combat or navigation hazard events).
        """
        for entity, fleet, pos in world.query(FleetStats, Position):
            if fleet.destination_x is None:
                continue

            if fleet.turns_remaining > 1:
                dx = fleet.destination_x - pos.x
                dy = fleet.destination_y - pos.y
                remaining_dist = math.sqrt(dx * dx + dy * dy)
                if remaining_dist > 0:
                    move_dist = min(fleet.speed, remaining_dist)
                    ratio = move_dist / remaining_dist
                    pos.x += dx * ratio
                    pos.y += dy * ratio
                fleet.turns_remaining -= 1
            else:
                pos.x = fleet.destination_x
                pos.y = fleet.destination_y
                pos.parent_system_id = fleet.destination_system_id

                if entity.has(ChildComponent):
                    world.remove_component(entity.id, ChildComponent)
                if fleet.destination_system_id is not None:
                    world.add_component(
                        entity.id,
                        ChildComponent(parent_id=fleet.destination_system_id),
                    )

                owner = entity.get(Owner) if entity.has(Owner) else None

                world.event_bus.publish(
                    Event(
                        who=entity.id,
                        what="FleetArrived",
                        when=world.current_turn,
                        why="MovementSystem",
                        effects={"x": pos.x, "y": pos.y},
                        visibility_scope=(
                            [str(owner.player_id)] if owner else None
                        ),
                    )
                )

                fleet.destination_x = None
                fleet.destination_y = None
                fleet.destination_system_id = None
                fleet.turns_remaining = 0


class VisibilitySystem(System):
    """Recomputes fog-of-war for every entity after all MAIN-phase systems finish.

    Runs in POST_TURN so that movement and colonization outcomes are already
    committed before visibility is recalculated.  Any entity within
    OBSERVATION_RANGE of an owned entity becomes visible_to that player;
    entities that were ever visible are accumulated in revealed_to so that
    the map is never 'un-seen'.
    """

    # Maximum distance (in coordinate units) at which an entity can observe
    # another.  Kept as a class attribute so subclasses or tests can override it.
    OBSERVATION_RANGE = 10.0

    @classmethod
    def system_name(cls) -> str:
        """Identifier used in logging, RNG seeding, and dependency graphs."""
        return "Visibility"

    @classmethod
    def phase(cls) -> str:
        """POST_TURN: runs after all MAIN systems so movement outcomes are committed."""
        return "POST_TURN"

    @classmethod
    def required_components(cls) -> list:
        """All entities with a VisibilityComponent are evaluated each turn."""
        return [VisibilityComponent]

    def update(self, world: World, rng: SystemRNG) -> None:
        """Rebuild visible_to and accumulate revealed_to for every visible entity.

        First builds a lookup of {player_id: [(x, y), ...]} from all owned
        positioned entities.  Then for each entity with a VisibilityComponent,
        clears this turn's visible_to set and re-evaluates which players can see
        it based on distance to any of their assets.  Owned entities are always
        visible to their owner.

        Args:
            world: The current game world.
            rng: Seeded RNG for this system and turn (unused).
        """
        observer_positions: dict[uuid.UUID, list[tuple[float, float]]] = {}

        for entity, owner, pos in world.query(Owner, Position):
            pid = owner.player_id
            if pid not in observer_positions:
                observer_positions[pid] = []
            observer_positions[pid].append((pos.x, pos.y))

        for entity, vis, pos in world.query(VisibilityComponent, Position):
            vis.visible_to.clear()

            if entity.has(Owner):
                own_pid = entity.get(Owner).player_id
                vis.visible_to.add(own_pid)
                vis.revealed_to.add(own_pid)

            for player_id, positions in observer_positions.items():
                if player_id in vis.visible_to:
                    continue
                for ox, oy in positions:
                    dist = math.sqrt((pos.x - ox) ** 2 + (pos.y - oy) ** 2)
                    if dist <= self.OBSERVATION_RANGE:
                        vis.visible_to.add(player_id)
                        vis.revealed_to.add(player_id)
                        break
