import json
import os
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


def strip_prefix(s: str, prefix: str) -> str:
    if s.startswith(prefix):
        return s[len(prefix):]
    return s


def fmt_card(card_id: str) -> str:
    return strip_prefix(card_id, "CARD.").replace("_", " ").title()


def fmt_relic(relic_id: str) -> str:
    return strip_prefix(relic_id, "RELIC.").replace("_", " ").title()


def fmt_character(char_id: str) -> str:
    return strip_prefix(char_id, "CHARACTER.").replace("_", " ").title()


def fmt_act(act_id: str) -> str:
    return strip_prefix(act_id, "ACT.").replace("_", " ").title()


@dataclass
class CardPick:
    card_id: str
    was_picked: bool
    floor: int


@dataclass
class RelicPick:
    relic_id: str
    was_picked: bool
    floor: int


@dataclass
class RunSummary:
    filename: str
    start_time: int
    character: str
    win: bool
    ascension: int
    acts: list[str]
    run_time_seconds: int
    was_abandoned: bool
    final_deck: list[str]
    final_relics: list[str]
    card_picks: list[CardPick]
    relic_picks: list[RelicPick]
    floors_reached: int
    final_gold: int
    final_hp: int
    final_max_hp: int
    killed_by: str
    game_mode: str
    player_count: int = 1
    notes: str = ""

    @property
    def is_multiplayer(self) -> bool:
        return self.player_count > 1

    @property
    def is_daily(self) -> bool:
        return self.game_mode == "daily"

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.start_time)

    @property
    def character_display(self) -> str:
        return fmt_character(self.character)

    @property
    def acts_display(self) -> str:
        return " → ".join(fmt_act(a) for a in self.acts)

    @property
    def run_time_display(self) -> str:
        m, s = divmod(self.run_time_seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m {s}s"
        return f"{m}m {s}s"

    @property
    def killed_by_display(self) -> str:
        if not self.killed_by:
            return "—"
        return (self.killed_by
                .replace("ENCOUNTER.", "")
                .replace("EVENT.", "")
                .replace("_", " ")
                .title())


def _find_local_player(players: list[dict], steam_id: str | None) -> dict:
    """Return the local player's data. Matches by Steam ID, falls back to index 0."""
    if steam_id:
        for p in players:
            if str(p.get("id", "")) == steam_id:
                return p
    return players[0] if players else {}


def _extract_card_picks(map_point_history: list, local_player_id: str | None) -> list[CardPick]:
    """Extract card pick events. In multiplayer, only include the local player's choices."""
    picks = []
    for act in map_point_history:
        for point in act:
            for ps in point.get("player_stats", []):
                # Filter to local player in MP; in SP there's only one player_stats entry
                if local_player_id and str(ps.get("player_id", "")) != local_player_id:
                    continue
                floor = ps.get("floor", 0)
                for choice in ps.get("card_choices", []):
                    if isinstance(choice, dict):
                        card = choice.get("card", {})
                        card_id = card.get("id", "") if isinstance(card, dict) else ""
                        was_picked = choice.get("was_picked", False)
                        if card_id:
                            picks.append(CardPick(card_id=card_id, was_picked=was_picked, floor=floor))
    return picks


def _extract_relic_picks(map_point_history: list, local_player_id: str | None) -> list[RelicPick]:
    """Extract relic pick events for the local player only."""
    picks = []
    for act in map_point_history:
        for point in act:
            for ps in point.get("player_stats", []):
                if local_player_id and str(ps.get("player_id", "")) != local_player_id:
                    continue
                floor = ps.get("floor", 0)
                for choice in ps.get("relic_choices", []):
                    for relic in choice:
                        relic_id = relic.get("TextKey", "") if isinstance(relic, dict) else relic
                        was_chosen = relic.get("was_chosen", False) if isinstance(relic, dict) else False
                        picks.append(RelicPick(relic_id=relic_id, was_picked=was_chosen, floor=floor))
                for choice in ps.get("ancient_choice", []):
                    relic_id = choice.get("TextKey", "")
                    was_chosen = choice.get("was_chosen", False)
                    picks.append(RelicPick(relic_id=relic_id, was_picked=was_chosen, floor=floor))
    return picks


def _get_final_player_stats(map_point_history: list, local_player_id: str | None) -> dict:
    """Return the last player_stats entry for the local player."""
    last_ps = {}
    for act in map_point_history:
        for point in act:
            for ps in point.get("player_stats", []):
                if local_player_id and str(ps.get("player_id", "")) != local_player_id:
                    continue
                last_ps = ps
    return last_ps


def parse_run_file(path: str | Path, steam_id: str | None = None) -> Optional[RunSummary]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    players = data.get("players", [{}])
    player = _find_local_player(players, steam_id)
    local_player_id = str(player.get("id", "")) if player.get("id") else None

    map_history = data.get("map_point_history", [])
    final_ps = _get_final_player_stats(map_history, local_player_id)

    final_deck = [c.get("id", "") for c in player.get("deck", [])]
    final_relics = [r.get("id", "") for r in player.get("relics", [])]

    floors = sum(len(act) for act in map_history)
    killed_by = data.get("killed_by_encounter", "") or data.get("killed_by_event", "") or ""
    if killed_by == "NONE.NONE":
        killed_by = ""

    return RunSummary(
        filename=str(Path(path).name),
        start_time=data.get("start_time", 0),
        character=player.get("character", "UNKNOWN"),
        win=data.get("win", False),
        ascension=data.get("ascension", 0),
        acts=data.get("acts", []),
        run_time_seconds=data.get("run_time", 0),
        was_abandoned=data.get("was_abandoned", False),
        final_deck=final_deck,
        final_relics=final_relics,
        card_picks=_extract_card_picks(map_history, local_player_id),
        relic_picks=_extract_relic_picks(map_history, local_player_id),
        floors_reached=floors,
        final_gold=final_ps.get("current_gold", 0),
        final_hp=final_ps.get("current_hp", 0),
        final_max_hp=final_ps.get("max_hp", 0),
        killed_by=killed_by,
        game_mode=data.get("game_mode", "standard"),
        player_count=len(players),
    )


def load_all_runs(history_dir: str | Path) -> list[RunSummary]:
    """Load all runs from the history directory.

    The Steam ID is extracted from the directory path
    (structure: .../steam/{steam_id}/profile1/saves/history)
    so multiplayer runs correctly show the local player's data.
    """
    history_dir = Path(history_dir)

    # Extract Steam ID from directory structure
    try:
        steam_id = history_dir.parts[
            list(history_dir.parts).index("steam") + 1
        ]
    except (ValueError, IndexError):
        steam_id = None

    runs = []
    for f in history_dir.glob("*.run"):
        if f.name.endswith(".backup"):
            continue
        run = parse_run_file(f, steam_id)
        if run:
            runs.append(run)
    runs.sort(key=lambda r: r.start_time, reverse=True)
    return runs


def find_default_save_path() -> Optional[Path]:
    appdata = Path(os.environ.get("APPDATA", ""))
    base = appdata / "SlayTheSpire2" / "steam"
    if not base.exists():
        return None
    for user_dir in base.iterdir():
        if user_dir.is_dir():
            history = user_dir / "profile1" / "saves" / "history"
            if history.exists():
                return history
    return None
