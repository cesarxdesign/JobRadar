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
if pgrep -f "vision.py" >/dev/null; then echo "a run is already going; leaving it alone"; exit 0; fi

publish() {
  python3 results.py | head -1 | cut -c1-240
  git add data/pool.json data/sources.json data/discovered.json data/results.json data/vision.json \
          data/shipped.json data/vision_runs.jsonl 2>/dev/null
  git diff --cached --quiet || { git commit -q -m "nightly $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
}

ATS="ashby,greenhouse,lever,workable,recruitee,teamtailor,smartrecruiters,bamboohr,breezy,join,personio,rippling,pinpoint,jazzhr,manatal"

# Radar's own hidden Chrome, left over from a stopped run, answers AppleScript
# in place of his: with one alive, the script reads the wrong browser's tabs.
pkill -f "radar-chrome-" 2>/dev/null; sleep 2
echo "-- his tabs";          python3 tabs.py remoteio
echo "-- scrape";            caffeinate -i python3 pool.py | tail -6
echo "-- discover";          caffeinate -i python3 discover.py | tail -3
echo "-- scrape new boards"; caffeinate -i python3 pool.py --only "$ATS" | tail -4
[ -f inbox.py ] && { echo "-- inbox"; caffeinate -i python3 inbox.py | tail -3; }
publish
( while sleep 1200; do publish; done ) &
TICK=$!
echo "-- read"; caffeinate -i python3 vision.py --new | grep -v "^  \[" | tail -12
kill $TICK 2>/dev/null
publish
echo "=== done $(date '+%F %H:%M') ==="
