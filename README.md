# Slay the Spire 2 Run Tracker

A local desktop app (PyQt6) that auto-imports your StS2 run history and shows
run stats, card pick/win analytics, relic win rates, and per-card detail. Created with Claude as learning experiment

## Run it

```sh
python app.py
```

Or double-click `launch.bat`, or build a standalone exe:

```sh
python -m PyInstaller --onefile --windowed --name STS2Tracker --hidden-import PyQt6.sip app.py
```

The exe lands in `dist/`. Save data is auto-detected from
`%APPDATA%\SlayTheSpire2\...\saves\history`; use **Browse...** to point elsewhere.

## Module layout

| File | Responsibility |
|------|----------------|
| `app.py` | UI tabs + `MainWindow` + entry point |
| `parser.py` | Reads `.run` save files â†’ `RunSummary` objects |
| `stats.py` | Pure analytics (`compute_card_stats`, `filter_runs`) â€” no Qt |
| `workers.py` | Background `QThread`s for file loading + image fetch |
| `ui_utils.py` | Reusable Qt helpers (labels, sortable items, filter combos, CSV export) |
| `theme.py` | Colors, stylesheet, tooltip text |
| `cards_db.py` | Card descriptions/costs/types (generated from the wiki) |
| `card_images.json` | Card name â†’ wiki image URL map |
| `image_cache.py` | Downloads + caches card art into `card_img_cache/` |
| `notes_store.py` | Per-run notes persisted to `run_notes.json` |

## Dev tools (`tools/`)

One-off scripts for regenerating data from the StS2 wiki. Run from anywhere;
they write to the project root.

- `scrape_cards.py` â€” rebuild `cards_db.py` (names, types, descriptions)
- `fetch_card_images.py` â€” rebuild `card_images.json`
- `_fetch_costs.py` â€” backfill card energy costs

## Notes

StS2 is in early access; card text/numbers may drift between patches. Re-run the
`tools/` scrapers to refresh. In multiplayer, the card pool is shared, so a run
can be offered cards from other classes that's expected, not a bug.
