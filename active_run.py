"""Parser for current_run.save — live run state while the game is running."""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from parser import fmt_card, fmt_relic, fmt_character, fmt_act, find_default_save_path


@dataclass
class ActiveCard:
    card_id: str
    floor_added: int
    upgrade_level: int = 0
    enchantment: str | None = None

    @property
    def display_name(self) -> str:
        name = fmt_card(self.card_id)
        suffix = "+" * self.upgrade_level if self.upgrade_level else ""
        if self.enchantment:
            enc = self.enchantment.replace("ENCHANTMENT.", "").replace("_", " ").title()
            suffix += f" [{enc}]"
        return name + suffix

    @property
    def is_upgraded(self) -> bool:
        return self.upgrade_level > 0


@dataclass
class ActiveRelic:
    relic_id: str
    floor_added: int

    @property
    def display_name(self) -> str:
        return fmt_relic(self.relic_id)


@dataclass
class ActivePotion:
    potion_id: str
    slot_index: int

    @property
    def display_name(self) -> str:
        name = self.potion_id.replace("POTION.", "").replace("_", " ").title()
        return name


@dataclass
class ActiveRunState:
    character: str
    ascension: int
    game_mode: str
    current_act: str
    act_index: int          # 0-based
    floors_completed: int
    current_hp: int
    max_hp: int
    gold: int
    deck: list[ActiveCard]
    relics: list[ActiveRelic]
    potions: list[ActivePotion]
    player_count: int
    save_time: int
    is_reward_pending: bool = False
    reward_encounter_id: str | None = None

    @property
    def character_display(self) -> str:
        return fmt_character(self.character)

    @property
    def act_display(self) -> str:
        return fmt_act(self.current_act)

    @property
    def hp_pct(self) -> float:
        return self.current_hp / self.max_hp if self.max_hp else 0

    @property
    def is_daily(self) -> bool:
        return self.game_mode == "daily"

    @property
    def is_multiplayer(self) -> bool:
        return self.player_count > 1


def parse_active_run(path: Path | str, steam_id: str | None = None) -> Optional[ActiveRunState]:
    """Parse current_run.save. Returns None if file is missing or malformed."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None

    players = data.get("players", [])
    if not players:
        return None

    # Identify local player: match by net_id=1 (host) or fall back to index 0
    player = players[0]
    if len(players) > 1:
        for p in players:
            if p.get("net_id") == 1:
                player = p
                break

    # Deck
    deck = []
    for c in player.get("deck", []):
        cid = c.get("id", "")
        if not cid:
            continue
        enc_raw = c.get("enchantment", {})
        enc = enc_raw.get("id") if isinstance(enc_raw, dict) else None
        deck.append(ActiveCard(
            card_id=cid,
            floor_added=c.get("floor_added_to_deck", 0),
            upgrade_level=c.get("current_upgrade_level", 0),
            enchantment=enc,
        ))

    # Relics
    relics = [
        ActiveRelic(relic_id=r.get("id", ""), floor_added=r.get("floor_added_to_deck", 0))
        for r in player.get("relics", []) if r.get("id")
    ]

    # Potions
    potions = [
        ActivePotion(potion_id=p.get("id", ""), slot_index=p.get("slot_index", 0))
        for p in player.get("potions", []) if p.get("id")
    ]

    # Act / floor
    acts = data.get("acts", [])
    act_idx = data.get("current_act_index", 0)
    current_act = acts[act_idx]["id"] if acts and act_idx < len(acts) else "ACT.UNKNOWN"

    # Floor calculation:
    # map_point_history only adds a room when it's COMPLETED, so it lags by 1
    # while you're mid-room.  visited_map_coords tracks nodes ENTERED in the
    # current act (resets each act), so it correctly reflects the room you're
    # currently in.  Use it for the current act; sum map_point_history for
    # previous acts (which are fully completed).
    map_history = data.get("map_point_history", [])
    previous_acts_floors = sum(len(map_history[i]) for i in range(min(act_idx, len(map_history))))
    # visited_map_coords includes the act-start ancient node (row 0) which isn't
    # a numbered floor, so subtract 1.
    visited = data.get("visited_map_coords", [])
    current_act_floors = max(0, len(visited) - 1) if visited else (
        len(map_history[act_idx]) if act_idx < len(map_history) else 0
    )
    floors = previous_acts_floors + current_act_floors

    pre_finished = data.get("pre_finished_room") or {}
    is_reward_pending = bool(pre_finished.get("is_pre_finished", False))
    reward_encounter_id = pre_finished.get("encounter_id") if is_reward_pending else None

    return ActiveRunState(
        character=player.get("character_id", "UNKNOWN"),
        ascension=data.get("ascension", 0),
        game_mode=data.get("game_mode", "standard"),
        current_act=current_act,
        act_index=act_idx,
        floors_completed=floors,
        current_hp=player.get("current_hp", 0),
        max_hp=player.get("max_hp", 0),
        gold=player.get("gold", 0),
        deck=deck,
        relics=relics,
        potions=potions,
        player_count=len(players),
        save_time=data.get("save_time", 0),
        is_reward_pending=is_reward_pending,
        reward_encounter_id=reward_encounter_id,
    )


def find_active_run_path() -> Optional[Path]:
    """Return the path to current_run.save, or None if not found."""
    history = find_default_save_path()
    if history is None:
        return None
    save = history.parent / "current_run.save"
    return save if save.exists() else None
