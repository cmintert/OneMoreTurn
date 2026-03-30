---
title: "Phase 3 Documentation: Turn Engine"
status: "Complete"
date: 2026-03-30
---

# Phase 3 Documentation: Turn Engine

## Overview

Phase 3 implements the **turn resolution loop** — the core PBEM pipeline: orders in → validate → execute → systems run → snapshot → events out. This phase adds the Action protocol, conflict resolution, order management, a Typer CLI, and name-to-UUID resolution. No game-specific content is shipped; all gameplay behavior uses stub components and actions from the test infrastructure.

**Status:** Complete. 68 new tests passing. All exit criteria met. All 179 Phase 1+2 tests still passing (247 total).

---

## What Was Built

### New Modules

| File | Purpose |
|------|---------|
| `src/engine/actions.py` | Action ABC, ValidationResult, ActionResult, ActionSystem |
| `src/engine/names.py` | NameComponent, NameResolver (name↔UUID bridge) |
| `src/engine/turn.py` | TurnManager, TurnState, TurnResult, TurnError |
| `src/cli/__init__.py` | CLI package init |
| `src/cli/main.py` | Typer CLI: create-game, submit-orders, resolve-turn, query-state |
| `tests/stubs.py` | Stub components, actions, and systems for testing |
| `tests/test_actions.py` | 27 tests for Action protocol and ActionSystem |
| `tests/test_names.py` | 11 tests for NameComponent and NameResolver |
| `tests/test_turn.py` | 17 tests for TurnManager and turn loop |
| `tests/test_cli.py` | 13 tests for CLI commands and exit criteria |

### Modified Files

| File | Change |
|------|--------|
| `src/persistence/db.py` | Added `orders` table, `save_orders()`, `load_orders()` |
| `src/persistence/serialization.py` | Added `ActionRegistry`, `serialize_action()`, `deserialize_action()` |
| `src/engine/__init__.py` | Exported all Phase 3 symbols |
| `src/persistence/__init__.py` | Exported ActionRegistry, serialize/deserialize_action |
| `pyproject.toml` | Version 0.2.0, `cli` optional dep, `[project.scripts]` entry, `tests` on pythonpath |

---

## Architecture

### Action Protocol

Every player order is an `Action` subclass (dataclass + ABC):

```
Action.action_type() -> str           # Unique type identifier
Action.player_id -> UUID              # Who issued it
Action.order_id -> UUID               # Unique order ID (for replacement)
Action.validate(world) -> ValidationResult   # Can it execute?
Action.execute(world) -> list[Event]         # Mutate state, emit events
Action.conflict_key() -> str | None          # Conflict grouping (None = no conflict)
Action.conflict_weight() -> float            # Weight for conflict resolution
```

### ActionSystem

The `ActionSystem` is a `System` (MAIN phase) that processes all actions in a turn:

1. **Validate** each action independently — reject invalid ones with feedback
2. **Group** valid actions by `conflict_key()`
3. **Resolve conflicts** — per-conflict deterministic RNG (seed = SHA256 of `rng_seed:conflict_key`), weighted random selection picks winner
4. **Execute** winners + non-conflicting actions in deterministic order (sorted by `(action_type, order_id)`)
5. **Publish events** — ActionExecuted, ActionRejected, ActionConflictLost

Invalid actions never block valid ones. Conflict losers receive feedback.

### TurnManager

Orchestrates the full turn lifecycle:

```
ORDERS_OPEN → submit_order() / replace_order() / remove_order()
            → resolve_turn():
                1. Lock orders (RESOLVING)
                2. Build SystemExecutor (ActionSystem first, then registered systems)
                3. execute_all()
                4. Save snapshot (turn+1) + orders + events to DB
                5. Advance world.current_turn
                6. Clear orders
                7. Unlock (ORDERS_OPEN)
            → TurnResult with events, results, snapshot_id
```

Stateless across CLI invocations — rebuilt from DB each time.

### Name Resolution

`NameComponent` is a standard Component with a `name: str` field. `NameResolver` queries the World for entities matching a name, providing the player-facing name→UUID bridge. Players never see UUIDs.

### CLI

Four Typer commands provide the PBEM workflow:

- **`create-game`** — Initialize DB, create player + claimable entities, save turn-0 snapshot
- **`submit-orders`** — Load state, resolve names, validate actions, persist orders
- **`resolve-turn`** — Load state + orders, run TurnManager.resolve_turn(), save results
- **`query-state`** — Display entity state at any turn, with optional entity filter

### Order Persistence

Orders are serialized via `ActionRegistry` (mirrors `ComponentRegistry`) and stored in an `orders` table:

```sql
orders(order_id, game_id, turn_number, player_id, action_type, action_data, submitted_at)
```

This enables turn replay: load snapshot N, load orders for turn N, re-resolve → identical result.

---

## Test Infrastructure

### Stub Components (tests/stubs.py)

| Stub | Purpose |
|------|---------|
| `PlayerComponent` | Identifies a player entity (name, player_id) |
| `ScoreComponent` | Simple numeric state (depends on PlayerComponent) |
| `ClaimableComponent` | Entity that can be claimed (claimed_by UUID) |
| `IncrementScoreAction` | Validates ownership, increments score |
| `ClaimAction` | Validates unclaimed, claims entity. conflict_key = `claim:{target_id}` |
| `ScoreBonusSystem` | POST_TURN: awards +1 score per claimed entity owned |

Stubs are in a separate importable module (not conftest) so both test files and the CLI can import them.

---

## Exit Criteria — Met

1. **2-player, 3-turn game via CLI**: `test_two_player_three_turns_via_cli` — creates game, submits orders across 3 turns with claims and score increments, verifies final state.

2. **Replay determinism**: `test_replay_turn_from_snapshot_determinism` — resolves turn 1, then reloads turn-1 snapshot + orders, re-resolves in a fresh DB, compares entity snapshots — identical.

3. **Conflict resolution**: `test_conflict_one_wins_one_loses` + `test_conflict_resolution_determinism` — two ClaimActions on same target, one wins, one gets ActionConflictLost. Same seed = same winner.

4. **Invalid orders don't block valid**: `test_invalid_does_not_block_valid` — one invalid IncrementScoreAction and one valid ClaimAction in the same batch; claim executes.

5. **Order replacement**: `test_replace_order_supersedes_original` — replace_order with same order_id overwrites the previous action.

---

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Conflict RNG: SHA256(rng_seed:conflict_key) | Deterministic per-conflict, independent of processing order |
| ActionSystem runs in MAIN phase | Other systems declaring `required_prior_systems=[ActionSystem]` run after |
| Stubs in `tests/stubs.py` not conftest | Must be importable by both tests and CLI; conftest is auto-loaded by pytest |
| CLI uses `stubs` imports directly | Phase 3 has no real game content; Phase 4 will register domain types |
| `tests` added to pytest pythonpath | Allows `from stubs import ...` in test files and CLI |
| Orders persisted even if invalid at submit time | Player can fix later; early validation is feedback, resolution is authoritative |

---

## Test Counts

| Test File | Count |
|-----------|-------|
| test_actions.py | 27 |
| test_names.py | 11 |
| test_turn.py | 17 |
| test_cli.py | 13 |
| **Phase 3 total** | **68** |
| Phase 1+2 (unchanged) | 179 |
| **Grand total** | **247** |
