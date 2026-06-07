"""Shared fixtures and helpers for all test modules."""
import json
import pytest
from pathlib import Path
from parser import RunSummary, CardPick, RelicPick

FIXTURES = Path(__file__).parent / "fixtures"
REAL_HISTORY = Path(r"C:\Users\Logan\AppData\Roaming\SlayTheSpire2\steam\76561198040014482\profile1\saves\history")


# ── Minimal run JSON builders ─────────────────────────────────────────────────

def make_run_data(
    *,
    win=True,
    ascension=0,
    game_mode="standard",
    character="CHARACTER.IRONCLAD",
    start_time=1_700_000_000,
    run_time=300,
    was_abandoned=False,
    killed_by_encounter=None,
    acts=None,
    deck=None,
    relics=None,
    map_point_history=None,
    player_count=1,
) -> dict:
    """Return a minimal but valid .run JSON dict."""
    players = [
        {
            "character": character,
            "current_hp": 50,
            "max_hp": 80,
            "gold": 100,
            "deck": deck or [{"id": "CARD.STRIKE_IRONCLAD"}, {"id": "CARD.DEFEND_IRONCLAD"}],
            "relics": relics or [{"id": "RELIC.BURNING_BLOOD"}],
        }
        for _ in range(player_count)
    ]
    return {
        "acts": acts or ["ACT.OVERGROWTH"],
        "ascension": ascension,
        "game_mode": game_mode,
        "win": win,
        "was_abandoned": was_abandoned,
        "start_time": start_time,
        "run_time": run_time,
        "killed_by_encounter": killed_by_encounter,
        "killed_by_event": None,
        "players": players,
        "map_point_history": map_point_history or [],
    }


def make_card_pick(card_id: str, was_picked: bool, floor: int = 1) -> CardPick:
    return CardPick(card_id=card_id, was_picked=was_picked, floor=floor)


def make_run_summary(
    *,
    filename="test.run",
    start_time=1_700_000_000,
    character="CHARACTER.IRONCLAD",
    win=True,
    ascension=0,
    game_mode="standard",
    card_picks=None,
    final_deck=None,
    floors_reached=5,
    player_count=1,
) -> RunSummary:
    return RunSummary(
        filename=filename,
        start_time=start_time,
        character=character,
        win=win,
        ascension=ascension,
        acts=["ACT.OVERGROWTH"],
        run_time_seconds=300,
        was_abandoned=False,
        final_deck=final_deck or ["CARD.STRIKE_IRONCLAD"],
        final_relics=["RELIC.BURNING_BLOOD"],
        card_picks=card_picks or [],
        relic_picks=[],
        floors_reached=floors_reached,
        final_gold=100,
        final_hp=50,
        final_max_hp=80,
        killed_by="",
        game_mode=game_mode,
        player_count=player_count,
    )


@pytest.fixture
def real_history_dir():
    """The actual save history directory — skipped if not on the dev machine."""
    if not REAL_HISTORY.exists():
        pytest.skip("Real history directory not available")
    return REAL_HISTORY
