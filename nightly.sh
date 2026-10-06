#!/bin/sh
# JobRadar, every night at 00:00 on this Mac (lid open), so the board has
# fresh postings by morning. Started by launchd:
#   ~/Library/LaunchAgents/com.cesarxdesign.jobradar.plist
#
#   tabs      the remote.io tab he leaves open in Chrome, read for its listings
#   scrape    every source: company boards and the job boards
#   discover  companies seen only on a job board -> their own hiring board
#   scrape    the hiring boards just found, so their roles are read tonight
#   inbox     new mail on the Gmail tab he leaves open -> applications
#   read      every design-titled role vision has not read, on its real page
#   publish   lanes rebuilt and pushed; and every 20 minutes while reading
#
# vision.py waits out a usage limit and restarts its own browser, so nobody
# has to watch. Each step is allowed to fail without stopping the night: a
# board being down must not cost him the reading.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
LOG="data/nightly.log"
exec >>"$LOG" 2>&1
echo; echo "=== nightly $(date '+%F %H:%M') ==="
if [ -f data/PAUSED ]; then echo "paused (data/PAUSED is there): $(cat data/PAUSED)"; exit 0; fi
if pgrep -f "vision.py" >/dev/null || pgrep -f "stream.sh" >/dev/null; then echo "a run is already going; leaving it alone"; exit 0; fi

publish() {
  python3 results.py | head -1 | cut -c1-240
  python3 poolparts.py split >/dev/null
  git add data/boards.json data/pool[0-9]*.json data/sources.json data/discovered.json data/results.json data/vision.json \
          data/shipped.json data/vision_runs.jsonl 2>/dev/null
  git diff --cached --quiet || { git commit -q -m "nightly $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
}

# One line per step when it ends, and a table at the end, so the first full
# night can be timed. Every step but the vision read has a time limit: on
# 2026-10-05 the scrape hung from 02:01 to 10:07 and the night was lost. A step
# past its limit is killed (limit.py), one line says so, and the next one runs.
# The read has none: it sleeps for hours on a usage limit and resumes by itself,
# so it gets a page cap instead (--limit).
#   step NAME LIMIT_MINUTES "output filter" command ...
SUMMARY=""
NIGHT_START=$(date +%s)
STAT=$(mktemp)
RUNS="data/vision_runs.jsonl"
clock() { date -r "$1" +%H:%M 2>/dev/null || date -d "@$1" +%H:%M; }   # BSD date on the Mac, GNU elsewhere
step() {
  name=$1; mins=$2; filt=$3; shift 3
  echo "-- $name"
  runs_before=$(cat "$RUNS" 2>/dev/null | wc -l | tr -d ' ')
  t0=$(date +%s)
  : > "$STAT"                       # never report the previous step's status for this one
  python3 limit.py --status "$STAT" $((mins * 60)) "$@" | eval "$filt"
  t1=$(date +%s)
  st=$(cat "$STAT" 2>/dev/null); [ -n "$st" ] || st="exit ?"
  case "$st" in
    killed*) st="killed after ${st#killed } min" ;;
    "exit 0") st="ok" ;;
  esac
  extra=""
  if [ "$1" = "caffeinate" ] && [ "$4" = "vision.py" ] && [ "$(cat "$RUNS" 2>/dev/null | wc -l | tr -d ' ')" -gt "$runs_before" ]; then
    extra=$(tail -1 "$RUNS" | python3 -c 'import json,sys; r=json.loads(sys.stdin.read()); print("  pages %s, tokens %s" % (r.get("pages_read"), (r.get("pages_read") or 0) * (r.get("tokens_per_page") or 0)))' 2>/dev/null)
  fi
  line=$(awk -v n="$name" -v a="$(clock "$t0")" -v b="$(clock "$t1")" -v d="$((t1 - t0))" -v s="$st" \
    'BEGIN { printf "%-36s %s - %s  %6.1f min  %s", n, a, b, d / 60, s }')
  echo "   [clock] $line$extra"
  SUMMARY="$SUMMARY
$line$extra"
}

# Radar's own hidden Chrome, left over from a stopped run, answers AppleScript
# in place of his: with one alive, the script reads the wrong browser's tabs.
pkill -f "radar-chrome-" 2>/dev/null; sleep 2
# NO_CHROME=1 leaves his Chrome alone (tabs, inbox): for a run by day, while he is working in it
[ -n "$NO_CHROME" ] || step "tabs" 5 cat python3 tabs.py remoteio
# every company board on every hiring system: the list is refreshed weekly,
# and each night the boards that are due get checked for a design role
if [ ! -f data/boards.json ] || [ -n "$(find data/boards.json -mtime +7 2>/dev/null)" ]; then
  step "SOURCE: list links" 60 "tail -24" caffeinate -i python3 harvest.py enumerate
  # the Internet Archive knows about twice as many links as the web index does
  # (62,000 more on 2026-10-06); asked in the background, it takes an hour or two
  ( python3 limit.py 14400 caffeinate -i python3 harvest.py wayback > data/night_wayback.log 2>&1 ) &
fi
# How the night is fed (his description, 2026-10-06). Tokens are the scarce
# thing, so VISION must be busy from the first minute to the last:
#   SOURCE  every link opened, in the background
#   POOL    in the background too: the full pass, then the links SOURCE keeps
#           finding, round after round, until SOURCE is done
#   VISION  pulls. As soon as 10 jobs have come through CUT it reads them;
#           when it is done it takes whatever has queued up meanwhile, and so
#           on. The pulls grow until it never stops, and it ends when SOURCE
#           and POOL are finished and the queue is empty.
# Nothing here waits for anything else to finish.
VISION_WORKERS=$(cat data/vision_workers 2>/dev/null || echo 6); export VISION_WORKERS
RUNS_AT_START=$(cat "$RUNS" 2>/dev/null | wc -l | tr -d ' ')
rm -f data/night_pool.done data/night_pool.clock
CHECK_T0=$(date +%s)
if pgrep -f "source_loop.sh" >/dev/null; then
  echo "-- SOURCE: check links: left to source_loop.sh, which opens every link all day"
else
  echo "-- SOURCE: check links, in the background"
  ( python3 limit.py 21600 caffeinate -i python3 harvest.py check > data/night_check.log 2>&1
    echo "SOURCE: check links (background)       $(( ($(date +%s) - CHECK_T0) / 60 )) min  $(grep -i "checked .* in " data/night_check.log | tail -1 | cut -c1-110)" >> data/night_pool.clock ) &
  sleep 5
fi
# the POOL lane
(
  lane() { t0=$(date +%s); "$@" 2>&1 | grep -v "^  \[\|^   *…" | tail -3 | cut -c1-220
           echo "$LANE_NAME   $(( ($(date +%s) - t0) / 60 )) min" >> data/night_pool.clock; }
  LANE_NAME="POOL (background)                     "; lane python3 limit.py 9000 caffeinate -i python3 pool.py
  LANE_NAME="SOURCE: discover links (background)   "; lane python3 limit.py 900 caffeinate -i python3 discover.py
  R=0
  while :; do
    R=$((R + 1)); more=0
    pgrep -f "harvest.py check" >/dev/null && more=1          # asked BEFORE the pass, so links found during it get one more
    LANE_NAME="POOL: new links, pass $R (background)   "; lane python3 limit.py 1800 caffeinate -i python3 pool.py --new-boards
    [ "$more" = 1 ] || break
    sleep 120
  done
  touch data/night_pool.done
) &
# cesarxdesign@gmail.com only (his call, 2026-10-05). inbox_all.py reads the
# other accounts and is run by hand, when he asks.
[ -f inbox.py ] && [ -z "$NO_CHROME" ] && step "inbox" 10 "tail -3" caffeinate -i python3 inbox.py
# the applying numbers, dates and outcomes only, onto the cxd-stats page
step "stats" 5 "tail -1" python3 stats_export.py
# the VISION lane. The night starts at midnight with the work that costs no
# tokens, so a full queue is waiting; VISION itself starts at 01:00, when his
# own day with his tokens is over (his call, 2026-10-06). A run started by
# hand at any other hour does not wait.
[ "$(date +%H)" = "00" ] && echo "-- VISION holds until 01:00; SOURCE and POOL are filling the queue"
while [ "$(date +%H)" = "00" ]; do sleep 30; done
PULL=0; WAITED=0
while :; do
  Q=$(python3 vision.py --new --count 2>/dev/null | tail -1); case "$Q" in ''|*[!0-9]*) Q=0 ;; esac
  if [ "$Q" -ge 10 ] || { [ -f data/night_pool.done ] && [ "$Q" -gt 0 ]; }; then
    PULL=$((PULL + 1))
    step "VISION, pull $PULL: $Q jobs" 0 'grep -v "^  \[" | tail -6' caffeinate -i python3 vision.py --new
    publish
  elif [ -f data/night_pool.done ]; then
    break                                   # SOURCE and POOL are done and nothing is waiting
  else
    sleep 30; WAITED=$((WAITED + 30))       # fewer than 10 through CUT so far: look again in half a minute
  fi
  [ "$PULL" -ge 200 ] && break
done
echo "   VISION waited $((WAITED / 60)) min in all for jobs to come through CUT"
# jobs he asked to have read again, once: behind every new job
if [ -s data/reread_once.ids ]; then
  step "VISION: read again, once" 0 'grep -v "^  \[" | tail -4' caffeinate -i python3 vision.py --ids "$(cat data/reread_once.ids)" --again
  rm -f data/reread_once.ids; publish
fi
# one cut in ten from this run, read a second time; disagreements go to For Reviewing
step "VISION: second read of rejections" 60 'grep -v "^  \[" | tail -8' caffeinate -i python3 vision.py --audit
publish
step "battery" 10 "head -4" python3 battery.py      # free: reads nothing; updates the TestBattery page
rm -f "$STAT"
NIGHT_END=$(date +%s)
echo "--- night clock"
echo "$SUMMARY" | sed '1d'
cat data/night_pool.clock 2>/dev/null
# Did VISION use the night's tokens? If it never reached the usage limit and
# was reading the whole time, tokens went unspent: three more readers tomorrow.
python3 - "$RUNS_AT_START" "$VISION_WORKERS" <<'PY'
import json, sys
runs = [json.loads(l) for l in open("data/vision_runs.jsonl") if l.strip()][int(sys.argv[1]):]
w = int(sys.argv[2])
pages = sum(r.get("pages_read") or 0 for r in runs)
tokens = sum((r.get("pages_read") or 0) * (r.get("tokens_per_page") or 0) for r in runs)
waited = sum(r.get("waited") or 0 for r in runs)
print(f"VISION tonight: {pages} jobs, {tokens / 1e6:.1f}M tokens, {w} readers, {waited / 60:.0f} min waiting on the usage limit")
if pages >= 2500 and waited == 0 and w < 18:
    open("data/vision_workers", "w").write(str(w + 3))
    print(f"  the limit was never reached with VISION busy all night: {w + 3} readers from tomorrow")
elif waited:
    print("  the limit was reached, so the session's tokens were used; readers stay as they are")
PY
awk -v d="$((NIGHT_END - NIGHT_START))" 'BEGIN { printf "total wall time    %.1f min\n", d / 60 }'
echo "=== done $(date '+%F %H:%M') ==="
