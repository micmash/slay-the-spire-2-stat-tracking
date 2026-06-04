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
