"""Tests for SystemRNG determinism and correctness."""

from __future__ import annotations

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from engine.rng import SystemRNG


GAME_ID = "test-game-001"


def test_identical_seeds_identical_results():
    rng1 = SystemRNG(GAME_ID, turn_number=1, system_name="Combat")
    rng2 = SystemRNG(GAME_ID, turn_number=1, system_name="Combat")
    assert [rng1.random() for _ in range(20)] == [rng2.random() for _ in range(20)]


def test_different_system_different_results():
    rng1 = SystemRNG(GAME_ID, turn_number=1, system_name="Combat")
    rng2 = SystemRNG(GAME_ID, turn_number=1, system_name="Movement")
    assert [rng1.random() for _ in range(10)] != [rng2.random() for _ in range(10)]


def test_different_turn_different_results():
    rng1 = SystemRNG(GAME_ID, turn_number=1, system_name="Combat")
    rng2 = SystemRNG(GAME_ID, turn_number=2, system_name="Combat")
    assert [rng1.random() for _ in range(10)] != [rng2.random() for _ in range(10)]


def test_different_game_different_results():
    rng1 = SystemRNG("game-a", turn_number=1, system_name="Combat")
    rng2 = SystemRNG("game-b", turn_number=1, system_name="Combat")
    assert [rng1.random() for _ in range(10)] != [rng2.random() for _ in range(10)]


def test_random_range():
    rng = SystemRNG(GAME_ID, turn_number=1, system_name="Test")
    for _ in range(100):
        val = rng.random()
        assert 0.0 <= val < 1.0


def test_randint_range():
    rng = SystemRNG(GAME_ID, turn_number=1, system_name="Test")
    for _ in range(100):
        val = rng.randint(5, 10)
        assert 5 <= val <= 10


def test_choice_from_sequence():
    rng = SystemRNG(GAME_ID, turn_number=1, system_name="Test")
    options = ["a", "b", "c"]
    for _ in range(50):
        assert rng.choice(options) in options


def test_shuffle_deterministic():
    items1 = [1, 2, 3, 4, 5, 6, 7, 8]
    items2 = [1, 2, 3, 4, 5, 6, 7, 8]
    rng1 = SystemRNG(GAME_ID, turn_number=1, system_name="Shuffle")
    rng2 = SystemRNG(GAME_ID, turn_number=1, system_name="Shuffle")
    rng1.shuffle(items1)
    rng2.shuffle(items2)
    assert items1 == items2


def test_independent_instances():
    rng1 = SystemRNG(GAME_ID, turn_number=1, system_name="A")
    rng2 = SystemRNG(GAME_ID, turn_number=1, system_name="B")
    # Consume some values from rng1
    for _ in range(10):
        rng1.random()
    # rng2 should still produce its original sequence
    rng2_fresh = SystemRNG(GAME_ID, turn_number=1, system_name="B")
    assert [rng2.random() for _ in range(10)] == [rng2_fresh.random() for _ in range(10)]


def test_uuid_game_id():
    gid = uuid.uuid4()
    rng1 = SystemRNG(gid, turn_number=1, system_name="Test")
    rng2 = SystemRNG(gid, turn_number=1, system_name="Test")
    assert [rng1.random() for _ in range(10)] == [rng2.random() for _ in range(10)]


def test_seed_property():
    rng = SystemRNG(GAME_ID, turn_number=1, system_name="Test")
    assert isinstance(rng.seed, int)


@given(
    game_id=st.text(min_size=1, max_size=20),
    turn=st.integers(min_value=0, max_value=10000),
    name=st.text(min_size=1, max_size=30),
)
@settings(max_examples=50)
def test_hypothesis_determinism(game_id: str, turn: int, name: str):
    rng1 = SystemRNG(game_id, turn_number=turn, system_name=name)
    rng2 = SystemRNG(game_id, turn_number=turn, system_name=name)
    seq1 = [rng1.random() for _ in range(20)]
    seq2 = [rng2.random() for _ in range(20)]
    assert seq1 == seq2
