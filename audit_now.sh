#!/bin/sh
# After a run: pages that would not open get their second try, then one cut in ten is read again.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
exec >>data/nightly.log 2>&1
echo; echo "=== retry + second read $(date '+%F %H:%M') ==="
echo "-- VISION: not read, second try"; python3 vision.py --new | grep -v "^  \[" | tail -5
echo "-- VISION: second read of every rejection not yet checked"; python3 vision.py --audit --all | grep -v "^  \[" | tail -40
python3 results.py | head -1 | cut -c1-260
python3 poolparts.py split >/dev/null
git add data/pool[0-9]*.json data/results.json data/vision.json data/shipped.json data/vision_runs.jsonl 2>/dev/null
git diff --cached --quiet || { git commit -q -m "retry and audit $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
python3 battery.py | head -5
echo "=== done $(date '+%F %H:%M') ==="
