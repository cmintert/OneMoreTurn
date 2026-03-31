"""Turn engine: order management, turn loop, and resolution."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.actions import Action, ActionResult, ActionSystem
from engine.events import Event
from engine.systems import System, SystemExecutor
from persistence.db import GameDatabase
from persistence.serialization import ComponentRegistry

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Turn state
# ---------------------------------------------------------------------------


class TurnState(enum.Enum):
    """State of the turn submission window."""

    ORDERS_OPEN = "orders_open"
    RESOLVING = "resolving"


class TurnError(Exception):
    """Raised for invalid turn operations (e.g., submitting while resolving)."""


# ---------------------------------------------------------------------------
# Turn result
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    """Outcome of resolving a single turn."""

    turn_number: int
    events: list[Event] = field(default_factory=list)
    results: list[ActionResult] = field(default_factory=list)
    snapshot_id: str = ""


# ---------------------------------------------------------------------------
# TurnManager
# ---------------------------------------------------------------------------


class TurnManager:
    """Orchestrates the full turn loop: order submission → resolution → persistence.

    Stateless across CLI invocations — rebuilt from DB each time.
    """

    def __init__(
        self,
        world: "World",
        game_id: str | uuid.UUID,
        db: GameDatabase,
        registry: ComponentRegistry,
        systems: list[System] | None = None,
    ) -> None:
        from engine.ecs import World

        self._world: World = world
        self._game_id = str(game_id)
        self._db = db
        self._registry = registry
        self._state = TurnState.ORDERS_OPEN
        # {player_id: {order_id: Action}}
        self._orders: dict[uuid.UUID, dict[uuid.UUID, Action]] = {}
        # Extra systems to register alongside ActionSystem
        self._systems: list[System] = list(systems or [])

    @property
    def state(self) -> TurnState:
        return self._state

    @property
    def current_turn(self) -> int:
        return self._world.current_turn

    # -- Order management --

    def submit_order(self, action: Action) -> "ValidationResult":
        """Submit an order with early validation feedback.

        Raises TurnError if the turn is not accepting orders.
        """
        from engine.actions import ValidationResult

        if self._state != TurnState.ORDERS_OPEN:
            raise TurnError("Cannot submit orders: turn is resolving")

        result = action.validate(self._world)

        # Store regardless of validation (player can fix later)
        # but give feedback now
        pid = action.player_id
        if pid not in self._orders:
            self._orders[pid] = {}
        self._orders[pid][action.order_id] = action

        return result

    def replace_order(
        self, order_id: uuid.UUID, action: Action
    ) -> "ValidationResult":
        """Replace an existing order. Same order_id, new action.

        Raises TurnError if the turn is not accepting orders.
        """
        from engine.actions import ValidationResult

        if self._state != TurnState.ORDERS_OPEN:
            raise TurnError("Cannot replace orders: turn is resolving")

        result = action.validate(self._world)

        pid = action.player_id
        if pid not in self._orders:
            self._orders[pid] = {}
        self._orders[pid][order_id] = action

        return result

    def remove_order(self, player_id: uuid.UUID, order_id: uuid.UUID) -> None:
        """Remove a specific order.

        Raises TurnError if the turn is not accepting orders.
        """
        if self._state != TurnState.ORDERS_OPEN:
            raise TurnError("Cannot remove orders: turn is resolving")

        if player_id in self._orders:
            self._orders[player_id].pop(order_id, None)

    def get_orders(self, player_id: uuid.UUID) -> list[Action]:
        """Return current orders for a player."""
        if player_id not in self._orders:
            return []
        return list(self._orders[player_id].values())

    def get_all_orders(self) -> list[Action]:
        """Return all orders from all players as a flat list."""
        actions: list[Action] = []
        for player_orders in self._orders.values():
            actions.extend(player_orders.values())
        return actions

    # -- Turn resolution --

    def resolve_turn(self) -> TurnResult:
        """Execute the full turn loop.

        1. Lock orders (state → RESOLVING)
        2. Build SystemExecutor with ActionSystem + registered systems
        3. Feed actions to ActionSystem
        4. execute_all() — ActionSystem runs first, then other systems
        5. Collect events
        6. Save snapshot + orders + events to DB
        7. Advance turn
        8. Unlock orders (state → ORDERS_OPEN)
        9. Return TurnResult
        """
        if self._state != TurnState.ORDERS_OPEN:
            raise TurnError("Turn is already resolving")

        self._state = TurnState.RESOLVING
        turn_number = self._world.current_turn

        try:
            # Clear event bus for clean event collection
            self._world.event_bus.clear()

            # Collect all orders
            all_actions = self.get_all_orders()

            # Build executor
            executor = SystemExecutor(
                self._world, self._game_id, turn_number
            )

            # ActionSystem is always first
            action_system = ActionSystem()
            action_system.set_actions(all_actions)
            executor.register(action_system)

            # Register additional systems
            for system in self._systems:
                executor.register(system)

            # Execute all systems in topological order
            executor.execute_all()

            # Collect results
            events = self._world.event_bus.emitted
            action_results = action_system.results

            # Persist snapshot
            next_turn = turn_number + 1
            self._world.current_turn = next_turn
            self._db.save_snapshot(
                self._game_id,
                next_turn,
                self._world,
                self._registry,
            )

            # Persist orders for this turn (for replay)
            self._db.save_orders(
                self._game_id, turn_number, all_actions
            )

            # Log events
            for event in events:
                self._db.log_event(
                    self._game_id,
                    turn_number,
                    event,
                )

            # Persist full events for round-trip loading
            self._db.save_events(self._game_id, turn_number, events)

            result = TurnResult(
                turn_number=turn_number,
                events=events,
                results=action_results,
                snapshot_id=f"{self._game_id}:turn:{next_turn}",
            )

            # Clear orders for next turn
            self._orders.clear()

            return result

        finally:
            self._state = TurnState.ORDERS_OPEN
