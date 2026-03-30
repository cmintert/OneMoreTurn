"""Tests for Event and EventBus."""

from __future__ import annotations

import uuid

import pytest

from engine.events import Event, EventBus


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


def _make_event(what: str = "TestEvent", **overrides) -> Event:
    defaults = dict(who="system", what=what, when=0, why="test", effects={})
    defaults.update(overrides)
    return Event(**defaults)


class TestEvent:
    def test_fields_present(self):
        e = _make_event(
            who="sys",
            what="Moved",
            when=1,
            why="order-1",
            effects={"dx": 5},
            visibility_scope=["player-a"],
        )
        assert e.who == "sys"
        assert e.what == "Moved"
        assert e.when == 1
        assert e.why == "order-1"
        assert e.effects == {"dx": 5}
        assert e.visibility_scope == ["player-a"]
        assert isinstance(e.timestamp, float)

    def test_visibility_scope_defaults_none(self):
        e = _make_event()
        assert e.visibility_scope is None

    def test_immutability(self):
        e = _make_event()
        with pytest.raises(AttributeError):
            e.what = "changed"

    def test_timestamp_auto_populated(self):
        e1 = _make_event()
        e2 = _make_event()
        assert isinstance(e1.timestamp, float)
        assert e2.timestamp >= e1.timestamp


class TestEventBus:
    def test_publish_to_subscriber(self, bus: EventBus):
        received = []
        bus.subscribe("Hit", received.append)
        event = _make_event(what="Hit")
        bus.publish(event)
        assert received == [event]

    def test_publish_no_subscriber_no_error(self, bus: EventBus):
        bus.publish(_make_event(what="Orphan"))

    def test_subscribe_filters_by_type(self, bus: EventBus):
        received_a = []
        received_b = []
        bus.subscribe("TypeA", received_a.append)
        bus.subscribe("TypeB", received_b.append)

        event_a = _make_event(what="TypeA")
        event_b = _make_event(what="TypeB")
        bus.publish(event_a)
        bus.publish(event_b)

        assert received_a == [event_a]
        assert received_b == [event_b]

    def test_subscribe_all(self, bus: EventBus):
        received = []
        bus.subscribe_all(received.append)
        e1 = _make_event(what="Alpha")
        e2 = _make_event(what="Beta")
        bus.publish(e1)
        bus.publish(e2)
        assert received == [e1, e2]

    def test_emitted_returns_ordered_history(self, bus: EventBus):
        events = [_make_event(what=f"E{i}") for i in range(5)]
        for e in events:
            bus.publish(e)
        assert bus.emitted == events

    def test_emitted_returns_copy(self, bus: EventBus):
        bus.publish(_make_event())
        history = bus.emitted
        history.clear()
        assert len(bus.emitted) == 1

    def test_clear(self, bus: EventBus):
        bus.publish(_make_event())
        bus.publish(_make_event())
        bus.clear()
        assert bus.emitted == []

    def test_multiple_subscribers_same_type(self, bus: EventBus):
        r1, r2 = [], []
        bus.subscribe("X", r1.append)
        bus.subscribe("X", r2.append)
        event = _make_event(what="X")
        bus.publish(event)
        assert r1 == [event]
        assert r2 == [event]

    def test_subscriber_order(self, bus: EventBus):
        order = []
        bus.subscribe("X", lambda e: order.append("first"))
        bus.subscribe("X", lambda e: order.append("second"))
        bus.subscribe_all(lambda e: order.append("wildcard"))
        bus.publish(_make_event(what="X"))
        assert order == ["first", "second", "wildcard"]

    def test_wildcard_receives_all_types(self, bus: EventBus):
        received = []
        bus.subscribe_all(received.append)
        bus.subscribe("Specific", lambda e: None)
        e1 = _make_event(what="Specific")
        e2 = _make_event(what="Other")
        bus.publish(e1)
        bus.publish(e2)
        assert received == [e1, e2]
