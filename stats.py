"""Pure run/card statistics — no Qt dependencies, easy to test in isolation."""
from collections import defaultdict

from parser import RunSummary


def filter_runs(
    runs: list[RunSummary],
    char_f: str,
    include_sp: bool = True,
    include_mp: bool = True,
    include_daily: bool = True,
) -> list[RunSummary]:
    """Apply character and mode filters to a run list.

    Each mode flag independently controls whether that run type is included.
    """
    out = runs
    if char_f != "All Characters":
        out = [r for r in out if r.character_display == char_f]
    out = [
        r for r in out
        if (include_sp and not r.is_multiplayer and not r.is_daily)
        or (include_mp and r.is_multiplayer and not r.is_daily)
        or (include_daily and r.is_daily)
    ]
    return out


def compute_card_stats(runs: list[RunSummary]) -> dict[str, dict]:
    """
    For each card seen as a pick choice, compute pick/win statistics.

    Returned per-card fields:
      times_picked, times_skipped, total_pick_events, avg_copies_per_run,
      multi_pick_runs, pick_rate,
      with_runs, with_wins, with_wr, with_avg_floor,
      without_runs, without_wins, without_wr, without_avg_floor,
      win_delta

    Win delta only considers runs where the card was actually offered as a pick
    choice, so cards gained via starters/events/boss rewards don't skew it.
    """
    offered_runs: dict[str, set] = defaultdict(set)   # card_id -> run filenames where offered
    picked_runs: dict[str, set] = defaultdict(set)    # card_id -> run filenames where picked >=1x
    pick_events: dict[str, int] = defaultdict(int)    # card_id -> total pick events (counts dupes)

    for run in runs:
        for cp in run.card_picks:
            if not cp.card_id:
                continue
            offered_runs[cp.card_id].add(run.filename)
            if cp.was_picked:
                picked_runs[cp.card_id].add(run.filename)
                pick_events[cp.card_id] += 1

    run_by_file = {r.filename: r for r in runs}
    stats: dict[str, dict] = {}

    for card_id, offered in offered_runs.items():
        picked = picked_runs.get(card_id, set())
        p = len(picked)                            # unique runs picked at least once
        s = len(offered) - p                       # unique runs offered but never picked
        total_picks = pick_events.get(card_id, 0)  # raw pick events (counts dupes)

        # General win rate: every run where the card ended in the final deck
        with_runs = [r for r in runs if card_id in r.final_deck]
        # Offered but skipped: appeared as a pick choice, never ended in deck
        without_runs = [run_by_file[fn] for fn in offered if card_id not in run_by_file[fn].final_deck]

        wn, wo = len(with_runs), len(without_runs)
        with_wins = sum(1 for r in with_runs if r.win)
        without_wins = sum(1 for r in without_runs if r.win)

        # Win delta: like-for-like on offered runs only.
        offered_and_took = [run_by_file[fn] for fn in offered if card_id in run_by_file[fn].final_deck]
        ot_n = len(offered_and_took)
        ot_wr = sum(1 for r in offered_and_took if r.win) / ot_n if ot_n else None
        os_wr = without_wins / wo if wo else None
        delta = (ot_wr - os_wr) if (ot_wr is not None and os_wr is not None) else None

        total_offered = p + s
        stats[card_id] = dict(
            times_picked=p,
            times_skipped=s,
            total_pick_events=total_picks,
            avg_copies_per_run=(total_picks / p if p else None),
            multi_pick_runs=total_picks - p,
            pick_rate=(p / total_offered if total_offered else 0),
            with_runs=wn,
            with_wins=with_wins,
            with_wr=(with_wins / wn if wn else None),
            with_avg_floor=(sum(r.floors_reached for r in with_runs) / wn if wn else None),
            without_runs=wo,
            without_wins=without_wins,
            without_wr=(without_wins / wo if wo else None),
            without_avg_floor=(sum(r.floors_reached for r in without_runs) / wo if wo else None),
            win_delta=delta,
        )
    return stats
