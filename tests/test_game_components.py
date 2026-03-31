"""Tests for game components: instantiation, validation, constraints, serialization."""

from __future__ import annotations

import uuid

import pytest

from engine.ecs import World
from game.components import (
    FleetStats,
    Owner,
    PopulationStats,
    Position,
    Resources,
    VisibilityComponent,
)
from persistence.serialization import (
    ComponentRegistry,
    deserialize_component,
    serialize_component,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _round_trip(component, registry: ComponentRegistry):
    """Serialize then deserialize a component and return the result."""
    record = serialize_component(component)
    return deserialize_component(record, registry)


def _make_registry(*classes):
    reg = ComponentRegistry()
    reg.register(*classes)
    return reg


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------


class TestPosition:
    def test_defaults(self):
        p = Position()
        assert p.x == 0.0
        assert p.y == 0.0
        assert p.parent_system_id is None

    def test_with_values(self):
        sid = uuid.uuid4()
        p = Position(x=10.5, y=20.3, parent_system_id=sid)
        assert p.x == 10.5
        assert p.y == 20.3
        assert p.parent_system_id == sid

    def test_round_trip(self):
        reg = _make_registry(Position)
        sid = uuid.uuid4()
        original = Position(x=42.0, y=-7.5, parent_system_id=sid)
        restored = _round_trip(original, reg)
        assert isinstance(restored, Position)
        assert restored.x == original.x
        assert restored.y == original.y
        assert restored.parent_system_id == sid

    def test_round_trip_none_parent(self):
        reg = _make_registry(Position)
        original = Position(x=1.0, y=2.0, parent_system_id=None)
        restored = _round_trip(original, reg)
        assert restored.parent_system_id is None


# ---------------------------------------------------------------------------
# Owner
# ---------------------------------------------------------------------------


class TestOwner:
    def test_defaults(self):
        o = Owner()
        assert isinstance(o.player_id, uuid.UUID)
        assert o.player_name == ""

    def test_with_values(self):
        pid = uuid.uuid4()
        o = Owner(player_id=pid, player_name="Alice")
        assert o.player_id == pid
        assert o.player_name == "Alice"

    def test_round_trip(self):
        reg = _make_registry(Owner)
        pid = uuid.uuid4()
        original = Owner(player_id=pid, player_name="Bob")
        restored = _round_trip(original, reg)
        assert isinstance(restored, Owner)
        assert restored.player_id == pid
        assert restored.player_name == "Bob"


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class TestResources:
    def test_defaults(self):
        r = Resources()
        assert r.amounts == {}
        assert r.capacity == 100.0

    def test_total(self):
        r = Resources(amounts={"minerals": 20.0, "energy": 30.0})
        assert r.total() == 50.0

    def test_validate_under_capacity(self):
        r = Resources(amounts={"minerals": 40.0}, capacity=100.0)
        assert r.validate() == []

    def test_validate_over_capacity(self):
        r = Resources(amounts={"minerals": 60.0, "energy": 50.0}, capacity=100.0)
        errors = r.validate()
        assert len(errors) == 1
        assert "exceeds capacity" in errors[0]

    def test_capacity_constraint_min(self):
        r = Resources(capacity=-1.0)
        errors = r.validate()
        assert any("min" in e for e in errors)

    def test_round_trip_dict(self):
        reg = _make_registry(Resources)
        original = Resources(
            amounts={"minerals": 10.5, "energy": 20.0, "food": 5.0},
            capacity=200.0,
        )
        restored = _round_trip(original, reg)
        assert isinstance(restored, Resources)
        assert restored.amounts == original.amounts
        assert restored.capacity == original.capacity


# ---------------------------------------------------------------------------
# FleetStats
# ---------------------------------------------------------------------------


class TestFleetStats:
    def test_defaults(self):
        f = FleetStats()
        assert f.speed == 1.0
        assert f.destination_x is None
        assert f.turns_remaining == 0

    def test_speed_constraint(self):
        f = FleetStats(speed=-1.0)
        errors = f.validate()
        assert any("speed" in e and "min" in e for e in errors)

    def test_condition_constraint_max(self):
        f = FleetStats(condition=101.0)
        errors = f.validate()
        assert any("condition" in e and "max" in e for e in errors)

    def test_round_trip(self):
        reg = _make_registry(FleetStats)
        dest_sys = uuid.uuid4()
        original = FleetStats(
            speed=5.0,
            capacity=50.0,
            condition=80.0,
            destination_x=10.0,
            destination_y=20.0,
            destination_system_id=dest_sys,
            turns_remaining=3,
        )
        restored = _round_trip(original, reg)
        assert isinstance(restored, FleetStats)
        assert restored.speed == 5.0
        assert restored.destination_x == 10.0
        assert restored.destination_system_id == dest_sys
        assert restored.turns_remaining == 3

    def test_round_trip_none_destination(self):
        reg = _make_registry(FleetStats)
        original = FleetStats(speed=2.0)
        restored = _round_trip(original, reg)
        assert restored.destination_x is None
        assert restored.destination_system_id is None


# ---------------------------------------------------------------------------
# PopulationStats
# ---------------------------------------------------------------------------


class TestPopulationStats:
    def test_defaults(self):
        p = PopulationStats()
        assert p.size == 0
        assert p.growth_rate == 0.05
        assert p.morale == 1.0

    def test_morale_constraint_max(self):
        p = PopulationStats(morale=2.5)
        errors = p.validate()
        assert any("morale" in e and "max" in e for e in errors)

    def test_size_constraint_min(self):
        p = PopulationStats(size=-1)
        errors = p.validate()
        assert any("size" in e and "min" in e for e in errors)

    def test_round_trip(self):
        reg = _make_registry(PopulationStats)
        original = PopulationStats(size=500, growth_rate=0.1, morale=1.5)
        restored = _round_trip(original, reg)
        assert isinstance(restored, PopulationStats)
        assert restored.size == 500
        assert restored.growth_rate == 0.1
        assert restored.morale == 1.5


# ---------------------------------------------------------------------------
# VisibilityComponent
# ---------------------------------------------------------------------------


class TestVisibilityComponent:
    def test_defaults(self):
        v = VisibilityComponent()
        assert v.visible_to == set()
        assert v.revealed_to == set()

    def test_with_uuids(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        v = VisibilityComponent(visible_to={a}, revealed_to={a, b})
        assert len(v.visible_to) == 1
        assert len(v.revealed_to) == 2

    def test_round_trip_uuid_sets(self):
        reg = _make_registry(VisibilityComponent)
        a, b = uuid.uuid4(), uuid.uuid4()
        original = VisibilityComponent(visible_to={a}, revealed_to={a, b})
        restored = _round_trip(original, reg)
        assert isinstance(restored, VisibilityComponent)
        assert restored.visible_to == {a}
        assert restored.revealed_to == {a, b}

    def test_round_trip_empty_sets(self):
        reg = _make_registry(VisibilityComponent)
        original = VisibilityComponent()
        restored = _round_trip(original, reg)
        assert restored.visible_to == set()
        assert restored.revealed_to == set()
