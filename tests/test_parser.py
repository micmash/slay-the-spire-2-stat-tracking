"""Tests for parser.py — formatting functions, run parsing, and loading."""
import json
import os
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from parser import (
    strip_prefix, fmt_card, fmt_relic, fmt_character, fmt_act,
    parse_run_file, load_all_runs, RunSummary, CardPick, RelicPick,
    _find_local_player, _extract_card_picks, _extract_relic_picks,
    _get_final_player_stats, find_default_save_path,
)
from conftest import make_run_data


# ── Formatting helpers ────────────────────────────────────────────────────────

class TestStripPrefix:
    def test_removes_present_prefix(self):
        assert strip_prefix("CARD.BASH", "CARD.") == "BASH"

    def test_no_op_when_prefix_absent(self):
        assert strip_prefix("BASH", "CARD.") == "BASH"

    def test_empty_string(self):
        assert strip_prefix("", "CARD.") == ""

    def test_empty_prefix(self):
        assert strip_prefix("BASH", "") == "BASH"

    def test_prefix_equals_string(self):
        assert strip_prefix("CARD.", "CARD.") == ""


class TestFmtCard:
    def test_strips_prefix_and_formats(self):
        assert fmt_card("CARD.STRIKE_IRONCLAD") == "Strike Ironclad"

    def test_no_prefix(self):
        assert fmt_card("BASH") == "Bash"

    def test_single_word(self):
        assert fmt_card("CARD.BASH") == "Bash"

    def test_multiple_underscores(self):
        assert fmt_card("CARD.FEEL_NO_PAIN") == "Feel No Pain"


class TestFmtRelic:
    def test_strips_relic_prefix(self):
        assert fmt_relic("RELIC.BURNING_BLOOD") == "Burning Blood"

    def test_no_prefix(self):
        assert fmt_relic("ANCHOR") == "Anchor"


class TestFmtCharacter:
    def test_strips_character_prefix(self):
        assert fmt_character("CHARACTER.IRONCLAD") == "Ironclad"

    def test_multiword(self):
        assert fmt_character("CHARACTER.THE_SILENT") == "The Silent"


class TestFmtAct:
    def test_strips_act_prefix(self):
        assert fmt_act("ACT.OVERGROWTH") == "Overgrowth"

    def test_multiword(self):
        assert fmt_act("ACT.THE_HIVE") == "The Hive"


# ── RunSummary properties ─────────────────────────────────────────────────────

class TestRunSummaryProperties:
    def _make(self, **kw):
        from conftest import make_run_summary
        return make_run_summary(**kw)

    def test_is_multiplayer_false_for_sp(self):
        assert not self._make(player_count=1).is_multiplayer

    def test_is_multiplayer_true_for_mp(self):
        assert self._make(player_count=2).is_multiplayer

    def test_is_daily_false_for_standard(self):
        assert not self._make(game_mode="standard").is_daily

    def test_is_daily_true_for_daily(self):
        assert self._make(game_mode="daily").is_daily

    def test_date_returns_datetime(self):
        r = self._make(start_time=1_700_000_000)
        assert isinstance(r.date, datetime)

    def test_character_display(self):
        assert self._make(character="CHARACTER.IRONCLAD").character_display == "Ironclad"

    def test_acts_display_single(self):
        r = self._make()
        r.acts = ["ACT.OVERGROWTH"]
        assert r.acts_display == "Overgrowth"

    def test_acts_display_multi(self):
        r = self._make()
        r.acts = ["ACT.OVERGROWTH", "ACT.HIVE"]
        assert r.acts_display == "Overgrowth → Hive"

    def test_run_time_display_minutes_only(self):
        r = self._make()
        r.run_time_seconds = 150  # 2m 30s
        assert r.run_time_display == "2m 30s"

    def test_run_time_display_with_hours(self):
        r = self._make()
        r.run_time_seconds = 3661  # 1h 1m 1s
        assert r.run_time_display == "1h 1m 1s"

    def test_killed_by_display_empty(self):
        r = self._make()
        r.killed_by = ""
        assert r.killed_by_display == "—"

    def test_killed_by_display_encounter(self):
        r = self._make()
        r.killed_by = "ENCOUNTER.SLIMES_WEAK"
        assert r.killed_by_display == "Slimes Weak"

    def test_killed_by_display_event(self):
        r = self._make()
        r.killed_by = "EVENT.THE_FOUNTAIN"
        assert r.killed_by_display == "The Fountain"


# ── Internal helpers ──────────────────────────────────────────────────────────

class TestFindLocalPlayer:
    def test_falls_back_to_index_0(self):
        players = [{"id": "111"}, {"id": "222"}]
        assert _find_local_player(players, None) == players[0]

    def test_matches_by_steam_id(self):
        players = [{"id": "111"}, {"id": "222"}]
        assert _find_local_player(players, "222") == players[1]

    def test_falls_back_when_no_match(self):
        players = [{"id": "111"}]
        assert _find_local_player(players, "999") == players[0]

    def test_empty_players_list(self):
        assert _find_local_player([], None) == {}


class TestExtractCardPicks:
    def _history_with_choices(self, choices, player_id=None):
        ps = {"card_choices": choices}
        if player_id:
            ps["player_id"] = player_id
        return [[{"player_stats": [ps]}]]

    def test_extracts_picked_card(self):
        history = self._history_with_choices([
            {"card": {"id": "CARD.BASH"}, "was_picked": True},
        ])
        picks = _extract_card_picks(history, None)
        assert len(picks) == 1
        assert picks[0].card_id == "CARD.BASH"
        assert picks[0].was_picked is True

    def test_extracts_skipped_card(self):
        history = self._history_with_choices([
            {"card": {"id": "CARD.BASH"}, "was_picked": False},
        ])
        picks = _extract_card_picks(history, None)
        assert picks[0].was_picked is False

    def test_skips_empty_card_id(self):
        history = self._history_with_choices([
            {"card": {"id": ""}, "was_picked": True},
        ])
        picks = _extract_card_picks(history, None)
        assert picks == []

    def test_multiple_acts(self):
        act = [{"player_stats": [{"card_choices": [
            {"card": {"id": "CARD.BASH"}, "was_picked": True}
        ]}]}]
        history = [act, act]
        picks = _extract_card_picks(history, None)
        assert len(picks) == 2

    def test_filters_by_player_id(self):
        history = [[{"player_stats": [
            {"player_id": "1", "card_choices": [{"card": {"id": "CARD.BASH"}, "was_picked": True}]},
            {"player_id": "2", "card_choices": [{"card": {"id": "CARD.RAGE"}, "was_picked": True}]},
        ]}]]
        picks = _extract_card_picks(history, "1")
        assert len(picks) == 1
        assert picks[0].card_id == "CARD.BASH"

    def test_empty_history(self):
        assert _extract_card_picks([], None) == []


class TestGetFinalPlayerStats:
    def test_returns_last_entry(self):
        history = [[
            {"player_stats": [{"current_gold": 10}]},
            {"player_stats": [{"current_gold": 99}]},
        ]]
        ps = _get_final_player_stats(history, None)
        assert ps["current_gold"] == 99

    def test_empty_history(self):
        assert _get_final_player_stats([], None) == {}

    def test_filters_by_player_id(self):
        history = [[{"player_stats": [
            {"player_id": "1", "current_gold": 10},
            {"player_id": "2", "current_gold": 99},
        ]}]]
        ps = _get_final_player_stats(history, "1")
        assert ps["current_gold"] == 10


# ── parse_run_file ────────────────────────────────────────────────────────────

class TestParseRunFile:
    def test_returns_none_for_missing_file(self, tmp_path):
        assert parse_run_file(tmp_path / "nonexistent.run") is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        f = tmp_path / "bad.run"
        f.write_text("not json")
        assert parse_run_file(f) is None

    def test_parses_minimal_win(self, tmp_path):
        data = make_run_data(win=True, ascension=4)
        f = tmp_path / "1234.run"
        f.write_text(json.dumps(data))
        run = parse_run_file(f)
        assert run is not None
        assert run.win is True
        assert run.ascension == 4
        assert run.filename == "1234.run"

    def test_parses_loss(self, tmp_path):
        data = make_run_data(win=False, killed_by_encounter="ENCOUNTER.SLIMES_WEAK")
        f = tmp_path / "test.run"
        f.write_text(json.dumps(data))
        run = parse_run_file(f)
        assert run.win is False
        assert run.killed_by == "ENCOUNTER.SLIMES_WEAK"

    def test_killed_by_none_none_becomes_empty(self, tmp_path):
        data = make_run_data(win=True, killed_by_encounter="NONE.NONE")
        f = tmp_path / "test.run"
        f.write_text(json.dumps(data))
        run = parse_run_file(f)
        assert run.killed_by == ""

    def test_final_deck_extracted(self, tmp_path):
        data = make_run_data(deck=[{"id": "CARD.BASH"}, {"id": "CARD.RAGE"}])
        f = tmp_path / "test.run"
        f.write_text(json.dumps(data))
        run = parse_run_file(f)
        assert "CARD.BASH" in run.final_deck
        assert "CARD.RAGE" in run.final_deck

    def test_player_count_from_players_list(self, tmp_path):
        data = make_run_data(player_count=2)
        f = tmp_path / "test.run"
        f.write_text(json.dumps(data))
        run = parse_run_file(f)
        assert run.player_count == 2

    def test_floors_counted_from_map_history(self, tmp_path):
        history = [
            [{"player_stats": []}, {"player_stats": []}],  # act 1: 2 rooms
            [{"player_stats": []}],                         # act 2: 1 room
        ]
        data = make_run_data(map_point_history=history)
        f = tmp_path / "test.run"
        f.write_text(json.dumps(data))
        run = parse_run_file(f)
        assert run.floors_reached == 3

    def test_card_picks_extracted(self, tmp_path):
        history = [[{"player_stats": [{"card_choices": [
            {"card": {"id": "CARD.BASH"}, "was_picked": True},
            {"card": {"id": "CARD.RAGE"}, "was_picked": False},
        ]}]}]]
        data = make_run_data(map_point_history=history)
        f = tmp_path / "test.run"
        f.write_text(json.dumps(data))
        run = parse_run_file(f)
        assert len(run.card_picks) == 2
        picked = [p for p in run.card_picks if p.was_picked]
        assert len(picked) == 1
        assert picked[0].card_id == "CARD.BASH"

    def test_game_mode_preserved(self, tmp_path):
        data = make_run_data(game_mode="daily")
        f = tmp_path / "test.run"
        f.write_text(json.dumps(data))
        run = parse_run_file(f)
        assert run.game_mode == "daily"
        assert run.is_daily

    def test_empty_players_list_returns_none(self, tmp_path):
        data = make_run_data()
        data["players"] = []
        f = tmp_path / "test.run"
        f.write_text(json.dumps(data))
        # With empty players, _find_local_player returns {} — run still parsed
        run = parse_run_file(f)
        assert run is not None  # doesn't crash, just has defaults


# ── load_all_runs ─────────────────────────────────────────────────────────────

class TestLoadAllRuns:
    def test_empty_directory(self, tmp_path):
        assert load_all_runs(tmp_path) == []

    def test_loads_valid_run_files(self, tmp_path):
        for i, ts in enumerate([1_000, 2_000, 3_000]):
            data = make_run_data(start_time=ts)
            (tmp_path / f"{ts}.run").write_text(json.dumps(data))
        runs = load_all_runs(tmp_path)
        assert len(runs) == 3

    def test_sorted_newest_first(self, tmp_path):
        for ts in [1_000, 3_000, 2_000]:
            data = make_run_data(start_time=ts)
            (tmp_path / f"{ts}.run").write_text(json.dumps(data))
        runs = load_all_runs(tmp_path)
        assert runs[0].start_time == 3_000
        assert runs[-1].start_time == 1_000

    def test_skips_backup_files(self, tmp_path):
        data = make_run_data()
        (tmp_path / "real.run").write_text(json.dumps(data))
        (tmp_path / "real.run.backup").write_text(json.dumps(data))
        runs = load_all_runs(tmp_path)
        assert len(runs) == 1

    def test_skips_invalid_json(self, tmp_path):
        (tmp_path / "bad.run").write_text("not json")
        data = make_run_data()
        (tmp_path / "good.run").write_text(json.dumps(data))
        runs = load_all_runs(tmp_path)
        assert len(runs) == 1

    def test_real_history_loads(self, real_history_dir):
        runs = load_all_runs(real_history_dir)
        assert len(runs) > 0
        assert all(isinstance(r, RunSummary) for r in runs)
        assert runs == sorted(runs, key=lambda r: r.start_time, reverse=True)


# ── find_default_save_path ────────────────────────────────────────────────────

class TestFindDefaultSavePath:
    def test_returns_none_when_base_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        # No SlayTheSpire2/steam directory created
        assert find_default_save_path() is None

    def test_returns_none_when_history_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        base = tmp_path / "SlayTheSpire2" / "steam" / "12345"
        base.mkdir(parents=True)
        # steam/12345 exists but no profile1/saves/history
        assert find_default_save_path() is None

    def test_returns_history_path_when_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        history = tmp_path / "SlayTheSpire2" / "steam" / "12345" / "profile1" / "saves" / "history"
        history.mkdir(parents=True)
        result = find_default_save_path()
        assert result == history

    def test_skips_files_in_steam_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        steam = tmp_path / "SlayTheSpire2" / "steam"
        steam.mkdir(parents=True)
        (steam / "notadir.txt").write_text("x")  # file, not dir — should be skipped
        assert find_default_save_path() is None


class TestLoadAllRunsSteamId:
    def test_non_steam_path_still_loads(self, tmp_path):
        """load_all_runs doesn't require 'steam' in path — steam_id falls back to None."""
        data = make_run_data()
        (tmp_path / "run1.run").write_text(json.dumps(data))
        # tmp_path has no "steam" component — should still load without crashing
        runs = load_all_runs(tmp_path)
        assert len(runs) == 1
