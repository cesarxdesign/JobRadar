#!/bin/sh
# RESULTS to his board: names, results, the pool in pieces, then commit and push the data.
# Called by the run after every pull and by VISION's slow lane; one at a time.
cd "$(dirname "$0")" || exit 1
mkdir data/.publishing 2>/dev/null || exit 0
trap 'rmdir data/.publishing' EXIT
python3 names.py | tail -1
python3 results.py | head -1 | cut -c1-240
git add data/board.json   # only the roles that passed go to git (his rule, 2026-11-17)
git diff --cached --quiet || { git commit -q -m "run $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
