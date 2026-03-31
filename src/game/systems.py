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
    """Planets produce resources based on population each turn."""

    @classmethod
    def system_name(cls) -> str:
        return "Production"

    @classmethod
    def phase(cls) -> str:
        return "MAIN"

    @classmethod
    def required_components(cls) -> list:
        return [PopulationStats, Resources, Owner]

    @classmethod
    def required_prior_systems(cls) -> list:
        return [ActionSystem]

    def update(self, world: World, rng: SystemRNG) -> None:
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
    """Advances fleets toward their destinations each turn."""

    @classmethod
    def system_name(cls) -> str:
        return "Movement"

    @classmethod
    def phase(cls) -> str:
        return "MAIN"

    @classmethod
    def required_components(cls) -> list:
        return [FleetStats, Position]

    @classmethod
    def required_prior_systems(cls) -> list:
        return [ActionSystem]

    def update(self, world: World, rng: SystemRNG) -> None:
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
    """Updates fog of war based on fleet and planet positions."""

    OBSERVATION_RANGE = 10.0

    @classmethod
    def system_name(cls) -> str:
        return "Visibility"

    @classmethod
    def phase(cls) -> str:
        return "POST_TURN"

    @classmethod
    def required_components(cls) -> list:
        return [VisibilityComponent]

    def update(self, world: World, rng: SystemRNG) -> None:
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
