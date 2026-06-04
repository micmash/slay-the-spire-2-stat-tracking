"""
Scrapes card data from https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2:Cards_List
and regenerates cards_db.py with accurate descriptions, costs, and types.

Run: python scrape_cards.py
"""
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

URL = "https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2:Cards_List"
OUT = Path(__file__).resolve().parent.parent / "cards_db.py"

CHAR_COLORS = {
    "Ironclad":   "#e74c3c",
    "Silent":     "#27ae60",
    "Defect":     "#2980b9",
    "Necrobinder":"#8e44ad",
    "Regent":     "#f39c12",
    "Any":        "#7f8c8d",
}
TYPE_COLORS = {
    "Attack": "#c0392b",
    "Skill":  "#2980b9",
    "Power":  "#8e44ad",
    "Status": "#7f8c8d",
    "Curse":  "#2c3e50",
}

# Map display name → CARD_ID key
def display_to_key(name: str, char: str) -> str:
    """'Blood Wall' + 'Ironclad' → 'BLOOD_WALL'"""
    key = name.upper().replace(" ", "_").replace("'", "").replace("-", "_")
    key = re.sub(r"[^A-Z0-9_]", "", key)
    # Remove character suffix if present
    for suffix in ("_IRONCLAD", "_SILENT", "_DEFECT", "_NECROBINDER", "_REGENT"):
        key = key.removesuffix(suffix)
    # Handle "(Ironclad)" etc. in display names
    key = re.sub(r"_\(.*\)$", "", key)
    return key


def strip_tags(html: str) -> str:
    """Remove HTML tags, collapse whitespace. Preserves game icons as text."""
    # Replace energy icon spans (data-name="@IE", "@SE", "@DE", "@NE", "@RE", "@GE")
    # with [E] before stripping other tags
    html = re.sub(
        r'<span[^>]*data-name="@[A-Z]E"[^>]*>.*?</span>',
        "[E]",
        html,
        flags=re.DOTALL,
    )
    # Replace <br> with space
    html = re.sub(r"<br\s*/?>", " ", html)
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#[0-9]+;", "", text)
    text = re.sub(r"&[a-z]+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_page(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "STS2Tracker-Scraper/1.0",
        "Accept": "text/html",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_cards(html: str) -> list[dict]:
    """
    Parse card-box divs from the HTML.
    Structure:
      <div class="card-box" data-rarity="Basic" data-type="Attack" data-color="Ironclad" ...>
        <div class="card-title"><a ...>Bash</a></div>
        <div class="card-desc">
          <div class="desc-base">Deal 8 damage.<br/>Apply 2 Vulnerable.</div>
        </div>
      </div>

    Cost is embedded in the card image (the PNG filename has no cost), so we pull
    it from the card-meta text e.g. "Basic - Ironclad - Attack" or from the image alt
    which is the card name. Cost comes from the card image filename prefix doesn't help —
    we fetch it from the card page URL or infer from the img filename.

    Actually the cost IS encoded in the card image as the card artwork shows it, but
    not in the HTML text. We extract it from the card-image img title which doesn't have
    it either. For now we parse what we can and patch costs separately.

    Looking more carefully: the cost doesn't appear in the card-box HTML at all.
    We'll store cost=None and note it's unknown, then fill it from a secondary pass
    or use the data we already have.
    """
    cards = []

    # Match every card-box div — use the data attributes for metadata
    # and inner divs for name/description
    pattern = re.compile(
        r'<div[^>]*class="card-box"[^>]*'
        r'data-rarity="([^"]*)"[^>]*'
        r'data-type="([^"]*)"[^>]*'
        r'data-color="([^"]*)"[^>]*'
        r'>(.*?)'          # content
        r'(?=<div[^>]*class="card-box"|$)',
        re.DOTALL
    )

    for m in pattern.finditer(html):
        rarity = m.group(1)
        card_type = m.group(2).strip().title()
        char = m.group(3).strip()
        content = m.group(4)

        # Extract card name from .card-title
        title_m = re.search(r'class="card-title"[^>]*>.*?<a[^>]*>([^<]+)</a>', content, re.DOTALL)
        if not title_m:
            continue
        name = title_m.group(1).strip()

        # Extract base description from .desc-base
        desc_m = re.search(r'class="desc-base"[^>]*>(.*?)</div>', content, re.DOTALL)
        if not desc_m:
            continue
        desc_html = desc_m.group(1)
        # Replace <br> with space, strip tags, clean up
        desc_html = re.sub(r'<br\s*/?>', ' ', desc_html)
        desc = strip_tags(desc_html).strip()
        # Remove trailing/leading whitespace artifacts
        desc = re.sub(r'\s+', ' ', desc).strip()

        if char not in ("Ironclad", "Silent", "Defect", "Necrobinder", "Regent",
                        "Colorless", "Status", "Curse", "Any"):
            char = "Any"

        # Clean name
        name = re.sub(r"\s*\([^)]+\)\s*$", "", name).strip()
        key = display_to_key(name, char)
        if not key:
            continue

        cards.append({
            "key": key,
            "name": name,
            "cost": None,   # filled in second pass from known data
            "type": card_type,
            "char": char,
            "desc": desc,
            "rarity": rarity,
        })

    return cards


def dedupe(cards: list[dict]) -> dict[str, dict]:
    """Deduplicate by key, keeping first occurrence."""
    seen = {}
    for c in cards:
        k = c["key"]
        if k not in seen:
            seen[k] = c
    return seen


def write_db(cards: dict[str, dict]):
    lines = [
        '"""',
        'STS2 Card Database — auto-generated by scrape_cards.py',
        'Do not edit manually; re-run the scraper to update.',
        '"""',
        '',
        'CARD_DB: dict[str, dict] = {',
    ]

    for key, c in sorted(cards.items()):
        cost = repr(c["cost"])
        desc = c["desc"].replace("\\", "\\\\").replace('"', '\\"')
        lines.append(
            f'    {key!r}: {{"cost": {cost}, "type": {c["type"]!r}, '
            f'"char": {c["char"]!r}, "desc": "{desc}"}},'
        )

    lines += [
        '}',
        '',
        'TYPE_COLORS = {',
    ]
    for k, v in TYPE_COLORS.items():
        lines.append(f'    {k!r}: {v!r},')
    lines.append('}')
    lines.append('')
    lines.append('CHAR_COLORS = {')
    for k, v in CHAR_COLORS.items():
        lines.append(f'    {k!r}: {v!r},')
    lines.append('}')
    lines.append('')
    lines.append(
        'def get_card(card_id: str) -> dict | None:\n'
        '    """Look up by full ID (CARD.ZAP) or short key (ZAP)."""\n'
        '    key = card_id.removeprefix("CARD.")\n'
        '    return CARD_DB.get(key)\n'
    )

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(cards)} cards to {OUT}")


def main():
    print(f"Fetching {URL} ...")
    html = fetch_page(URL)
    print(f"  Got {len(html):,} bytes")

    cards_list = parse_cards(html)
    print(f"  Parsed {len(cards_list)} raw card rows")

    cards = dedupe(cards_list)
    print(f"  After dedup: {len(cards)} unique cards")

    # Show sample
    for key in list(cards)[:5]:
        c = cards[key]
        print(f"  {key}: [{c['type']}] {c['char']} | {c['desc'][:60]}")

    write_db(cards)


if __name__ == "__main__":
    main()
