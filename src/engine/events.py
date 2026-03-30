"""Event system: immutable events and publish/subscribe event bus."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Event:
    """Immutable record of something that happened in the world."""

    who: str | uuid.UUID
    what: str
    when: int
    why: str
    effects: dict[str, Any]
    visibility_scope: list[str | uuid.UUID] | None = None
    timestamp: float = field(default_factory=time.monotonic)


class EventBus:
    """Typed publish/subscribe event bus with ordered history."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}
        self._wildcard_subscribers: list[Callable[[Event], None]] = []
        self._history: list[Event] = []

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        """Register a handler for a specific event type (matched on event.what)."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: Callable[[Event], None]) -> None:
        """Register a handler that receives all events regardless of type."""
        self._wildcard_subscribers.append(handler)

    def publish(self, event: Event) -> None:
        """Publish an event. Dispatches to type-specific then wildcard handlers."""
        self._history.append(event)
        for handler in self._subscribers.get(event.what, []):
            handler(event)
        for handler in self._wildcard_subscribers:
            handler(event)

    @property
    def emitted(self) -> list[Event]:
        """All events published so far, in order."""
        return list(self._history)

    def clear(self) -> None:
        """Clear event history."""
        self._history.clear()
