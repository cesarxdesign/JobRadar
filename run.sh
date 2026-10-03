#!/bin/sh
# One unattended pass on this Mac, lid open: read what is waiting, rebuild the
# lanes, push the board. vision.py waits out a usage limit by itself and
# restarts its own browser, so this needs nobody watching. While it reads, the
# board is refreshed every 20 minutes with what has been read so far.
cd "$(dirname "$0")"
publish() {
  python3 results.py >/dev/null 2>&1 || return
  git add data/results.json data/vision.json data/shipped.json data/vision_runs.jsonl 2>/dev/null
  git diff --cached --quiet || { git commit -q -m "run $(date +%F\ %H:%M): roles read by vision

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q; }
}
( while sleep 1200; do publish; done ) &
TICK=$!
python3 vision.py --fresh "$@"
kill $TICK 2>/dev/null
publish
echo "run.sh finished $(date)"
