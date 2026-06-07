#!/bin/bash
SHEET_DIR="$HOME/Music/sheet-music/flamingos"
OUT_DIR="$HOME/Music/sheet-music/exports/flamingos-pdfs"
ZIP_OUT="$HOME/Music/sheet-music/exports/Flamingos_2026_06_09.zip"
MSCORE="/Applications/MuseScore 4.app/Contents/MacOS/mscore"

mkdir -p "$OUT_DIR"

find "$SHEET_DIR" -maxdepth 1 -name "*.mscz" | sort | while read -r f; do
  base=$(basename "$f")
  base="${base%.mscz}"
  base="${base%.mscx}"
  # Strip leading number prefix (e.g. "01 ", "100 ", "04b ")
  tune=$(echo "$base" | sed 's/^[0-9]*[a-z]*[[:space:]_]*//')
  # Replace underscores with spaces
  tune="${tune//_/ }"

  out="$OUT_DIR/$tune.pdf"

  # If the score has multiple parts, export only the first (lead sheet)
  json=$("$MSCORE" --score-parts-pdf "$f" 2>/dev/null)
  nparts=$(echo "$json" | jq '.parts | length' 2>/dev/null)
  if [ "$nparts" -gt 1 ] 2>/dev/null; then
    echo "$json" | jq -r '.partsBin[0]' | base64 --decode > "$out"
  else
    "$MSCORE" -o "$out" "$f" 2>/dev/null
  fi

  if [ -f "$out" ]; then
    echo "✓ $tune"
  else
    echo "✗ Failed: $base"
  fi
done

# Normalize a filename for comparison: lowercase, strip extension, collapse hyphens/underscores to spaces
normalize() { echo "$1" | sed 's/\.[Pp][Dd][Ff]$//' | tr '[:upper:]' '[:lower:]' | tr '-' ' ' | tr '_' ' ' | tr -s ' '; }

# Build list of normalized names already in OUT_DIR
existing_normalized=()
while IFS= read -r f; do
  existing_normalized+=("$(normalize "$(basename "$f")")")
done < <(find "$OUT_DIR" -maxdepth 1 -iname "*.pdf")

# Copy share/ PDFs that don't already have a MuseScore-generated version (by normalized name)
find "$SHEET_DIR/share" -iname "*.pdf" | while read -r f; do
  name=$(basename "$f")
  norm=$(normalize "$name")
  already=false
  for en in "${existing_normalized[@]}"; do
    [ "$norm" = "$en" ] && already=true && break
  done
  if [ "$already" = false ]; then
    cp "$f" "$OUT_DIR/$name"
    echo "+ $name (from share/)"
  fi
done

rm -f "$ZIP_OUT"
find "$OUT_DIR" -iname "*.pdf" -print0 | xargs -0 zip -j "$ZIP_OUT"
echo ""
echo "Done: $ZIP_OUT"
echo "Files included:"
zipinfo -1 "$ZIP_OUT"
