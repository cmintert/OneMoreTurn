"""Deterministic RNG scoped to a specific system and turn."""

from __future__ import annotations

import hashlib
import random
import uuid
from typing import MutableSequence, Sequence, TypeVar

T = TypeVar("T")


class SystemRNG:
    """Seeded RNG derived from (game_id, turn_number, system_name).

    Each system gets its own independent RNG instance so that adding or
    removing systems does not change the random sequence of other systems.
    """

    def __init__(
        self,
        game_id: str | uuid.UUID,
        turn_number: int,
        system_name: str,
    ) -> None:
        seed_string = f"{game_id}:{turn_number}:{system_name}"
        seed_bytes = hashlib.sha256(seed_string.encode()).digest()
        self._seed = int.from_bytes(seed_bytes[:8])
        self._rng = random.Random(self._seed)

    @property
    def seed(self) -> int:
        """The computed seed value (for debugging/logging)."""
        return self._seed

    def random(self) -> float:
        """Return random float in [0.0, 1.0)."""
        return self._rng.random()

    def randint(self, a: int, b: int) -> int:
        """Return random integer N such that a <= N <= b."""
        return self._rng.randint(a, b)

    def choice(self, seq: Sequence[T]) -> T:
        """Return a random element from a non-empty sequence."""
        return self._rng.choice(seq)

    def shuffle(self, seq: MutableSequence[T]) -> None:
        """Shuffle sequence in place."""
        self._rng.shuffle(seq)
