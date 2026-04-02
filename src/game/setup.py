"""Game initialization: map generation and starting positions."""

from __future__ import annotations

import uuid

from engine.ecs import World
from engine.rng import SystemRNG
from game.archetypes import create_civilization, create_fleet, create_planet, create_star_system
from game.config import MAP


def setup_game(
    world: World,
    player_names: list[str],
    rng: SystemRNG,
) -> dict[str, uuid.UUID]:
    """Initialize the game map with star systems, planets, and starting fleets.

    Returns a dict mapping player_name -> player_id (UUID).
    """
    player_ids: dict[str, uuid.UUID] = {}
    for name in player_names:
        player_ids[name] = uuid.UUID(
            int=rng.randint(0, 2**128 - 1)
        )

    home_positions = [tuple(pos) for pos in MAP.home_worlds.positions]

    for i, (pname, pid) in enumerate(player_ids.items()):
        hx, hy = home_positions[i]

        system = create_star_system(world, f"{pname}_Home", hx, hy)
        create_planet(
            world,
            f"{pname}_Prime",
            system,
            resources={
                "minerals": MAP.home_worlds.starting_minerals,
                "energy": MAP.home_worlds.starting_energy,
                "food": MAP.home_worlds.starting_food,
            },
            population=MAP.home_worlds.starting_population,
            owner_id=pid,
            owner_name=pname,
        )
        create_fleet(
            world,
            f"{pname}_Fleet1",
            pid,
            pname,
            system,
            cargo={
                "minerals": MAP.home_worlds.fleet_minerals,
                "energy": MAP.home_worlds.fleet_energy,
            },
        )
        create_civilization(world, pid, pname)

    _npr = MAP.neutral_planet_resources
    _pps = _npr.planets_per_system
    for ns in MAP.neutral_system:
        system = create_star_system(world, ns.name, ns.x, ns.y)
        n_planets = rng.randint(_pps[0], _pps[1])
        for j in range(n_planets):
            create_planet(
                world,
                f"{ns.name}_{j + 1}",
                system,
                resources={
                    "minerals": float(rng.randint(int(_npr.mineral_range[0]), int(_npr.mineral_range[1]))),
                    "energy": float(rng.randint(int(_npr.energy_range[0]), int(_npr.energy_range[1]))),
                    "food": float(rng.randint(int(_npr.food_range[0]), int(_npr.food_range[1]))),
                },
            )

    return player_ids
