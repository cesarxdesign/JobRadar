#!/bin/sh
# JobRadar, every night at 02:00 on this Mac (lid open), so the board has
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
step "tabs" 5 cat python3 tabs.py remoteio
# every company board on every hiring system: the list is refreshed weekly,
# and each night the boards that are due get checked for a design role
if [ ! -f data/boards.json ] || [ -n "$(find data/boards.json -mtime +7 2>/dev/null)" ]; then
  step "SOURCE: list links" 60 "tail -24" caffeinate -i python3 harvest.py enumerate
fi
step "SOURCE: check links" 45 "tail -8" caffeinate -i python3 harvest.py check --minutes 40
step "POOL" 150 'grep -v "^  \[\|^   *…" | tail -8' caffeinate -i python3 pool.py
step "SOURCE: discover links" 15 "tail -3" caffeinate -i python3 discover.py
# only the boards discover just added: they have no row in the pool yet. The
# old `--only <every system>` re-scraped all 4,087 boards for the sake of a few.
step "POOL: new links" 30 'grep -v "^  \[\|^   *…" | tail -6' caffeinate -i python3 pool.py --new-boards
# cesarxdesign@gmail.com only (his call, 2026-10-05). inbox_all.py reads the
# other accounts and is run by hand, when he asks.
[ -f inbox.py ] && step "inbox" 10 "tail -3" caffeinate -i python3 inbox.py
# the applying numbers, dates and outcomes only, onto the cxd-stats page
step "stats" 5 "tail -1" python3 stats_export.py
publish
( while sleep 1200; do publish; done ) &
TICK=$!
# no time limit (see above); at most 1000 pages a night, the newest first, and
# vision.py says how many it left for the next night
step "VISION" 0 'grep -v "^  \[" | tail -12' caffeinate -i python3 vision.py --new --limit 1000
kill $TICK 2>/dev/null
# one cut in ten from this run, read a second time; disagreements go to For Reviewing
step "VISION: second read of rejections" 60 'grep -v "^  \[" | tail -8' caffeinate -i python3 vision.py --audit
publish
step "battery" 10 "head -4" python3 battery.py      # free: reads nothing; updates the TestBattery page
rm -f "$STAT"
NIGHT_END=$(date +%s)
echo "--- night clock"
echo "$SUMMARY" | sed '1d'
awk -v d="$((NIGHT_END - NIGHT_START))" 'BEGIN { printf "total wall time    %.1f min\n", d / 60 }'
echo "=== done $(date '+%F %H:%M') ==="
