"""Tests for card_ocr.py — pure-logic functions only (no screen capture or Tesseract)."""
import sys
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
import card_ocr
from card_ocr import _clean, match_to_card_ids, _find_banner_y, save_zones, _load_zones


# ── _clean ────────────────────────────────────────────────────────────────────

class TestClean:
    def test_strips_whitespace(self):
        assert _clean("  Bash  ") == "Bash"

    def test_drops_single_char_prefix(self):
        # Energy-cost badge artifact: leading single char like '1' or 'E'
        assert _clean("1 Bash") == "Bash"

    def test_keeps_multi_char_first_word(self):
        assert _clean("Bash") == "Bash"

    def test_multiword(self):
        assert _clean("2 Feel No Pain") == "Feel No Pain"

    def test_empty_string(self):
        assert _clean("") == ""

    def test_whitespace_only(self):
        assert _clean("   ") == ""

    def test_single_char_only_returns_empty(self):
        assert _clean("X") == ""

    def test_no_artifact(self):
        assert _clean("Whirlwind") == "Whirlwind"

    def test_newline_stripped(self):
        assert _clean("Bash\n") == "Bash"

    def test_tab_treated_as_whitespace(self):
        assert _clean("1\tBash") == "Bash"


# ── match_to_card_ids ─────────────────────────────────────────────────────────

CARD_DB = [
    "CARD.BASH",
    "CARD.STRIKE_IRONCLAD",
    "CARD.DEFEND_IRONCLAD",
    "CARD.FEEL_NO_PAIN",
    "CARD.WHIRLWIND",
    "CARD.RAGE",
]


class TestMatchToCardIds:
    def test_exact_match(self):
        result = match_to_card_ids(["Bash"], CARD_DB)
        assert result == ["CARD.BASH"]

    def test_case_insensitive(self):
        result = match_to_card_ids(["bash"], CARD_DB)
        assert result == ["CARD.BASH"]

    def test_multiword_exact(self):
        result = match_to_card_ids(["Feel No Pain"], CARD_DB)
        assert result == ["CARD.FEEL_NO_PAIN"]

    def test_empty_string_returns_none(self):
        result = match_to_card_ids([""], CARD_DB)
        assert result == [None]

    def test_no_match_returns_none(self):
        result = match_to_card_ids(["ZZZQQQXXX"], CARD_DB)
        assert result == [None]

    def test_multiple_cards(self):
        result = match_to_card_ids(["Bash", "Whirlwind"], CARD_DB)
        assert result == ["CARD.BASH", "CARD.WHIRLWIND"]

    def test_mixed_match_and_none(self):
        result = match_to_card_ids(["Bash", ""], CARD_DB)
        assert result == ["CARD.BASH", None]

    def test_fuzzy_typo(self):
        # "Bosh" close enough to "Bash"
        result = match_to_card_ids(["Bosh"], CARD_DB)
        assert result == ["CARD.BASH"]

    def test_empty_card_list(self):
        result = match_to_card_ids(["Bash"], [])
        assert result == [None]

    def test_empty_inputs(self):
        assert match_to_card_ids([], CARD_DB) == []

    def test_three_cards(self):
        result = match_to_card_ids(["Bash", "Rage", "Whirlwind"], CARD_DB)
        assert result == ["CARD.BASH", "CARD.RAGE", "CARD.WHIRLWIND"]

    def test_partial_name_low_cutoff(self):
        # "Strike" matches "Strike Ironclad" — enough overlap for fuzzy match
        result = match_to_card_ids(["Strike Ironclad"], CARD_DB)
        assert result == ["CARD.STRIKE_IRONCLAD"]


# ── _find_banner_y ────────────────────────────────────────────────────────────

def _make_strip(height, width, banner_start, banner_end, banner_brightness=145, bg_brightness=220):
    """Create a fake RGB column strip with a gray banner region."""
    strip = np.full((height, width, 3), bg_brightness, dtype=np.uint8)
    strip[banner_start:banner_end, :, :] = banner_brightness
    return strip


class TestFindBannerY:
    def test_finds_banner_in_middle(self):
        h = 300
        strip = _make_strip(h, 100, banner_start=80, banner_end=130, banner_brightness=145)
        result = _find_banner_y(strip)
        assert result is not None
        y1, y2 = result
        assert 70 <= y1 <= 90   # ~banner_start
        assert 120 <= y2 <= 140  # ~banner_end

    def test_returns_none_when_no_banner(self):
        # Uniform bright image — no banner
        strip = np.full((300, 100, 3), 230, dtype=np.uint8)
        result = _find_banner_y(strip)
        assert result is None

    def test_returns_none_when_banner_too_small(self):
        # Banner only 2 pixels tall — below minimum
        h = 300
        strip = _make_strip(h, 100, banner_start=100, banner_end=102, banner_brightness=145)
        result = _find_banner_y(strip)
        assert result is None

    def test_returns_none_when_banner_too_large(self):
        # Banner covers 50% of height — above the 18% maximum
        h = 300
        strip = _make_strip(h, 100, banner_start=0, banner_end=200, banner_brightness=145)
        result = _find_banner_y(strip)
        assert result is None

    def test_picks_longest_banner_segment(self):
        # Two banner segments; function should pick the longer one
        h = 300
        strip = np.full((h, 100, 3), 230, dtype=np.uint8)
        strip[30:40, :, :] = 145    # short: 10 rows
        strip[100:140, :, :] = 145  # longer: 40 rows
        result = _find_banner_y(strip)
        assert result is not None
        y1, y2 = result
        assert 95 <= y1 <= 105
        assert 135 <= y2 <= 145

    def test_banner_at_top(self):
        h = 300
        strip = _make_strip(h, 100, banner_start=0, banner_end=30, banner_brightness=145)
        result = _find_banner_y(strip)
        assert result is not None
        y1, y2 = result
        assert y1 == 0
        assert 25 <= y2 <= 35

    def test_banner_at_bottom(self):
        h = 300
        strip = _make_strip(h, 100, banner_start=270, banner_end=300, banner_brightness=145)
        result = _find_banner_y(strip)
        assert result is not None
        y1, y2 = result
        assert 265 <= y1 <= 275
        assert y2 == 300


# ── save_zones / _load_zones ──────────────────────────────────────────────────

class TestSaveLoadZones:
    def test_round_trip(self, tmp_path, monkeypatch):
        """save_zones persists and _load_zones reads back the same values."""
        import card_ocr
        config_path = tmp_path / "ocr_config.json"
        monkeypatch.setattr(card_ocr, "_OCR_CONFIG", config_path)

        new_card_x = [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)]
        new_search_y = (0.25, 0.45)
        save_zones(new_card_x, new_search_y)

        loaded_x, loaded_y = card_ocr._load_zones()
        assert loaded_x == [tuple(x) for x in new_card_x]
        assert loaded_y == new_search_y

    def test_save_updates_module_globals(self, monkeypatch, tmp_path):
        import card_ocr
        config_path = tmp_path / "ocr_config.json"
        monkeypatch.setattr(card_ocr, "_OCR_CONFIG", config_path)

        new_x = [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)]
        new_y = (0.1, 0.2)
        save_zones(new_x, new_y)

        assert card_ocr._CARD_X == [tuple(x) for x in new_x]
        assert card_ocr._SEARCH_Y == new_y

    def test_load_zones_falls_back_to_defaults_on_bad_json(self, tmp_path, monkeypatch):
        import card_ocr
        config_path = tmp_path / "ocr_config.json"
        config_path.write_text("not json")
        monkeypatch.setattr(card_ocr, "_OCR_CONFIG", config_path)

        cx, sy = card_ocr._load_zones()
        assert cx == card_ocr._DEFAULT_CARD_X
        assert sy == card_ocr._DEFAULT_SEARCH_Y

    def test_load_zones_falls_back_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(card_ocr, "_OCR_CONFIG", tmp_path / "nonexistent.json")

        cx, sy = card_ocr._load_zones()
        assert cx == card_ocr._DEFAULT_CARD_X
        assert sy == card_ocr._DEFAULT_SEARCH_Y


# ── _vendor_tesseract ─────────────────────────────────────────────────────────

class TestVendorTesseract:
    def test_returns_none_when_no_vendor_dir(self, tmp_path, monkeypatch):
        # Patch __file__ path so vendor/ doesn't exist relative to it
        with patch.object(sys.modules["card_ocr"], "__file__", str(tmp_path / "card_ocr.py")):
            result = card_ocr._vendor_tesseract()
        assert result is None

    def test_returns_path_when_vendor_exists(self, tmp_path, monkeypatch):
        # Create the vendored exe
        vendor = tmp_path / "vendor" / "tesseract"
        vendor.mkdir(parents=True)
        exe = vendor / "tesseract.exe"
        exe.write_bytes(b"fake exe")
        with patch.object(sys.modules["card_ocr"], "__file__", str(tmp_path / "card_ocr.py")):
            result = card_ocr._vendor_tesseract()
        assert result == exe

    def test_frozen_mode_uses_meipass(self, tmp_path):
        vendor = tmp_path / "vendor" / "tesseract"
        vendor.mkdir(parents=True)
        exe = vendor / "tesseract.exe"
        exe.write_bytes(b"fake exe")
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
            result = card_ocr._vendor_tesseract()
        assert result == exe


# ── is_available ──────────────────────────────────────────────────────────────

class TestIsAvailable:
    def test_returns_false_when_deps_missing(self):
        with patch.object(card_ocr, "_DEPS_OK", False):
            assert card_ocr.is_available() is False

    def test_returns_false_when_tesseract_not_found(self):
        with patch.object(card_ocr, "_DEPS_OK", True), \
             patch.object(card_ocr, "_find_tesseract", return_value=None):
            assert card_ocr.is_available() is False

    def test_returns_true_when_deps_and_tesseract_present(self, tmp_path):
        fake_exe = tmp_path / "tesseract.exe"
        fake_exe.write_bytes(b"")
        with patch.object(card_ocr, "_DEPS_OK", True), \
             patch.object(card_ocr, "_find_tesseract", return_value=str(fake_exe)):
            assert card_ocr.is_available() is True


# ── _find_tesseract fallback paths ────────────────────────────────────────────

class TestFindTesseract:
    def test_prefers_vendor_over_system(self, tmp_path):
        vendor_exe = tmp_path / "tesseract.exe"
        vendor_exe.write_bytes(b"")
        with patch.object(card_ocr, "_vendor_tesseract", return_value=vendor_exe):
            result = card_ocr._find_tesseract()
        assert result == str(vendor_exe)

    def test_falls_back_to_which(self, tmp_path):
        with patch.object(card_ocr, "_vendor_tesseract", return_value=None), \
             patch("shutil.which", return_value="/usr/bin/tesseract"):
            result = card_ocr._find_tesseract()
        assert result == "/usr/bin/tesseract"

    def test_falls_back_to_hardcoded_paths(self, tmp_path):
        fake_exe = tmp_path / "tesseract.exe"
        fake_exe.write_bytes(b"")
        original_paths = card_ocr._TESS_PATHS
        try:
            card_ocr._TESS_PATHS = [str(fake_exe)]
            with patch.object(card_ocr, "_vendor_tesseract", return_value=None), \
                 patch("shutil.which", return_value=None):
                result = card_ocr._find_tesseract()
            assert result == str(fake_exe)
        finally:
            card_ocr._TESS_PATHS = original_paths

    def test_returns_none_when_nothing_found(self):
        with patch.object(card_ocr, "_vendor_tesseract", return_value=None), \
             patch("shutil.which", return_value=None), \
             patch.object(card_ocr, "_TESS_PATHS", []):
            result = card_ocr._find_tesseract()
        assert result is None


# ── _preprocess ───────────────────────────────────────────────────────────────

class TestPreprocess:
    def test_produces_binary_image(self):
        from PIL import Image
        import numpy as np
        img = Image.new("RGB", (60, 20), (210, 210, 210))
        arr = np.array(img)
        arr[5:15, 10:50] = [255, 255, 255]
        img = Image.fromarray(arr)
        result = card_ocr._preprocess(img)
        assert result.mode == "L"
        pixels = np.array(result).flatten()
        assert set(pixels.tolist()).issubset({0, 255})

    def test_white_pixels_become_black(self):
        from PIL import Image
        import numpy as np
        img = Image.new("RGB", (40, 10), (255, 255, 255))
        result = card_ocr._preprocess(img)
        assert np.array(result).max() == 0  # all black → white text rendered black

    def test_dark_pixels_become_white(self):
        from PIL import Image
        import numpy as np
        img = Image.new("RGB", (40, 10), (50, 50, 50))
        result = card_ocr._preprocess(img)
        assert np.array(result).min() == 255  # all background → white

    def test_output_is_3x_size(self):
        from PIL import Image
        img = Image.new("RGB", (30, 10), (200, 200, 200))
        result = card_ocr._preprocess(img)
        assert result.size == (90, 30)
