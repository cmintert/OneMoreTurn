"""Integration tests: Phase 1 exit criteria and determinism."""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.components import Component
from engine.ecs import World
from engine.rng import SystemRNG
from engine.systems import System, SystemExecutor


# ---------------------------------------------------------------------------
# Test components (not game-specific — just enough to prove the engine)
# ---------------------------------------------------------------------------


@dataclass
class CounterComponent(Component):
    value: int = 0

    @classmethod
    def component_name(cls) -> str:
        return "Counter"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"


@dataclass
class TagComponent(Component):
    label: str = ""

    @classmethod
    def component_name(cls) -> str:
        return "Tag"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"


# ---------------------------------------------------------------------------
# Test systems
# ---------------------------------------------------------------------------


class IncrementSystem(System):
    """Increments all Counter components. Runs in MAIN phase."""

    @classmethod
    def system_name(cls) -> str:
        return "Increment"

    @classmethod
    def phase(cls) -> str:
        return "MAIN"

    @classmethod
    def required_components(cls) -> list[type[Component]]:
        return [CounterComponent]

    def update(self, world: World, rng: SystemRNG) -> None:
        for entity, counter in world.query(CounterComponent):
            counter.value += 1


class LabelSystem(System):
    """Appends turn info to Tag labels. Runs in POST_TURN, after Increment."""

    @classmethod
    def system_name(cls) -> str:
        return "Label"

    @classmethod
    def phase(cls) -> str:
        return "POST_TURN"

    @classmethod
    def required_components(cls) -> list[type[Component]]:
        return [TagComponent]

    def update(self, world: World, rng: SystemRNG) -> None:
        for entity, tag in world.query(TagComponent):
            tag.label += f"t{world.current_turn};"


# ---------------------------------------------------------------------------
# Exit criteria test
# ---------------------------------------------------------------------------


def _run_scenario(game_id: str = "integration-test", turn: int = 1) -> tuple[World, list]:
    """Run the exit criteria scenario and return (world, events)."""
    world = World()

    # 3 entities, 2 component types
    entity_a = world.create_entity([CounterComponent(), TagComponent(label="")])
    entity_b = world.create_entity([CounterComponent(value=10)])
    entity_c = world.create_entity([TagComponent(label="start;")])

    world.event_bus.clear()

    # 2 systems, declared dependency via phase ordering
    executor = SystemExecutor(world, game_id=game_id, turn_number=turn)
    executor.register(IncrementSystem())
    executor.register(LabelSystem())
    executor.execute_all()

    return world, world.event_bus.emitted


class TestExitCriteria:
    def test_three_entities_two_components_two_systems(self):
        """Exit criteria: World with 3 entities, 2 component types, 2 systems
        resolves in declared order and emits events."""
        world, events = _run_scenario()

        # Verify 3 entities exist
        assert len(world.entities()) == 3

        # Verify systems ran in correct order: Increment (MAIN) before Label (POST_TURN)
        system_events = [e for e in events if e.what in ("SystemStarted", "SystemCompleted")]
        started_names = [e.effects["system"] for e in system_events if e.what == "SystemStarted"]
        assert started_names == ["Increment", "Label"]

        # Verify IncrementSystem processed entities A and B (have Counter)
        counter_results = world.query(CounterComponent)
        assert len(counter_results) == 2
        values = sorted(entity.get(CounterComponent).value for entity, _ in counter_results)
        assert values == [1, 11]  # 0+1 and 10+1

        # Verify LabelSystem processed entities A and C (have Tag)
        tag_results = world.query(TagComponent)
        assert len(tag_results) == 2
        labels = sorted(entity.get(TagComponent).label for entity, _ in tag_results)
        assert labels == ["start;t1;", "t1;"]

        # Verify events were emitted
        assert len(events) >= 4  # At least SystemStarted/Completed for each

    def test_systems_emit_start_and_complete(self):
        _, events = _run_scenario()
        whats = [e.what for e in events]
        assert whats.count("SystemStarted") == 2
        assert whats.count("SystemCompleted") == 2


# ---------------------------------------------------------------------------
# Determinism test
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_inputs_identical_outputs(self):
        """Same scenario run twice produces identical results."""
        world1, events1 = _run_scenario(game_id="det-test", turn=5)
        world2, events2 = _run_scenario(game_id="det-test", turn=5)

        # Same number of events
        assert len(events1) == len(events2)

        # Same event types in same order
        assert [e.what for e in events1] == [e.what for e in events2]

        # Same counter values
        counters1 = sorted(
            e.get(CounterComponent).value
            for e, _ in world1.query(CounterComponent)
        )
        counters2 = sorted(
            e.get(CounterComponent).value
            for e, _ in world2.query(CounterComponent)
        )
        assert counters1 == counters2

        # Same tag labels
        tags1 = sorted(
            e.get(TagComponent).label
            for e, _ in world1.query(TagComponent)
        )
        tags2 = sorted(
            e.get(TagComponent).label
            for e, _ in world2.query(TagComponent)
        )
        assert tags1 == tags2

    def test_different_turns_different_labels(self):
        """Different turn numbers produce different tag labels."""
        _, events1 = _run_scenario(turn=1)
        _, events2 = _run_scenario(turn=2)

        # Labels include turn number, so they differ
        labels1 = [e.effects.get("system") for e in events1 if e.what == "SystemStarted"]
        labels2 = [e.effects.get("system") for e in events2 if e.what == "SystemStarted"]
        # Systems still run in same order
        assert labels1 == labels2
