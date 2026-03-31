"""Tests for System, topological sort, and SystemExecutor."""

from __future__ import annotations

import pytest

from engine.components import Component
from engine.ecs import World
from engine.rng import SystemRNG
from engine.systems import (
    CycleDetectedError,
    MissingEntitiesError,
    System,
    SystemExecutor,
    topological_sort,
)
from tests.conftest import ComponentBuilder, HealthComponent, StubPositionComponent


# ---------------------------------------------------------------------------
# Test systems
# ---------------------------------------------------------------------------


class AlphaSystem(System):
    @classmethod
    def system_name(cls) -> str:
        return "Alpha"

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class BetaSystem(System):
    """Depends on Alpha."""

    @classmethod
    def system_name(cls) -> str:
        return "Beta"

    @classmethod
    def required_prior_systems(cls) -> list[type[System]]:
        return [AlphaSystem]

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class GammaSystem(System):
    @classmethod
    def system_name(cls) -> str:
        return "Gamma"

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class PreTurnSystem(System):
    @classmethod
    def system_name(cls) -> str:
        return "PreTurn"

    @classmethod
    def phase(cls) -> str:
        return "PRE_TURN"

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class PostTurnSystem(System):
    @classmethod
    def system_name(cls) -> str:
        return "PostTurn"

    @classmethod
    def phase(cls) -> str:
        return "POST_TURN"

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class HealthRequiredSystem(System):
    @classmethod
    def system_name(cls) -> str:
        return "HealthRequired"

    @classmethod
    def required_components(cls) -> list[type[Component]]:
        return [HealthComponent]

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class NoSkipSystem(System):
    @classmethod
    def system_name(cls) -> str:
        return "NoSkip"

    @classmethod
    def required_components(cls) -> list[type[Component]]:
        return [HealthComponent]

    @classmethod
    def skip_if_missing(cls) -> bool:
        return False

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


# Cycle systems
class CycleA(System):
    @classmethod
    def system_name(cls) -> str:
        return "CycleA"

    @classmethod
    def required_prior_systems(cls) -> list[type[System]]:
        return [CycleB]

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class CycleB(System):
    @classmethod
    def system_name(cls) -> str:
        return "CycleB"

    @classmethod
    def required_prior_systems(cls) -> list[type[System]]:
        return [CycleA]

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class CycleX(System):
    @classmethod
    def system_name(cls) -> str:
        return "CycleX"

    @classmethod
    def required_prior_systems(cls) -> list[type[System]]:
        return [CycleZ]

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class CycleY(System):
    @classmethod
    def system_name(cls) -> str:
        return "CycleY"

    @classmethod
    def required_prior_systems(cls) -> list[type[System]]:
        return [CycleX]

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


class CycleZ(System):
    @classmethod
    def system_name(cls) -> str:
        return "CycleZ"

    @classmethod
    def required_prior_systems(cls) -> list[type[System]]:
        return [CycleY]

    def update(self, world: World, rng: SystemRNG) -> None:
        pass


# ---------------------------------------------------------------------------
# ABC Tests
# ---------------------------------------------------------------------------


class TestSystemABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            System()  # type: ignore[abstract]

    def test_defaults(self):
        assert AlphaSystem.phase() == "MAIN"
        assert AlphaSystem.required_components() == []
        assert AlphaSystem.required_prior_systems() == []
        assert AlphaSystem.skip_if_missing() is True


# ---------------------------------------------------------------------------
# Topological Sort Tests
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    def test_simple_dependency(self):
        order = topological_sort([BetaSystem, AlphaSystem])
        names = [s.system_name() for s in order]
        assert names.index("Alpha") < names.index("Beta")

    def test_phases_respected(self):
        order = topological_sort([PostTurnSystem, AlphaSystem, PreTurnSystem])
        names = [s.system_name() for s in order]
        assert names == ["PreTurn", "Alpha", "PostTurn"]

    def test_deterministic(self):
        systems = [GammaSystem, AlphaSystem, BetaSystem]
        order1 = [s.system_name() for s in topological_sort(systems)]
        order2 = [s.system_name() for s in topological_sort(systems)]
        assert order1 == order2

    def test_stable_alphabetical_tiebreaker(self):
        order = topological_sort([GammaSystem, AlphaSystem])
        names = [s.system_name() for s in order]
        # No dependency between them, so alphabetical: Alpha, Gamma
        assert names == ["Alpha", "Gamma"]

    def test_cycle_detection_two_way(self):
        with pytest.raises(CycleDetectedError) as exc_info:
            topological_sort([CycleA, CycleB])
        assert len(exc_info.value.cycle) == 2

    def test_cycle_detection_three_way(self):
        with pytest.raises(CycleDetectedError) as exc_info:
            topological_sort([CycleX, CycleY, CycleZ])
        assert len(exc_info.value.cycle) == 3

    def test_cycle_error_message(self):
        with pytest.raises(CycleDetectedError, match="Cycle detected"):
            topological_sort([CycleA, CycleB])

    def test_empty_systems(self):
        assert topological_sort([]) == []

    def test_single_system(self):
        order = topological_sort([AlphaSystem])
        assert [s.system_name() for s in order] == ["Alpha"]


# ---------------------------------------------------------------------------
# Executor Tests
# ---------------------------------------------------------------------------


class TestSystemExecutor:
    def test_runs_in_order(self):
        world = World()
        executor = SystemExecutor(world, game_id="test", turn_number=1)
        run_order = []

        class TrackAlpha(System):
            @classmethod
            def system_name(cls) -> str:
                return "Alpha"

            def update(self, world: World, rng: SystemRNG) -> None:
                run_order.append("Alpha")

        class TrackBeta(System):
            @classmethod
            def system_name(cls) -> str:
                return "Beta"

            @classmethod
            def required_prior_systems(cls) -> list[type[System]]:
                return [TrackAlpha]

            def update(self, world: World, rng: SystemRNG) -> None:
                run_order.append("Beta")

        executor.register(TrackBeta())
        executor.register(TrackAlpha())
        executor.execute_all()
        assert run_order == ["Alpha", "Beta"]

    def test_skip_if_missing(self):
        world = World()
        executor = SystemExecutor(world, game_id="test", turn_number=1)
        executor.register(HealthRequiredSystem())
        # No entities with Health — should skip silently
        executor.execute_all()

    def test_no_skip_raises(self):
        world = World()
        executor = SystemExecutor(world, game_id="test", turn_number=1)
        executor.register(NoSkipSystem())
        with pytest.raises(MissingEntitiesError):
            executor.execute_all()

    def test_emits_system_events(self):
        world = World()
        executor = SystemExecutor(world, game_id="test", turn_number=1)
        executor.register(AlphaSystem())
        executor.execute_all()

        events = world.event_bus.emitted
        whats = [e.what for e in events]
        assert "SystemStarted" in whats
        assert "SystemCompleted" in whats

    def test_passes_rng(self):
        world = World()
        executor = SystemExecutor(world, game_id="test-game", turn_number=3)
        captured_rng = []

        class RngCapture(System):
            @classmethod
            def system_name(cls) -> str:
                return "RngCapture"

            def update(self, world: World, rng: SystemRNG) -> None:
                captured_rng.append(rng)

        executor.register(RngCapture())
        executor.execute_all()

        assert len(captured_rng) == 1
        # Verify it produces deterministic results
        expected_rng = SystemRNG("test-game", 3, "RngCapture")
        assert captured_rng[0].random() == expected_rng.random()

    def test_execution_order_property(self):
        world = World()
        executor = SystemExecutor(world, game_id="test", turn_number=1)
        executor.register(BetaSystem())
        executor.register(AlphaSystem())
        order = executor.execution_order
        names = [s.system_name() for s in order]
        assert names.index("Alpha") < names.index("Beta")

    def test_turn_number_property(self):
        world = World()
        executor = SystemExecutor(world, game_id="test", turn_number=5)
        assert executor.turn_number == 5
        executor.turn_number = 10
        assert executor.turn_number == 10

    def test_sets_world_current_turn(self):
        world = World()
        executor = SystemExecutor(world, game_id="test", turn_number=7)
        executor.register(AlphaSystem())
        executor.execute_all()
        assert world.current_turn == 7
