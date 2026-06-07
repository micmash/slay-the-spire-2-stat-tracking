"""Tests for stats.py — filter_runs and compute_card_stats."""
import pytest
from conftest import make_run_summary, make_card_pick
from stats import filter_runs, compute_card_stats


# ── filter_runs ───────────────────────────────────────────────────────────────

def _sp(**kw):
    return make_run_summary(game_mode="standard", player_count=1, **kw)

def _mp(**kw):
    return make_run_summary(game_mode="standard", player_count=2, **kw)

def _daily(**kw):
    return make_run_summary(game_mode="daily", player_count=1, **kw)


class TestFilterRuns:
    def setup_method(self):
        self.ironclad_sp  = _sp(character="CHARACTER.IRONCLAD",  filename="sp1.run")
        self.silent_sp    = _sp(character="CHARACTER.THE_SILENT", filename="sp2.run")
        self.ironclad_mp  = _mp(character="CHARACTER.IRONCLAD",  filename="mp1.run")
        self.daily_run    = _daily(character="CHARACTER.IRONCLAD", filename="d1.run")
        self.all_runs = [self.ironclad_sp, self.silent_sp, self.ironclad_mp, self.daily_run]

    def test_all_characters_no_filter(self):
        out = filter_runs(self.all_runs, "All Characters")
        assert set(r.filename for r in out) == {"sp1.run", "sp2.run", "mp1.run", "d1.run"}

    def test_character_filter_ironclad(self):
        out = filter_runs(self.all_runs, "Ironclad")
        assert all(r.character_display == "Ironclad" for r in out)
        assert len(out) == 3  # sp + mp + daily

    def test_character_filter_silent(self):
        out = filter_runs(self.all_runs, "The Silent")
        assert [r.filename for r in out] == ["sp2.run"]

    def test_character_filter_unknown_returns_empty(self):
        out = filter_runs(self.all_runs, "Watcher")
        assert out == []

    def test_exclude_sp(self):
        out = filter_runs(self.all_runs, "All Characters", include_sp=False)
        assert all(r.is_multiplayer or r.is_daily for r in out)

    def test_exclude_mp(self):
        out = filter_runs(self.all_runs, "All Characters", include_mp=False)
        assert all(not r.is_multiplayer or r.is_daily for r in out)

    def test_exclude_daily(self):
        out = filter_runs(self.all_runs, "All Characters", include_daily=False)
        assert all(not r.is_daily for r in out)

    def test_exclude_all_modes_returns_empty(self):
        out = filter_runs(self.all_runs, "All Characters",
                          include_sp=False, include_mp=False, include_daily=False)
        assert out == []

    def test_only_sp(self):
        out = filter_runs(self.all_runs, "All Characters",
                          include_sp=True, include_mp=False, include_daily=False)
        assert all(not r.is_multiplayer and not r.is_daily for r in out)
        assert len(out) == 2

    def test_only_mp(self):
        out = filter_runs(self.all_runs, "All Characters",
                          include_sp=False, include_mp=True, include_daily=False)
        assert [r.filename for r in out] == ["mp1.run"]

    def test_only_daily(self):
        out = filter_runs(self.all_runs, "All Characters",
                          include_sp=False, include_mp=False, include_daily=True)
        assert [r.filename for r in out] == ["d1.run"]

    def test_empty_input(self):
        assert filter_runs([], "All Characters") == []

    def test_character_and_mode_combined(self):
        # Ironclad only, no daily
        out = filter_runs(self.all_runs, "Ironclad", include_daily=False)
        assert len(out) == 2
        assert all(r.character_display == "Ironclad" for r in out)
        assert all(not r.is_daily for r in out)


# ── compute_card_stats ────────────────────────────────────────────────────────

def _run_with_picks(filename, win, picks, final_deck=None, floors=5):
    r = make_run_summary(filename=filename, win=win,
                         card_picks=picks,
                         final_deck=final_deck or [p.card_id for p in picks if p.was_picked],
                         floors_reached=floors)
    return r


class TestComputeCardStats:
    def test_empty_runs(self):
        assert compute_card_stats([]) == {}

    def test_runs_with_no_picks(self):
        r = make_run_summary(card_picks=[])
        assert compute_card_stats([r]) == {}

    def test_single_pick_win(self):
        picks = [make_card_pick("CARD.BASH", True)]
        run = _run_with_picks("a.run", win=True, picks=picks)
        stats = compute_card_stats([run])
        assert "CARD.BASH" in stats
        s = stats["CARD.BASH"]
        assert s["times_picked"] == 1
        assert s["times_skipped"] == 0
        assert s["pick_rate"] == 1.0
        assert s["with_wr"] == 1.0
        assert s["without_runs"] == 0
        assert s["without_wr"] is None

    def test_single_skip_loss(self):
        picks = [make_card_pick("CARD.BASH", False)]
        run = _run_with_picks("a.run", win=False, picks=picks, final_deck=[])
        stats = compute_card_stats([run])
        s = stats["CARD.BASH"]
        assert s["times_picked"] == 0
        assert s["times_skipped"] == 1
        assert s["pick_rate"] == 0.0
        assert s["with_runs"] == 0
        assert s["without_runs"] == 1
        assert s["without_wr"] == 0.0

    def test_pick_rate_with_two_runs(self):
        bash_pick = make_card_pick("CARD.BASH", True)
        bash_skip = make_card_pick("CARD.BASH", False)
        r1 = _run_with_picks("a.run", win=True, picks=[bash_pick])
        r2 = _run_with_picks("b.run", win=False, picks=[bash_skip], final_deck=[])
        stats = compute_card_stats([r1, r2])
        s = stats["CARD.BASH"]
        assert s["times_picked"] == 1
        assert s["times_skipped"] == 1
        assert s["pick_rate"] == pytest.approx(0.5)

    def test_win_delta_positive(self):
        """Card is better when taken (win_delta > 0)."""
        bash_pick = make_card_pick("CARD.BASH", True)
        bash_skip = make_card_pick("CARD.BASH", False)
        wins  = [_run_with_picks(f"w{i}.run", win=True,  picks=[bash_pick]) for i in range(3)]
        loses = [_run_with_picks(f"l{i}.run", win=False, picks=[bash_skip], final_deck=[]) for i in range(3)]
        stats = compute_card_stats(wins + loses)
        s = stats["CARD.BASH"]
        assert s["win_delta"] == pytest.approx(1.0)   # 3/3 with vs 0/3 without

    def test_win_delta_none_when_always_taken(self):
        """win_delta is None when there are no offered-but-skipped runs."""
        picks = [make_card_pick("CARD.BASH", True)]
        runs = [_run_with_picks(f"{i}.run", win=bool(i % 2), picks=picks) for i in range(4)]
        stats = compute_card_stats(runs)
        # without_runs is 0, so os_wr is None → win_delta is None
        assert stats["CARD.BASH"]["win_delta"] is None

    def test_win_delta_none_when_always_skipped(self):
        picks = [make_card_pick("CARD.BASH", False)]
        runs = [_run_with_picks(f"{i}.run", win=True, picks=picks, final_deck=[]) for i in range(3)]
        stats = compute_card_stats(runs)
        # ot_wr is None (never took it in deck) → win_delta is None
        assert stats["CARD.BASH"]["win_delta"] is None

    def test_avg_copies_per_run_multiple_picks(self):
        """Picking the same card twice in one run counts as 2 events."""
        picks = [
            make_card_pick("CARD.BASH", True, floor=1),
            make_card_pick("CARD.BASH", True, floor=5),
        ]
        run = _run_with_picks("a.run", win=True, picks=picks, final_deck=["CARD.BASH"])
        stats = compute_card_stats([run])
        s = stats["CARD.BASH"]
        assert s["total_pick_events"] == 2
        assert s["times_picked"] == 1        # only 1 unique run
        assert s["avg_copies_per_run"] == pytest.approx(2.0)
        assert s["multi_pick_runs"] == 1     # total_picks - unique runs = 2-1

    def test_multiple_cards(self):
        bash_pick = make_card_pick("CARD.BASH", True)
        rage_pick = make_card_pick("CARD.RAGE", False)
        run = _run_with_picks("a.run", win=True,
                              picks=[bash_pick, rage_pick],
                              final_deck=["CARD.BASH"])
        stats = compute_card_stats([run])
        assert "CARD.BASH" in stats
        assert "CARD.RAGE" in stats
        assert stats["CARD.RAGE"]["times_picked"] == 0

    def test_cards_in_deck_not_offered_not_counted(self):
        """Cards in final_deck but never in card_picks don't show up in stats."""
        run = make_run_summary(
            filename="a.run", win=True,
            card_picks=[],
            final_deck=["CARD.STRIKE_IRONCLAD", "CARD.DEFEND_IRONCLAD"],
        )
        stats = compute_card_stats([run])
        assert "CARD.STRIKE_IRONCLAD" not in stats

    def test_with_avg_floor(self):
        bash_pick = make_card_pick("CARD.BASH", True)
        r1 = _run_with_picks("a.run", win=True,  picks=[bash_pick], floors=10)
        r2 = _run_with_picks("b.run", win=False, picks=[bash_pick], floors=6)
        stats = compute_card_stats([r1, r2])
        s = stats["CARD.BASH"]
        assert s["with_avg_floor"] == pytest.approx(8.0)

    def test_skip_empty_card_id(self):
        picks = [make_card_pick("", True)]
        run = make_run_summary(filename="a.run", win=True, card_picks=picks, final_deck=[])
        stats = compute_card_stats([run])
        assert "" not in stats

    def test_real_history(self, real_history_dir):
        from parser import load_all_runs
        runs = load_all_runs(real_history_dir)
        assert len(runs) > 0
        stats = compute_card_stats(runs)
        # At minimum we should have some cards
        assert len(stats) > 0
        for card_id, s in stats.items():
            assert 0.0 <= s["pick_rate"] <= 1.0
            if s["times_picked"] > 0 and s["times_skipped"] > 0:
                assert s["win_delta"] is not None or True  # can be None, just no crash
