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
if pgrep -f "vision.py" >/dev/null || pgrep -f "stream.sh" >/dev/null; then echo "a run is already going; leaving it alone"; exit 0; fi

publish() {
  python3 results.py | head -1 | cut -c1-240
  python3 poolparts.py split >/dev/null
  git add data/boards.json data/pool[0-9]*.json data/sources.json data/discovered.json data/results.json data/vision.json \
          data/shipped.json data/vision_runs.jsonl 2>/dev/null
  git diff --cached --quiet || { git commit -q -m "nightly $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
}

ATS="ashby,greenhouse,lever,workable,recruitee,teamtailor,smartrecruiters,bamboohr,breezy,join,personio,rippling,pinpoint,jazzhr,manatal"

# Radar's own hidden Chrome, left over from a stopped run, answers AppleScript
# in place of his: with one alive, the script reads the wrong browser's tabs.
pkill -f "radar-chrome-" 2>/dev/null; sleep 2
echo "-- his tabs";          python3 tabs.py remoteio
# every company board on every hiring system: the list is refreshed weekly,
# and each night the boards that are due get checked for a design role
if [ ! -f data/boards.json ] || [ -n "$(find data/boards.json -mtime +7 2>/dev/null)" ]; then
  echo "-- harvest: list";   caffeinate -i python3 harvest.py enumerate | tail -24
fi
echo "-- harvest: check";    caffeinate -i python3 harvest.py check --minutes 40 | tail -8
echo "-- scrape";            caffeinate -i python3 pool.py | grep -v "^  \[\|^   *…" | tail -8
echo "-- discover";          caffeinate -i python3 discover.py | tail -3
echo "-- scrape new boards"; caffeinate -i python3 pool.py --only "$ATS" | grep -v "^  \[\|^   *…" | tail -6
# cesarxdesign@gmail.com only (his call, 2026-10-05). inbox_all.py reads the
# other accounts and is run by hand, when he asks.
[ -f inbox.py ] && { echo "-- inbox"; caffeinate -i python3 inbox.py | tail -3; }
publish
( while sleep 1200; do publish; done ) &
TICK=$!
echo "-- read"; caffeinate -i python3 vision.py --new | grep -v "^  \[" | tail -12
kill $TICK 2>/dev/null
# one cut in ten from this run, read a second time; disagreements go to For Reviewing
echo "-- audit"; caffeinate -i python3 vision.py --audit | grep -v "^  \[" | tail -8
publish
echo "-- battery"; python3 battery.py | head -4      # free: reads nothing; updates the TestBattery page
echo "=== done $(date '+%F %H:%M') ==="
