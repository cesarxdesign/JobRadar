#!/bin/sh
# RESULTS to his board: names, results, the pool in pieces, then commit and push the data.
# Called by the run after every pull and by VISION's slow lane; one at a time.
cd "$(dirname "$0")" || exit 1
mkdir data/.publishing 2>/dev/null || exit 0
trap 'rmdir data/.publishing' EXIT
python3 names.py | tail -1
python3 results.py | head -1 | cut -c1-240
python3 poolparts.py split >/dev/null
git add data/boards.json data/pool[0-9]*.json data/sources.json data/discovered.json data/results.json data/vision.json data/shipped.json data/vision_runs.jsonl data/cut_names.json 2>/dev/null
git diff --cached --quiet || { git commit -q -m "run $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
