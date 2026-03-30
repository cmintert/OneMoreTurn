"""Stub components, actions, and systems for Phase 3 testing.

These are test infrastructure — not shipped game content. They exist to
exercise the Action protocol and TurnManager with minimal game-like behavior.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from engine.actions import Action, ActionSystem, ValidationResult
from engine.components import Component
from engine.events import Event
from engine.names import NameComponent
from engine.systems import System


# ---------------------------------------------------------------------------
# Stub components
# ---------------------------------------------------------------------------


@dataclass
class PlayerComponent(Component):
    """Identifies a player entity."""

    name: str = "Player"
    player_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def component_name(cls) -> str:
        return "Player"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"


@dataclass
class ScoreComponent(Component):
    """Simple numeric state for testing actions."""

    score: int = 0

    @classmethod
    def component_name(cls) -> str:
        return "Score"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"

    @classmethod
    def dependencies(cls) -> list[type[Component]]:
        return [PlayerComponent]


@dataclass
class ClaimableComponent(Component):
    """An entity that can be claimed by a player."""

    claimed_by: uuid.UUID | None = None

    @classmethod
    def component_name(cls) -> str:
        return "Claimable"

    @classmethod
    def version(cls) -> str:
        return "1.0.0"


# ---------------------------------------------------------------------------
# Stub actions
# ---------------------------------------------------------------------------


@dataclass
class IncrementScoreAction(Action):
    """Increments a player's score. No conflict possible."""

    _player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    target_id: uuid.UUID = field(default_factory=uuid.uuid4)
    amount: int = 1

    @classmethod
    def action_type(cls) -> str:
        return "IncrementScore"

    @property
    def player_id(self) -> uuid.UUID:
        return self._player_id

    @property
    def order_id(self) -> uuid.UUID:
        return self._order_id

    def validate(self, world) -> ValidationResult:
        try:
            entity = world.get_entity(self.target_id)
        except KeyError:
            return ValidationResult(valid=False, errors=["Target entity not found"])

        if not entity.has(ScoreComponent):
            return ValidationResult(valid=False, errors=["Target has no ScoreComponent"])

        if not entity.has(PlayerComponent):
            return ValidationResult(valid=False, errors=["Target has no PlayerComponent"])

        player_comp = entity.get(PlayerComponent)
        if player_comp.player_id != self._player_id:
            return ValidationResult(valid=False, errors=["Not your entity"])

        return ValidationResult(valid=True)

    def execute(self, world) -> list[Event]:
        entity = world.get_entity(self.target_id)
        score_comp = entity.get(ScoreComponent)
        score_comp.score += self.amount
        return [Event(
            who=self.target_id,
            what="ScoreIncremented",
            when=world.current_turn,
            why=str(self._order_id),
            effects={"amount": self.amount, "new_score": score_comp.score},
        )]


@dataclass
class ClaimAction(Action):
    """Claims an entity. Conflict when two players claim the same target."""

    _player_id: uuid.UUID = field(default_factory=uuid.uuid4)
    _order_id: uuid.UUID = field(default_factory=uuid.uuid4)
    target_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def action_type(cls) -> str:
        return "Claim"

    @property
    def player_id(self) -> uuid.UUID:
        return self._player_id

    @property
    def order_id(self) -> uuid.UUID:
        return self._order_id

    def validate(self, world) -> ValidationResult:
        try:
            entity = world.get_entity(self.target_id)
        except KeyError:
            return ValidationResult(valid=False, errors=["Target entity not found"])

        if not entity.has(ClaimableComponent):
            return ValidationResult(valid=False, errors=["Target is not claimable"])

        claimable = entity.get(ClaimableComponent)
        if claimable.claimed_by is not None:
            return ValidationResult(
                valid=False,
                errors=[f"Already claimed by {claimable.claimed_by}"],
            )

        return ValidationResult(valid=True)

    def execute(self, world) -> list[Event]:
        entity = world.get_entity(self.target_id)
        claimable = entity.get(ClaimableComponent)
        claimable.claimed_by = self._player_id
        return [Event(
            who=self.target_id,
            what="EntityClaimed",
            when=world.current_turn,
            why=str(self._order_id),
            effects={"claimed_by": str(self._player_id)},
        )]

    def conflict_key(self) -> str | None:
        return f"claim:{self.target_id}"


# ---------------------------------------------------------------------------
# Stub system
# ---------------------------------------------------------------------------


class ScoreBonusSystem(System):
    """POST_TURN system: awards +1 bonus score to players who own a claimed entity."""

    @classmethod
    def system_name(cls) -> str:
        return "ScoreBonus"

    @classmethod
    def phase(cls) -> str:
        return "POST_TURN"

    @classmethod
    def required_prior_systems(cls) -> list[type[System]]:
        return [ActionSystem]

    @classmethod
    def required_components(cls) -> list[type[Component]]:
        return [ScoreComponent]

    def update(self, world, rng) -> None:
        claimed_players: set[uuid.UUID] = set()
        for entity, claimable in world.query(ClaimableComponent):
            if claimable.claimed_by is not None:
                claimed_players.add(claimable.claimed_by)

        for entity, score_comp in world.query(ScoreComponent):
            player_comp = entity.get(PlayerComponent)
            if player_comp.player_id in claimed_players:
                score_comp.score += 1
