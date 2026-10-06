#!/bin/sh
# A full run, started by hand (he says "run" in chat). This is the loop that ran for real on
# 2026-10-06, 16:48 to 21:56: 4,936 jobs settled, 68% of them without a token.
#   SOURCE  every link opened, in the background
#   POOL    a full pass, then the links SOURCE finds, with FETCH and CL on what comes through CTF
#   VISION  1000 at a time, newest first, until the queue is empty; waits out the usage limit by itself
# then the second read of rejections, and the battery. RESULTS is published every 20 minutes and after every pull.
# One at a time: it leaves if a run is already going. Log: data/nightly.log
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
if pgrep -f "vision.py --new" >/dev/null; then echo "a run is already going"; exit 0; fi
export VISION_WORKERS=${VISION_WORKERS:-9}
exec >> data/nightly.log 2>&1
publish() {
  python3 names.py | tail -1
  python3 results.py | head -1 | cut -c1-240
  python3 poolparts.py split >/dev/null
  git add data/boards.json data/pool[0-9]*.json data/sources.json data/discovered.json data/results.json data/vision.json data/shipped.json data/vision_runs.jsonl data/cut_names.json 2>/dev/null
  git diff --cached --quiet || { git commit -q -m "run $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
}
echo; echo "=== run $(date '+%F %H:%M'): $VISION_WORKERS readers, 1000 a pull ==="
# SOURCE: every link not yet opened today, in the background; the POOL lane below runs for as long as this does
pgrep -f "harvest.py check" >/dev/null || ( python3 limit.py 21600 python3 harvest.py check > data/run_check.log 2>&1 ) &
sleep 5
# a VISION that gives no verdict for 20 minutes, and is not waiting on the usage limit, is stopped; the loop starts the next pull
( while sleep 300; do
    pgrep -f "vision.py --new" >/dev/null || continue
    [ -f data/vision.paused ] && continue
    [ -n "$(find data/vision.beat -mmin +20 2>/dev/null)" ] && { echo "   VISION gave no verdict for 20 minutes: stopped; the next pull carries on"; pkill -f "vision.py --new"; }
  done ) &
WATCH=$!
# POOL lane: a full pass now for today's fresh jobs, then FETCH and CL on what comes through CTF, again and again
(
  while pgrep -f "pool.py" >/dev/null; do sleep 15; done
  T0=$(date +%s); echo "-- POOL: every link with a design job, and every job board  $(date +%H:%M)"
  python3 limit.py 9000 python3 pool.py 2>&1 | grep -v "^  \[\|^   *…" | tail -4 | cut -c1-240
  echo "   POOL full pass: $(( ($(date +%s) - T0) / 60 )) min"
  python3 limit.py 900 python3 discover.py 2>&1 | tail -2 | cut -c1-200
  while :; do
    pgrep -f "pool.py" >/dev/null || python3 pool.py --new-boards 2>&1 | grep -v "^  \[\|^   *…" | tail -1 | cut -c1-200
    pgrep -f "vision.py --fetch" >/dev/null || python3 vision.py --fetch --new 2>&1 | grep -v "^  \[" | tail -1 | cut -c1-200
    pgrep -f "harvest.py check" >/dev/null || break
    sleep 300
  done
  touch data/run_pool.done; echo "   POOL lane done $(date +%H:%M)"
) &
( while sleep 1200; do pgrep -f "vision.py --new" >/dev/null && publish; done ) &
TICK=$!
rm -f data/run_pool.done
while pgrep -f "vision.py --new" >/dev/null; do sleep 20; done
EMPTY=0; N=0
while [ "$EMPTY" -lt 3 ]; do
  Q=$(python3 vision.py --new --count 2>/dev/null | tail -1); case "$Q" in ''|*[!0-9]*) Q=0 ;; esac
  if [ "$Q" -gt 0 ]; then
    EMPTY=0; N=$((N + 1)); echo "-- VISION, pull $N: 1000 of $Q  $(date +%H:%M)"
    python3 vision.py --new --limit 1000 2>&1 | grep -v "^  \[" | tail -4
    publish
  else
    [ -f data/run_pool.done ] && EMPTY=$((EMPTY + 1))
    sleep 120
  fi
done
kill $TICK $WATCH 2>/dev/null
echo "-- VISION: second read of rejections"; python3 vision.py --audit 2>&1 | grep -v "^  \[" | tail -6
publish
python3 battery.py | head -4
echo "=== run done $(date '+%F %H:%M'): the queue is empty ==="
