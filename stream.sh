#!/bin/sh
# The harvest, as a stream: boards the check has just added are scraped, their
# design roles read, and the board published - round after round - instead of
# waiting for 45,000 boards to be checked before anything is read.
# (His call, 2026-10-05: "why wait for all boards, to start vision, if we
# already have a bunch of roles?")
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
exec >>data/nightly.log 2>&1
echo; echo "=== stream $(date '+%F %H:%M') ==="
publish() {
  python3 results.py | head -1 | cut -c1-240
  python3 poolparts.py split >/dev/null
  git add data/boards.json data/pool[0-9]*.json data/sources.json data/discovered.json data/results.json data/vision.json data/shipped.json data/vision_runs.jsonl 2>/dev/null
  git diff --cached --quiet || { git commit -q -m "stream $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
}
ROUND=0
while :; do
  ROUND=$((ROUND + 1))
  # the batch: X POOL roles, sized so what survives CUT keeps VISION busy until the next handover
  B=$(python3 harvest.py batch); echo "$B" | head -1
  eval "$(echo "$B" | tail -1)"
  echo "-- round $ROUND $(date +%H:%M): POOL, $BOARDS boards"
  S=$(python3 pool.py --new-boards --boards "$BOARDS" 2>&1 | grep -v "^  \[\|^   *…" | tail -5); echo "$S"
  echo "-- round $ROUND: CUT, then VISION on $READS"
  V=$(python3 vision.py --new --limit "$READS" 2>&1 | grep -v "^  \[" | tail -4); echo "$V"
  publish
  # done when the check has finished, no board is left unread and nothing is left to read
  if ! pgrep -f "harvest.py" >/dev/null && echo "$S" | grep -q "new boards: 0 never read" && echo "$V" | grep -q "vision: 0 roles to read"; then break; fi
  echo "$S" | grep -q "new boards: 0 never read" && echo "$V" | grep -q "vision: 0 roles to read" && sleep 120
done
echo "-- audit"; python3 vision.py --audit | grep -v "^  \[" | tail -8
publish
python3 battery.py | head -5
echo "=== stream done $(date '+%F %H:%M') ==="
