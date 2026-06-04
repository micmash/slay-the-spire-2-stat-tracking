"""
Card image downloader + cache.
Images are fetched from the STS2 wiki and stored in ./card_img_cache/.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path
from functools import lru_cache


def _data_dir() -> Path:
    """Directory for bundled read-only assets (card_images.json)."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundles --add-data files into sys._MEIPASS
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent


def _cache_dir() -> Path:
    """Directory for user-writable cached images — always next to the exe or script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "card_img_cache"
    return Path(__file__).parent / "card_img_cache"


CACHE_DIR = _cache_dir()
MAP_FILE  = _data_dir() / "card_images.json"
CHARACTERS = ["Ironclad", "Silent", "Defect", "Necrobinder", "Regent", "Colorless", "Curse"]


def _load_wiki_map() -> dict[str, str]:
    if MAP_FILE.exists():
        return json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return {}


# Load once at import time
_WIKI_MAP: dict[str, str] = _load_wiki_map()

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Build a lookup: norm_card_name -> {norm_char -> wiki_stem}
# e.g. "allforone" -> {"defect": "StS2_Defect-AllforOne", ...}
_BY_NAME: dict[str, dict[str, str]] = {}
for _stem in _WIKI_MAP:
    # stem like "StS2_Ironclad-BloodWall"
    _m = re.match(r"StS2_([A-Za-z]+)-(.+)", _stem)
    if _m:
        _char_n = _norm(_m.group(1))   # "ironclad"
        _card_n = _norm(_m.group(2))   # "bloodwall"
        _BY_NAME.setdefault(_card_n, {})[_char_n] = _stem


def _card_to_wiki_stem(card_id: str, char_hint: str | None = None) -> str | None:
    """
    Map 'CARD.BLOOD_WALL' → 'StS2_Ironclad-BloodWall' by normalised matching.
    char_hint: display name of the character ('Ironclad', 'Defect', etc.)
    """
    key = card_id.removeprefix("CARD.")
    # Remove character suffixes
    for suffix in ("_IRONCLAD", "_SILENT", "_DEFECT", "_NECROBINDER", "_REGENT"):
        key = key.removesuffix(suffix)

    # Normalise the card name
    norm_name = _norm(key)   # e.g. "allforone", "bloodwall"

    char_map = _BY_NAME.get(norm_name)
    if not char_map:
        return None

    # Prefer char_hint if provided
    if char_hint:
        norm_char = _norm(char_hint)
        if norm_char in char_map:
            return char_map[norm_char]

    # Fall back: prefer non-Colorless, deterministic order
    for char in ("ironclad", "silent", "defect", "necrobinder", "regent", "colorless", "curse"):
        if char in char_map:
            return char_map[char]

    return next(iter(char_map.values()))


@lru_cache(maxsize=512)
def get_image_path(card_id: str, char_hint: str | None = None) -> Path | None:
    """
    Return a local Path to the cached card image, downloading if needed.
    Returns None if image not available.
    """
    CACHE_DIR.mkdir(exist_ok=True)

    stem = _card_to_wiki_stem(card_id, char_hint)
    if not stem:
        return None

    url = _WIKI_MAP.get(stem)
    if not url:
        return None

    # Use stem as filename (safe for filesystem)
    filename = stem + ".png"
    local = CACHE_DIR / filename
    if local.exists():
        return local

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "STS2Tracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            local.write_bytes(resp.read())
        return local
    except Exception:
        return None
