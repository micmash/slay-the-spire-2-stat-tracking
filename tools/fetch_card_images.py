"""
Fetches all STS2 card image URLs from the wiki API and saves to card_images.json.
Run once (or whenever you want to refresh): python fetch_card_images.py
"""
import json
import re
import urllib.request
from pathlib import Path

API = "https://slaythespire.wiki.gg/api.php"
CHARACTERS = ["Ironclad", "Silent", "Defect", "Necrobinder", "Regent", "Colorless", "Status", "Curse"]
OUT = Path(__file__).resolve().parent.parent / "card_images.json"


def fetch_all_images(prefix: str) -> list[dict]:
    results = []
    params = f"action=query&list=allimages&aiprefix={prefix}&ailimit=500&aiprop=url&format=json"
    url = f"{API}?{params}"
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": "STS2Tracker/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        results.extend(data["query"]["allimages"])
        cont = data.get("continue", {}).get("aicontinue")
        url = f"{API}?{params}&aicontinue={cont}" if cont else None
    return results


def card_name_to_wiki(card_id: str) -> str:
    """Convert CARD.BLOOD_WALL → BloodWall (wiki CamelCase name)."""
    key = card_id.removeprefix("CARD.")
    # Remove character suffixes
    for suffix in ("_IRONCLAD", "_SILENT", "_DEFECT", "_NECROBINDER", "_REGENT"):
        key = key.removesuffix(suffix)
    # TitleCase each word
    return "".join(w.capitalize() for w in key.split("_"))


def build_mapping(images: list[dict]) -> dict[str, str]:
    """Map wiki filename stem → full URL."""
    mapping = {}
    for img in images:
        name = img["name"]   # e.g. StS2_Ironclad-Bash.png
        url  = img["url"]
        # Only keep base card images (not -Art, not Plus)
        if name.endswith("-Art.png") or "Plus" in name:
            continue
        # stem: StS2_Ironclad-Bash
        stem = name.removesuffix(".png")
        mapping[stem] = url
    return mapping


def main():
    print("Fetching card images from wiki...")
    all_images = []
    for char in CHARACTERS:
        prefix = f"StS2_{char}-"
        imgs = fetch_all_images(prefix)
        print(f"  {char}: {len(imgs)} images")
        all_images.extend(imgs)

    wiki_map = build_mapping(all_images)
    print(f"Base card images: {len(wiki_map)}")

    # Save the raw wiki_map (stem -> url)
    OUT.write_text(json.dumps(wiki_map, indent=2), encoding="utf-8")
    print(f"Saved to {OUT}")

    # Quick test
    test = "StS2_Ironclad-Bash"
    if test in wiki_map:
        print(f"Test lookup {test}: {wiki_map[test]}")
    else:
        print(f"Warning: {test} not found in map")


if __name__ == "__main__":
    main()
