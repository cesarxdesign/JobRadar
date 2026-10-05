#!/bin/sh
# After the full board check: scrape everything it added, read the new design roles, audit, publish.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
exec >>data/nightly.log 2>&1
while pgrep -f "harvest_now.sh" >/dev/null || pgrep -f "harvest.py" >/dev/null; do sleep 30; done
echo; echo "=== round 2 $(date '+%F %H:%M') ==="
tail -4 data/harvest_wayback.log 2>/dev/null; tail -30 data/harvest_check2.log 2>/dev/null | cut -c1-200
publish() {
  python3 results.py | head -1 | cut -c1-240
  python3 poolparts.py split >/dev/null
  git add data/boards.json data/pool[0-9]*.json data/sources.json data/discovered.json data/results.json data/vision.json data/shipped.json data/vision_runs.jsonl 2>/dev/null
  git diff --cached --quiet || { git commit -q -m "round 2 $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
}
echo "-- check the boards the second list added"; python3 harvest.py check | tail -6
echo "-- scrape"; python3 pool.py | grep -v "^  \[\|^   *…" | tail -8
publish
( while sleep 1200; do publish; done ) &
TICK=$!
echo "-- read new"; python3 vision.py --new | grep -v "^  \[" | tail -8
kill $TICK 2>/dev/null
echo "-- audit"; python3 vision.py --audit | grep -v "^  \[" | tail -8
publish
python3 battery.py | head -5
echo "=== done $(date '+%F %H:%M') ==="
