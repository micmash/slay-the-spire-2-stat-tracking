"""Tests for active_run.py — parse_active_run and model properties."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from active_run import (
    parse_active_run, ActiveRunState, ActiveCard, ActiveRelic, ActivePotion,
    find_active_run_path,
)


# ── Minimal save builder ──────────────────────────────────────────────────────

def make_save_data(
    *,
    character_id="CHARACTER.IRONCLAD",
    ascension=0,
    game_mode="standard",
    acts=None,
    act_index=0,
    current_hp=50,
    max_hp=80,
    gold=100,
    deck=None,
    relics=None,
    potions=None,
    players=None,
    map_point_history=None,
    visited_map_coords=None,
    save_time=1_700_000_000,
    pre_finished_room=None,
    net_id=None,
):
    player = {
        "character_id": character_id,
        "current_hp": current_hp,
        "max_hp": max_hp,
        "gold": gold,
        "deck": deck or [
            {"id": "CARD.STRIKE_IRONCLAD", "floor_added_to_deck": 0, "current_upgrade_level": 0},
            {"id": "CARD.DEFEND_IRONCLAD", "floor_added_to_deck": 0, "current_upgrade_level": 0},
        ],
        "relics": relics or [{"id": "RELIC.BURNING_BLOOD", "floor_added_to_deck": 0}],
        "potions": potions or [],
    }
    if net_id is not None:
        player["net_id"] = net_id
    return {
        "ascension": ascension,
        "game_mode": game_mode,
        "acts": acts or [{"id": "ACT.OVERGROWTH"}],
        "current_act_index": act_index,
        "players": players if players is not None else [player],
        "map_point_history": map_point_history or [],
        "visited_map_coords": visited_map_coords or [],
        "save_time": save_time,
        "pre_finished_room": pre_finished_room or {},
    }


# ── parse_active_run ──────────────────────────────────────────────────────────

class TestParseActiveRun:
    def test_returns_none_for_missing_file(self, tmp_path):
        assert parse_active_run(tmp_path / "nonexistent.save") is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        f = tmp_path / "bad.save"
        f.write_text("not json")
        assert parse_active_run(f) is None

    def test_returns_none_for_empty_players(self, tmp_path):
        data = make_save_data(players=[])
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        assert parse_active_run(f) is None

    def test_basic_parse(self, tmp_path):
        data = make_save_data()
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state is not None
        assert state.character == "CHARACTER.IRONCLAD"
        assert state.ascension == 0
        assert state.game_mode == "standard"
        assert state.current_hp == 50
        assert state.max_hp == 80
        assert state.gold == 100

    def test_deck_parsed(self, tmp_path):
        deck = [
            {"id": "CARD.BASH", "floor_added_to_deck": 3, "current_upgrade_level": 1},
            {"id": "CARD.STRIKE_IRONCLAD", "floor_added_to_deck": 0, "current_upgrade_level": 0},
        ]
        data = make_save_data(deck=deck)
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert len(state.deck) == 2
        bash = next(c for c in state.deck if c.card_id == "CARD.BASH")
        assert bash.floor_added == 3
        assert bash.upgrade_level == 1
        assert bash.is_upgraded

    def test_deck_skips_empty_card_id(self, tmp_path):
        deck = [{"id": "", "floor_added_to_deck": 0, "current_upgrade_level": 0}]
        data = make_save_data(deck=deck)
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.deck == []

    def test_relic_parsed(self, tmp_path):
        relics = [{"id": "RELIC.ANCHOR", "floor_added_to_deck": 1}]
        data = make_save_data(relics=relics)
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert len(state.relics) == 1
        assert state.relics[0].relic_id == "RELIC.ANCHOR"
        assert state.relics[0].floor_added == 1

    def test_potion_parsed(self, tmp_path):
        potions = [{"id": "POTION.FIRE_POTION", "slot_index": 0}]
        data = make_save_data(potions=potions)
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert len(state.potions) == 1
        assert state.potions[0].potion_id == "POTION.FIRE_POTION"
        assert state.potions[0].slot_index == 0

    def test_act_index(self, tmp_path):
        acts = [{"id": "ACT.OVERGROWTH"}, {"id": "ACT.THE_HIVE"}]
        data = make_save_data(acts=acts, act_index=1)
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.current_act == "ACT.THE_HIVE"
        assert state.act_index == 1

    def test_act_index_out_of_range(self, tmp_path):
        acts = [{"id": "ACT.OVERGROWTH"}]
        data = make_save_data(acts=acts, act_index=5)
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.current_act == "ACT.UNKNOWN"

    def test_floor_count_previous_acts_plus_visited(self, tmp_path):
        # Act 0 fully done: 4 rooms in map_point_history[0]
        # Act 1 current: visited 3 nodes (including ancient=floor 0, so 2 real floors)
        map_history = [
            [{"player_stats": []} for _ in range(4)],  # act 0 done
            [],                                          # act 1 placeholder
        ]
        visited = [{"x": 0, "y": 0}] * 3  # 3 nodes = 2 floors (subtract ancient)
        data = make_save_data(map_point_history=map_history, visited_map_coords=visited, act_index=1,
                              acts=[{"id": "ACT.OVERGROWTH"}, {"id": "ACT.THE_HIVE"}])
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.floors_completed == 4 + 2  # 4 from act 0 + 2 from act 1

    def test_floor_count_no_visited_falls_back_to_map_history(self, tmp_path):
        # When visited_map_coords is empty, floor count falls back to map_point_history[act_idx]
        map_history = [[{"player_stats": []} for _ in range(3)]]
        data = make_save_data(map_point_history=map_history, visited_map_coords=[], act_index=0)
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.floors_completed == 3  # fallback to len(map_history[0])

    def test_reward_pending_false(self, tmp_path):
        data = make_save_data(pre_finished_room={"is_pre_finished": False})
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert not state.is_reward_pending
        assert state.reward_encounter_id is None

    def test_reward_pending_true(self, tmp_path):
        pre = {"is_pre_finished": True, "encounter_id": "ENCOUNTER.JAW_WORM"}
        data = make_save_data(pre_finished_room=pre)
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.is_reward_pending
        assert state.reward_encounter_id == "ENCOUNTER.JAW_WORM"

    def test_multiplayer_picks_host_by_net_id(self, tmp_path):
        p1 = {
            "character_id": "CHARACTER.IRONCLAD",
            "current_hp": 70, "max_hp": 80, "gold": 50,
            "net_id": 2,
            "deck": [], "relics": [], "potions": [],
        }
        p2 = {
            "character_id": "CHARACTER.THE_SILENT",
            "current_hp": 40, "max_hp": 60, "gold": 90,
            "net_id": 1,
            "deck": [], "relics": [], "potions": [],
        }
        data = make_save_data(players=[p1, p2])
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.character == "CHARACTER.THE_SILENT"  # net_id=1 is host
        assert state.player_count == 2

    def test_player_count_sp(self, tmp_path):
        data = make_save_data()
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.player_count == 1

    def test_ascension_and_game_mode(self, tmp_path):
        data = make_save_data(ascension=10, game_mode="daily")
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.ascension == 10
        assert state.is_daily

    def test_enchanted_card(self, tmp_path):
        deck = [{"id": "CARD.BASH", "floor_added_to_deck": 1, "current_upgrade_level": 0,
                 "enchantment": {"id": "ENCHANTMENT.ECHO"}}]
        data = make_save_data(deck=deck)
        f = tmp_path / "run.save"
        f.write_text(json.dumps(data))
        state = parse_active_run(f)
        assert state.deck[0].enchantment == "ENCHANTMENT.ECHO"


# ── ActiveCard properties ─────────────────────────────────────────────────────

class TestActiveCard:
    def test_display_name_basic(self):
        c = ActiveCard(card_id="CARD.BASH", floor_added=0, upgrade_level=0)
        assert c.display_name == "Bash"

    def test_display_name_upgraded(self):
        c = ActiveCard(card_id="CARD.BASH", floor_added=0, upgrade_level=1)
        assert c.display_name == "Bash+"

    def test_display_name_double_upgrade(self):
        c = ActiveCard(card_id="CARD.BASH", floor_added=0, upgrade_level=2)
        assert c.display_name == "Bash++"

    def test_display_name_with_enchantment(self):
        c = ActiveCard(card_id="CARD.BASH", floor_added=0, upgrade_level=0,
                       enchantment="ENCHANTMENT.ECHO")
        assert "[Echo]" in c.display_name

    def test_is_upgraded_false(self):
        c = ActiveCard(card_id="CARD.BASH", floor_added=0, upgrade_level=0)
        assert not c.is_upgraded

    def test_is_upgraded_true(self):
        c = ActiveCard(card_id="CARD.BASH", floor_added=0, upgrade_level=1)
        assert c.is_upgraded


# ── ActiveRelic properties ────────────────────────────────────────────────────

class TestActiveRelic:
    def test_display_name(self):
        r = ActiveRelic(relic_id="RELIC.BURNING_BLOOD", floor_added=0)
        assert r.display_name == "Burning Blood"


# ── ActivePotion properties ───────────────────────────────────────────────────

class TestActivePotion:
    def test_display_name(self):
        p = ActivePotion(potion_id="POTION.FIRE_POTION", slot_index=0)
        assert p.display_name == "Fire Potion"


# ── ActiveRunState properties ─────────────────────────────────────────────────

class TestActiveRunState:
    def _make(self, **kw):
        defaults = dict(
            character="CHARACTER.IRONCLAD", ascension=0, game_mode="standard",
            current_act="ACT.OVERGROWTH", act_index=0, floors_completed=5,
            current_hp=50, max_hp=80, gold=100,
            deck=[], relics=[], potions=[],
            player_count=1, save_time=0,
        )
        defaults.update(kw)
        return ActiveRunState(**defaults)

    def test_character_display(self):
        assert self._make().character_display == "Ironclad"

    def test_act_display(self):
        assert self._make().act_display == "Overgrowth"

    def test_hp_pct(self):
        s = self._make(current_hp=40, max_hp=80)
        assert s.hp_pct == pytest.approx(0.5)

    def test_hp_pct_zero_max(self):
        s = self._make(current_hp=0, max_hp=0)
        assert s.hp_pct == 0.0

    def test_is_daily_false(self):
        assert not self._make(game_mode="standard").is_daily

    def test_is_daily_true(self):
        assert self._make(game_mode="daily").is_daily

    def test_is_multiplayer_false(self):
        assert not self._make(player_count=1).is_multiplayer

    def test_is_multiplayer_true(self):
        assert self._make(player_count=2).is_multiplayer


# ── find_active_run_path ──────────────────────────────────────────────────────

class TestFindActiveRunPath:
    def test_returns_none_when_no_save_dir(self):
        with patch("active_run.find_default_save_path", return_value=None):
            assert find_active_run_path() is None

    def test_returns_none_when_save_missing(self, tmp_path):
        fake_history = tmp_path / "history"
        fake_history.mkdir()
        with patch("active_run.find_default_save_path", return_value=fake_history):
            # current_run.save doesn't exist in tmp_path/saves/
            assert find_active_run_path() is None

    def test_returns_path_when_save_exists(self, tmp_path):
        fake_history = tmp_path / "history"
        fake_history.mkdir()
        save = fake_history.parent / "current_run.save"
        save.write_text("{}")
        with patch("active_run.find_default_save_path", return_value=fake_history):
            result = find_active_run_path()
            assert result == save
