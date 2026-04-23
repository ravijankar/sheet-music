#!/bin/bash
SHEET_DIR="$HOME/Music/sheet-music"
OUT_DIR="$SHEET_DIR/exports/tenor-pdfs"
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"

mkdir -p "$OUT_DIR"

find "$SHEET_DIR" -maxdepth 1 -name "*.mscx" | while read -r f; do
  base=$(basename "$f" .mscx)
  json=$("$MSCORE" --score-parts-pdf "$f" 2>/dev/null)
  
  # Find index of "Tenor Saxophone" in parts array
  idx=$(echo "$json" | jq '.parts | index("Tenor Saxophone")')
  
  if [ "$idx" != "null" ] && [ -n "$idx" ]; then
    echo "$json" | jq -r ".partsBin[$idx]" | base64 --decode > "$OUT_DIR/$base.pdf"
    echo "✓ $base"
  else
    echo "✗ No tenor part: $base"
  fi
done

rm -f "$SHEET_DIR/exports/tenor-charts.zip"
zip -j "$SHEET_DIR/exports/tenor-charts.zip" "$OUT_DIR"/*.pdf
echo ""
echo "Done: $SHEET_DIR/exports/tenor-charts.zip"
echo "Files included:"
zipinfo -1 "$SHEET_DIR/exports/tenor-charts.zip"