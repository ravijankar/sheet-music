#!/usr/bin/env bash
# setup-git-repo.sh
# Initializes a new git-managed MuseScore sheet music library.
# Usage: ./setup-git-repo.sh [path/to/library]
#   Defaults to ~/Music/sheet-music if no path is given.

set -euo pipefail

LIBRARY_DIR="${1:-$HOME/Music/sheet-music}"

echo "════════════════════════════════════════════"
echo "  MuseScore Sheet Music Library Setup"
echo "════════════════════════════════════════════"
echo "  Target: $LIBRARY_DIR"
echo

# ── Create directory structure ────────────────────────────────────────────────
echo "▸ Creating directory structure…"
mkdir -p \
  "$LIBRARY_DIR/originals" \
  "$LIBRARY_DIR/arrangements" \
  "$LIBRARY_DIR/in-progress" \
  "$LIBRARY_DIR/exports/pdf" \
  "$LIBRARY_DIR/exports/musicxml"

# ── Init git repo (safe to run on existing repo) ──────────────────────────────
echo "▸ Initializing git repository…"
git -C "$LIBRARY_DIR" init -q

# ── .gitignore ────────────────────────────────────────────────────────────────
echo "▸ Writing .gitignore…"
cat > "$LIBRARY_DIR/.gitignore" << 'EOF'
# MuseScore auto-backup files
*.mscz,
*.mscz~
*.mscx~

# macOS
.DS_Store
.AppleDouble
.LSOverride

# Thumbnails
._*

# Editor/IDE
.vscode/
.idea/
EOF

# ── README ────────────────────────────────────────────────────────────────────
if [[ ! -f "$LIBRARY_DIR/README.md" ]]; then
  echo "▸ Writing README.md…"
  cat > "$LIBRARY_DIR/README.md" << 'EOF'
# Sheet Music Library

Git-managed MuseScore sheet music library.

## Structure

| Directory | Contents |
|-----------|----------|
| `originals/` | Unmodified scores — transcriptions of existing works |
| `arrangements/` | Your own arrangements and adaptations |
| `in-progress/` | Works in progress |
| `exports/pdf/` | PDF exports for printing/sharing |
| `exports/musicxml/` | MusicXML exports for cross-app compatibility |

## How .mscx files are generated

A pre-commit hook automatically exports an `.mscx` (uncompressed XML) file
alongside every `.mscz` you commit. This lets `git diff` show meaningful
changes to the score structure rather than just "binary file changed".

You never need to create `.mscx` files manually — just commit your `.mscz`
files normally.

## Useful commands

```bash
# See what changed in a score between commits
git diff HEAD~1 HEAD -- path/to/score.mscx

# View history for a specific piece
git log --oneline -- originals/my-piece.mscz

# Revert a score to a previous version
git checkout <commit-hash> -- originals/my-piece.mscz
```
EOF
fi

# ── Install pre-commit hook ───────────────────────────────────────────────────
echo "▸ Installing pre-commit hook…"
HOOK_DIR="$LIBRARY_DIR/.git/hooks"
HOOK_FILE="$HOOK_DIR/pre-commit"

# The hook script (same logic as standalone pre-commit file)
cat > "$HOOK_FILE" << 'HOOK'
#!/usr/bin/env bash
# Auto-export .mscx alongside staged .mscz files

set -euo pipefail

find_mscore() {
  local candidates=(
    "/Applications/MuseScore 4.app/Contents/MacOS/mscore"
    "/Applications/MuseScore 3.app/Contents/MacOS/mscore"
    "/Applications/MuseScore.app/Contents/MacOS/mscore"
  )
  for path in "${candidates[@]}"; do
    [[ -x "$path" ]] && { echo "$path"; return 0; }
  done
  command -v mscore    2>/dev/null && return 0
  command -v musescore 2>/dev/null && return 0
  return 1
}

MSCORE=$(find_mscore) || {
  echo "⚠️  pre-commit: MuseScore CLI not found — skipping .mscx export."
  exit 0
}

STAGED=$(git diff --cached --name-only --diff-filter=AM | grep '\.mscz$' || true)
[[ -z "$STAGED" ]] && exit 0

echo "pre-commit: exporting .mscx for staged .mscz files…"

FAIL=0
while IFS= read -r mscz; do
  mscx="${mscz%.mscz}.mscx"
  printf "  %s → %s\n" "$mscz" "$mscx"
  if "$MSCORE" --export-to "$mscx" "$mscz" &>/dev/null; then
    git add "$mscx"
  else
    echo "  ⚠️  Export failed for $mscz"
    ((FAIL++))
  fi
done <<< "$STAGED"

[[ $FAIL -gt 0 ]] && echo "pre-commit: $FAIL export(s) failed — committing anyway."
exit 0
HOOK

chmod +x "$HOOK_FILE"

# ── Initial commit ────────────────────────────────────────────────────────────
echo "▸ Making initial commit…"
git -C "$LIBRARY_DIR" add .
git -C "$LIBRARY_DIR" commit -q -m "Initial library structure"

echo
echo "════════════════════════════════════════════"
echo "  ✅ Done!"
echo "════════════════════════════════════════════"
echo
echo "  Library created at: $LIBRARY_DIR"
echo
echo "  Next steps:"
echo "  1. Move your .mscz files into the appropriate subdirectory"
echo "  2. git add and git commit as usual — .mscx files will be"
echo "     generated and staged automatically on each commit"
echo
echo "  Optional — add a remote for backup:"
echo "    cd \"$LIBRARY_DIR\""
echo "    git remote add origin <your-github-or-remote-url>"
echo "    git push -u origin main"
echo