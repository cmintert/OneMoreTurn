"""Game initialization: map generation and starting positions."""

from __future__ import annotations

import uuid

from engine.ecs import World
from engine.rng import SystemRNG
from game.archetypes import create_fleet, create_planet, create_star_system


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

    home_positions = [(10.0, 50.0), (90.0, 50.0)]

    for i, (pname, pid) in enumerate(player_ids.items()):
        hx, hy = home_positions[i]

        system = create_star_system(world, f"{pname}_Home", hx, hy)
        create_planet(
            world,
            f"{pname}_Prime",
            system,
            resources={"minerals": 50.0, "energy": 30.0, "food": 40.0},
            population=100,
            owner_id=pid,
            owner_name=pname,
        )
        create_fleet(
            world,
            f"{pname}_Fleet1",
            pid,
            pname,
            system,
            speed=5.0,
            cargo={"minerals": 10.0, "energy": 5.0},
        )

    neutral_systems = [
        ("Alpha", 30.0, 30.0),
        ("Beta", 50.0, 50.0),
        ("Gamma", 70.0, 70.0),
        ("Delta", 50.0, 20.0),
        ("Epsilon", 40.0, 60.0),
    ]
    for sname, sx, sy in neutral_systems:
        system = create_star_system(world, sname, sx, sy)
        n_planets = rng.randint(1, 2)
        for j in range(n_planets):
            create_planet(
                world,
                f"{sname}_{j + 1}",
                system,
                resources={
                    "minerals": float(rng.randint(10, 60)),
                    "energy": float(rng.randint(5, 40)),
                    "food": float(rng.randint(5, 30)),
                },
            )

    return player_ids
