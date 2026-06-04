"""
Fetches energy costs for all cards by scraping individual card wiki pages.
Patches cards_db.py with correct costs.
"""
import re, json, urllib.request, time
from pathlib import Path

# Import current db from the project root
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cards_db import CARD_DB

WIKI = "https://slaythespire.wiki.gg"
COSTS_FILE = ROOT / "_card_costs.json"

def fetch_cost(card_name: str) -> str | int | None:
    """Fetch energy cost from individual card page."""
    # Title: "Slay_the_Spire_2:Bash" etc.
    display = card_name.replace("_", " ").title()
    # Try a few name formats
    for title in [display, card_name]:
        url = f"{WIKI}/api.php?action=parse&page=Slay_the_Spire_2:{urllib.request.quote(title)}&prop=wikitext&format=json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "STS2Tracker/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
            if not wikitext:
                continue
            # Card Infobox: {{Card Infobox|Bash|COST|2}} or {{Card Infobox|Bash||2}}
            # Cost is second param (may be blank = 0, or a number, or "X")
            m = re.search(r'\{\{Card Infobox\|[^|]*\|([^|]*)\|', wikitext)
            if m:
                cost_str = m.group(1).strip()
                if cost_str == "":
                    return 0
                if cost_str.upper() == "X":
                    return "X"
                try:
                    return int(cost_str)
                except ValueError:
                    return cost_str
        except Exception:
            pass
    return None


def main():
    # Load cached costs if available
    costs = {}
    if COSTS_FILE.exists():
        costs = json.loads(COSTS_FILE.read_text())
        print(f"Loaded {len(costs)} cached costs")

    # Find cards missing costs
    missing = [k for k, v in CARD_DB.items() if k not in costs]
    print(f"Fetching costs for {len(missing)} cards...")

    for i, key in enumerate(missing):
        # Convert key to display name for wiki lookup
        display = key.replace("_", " ").title()
        cost = fetch_cost(display)
        costs[key] = cost
        if i % 20 == 0:
            print(f"  {i}/{len(missing)}: {key} = {cost}")
            COSTS_FILE.write_text(json.dumps(costs, indent=2))
        time.sleep(0.05)  # be polite

    COSTS_FILE.write_text(json.dumps(costs, indent=2))
    print(f"Done. Saved {len(costs)} costs to {COSTS_FILE}")

    # Report how many we got
    found = sum(1 for v in costs.values() if v is not None)
    print(f"  Found: {found}, Missing: {len(costs) - found}")


if __name__ == "__main__":
    main()
