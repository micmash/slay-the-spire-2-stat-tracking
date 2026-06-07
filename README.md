# Slay the Spire 2 Run Tracker

A local desktop app (PyQt6) for Slay the Spire 2 that tracks your run history
and provides a live overlay during runs. Created with Claude as a learning experiment.

## Features

### Run history & analytics
- Auto-imports completed runs from your StS2 save folder
- Per-card win rate, pick rate, and win delta analytics
- Relic win rates and per-run detail view
- Filterable by character and game mode

### Active run overlay
Live tracking of your current run, updated as the save file changes:
- Current HP, gold, floor, act, and potions
- Full deck list with card descriptions and win-rate stats
- Relic list

### Card reward OCR overlay
When a card reward screen appears, a floating overlay shows stats for each of
the three offered cards (win rate, win delta, average score) pulled from your
run history, to help with picks.

- Uses Tesseract OCR + `mss` screen capture to read card names in real time
- Vote-based consensus (5 scans, 80% agreement) before locking a result
- Overlay hides automatically when you view your deck mid-reward and reappears when you return
- Dismissed instantly via `godot.log` watcher when a card is selected; OCR watch-mode (500 ms) as fallback
- Calibrate the capture zones with the **OCR Zones** button
- Toggle the feature on/off with the **Card OCR** button (setting persists between sessions)

## Requirements

- Python 3.11+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) installed and on PATH (for the card reward overlay)
- `pip install PyQt6 pytesseract Pillow numpy mss`

## Run it

```sh
python app.py
```

Or double-click `launch.bat` (keeps the console open on crash), or build a standalone exe:

```sh
python -m PyInstaller --onefile --windowed --name STS2Tracker --hidden-import PyQt6.sip app.py
```

The exe lands in `dist/`. Save data is auto-detected from
`%APPDATA%\SlayTheSpire2\...\saves\history`; use **Browse...** to point elsewhere.

## Module layout

| File | Responsibility |
|------|----------------|
| `app.py` | UI tabs, `MainWindow`, active run tab, entry point |
| `active_run.py` | Parses `current_run.save` into `ActiveRunState` |
| `card_ocr.py` | Screen capture + Tesseract OCR for card reward names |
| `calibrate_zones.py` | Interactive OCR zone calibration tool |
| `ocr_config.json` | Persisted OCR capture zone positions |
| `parser.py` | Reads `.run` save files into `RunSummary` objects |
| `stats.py` | Pure analytics (`compute_card_stats`, `filter_runs`) — no Qt |
| `workers.py` | Background `QThread`s for file loading, image fetch, OCR |
| `ui_utils.py` | Reusable Qt helpers (labels, sortable items, filter combos, CSV export) |
| `theme.py` | Colors, stylesheet, tooltip text |
| `cards_db.py` | Card descriptions/costs/types (generated from the wiki) |
| `card_images.json` | Card name to wiki image URL map |
| `image_cache.py` | Downloads and caches card art into `card_img_cache/` |
| `notes_store.py` | Per-run notes persisted to `run_notes.json` |

## Dev tools (`tools/`)

One-off scripts for regenerating data from the StS2 wiki. Run from anywhere;
they write to the project root.

- `scrape_cards.py` — rebuild `cards_db.py` (names, types, descriptions)
- `fetch_card_images.py` — rebuild `card_images.json`
- `_fetch_costs.py` — backfill card energy costs

## Notes

StS2 is in early access; card text/numbers may drift between patches. Re-run the
`tools/` scrapers to refresh. In multiplayer, the card pool is shared, so a run
can be offered cards from other classes — that's expected, not a bug.
