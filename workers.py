"""Background QThread workers for non-blocking file IO and image fetching."""
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from parser import load_all_runs
from image_cache import get_image_path


class RunLoader(QThread):
    """Parses all run files off the UI thread."""
    done = pyqtSignal(list)

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def run(self):
        self.done.emit(load_all_runs(self.path))


class ImageLoader(QThread):
    """Fetches a card image in the background; emits the local path (or '' on failure)."""
    done = pyqtSignal(str)

    def __init__(self, card_id: str, char_hint: str | None = None):
        super().__init__()
        self.card_id = card_id
        self.char_hint = char_hint

    def run(self):
        path = get_image_path(self.card_id, self.char_hint)
        self.done.emit(str(path) if path else "")


class CardOcrWorker(QThread):
    """Takes a screenshot and OCRs the three card reward name areas off the UI thread.

    Emits a list of (card_id_or_None, raw_ocr_text) pairs.
    """
    done = pyqtSignal(list)

    def __init__(self, all_card_ids: list[str]):
        super().__init__()
        self._card_ids = all_card_ids

    def run(self):
        try:
            from card_ocr import read_card_reward_names, match_to_card_ids
            raw = read_card_reward_names()
            if not raw:
                self.done.emit([])
                return
            matched = match_to_card_ids(raw, self._card_ids)
            self.done.emit(list(zip(matched, raw)))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.done.emit([])
