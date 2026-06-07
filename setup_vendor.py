"""
Copy a minimal Tesseract bundle from an existing system install into vendor/tesseract/.
Run once before building a standalone exe or to enable OCR without a system-wide install.

Usage:
    python setup_vendor.py
    python setup_vendor.py "C:\\path\\to\\Tesseract-OCR"   # custom source
"""
import shutil
import sys
from pathlib import Path

DEFAULT_SOURCES = [
    r"C:\Program Files\Tesseract-OCR",
    r"C:\Program Files (x86)\Tesseract-OCR",
]

DEST = Path(__file__).parent / "vendor" / "tesseract"


def find_source(override: str | None) -> Path:
    if override:
        p = Path(override)
        if not (p / "tesseract.exe").exists():
            sys.exit(f"tesseract.exe not found in {p}")
        return p
    for s in DEFAULT_SOURCES:
        p = Path(s)
        if (p / "tesseract.exe").exists():
            return p
    sys.exit(
        "Tesseract install not found. Install from:\n"
        "  https://github.com/UB-Mannheim/tesseract/wiki\n"
        "or pass the install path as an argument."
    )


def main():
    src = find_source(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Source: {src}")
    print(f"Dest:   {DEST}")

    DEST.mkdir(parents=True, exist_ok=True)

    # tesseract.exe
    shutil.copy2(src / "tesseract.exe", DEST / "tesseract.exe")
    print("  copied tesseract.exe")

    # All DLLs in the install root
    dlls = list(src.glob("*.dll"))
    for dll in dlls:
        shutil.copy2(dll, DEST / dll.name)
    print(f"  copied {len(dlls)} DLLs")

    # tessdata — only eng (keeps size down; add others if needed)
    tessdata_dest = DEST / "tessdata"
    tessdata_dest.mkdir(exist_ok=True)
    for name in ("eng.traineddata", "osd.traineddata"):
        src_file = src / "tessdata" / name
        if src_file.exists():
            shutil.copy2(src_file, tessdata_dest / name)
            print(f"  copied tessdata/{name}")

    total_mb = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file()) / 1_048_576
    print(f"\nDone. vendor/tesseract/ is {total_mb:.0f} MB.")
    print("Add --add-data 'vendor;vendor' to your PyInstaller command.")


if __name__ == "__main__":
    main()
