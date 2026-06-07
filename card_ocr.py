"""Screen OCR for reading card reward options from the STS2 card pick screen."""
import ctypes
import ctypes.wintypes
import sys
from pathlib import Path
from typing import Optional
from difflib import get_close_matches

try:
    import pytesseract
    from PIL import Image
    import numpy as np
    import mss as _mss
    _DEPS_OK = True
except ImportError:
    _DEPS_OK = False

_TESS_PATHS = [
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
]


def _vendor_tesseract() -> Path | None:
    """Return path to vendored tesseract.exe if it exists (dev tree or PyInstaller bundle)."""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    candidate = base / "vendor" / "tesseract" / "tesseract.exe"
    return candidate if candidate.exists() else None

# Horizontal card columns and vertical search band as fractions of game dimensions.
# Defaults; overridden by ocr_config.json if it exists.
_DEFAULT_CARD_X = [(0.338, 0.404), (0.474, 0.540), (0.610, 0.676)]
_DEFAULT_SEARCH_Y = (0.35, 0.58)
NUM_CARDS = 3

_OCR_CONFIG = Path(__file__).parent / "ocr_config.json"


def _load_zones():
    if _OCR_CONFIG.exists():
        try:
            import json
            d = json.loads(_OCR_CONFIG.read_text())
            cx = d.get("card_x")
            sy = d.get("search_y")
            if cx and sy and len(cx) == 3:
                return [tuple(x) for x in cx], tuple(sy)
        except Exception:
            pass
    return _DEFAULT_CARD_X, _DEFAULT_SEARCH_Y


_CARD_X, _SEARCH_Y = _load_zones()


def save_zones(card_x: list[tuple], search_y: tuple) -> None:
    """Persist zone positions and update module globals immediately."""
    global _CARD_X, _SEARCH_Y
    import json
    _CARD_X = [tuple(x) for x in card_x]
    _SEARCH_Y = tuple(search_y)
    _OCR_CONFIG.write_text(json.dumps(
        {"card_x": list(_CARD_X), "search_y": list(_SEARCH_Y)}, indent=2
    ))

# The name banner is a gray metallic scroll.  We detect it by looking for rows
# where the average brightness in the column strip is in the banner's gray range.
_BANNER_LO, _BANNER_HI = 100, 190   # grayscale brightness bounds


def _find_game_hwnd():
    """Return the HWND of the STS2 game window, or None."""
    hwnd = ctypes.windll.user32.FindWindowW(None, "Slay the Spire 2")
    return hwnd if hwnd else None


def get_game_window_rect() -> tuple[int, int, int, int] | None:
    """Return (left, top, width, height) of the STS2 client area, or None."""
    try:
        hwnd = _find_game_hwnd()
        if not hwnd:
            return None
        cr = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(cr))
        pt = ctypes.wintypes.POINT(0, 0)
        ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
        w, h = cr.right - cr.left, cr.bottom - cr.top
        if w <= 0 or h <= 0:
            return None
        return (pt.x, pt.y, w, h)
    except Exception:
        return None


def _find_tesseract() -> Optional[str]:
    import shutil
    # Vendored copy takes priority (works both in dev tree and PyInstaller bundle)
    if vendored := _vendor_tesseract():
        return str(vendored)
    if found := shutil.which("tesseract"):
        return found
    for p in _TESS_PATHS:
        if Path(p).exists():
            return p
    return None


def is_available() -> bool:
    return _DEPS_OK and _find_tesseract() is not None


def _preprocess(crop: "Image.Image") -> "Image.Image":
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    arr = np.array(crop.convert("RGB"))
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    # White text (normal cards)
    white = (r > 180) & (g > 180) & (b > 180)
    # Green text (upgraded cards): green channel dominant and bright
    green = (g > 140) & (g > r.astype(int) + 40) & (g > b.astype(int) + 40)
    out = np.full(arr.shape[:2], 255, dtype=np.uint8)
    out[white | green] = 0
    return Image.fromarray(out)


def _clean(text: str) -> str:
    parts = text.strip().split()
    # Drop leading single-char artifact from the energy cost badge
    if parts and len(parts[0]) == 1:
        parts = parts[1:]
    return " ".join(parts)


def _find_banner_y(col_strip: "np.ndarray") -> tuple[int, int] | None:
    """Return (y_start, y_end) of the card name banner within a column strip."""
    h = col_strip.shape[0]
    gray = col_strip.mean(axis=(1, 2))
    in_banner = (gray >= _BANNER_LO) & (gray <= _BANNER_HI)

    min_len = max(8, int(h * 0.03))
    max_len = int(h * 0.18)

    best_start, best_len = 0, 0
    cur_start, cur_len = 0, 0
    for y in range(h):
        if in_banner[y]:
            if cur_len == 0:
                cur_start = y
            cur_len += 1
        else:
            if min_len <= cur_len <= max_len and cur_len > best_len:
                best_len, best_start = cur_len, cur_start
            cur_len = 0
    if min_len <= cur_len <= max_len and cur_len > best_len:
        best_len, best_start = cur_len, cur_start

    if best_len < min_len:
        return None
    return best_start, best_start + best_len


def read_card_reward_names() -> list[str]:
    """Screenshot + OCR the three card name areas. Returns [] on failure."""
    if not _DEPS_OK:
        return []
    tess = _find_tesseract()
    if not tess:
        return []
    pytesseract.pytesseract.tesseract_cmd = tess
    # Point tesseract at the vendored tessdata if using the bundled binary
    if vendored := _vendor_tesseract():
        import os
        os.environ.setdefault("TESSDATA_PREFIX", str(vendored.parent / "tessdata"))

    game_rect = get_game_window_rect()
    with _mss.mss() as sct:
        if game_rect:
            gx, gy, gw, gh = game_rect
            monitor = {"left": gx, "top": gy, "width": gw, "height": gh}
        else:
            m = sct.monitors[1]
            gx, gy, gw, gh = m["left"], m["top"], m["width"], m["height"]
            monitor = m
        raw_frame = sct.grab(monitor)
        shot = Image.frombytes("RGB", raw_frame.size, raw_frame.bgra, "raw", "BGRX")
        sw, sh = gw, gh

    sy1, sy2 = int(sh * _SEARCH_Y[0]), int(sh * _SEARCH_Y[1])
    # If the zone is narrow enough to BE the banner (user-calibrated), skip detection.
    narrow_zone = (sy2 - sy1) < int(sh * 0.12)

    results = []
    for xf1, xf2 in _CARD_X:
        x1, x2 = int(sw * xf1), int(sw * xf2)
        search_strip = np.array(shot.crop((x1, sy1, x2, sy2)))

        if narrow_zone:
            by1, by2 = 0, search_strip.shape[0]
        else:
            banner = _find_banner_y(search_strip)
            if banner is None:
                results.append("")
                continue
            by1, by2 = banner

        crop = Image.fromarray(search_strip[by1:by2])
        processed = _preprocess(crop)
        raw = pytesseract.image_to_string(
            processed,
            config=(
                "--psm 8 --oem 3 "
                "-c tessedit_char_whitelist="
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz "
            ),
        )
        results.append(_clean(raw))
    return results


def match_to_card_ids(raw_names: list[str], all_card_ids: list[str]) -> list[Optional[str]]:
    """Fuzzy-match OCR output strings to card IDs from the database."""
    from parser import fmt_card
    name_to_id = {fmt_card(cid).lower(): cid for cid in all_card_ids}
    display_names = list(name_to_id.keys())

    matched = []
    for raw in raw_names:
        if not raw:
            matched.append(None)
            continue
        hits = get_close_matches(raw.lower(), display_names, n=1, cutoff=0.55)
        matched.append(name_to_id[hits[0]] if hits else None)
    return matched
