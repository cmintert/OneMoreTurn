"""Action protocol and ActionSystem for turn resolution."""

from __future__ import annotations

import hashlib
import random as _random
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.events import Event
from engine.rng import SystemRNG
from engine.systems import System

if TYPE_CHECKING:
    from engine.ecs import World


# ---------------------------------------------------------------------------
# Validation & result types
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Result of validating an action against the current world state."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid


@dataclass
class ActionResult:
    """Outcome of processing a single action during turn resolution."""

    order_id: uuid.UUID
    action_type: str
    player_id: uuid.UUID
    status: str  # "executed", "rejected", "conflict_lost"
    events: list[Event] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Action ABC
# ---------------------------------------------------------------------------


class Action(ABC):
    """Base class for all player actions.

    All subclasses must be dataclasses and implement action_type(),
    validate(), and execute().
    """

    @classmethod
    @abstractmethod
    def action_type(cls) -> str:
        """Unique identifier for this action type (e.g., 'MoveFleet')."""

    @property
    @abstractmethod
    def player_id(self) -> uuid.UUID:
        """The player who issued this action."""

    @property
    @abstractmethod
    def order_id(self) -> uuid.UUID:
        """Unique identifier for this order (for tracking and replacement)."""

    @abstractmethod
    def validate(self, world: World) -> ValidationResult:
        """Check whether this action can execute against the current state.

        Returns ValidationResult with errors/warnings. Must not mutate world.
        """

    @abstractmethod
    def execute(self, world: World) -> list[Event]:
        """Execute this action, mutating world state and returning events.

        Called only after validate() returns valid=True.
        """

    def conflict_key(self) -> str | None:
        """Key for conflict grouping.

        Actions with the same non-None conflict_key are in conflict.
        Returns None if this action cannot conflict with others.
        """
        return None

    def conflict_weight(self) -> float:
        """Weight for conflict resolution.

        Higher weight = more likely to win. Default 1.0; Phase 4 overrides
        with unit modifiers (speed, type, etc.).
        """
        return 1.0


# ---------------------------------------------------------------------------
# ActionSystem
# ---------------------------------------------------------------------------


class ActionSystem(System):
    """Receives all player actions, validates, resolves conflicts, executes.

    This system runs in the MAIN phase. Other systems that depend on action
    results should declare required_prior_systems = [ActionSystem].
    """

    def __init__(self) -> None:
        self._actions: list[Action] = []
        self._results: list[ActionResult] = []

    @classmethod
    def system_name(cls) -> str:
        return "ActionSystem"

    @classmethod
    def phase(cls) -> str:
        return "MAIN"

    @classmethod
    def skip_if_missing(cls) -> bool:
        return True

    def set_actions(self, actions: list[Action]) -> None:
        """Set the actions to process this turn. Called before execute_all()."""
        self._actions = list(actions)
        self._results = []

    @property
    def results(self) -> list[ActionResult]:
        """Action results from the last update(). Available after execution."""
        return list(self._results)

    def update(self, world: World, rng: SystemRNG) -> None:
        """Validate, resolve conflicts, and execute actions."""
        self._results = []

        if not self._actions:
            return

        # 1. Validate each action independently
        valid_actions: list[Action] = []
        for action in self._actions:
            result = action.validate(world)
            if result.valid:
                valid_actions.append(action)
            else:
                self._results.append(ActionResult(
                    order_id=action.order_id,
                    action_type=action.action_type(),
                    player_id=action.player_id,
                    status="rejected",
                    errors=result.errors,
                ))
                world.event_bus.publish(Event(
                    who=action.player_id,
                    what="ActionRejected",
                    when=world.current_turn,
                    why=str(action.order_id),
                    effects={
                        "action_type": action.action_type(),
                        "errors": result.errors,
                    },
                ))

        # 2. Group by conflict key
        conflict_groups: dict[str, list[Action]] = defaultdict(list)
        no_conflict: list[Action] = []

        for action in valid_actions:
            key = action.conflict_key()
            if key is not None:
                conflict_groups[key].append(action)
            else:
                no_conflict.append(action)

        # 3. Resolve conflicts
        actions_to_execute: list[Action] = list(no_conflict)

        for conflict_key in sorted(conflict_groups.keys()):
            group = conflict_groups[conflict_key]
            if len(group) == 1:
                # No actual conflict
                actions_to_execute.append(group[0])
                continue

            # Per-conflict deterministic RNG derived from the system RNG seed
            # Seed = SHA256(system_rng_seed : conflict_key)
            seed_string = f"{rng.seed}:{conflict_key}"
            seed_bytes = hashlib.sha256(seed_string.encode()).digest()
            conflict_seed = int.from_bytes(seed_bytes[:8])
            conflict_rng_instance = _random.Random(conflict_seed)

            # Weighted random selection
            weights = [a.conflict_weight() for a in group]
            total = sum(weights)
            roll = conflict_rng_instance.random() * total
            cumulative = 0.0
            winner_idx = len(group) - 1  # fallback to last
            for i, w in enumerate(weights):
                cumulative += w
                if roll < cumulative:
                    winner_idx = i
                    break

            winner = group[winner_idx]
            actions_to_execute.append(winner)

            # Mark losers
            for i, action in enumerate(group):
                if i == winner_idx:
                    continue
                self._results.append(ActionResult(
                    order_id=action.order_id,
                    action_type=action.action_type(),
                    player_id=action.player_id,
                    status="conflict_lost",
                    errors=[
                        f"Lost conflict '{conflict_key}' to "
                        f"{winner.action_type()} (order {winner.order_id})"
                    ],
                ))
                world.event_bus.publish(Event(
                    who=action.player_id,
                    what="ActionConflictLost",
                    when=world.current_turn,
                    why=str(action.order_id),
                    effects={
                        "action_type": action.action_type(),
                        "conflict_key": conflict_key,
                        "winner_order_id": str(winner.order_id),
                    },
                ))

        # 4. Execute in deterministic order (action_type, then order_id)
        actions_to_execute.sort(
            key=lambda a: (a.action_type(), str(a.order_id))
        )

        for action in actions_to_execute:
            events = action.execute(world)
            self._results.append(ActionResult(
                order_id=action.order_id,
                action_type=action.action_type(),
                player_id=action.player_id,
                status="executed",
                events=events,
            ))
            for event in events:
                world.event_bus.publish(event)
            world.event_bus.publish(Event(
                who=action.player_id,
                what="ActionExecuted",
                when=world.current_turn,
                why=str(action.order_id),
                effects={"action_type": action.action_type()},
            ))
