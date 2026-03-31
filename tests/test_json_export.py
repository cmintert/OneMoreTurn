"""Tests for cli.json_export — Phase 6 JSON export layer."""

from __future__ import annotations

import pytest

from cli.json_export import (
    create_game,
    export_game_state,
    list_games,
    resolve_turn,
    submit_action,
)


# ---------------------------------------------------------------------------
# list_games
# ---------------------------------------------------------------------------


class TestListGames:
    def test_no_games_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert list_games() == []

    def test_empty_games_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "games").mkdir()
        assert list_games() == []

    def test_lists_existing_game(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        create_game("mygame", player1="Alice", player2="Bob")
        result = list_games()
        assert len(result) == 1
        assert result[0]["id"] == "mygame"
        assert result[0]["turn"] == 0
        assert "Alice" in result[0]["players"]
        assert "Bob" in result[0]["players"]


# ---------------------------------------------------------------------------
# create_game
# ---------------------------------------------------------------------------


class TestCreateGame:
    def test_returns_expected_shape(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = create_game("g1", player1="Alice", player2="Bob")
        assert result["game_id"] == "g1"
        assert result["turn"] == 0
        assert "Alice" in result["players"]
        assert "Bob" in result["players"]

    def test_creates_db_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        create_game("g2")
        assert (tmp_path / "games" / "g2" / "g2.db").exists()

    def test_deterministic_with_seed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r1 = create_game("g_a", player1="Alice", player2="Bob", seed="fixed")
        r2 = create_game("g_b", player1="Alice", player2="Bob", seed="fixed")
        # Same seed → same player UUIDs
        assert r1["players"]["Alice"] == r2["players"]["Alice"]
        assert r1["players"]["Bob"] == r2["players"]["Bob"]


# ---------------------------------------------------------------------------
# export_game_state
# ---------------------------------------------------------------------------


class TestExportGameState:
    @pytest.fixture()
    def game(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        create_game("eg", player1="Alice", player2="Bob")
        return "eg"

    def test_returns_expected_keys(self, game):
        state = export_game_state(game, "Alice")
        assert state["game_id"] == game
        assert state["player_name"] == "Alice"
        for key in ("turn", "fleets", "planets", "star_systems", "visible_entities", "events"):
            assert key in state

    def test_own_fleet_present(self, game):
        state = export_game_state(game, "Alice")
        names = [f["name"] for f in state["fleets"]]
        assert any("Alice" in n for n in names)

    def test_enemy_fleet_not_in_own_fleets(self, game):
        state = export_game_state(game, "Alice")
        names = [f["name"] for f in state["fleets"]]
        assert not any("Bob" in n for n in names)

    def test_own_planet_present(self, game):
        state = export_game_state(game, "Alice")
        names = [p["name"] for p in state["planets"]]
        assert any("Alice" in n for n in names)

    def test_star_systems_always_present(self, game):
        state = export_game_state(game, "Alice")
        # setup_game creates 2 home systems + 5 neutral = 7 total
        assert len(state["star_systems"]) == 7

    def test_fog_of_war_backend_filtering(self, tmp_path, monkeypatch):
        """Enemy fleet outside OBSERVATION_RANGE must be absent from JSON entirely."""
        monkeypatch.chdir(tmp_path)
        from engine.ecs import World
        from engine.names import NameComponent
        from engine.rng import SystemRNG
        from game.archetypes import create_fleet, create_star_system
        from game.components import Owner, VisibilityComponent
        from game.registry import game_component_registry
        from persistence.db import GameDatabase
        import uuid

        world = World()
        alice_id = uuid.uuid4()
        bob_id = uuid.uuid4()

        # Alice's system at (0, 0), Bob's system far away at (100, 100)
        alice_sys = create_star_system(world, "AliceSys", 0.0, 0.0)
        bob_sys = create_star_system(world, "BobSys", 100.0, 100.0)

        create_fleet(world, "Alice_Fleet1", alice_id, "Alice", alice_sys)
        bob_fleet = create_fleet(world, "Bob_Fleet1", bob_id, "Bob", bob_sys)

        # Bob's fleet is owned by Bob — VisibilityComponent.visible_to stays empty
        # (VisibilitySystem hasn't run, so nobody can see Bob's fleet)
        vis = bob_fleet.get(VisibilityComponent)
        assert alice_id not in vis.visible_to
        assert alice_id not in vis.revealed_to

        game_dir = tmp_path / "games" / "fogtest"
        game_dir.mkdir(parents=True)
        db_path = game_dir / "fogtest.db"
        db = GameDatabase(str(db_path))
        db.init_schema()
        registry = game_component_registry()
        db.save_snapshot("fogtest", 0, world, registry)
        db.close()

        # Alice's view: Bob_Fleet1 must not appear anywhere
        state = export_game_state("fogtest", "Alice")
        all_names = (
            [f["name"] for f in state["fleets"]]
            + [e["name"] for e in state["visible_entities"]]
        )
        assert "Bob_Fleet1" not in all_names

    def test_stale_entity_appears_with_stale_flag(self, tmp_path, monkeypatch):
        """Entity in revealed_to but not visible_to shows as stale=True."""
        monkeypatch.chdir(tmp_path)
        from engine.ecs import World
        from game.archetypes import create_fleet, create_star_system
        from game.components import VisibilityComponent
        from game.registry import game_component_registry
        from persistence.db import GameDatabase
        import uuid

        world = World()
        alice_id = uuid.uuid4()
        bob_id = uuid.uuid4()

        alice_sys = create_star_system(world, "AliceSys", 0.0, 0.0)
        bob_sys = create_star_system(world, "BobSys", 100.0, 100.0)
        create_fleet(world, "Alice_Fleet1", alice_id, "Alice", alice_sys)
        bob_fleet = create_fleet(world, "Bob_Fleet1", bob_id, "Bob", bob_sys)

        # Manually mark Bob's fleet as previously seen (stale) by Alice
        world.remove_component(bob_fleet.id, VisibilityComponent)
        world.add_component(bob_fleet.id, VisibilityComponent(
            visible_to=set(),
            revealed_to={alice_id},
        ))

        game_dir = tmp_path / "games" / "staletest"
        game_dir.mkdir(parents=True)
        db_path = game_dir / "staletest.db"
        db = GameDatabase(str(db_path))
        db.init_schema()
        registry = game_component_registry()
        db.save_snapshot("staletest", 0, world, registry)
        db.close()

        state = export_game_state("staletest", "Alice")
        stale_entries = [e for e in state["visible_entities"] if e["name"] == "Bob_Fleet1"]
        assert len(stale_entries) == 1
        assert stale_entries[0]["stale"] is True

    def test_unknown_player_raises(self, game):
        with pytest.raises(KeyError, match="nobody"):
            export_game_state(game, "nobody")


# ---------------------------------------------------------------------------
# submit_action
# ---------------------------------------------------------------------------


class TestSubmitAction:
    @pytest.fixture()
    def game(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        create_game("sa", player1="Alice", player2="Bob")
        return "sa"

    def test_valid_move_fleet(self, game):
        result = submit_action(
            game, "Alice", "MoveFleet", {"fleet": "Alice_Fleet1", "target": "Alpha"}
        )
        assert result["valid"] is True
        assert result["errors"] == []

    def test_invalid_unknown_action_type(self, game):
        result = submit_action(game, "Alice", "FlyToMoon", {})
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_invalid_unknown_player(self, game):
        result = submit_action(
            game, "nobody", "MoveFleet", {"fleet": "Alice_Fleet1", "target": "Alpha"}
        )
        assert result["valid"] is False
        assert "nobody" in result["errors"][0]


# ---------------------------------------------------------------------------
# resolve_turn
# ---------------------------------------------------------------------------


class TestResolveTurn:
    def test_resolve_increments_turn(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        create_game("rt", player1="Alice", player2="Bob")
        result = resolve_turn("rt")
        assert result["turn"] == 1
        assert "event_count" in result
        assert isinstance(result["action_results"], list)

    def test_resolve_with_action(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        create_game("rt2", player1="Alice", player2="Bob")
        submit_action(
            "rt2", "Alice", "MoveFleet", {"fleet": "Alice_Fleet1", "target": "Alpha"}
        )
        result = resolve_turn("rt2")
        assert result["turn"] == 1
        executed = [r for r in result["action_results"] if r["status"] == "executed"]
        assert len(executed) >= 1
