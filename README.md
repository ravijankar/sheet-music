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
