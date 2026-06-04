import json
from pathlib import Path

NOTES_FILE = Path(__file__).parent / "run_notes.json"


def load_notes() -> dict[str, str]:
    if NOTES_FILE.exists():
        try:
            return json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_note(run_filename: str, note: str):
    notes = load_notes()
    notes[run_filename] = note
    NOTES_FILE.write_text(json.dumps(notes, indent=2), encoding="utf-8")
