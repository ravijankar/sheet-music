#!/usr/bin/env bash
# convert-to-mscx.sh
# Batch convert all .mscz files in a directory to .mscx (uncompressed XML)
# Usage: ./convert-to-mscx.sh [directory]
#   directory defaults to current directory if not specified

set -euo pipefail

# ── Locate MuseScore CLI ──────────────────────────────────────────────────────
find_mscore() {
  # Common locations for MuseScore 4 and 3 on macOS
  local candidates=(
    "/Applications/MuseScore 4.app/Contents/MacOS/mscore"
    "/Applications/MuseScore 3.app/Contents/MacOS/mscore"
    "/Applications/MuseScore.app/Contents/MacOS/mscore"
  )
  for path in "${candidates[@]}"; do
    if [[ -x "$path" ]]; then
      echo "$path"
      return 0
    fi
  done
  # Fall back to PATH (e.g. if installed via Homebrew or symlinked)
  if command -v mscore &>/dev/null; then
    command -v mscore
    return 0
  fi
  if command -v musescore &>/dev/null; then
    command -v musescore
    return 0
  fi
  return 1
}

MSCORE=$(find_mscore) || {
  echo "❌  MuseScore CLI not found."
  echo "    Install MuseScore 4 from https://musescore.org, then re-run this script."
  exit 1
}
echo "✔  Using MuseScore: $MSCORE"

# ── Target directory ─────────────────────────────────────────────────────────
TARGET_DIR="${1:-.}"
if [[ ! -d "$TARGET_DIR" ]]; then
  echo "❌  Directory not found: $TARGET_DIR"
  exit 1
fi

# ── Convert ───────────────────────────────────────────────────────────────────
FILES=()
while IFS= read -r -d '' f; do
  FILES+=("$f")
done < <(find "$TARGET_DIR" -name "*.mscz" -print0)

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "⚠️   No .mscz files found in $TARGET_DIR"
  exit 0
fi

echo "Found ${#FILES[@]} .mscz file(s) — converting…"
echo

PASS=0
FAIL=0

for src in "${FILES[@]}"; do
  dst="${src%.mscz}.mscx"
  printf "  %-60s → %s\n" "$(basename "$src")" "$(basename "$dst")"
  if "$MSCORE" --export-to "$dst" "$src" &>/dev/null; then
    ((PASS++))
  else
    echo "    ⚠️  Failed: $src"
    ((FAIL++))
  fi
done

echo
echo "Done. ✅ $PASS converted  ❌ $FAIL failed"