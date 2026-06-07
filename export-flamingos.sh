#!/bin/bash
SHEET_DIR="$HOME/Music/sheet-music/flamingos"
OUT_DIR="$HOME/Music/sheet-music/exports/flamingos-pdfs"
ZIP_OUT="$HOME/Music/sheet-music/exports/Flamingos_2026_06_09.zip"
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"

mkdir -p "$OUT_DIR"

find "$SHEET_DIR" -maxdepth 1 -name "*.mscz" -o -name "*.mscx" | sort | while read -r f; do
  base=$(basename "$f")
  base="${base%.mscz}"
  base="${base%.mscx}"
  # Strip leading number prefix (e.g. "01 ", "100 ", "04b ")
  tune=$(echo "$base" | sed 's/^[0-9]*[a-z]*[[:space:]_]*//')
  # Replace underscores with spaces
  tune="${tune//_/ }"

  out="$OUT_DIR/$tune.pdf"
  "$MSCORE" -o "$out" "$f" 2>/dev/null
  if [ -f "$out" ]; then
    echo "✓ $tune"
  else
    echo "✗ Failed: $base"
  fi
done

rm -f "$ZIP_OUT"
zip -j "$ZIP_OUT" "$OUT_DIR"/*.pdf
echo ""
echo "Done: $ZIP_OUT"
echo "Files included:"
zipinfo -1 "$ZIP_OUT"
