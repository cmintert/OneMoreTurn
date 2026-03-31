"""System base class, topological sorting, and system execution."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import TYPE_CHECKING

from engine.components import Component
from engine.events import Event
from engine.rng import SystemRNG

if TYPE_CHECKING:
    from engine.ecs import World


# Phase execution order
PHASE_ORDER = {"PRE_TURN": 0, "MAIN": 1, "POST_TURN": 2, "CLEANUP": 3}


class System(ABC):
    """Base class for all systems."""

    @classmethod
    @abstractmethod
    def system_name(cls) -> str:
        """Unique name for this system."""

    @classmethod
    def phase(cls) -> str:
        """Execution phase. Default: MAIN."""
        return "MAIN"

    @classmethod
    def required_components(cls) -> list[type[Component]]:
        """Component types this system operates on. Default: none."""
        return []

    @classmethod
    def required_prior_systems(cls) -> list[type[System]]:
        """Systems that must run before this one. Default: none."""
        return []

    @classmethod
    def skip_if_missing(cls) -> bool:
        """If True, silently skip when no matching entities exist. Default: True."""
        return True

    @abstractmethod
    def update(self, world: World, rng: SystemRNG) -> None:
        """Execute this system's logic for the current turn."""


class CycleDetectedError(Exception):
    """Raised when system dependencies form a cycle."""

    def __init__(self, cycle: list[str]) -> None:
        """Capture the cycle members for diagnostic output.

        Args:
            cycle: Ordered list of system names forming the cycle.
        """
        self.cycle = cycle
        super().__init__(f"Cycle detected: {' -> '.join(cycle)}")


class MissingEntitiesError(Exception):
    """Raised when a non-skippable system has no matching entities."""

    def __init__(self, system_name: str, required: list[str]) -> None:
        """Capture which system failed and what it needed.

        Args:
            system_name: Name of the system that could not find matching entities.
            required: Component names the system declared in required_components().
        """
        self.system_name = system_name
        self.required = required
        super().__init__(
            f"System '{system_name}' requires entities with "
            f"{required} but none exist"
        )


def topological_sort(systems: list[type[System]]) -> list[type[System]]:
    """Sort systems by phase, then by dependency order within each phase.

    Uses Kahn's algorithm with alphabetical tiebreaker for determinism.
    Raises CycleDetectedError if circular dependencies exist.
    """
    # Group by phase
    by_phase: dict[str, list[type[System]]] = defaultdict(list)
    for sys in systems:
        by_phase[sys.phase()].append(sys)

    result: list[type[System]] = []

    for phase_name in sorted(by_phase.keys(), key=lambda p: PHASE_ORDER.get(p, 99)):
        phase_systems = by_phase[phase_name]
        phase_set = set(phase_systems)

        # Build adjacency and in-degree for systems in this phase
        in_degree: dict[type[System], int] = {s: 0 for s in phase_systems}
        dependents: dict[type[System], list[type[System]]] = defaultdict(list)

        for sys in phase_systems:
            for dep in sys.required_prior_systems():
                if dep in phase_set:
                    dependents[dep].append(sys)
                    in_degree[sys] += 1

        # Kahn's algorithm with sorted queue for determinism
        queue = sorted(
            [s for s in phase_systems if in_degree[s] == 0],
            key=lambda s: s.system_name(),
        )
        sorted_phase: list[type[System]] = []

        while queue:
            current = queue.pop(0)
            sorted_phase.append(current)
            for dependent in dependents[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    # Insert in sorted order
                    name = dependent.system_name()
                    inserted = False
                    for i, q in enumerate(queue):
                        if name < q.system_name():
                            queue.insert(i, dependent)
                            inserted = True
                            break
                    if not inserted:
                        queue.append(dependent)

        if len(sorted_phase) != len(phase_systems):
            # Find the cycle for a useful error message
            remaining = [
                s.system_name()
                for s in phase_systems
                if s not in sorted_phase
            ]
            raise CycleDetectedError(remaining)

        result.extend(sorted_phase)

    return result


class SystemExecutor:
    """Manages system registration, sorting, and execution."""

    def __init__(
        self,
        world: World,
        game_id: str | uuid.UUID,
        turn_number: int = 0,
    ) -> None:
        """Initialise the executor bound to a world and game context.

        game_id and turn_number are forwarded to SystemRNG so every system
        gets a deterministic seed derived from (game_id, turn_number,
        system_name).  The sorted execution order is cached after first
        computation and invalidated whenever a new system is registered.

        Args:
            world: The game world systems will operate on.
            game_id: Unique game identifier used for RNG seeding.
            turn_number: Current turn number used for RNG seeding.
        """
        self._world = world
        self._game_id = game_id
        self._turn_number = turn_number
        self._systems: list[System] = []
        self._sorted: list[type[System]] | None = None

    @property
    def turn_number(self) -> int:
        """Current turn; updated by TurnManager before each execute_all() call."""
        return self._turn_number

    @turn_number.setter
    def turn_number(self, value: int) -> None:
        self._turn_number = value

    def register(self, system: System) -> None:
        """Register a system instance."""
        self._systems.append(system)
        self._sorted = None  # invalidate cache

    @property
    def execution_order(self) -> list[type[System]]:
        """The resolved execution order."""
        if self._sorted is None:
            self._sorted = topological_sort([type(s) for s in self._systems])
        return list(self._sorted)

    def execute_all(self) -> None:
        """Sort and execute all registered systems."""
        order = self.execution_order
        instance_map = {type(s): s for s in self._systems}

        self._world.current_turn = self._turn_number

        for sys_type in order:
            system = instance_map[sys_type]
            required = sys_type.required_components()

            # Check if matching entities exist
            if required:
                results = self._world.query(*required)
                if not results:
                    if sys_type.skip_if_missing():
                        continue
                    raise MissingEntitiesError(
                        sys_type.system_name(),
                        [c.component_name() for c in required],
                    )

            rng = SystemRNG(
                self._game_id, self._turn_number, sys_type.system_name()
            )

            self._world.event_bus.publish(Event(
                who=sys_type.system_name(),
                what="SystemStarted",
                when=self._turn_number,
                why="execute_all",
                effects={"system": sys_type.system_name()},
            ))

            system.update(self._world, rng)

            self._world.event_bus.publish(Event(
                who=sys_type.system_name(),
                what="SystemCompleted",
                when=self._turn_number,
                why="execute_all",
                effects={"system": sys_type.system_name()},
            ))
