#!/usr/bin/env python3
"""
Build forScore library import ZIPs — one for tenor, one for baritone.

Usage:
    python build-forscore-library.py [--no-charts]

Options:
    --no-charts   Omit real chart PDFs; only include NO CHART placeholder pages.
                  Use this when charts are already imported into forScore and you
                  just need to add the placeholders.

Output:
    exports/forscore-tenor.zip
    exports/forscore-bari.zip

Import into forScore: AirDrop the ZIPs to your iPad, tap to open with forScore.
"""

import argparse
import zipfile
from pathlib import Path

SHEET_DIR       = Path(__file__).parent
TENOR_DIR       = SHEET_DIR / "exports" / "tenor-pdfs"
BARI_DIR        = SHEET_DIR / "exports" / "bari-pdfs"
PLACEHOLDER_DIR = SHEET_DIR / "exports" / "placeholders"
OUT_DIR         = SHEET_DIR / "exports"


def build_zip(zip_path, sources):
    """Zip all PDFs from the given source directories into zip_path."""
    count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for src_dir in sources:
            if not src_dir.exists():
                continue
            for pdf in sorted(src_dir.glob("*.pdf")):
                zf.write(pdf, pdf.name)
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Build forScore library ZIPs for tenor and baritone."
    )
    parser.add_argument(
        "--no-charts",
        action="store_true",
        help="Omit chart PDFs — include only NO CHART placeholder pages.",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.no_charts:
        tenor_sources = [PLACEHOLDER_DIR]
        bari_sources  = [PLACEHOLDER_DIR]
        label = "placeholders only"
    else:
        tenor_sources = [TENOR_DIR, PLACEHOLDER_DIR]
        bari_sources  = [BARI_DIR,  PLACEHOLDER_DIR]
        label = "charts + placeholders"

    tenor_zip = OUT_DIR / "forscore-tenor.zip"
    bari_zip  = OUT_DIR / "forscore-bari.zip"

    n = build_zip(tenor_zip, tenor_sources)
    print(f"Tenor: {tenor_zip.name} — {n} PDFs ({label})")

    n = build_zip(bari_zip, bari_sources)
    print(f"Bari:  {bari_zip.name} — {n} PDFs ({label})")

    print("\nAirDrop these ZIPs to your iPad and open with forScore to import.")


if __name__ == "__main__":
    main()
