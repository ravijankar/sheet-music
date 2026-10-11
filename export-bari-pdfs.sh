#!/bin/bash
SHEET_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$SHEET_DIR/exports/bari-pdfs"
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"
WORK_DIR="$SHEET_DIR/exports/.work"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

find "$SHEET_DIR/scores" -maxdepth 1 -name "*.mscx" | while read -r f; do
  base=$(basename "$f" .mscx)
  # Export from an isolated copy: MuseScore treats the folder around an .mscx
  # as the score package and would pick up a stray Excerpts/ from another score.
  # The shared style file has to travel with it, or the parts lose their formatting.
  rm -rf "$WORK_DIR" && mkdir -p "$WORK_DIR" && cp "$f" "$SHEET_DIR/score_style.mss" "$WORK_DIR/"
  json=$("$MSCORE" --score-parts-pdf "$WORK_DIR/$base.mscx" 2>/dev/null)

  # Find index of baritone saxophone part (named either "Baritone Saxophone" or "Bari Sax")
  idx=$(echo "$json" | jq '.parts | index("Baritone Saxophone") // index("Baritone Saxophone (1)")')

  if [ "$idx" != "null" ] && [ -n "$idx" ]; then
    part=$(echo "$json" | jq -r ".parts[$idx]")
    echo "$json" | jq -r ".partsBin[$idx]" | base64 --decode > "$OUT_DIR/$base $part.pdf"
    echo "✓ $base"
  else
    echo "✗ No bari part: $base"
  fi
done

rm -rf "$WORK_DIR"
rm -f "$SHEET_DIR/exports/bari-charts.zip"
zip -j "$SHEET_DIR/exports/bari-charts.zip" "$OUT_DIR"/*.pdf
echo ""
echo "Done: $SHEET_DIR/exports/bari-charts.zip"
echo "Files included:"
zipinfo -1 "$SHEET_DIR/exports/bari-charts.zip"