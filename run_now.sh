#!/bin/sh
# The night's steps, by hand, after a night run that did not finish.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
exec >>data/nightly.log 2>&1
echo; echo "=== by hand $(date '+%F %H:%M') ==="
publish() {
  python3 results.py | head -1 | cut -c1-240
  python3 poolparts.py split >/dev/null
  git add data/pool[0-9]*.json data/sources.json data/discovered.json data/results.json data/vision.json data/shipped.json data/vision_runs.jsonl 2>/dev/null
  git diff --cached --quiet || { git commit -q -m "run $(date '+%F %H:%M')

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git push -q && echo "pushed $(date +%H:%M)"; }
}
pkill -f "radar-chrome-" 2>/dev/null; sleep 2
echo "-- scrape";   caffeinate -i python3 pool.py | grep -v "^  \[\|^   *…" | tail -8
echo "-- discover"; caffeinate -i python3 discover.py | tail -3
ATS="ashby,greenhouse,lever,workable,recruitee,teamtailor,smartrecruiters,bamboohr,breezy,join,personio,rippling,pinpoint,jazzhr,manatal"
echo "-- scrape new boards"; caffeinate -i python3 pool.py --only "$ATS" | grep -v "^  \[\|^   *…" | tail -6
echo "-- inbox"; caffeinate -i python3 inbox.py | tail -3
publish
( while sleep 1200; do publish; done ) &
TICK=$!
echo "-- read new";  caffeinate -i python3 vision.py --new | grep -v "^  \[" | tail -8
echo "-- re-read the live lanes under the new rules"; caffeinate -i python3 vision.py --lanes --again | grep -v "^  \[" | tail -8
kill $TICK 2>/dev/null
publish
echo "-- battery"; python3 battery.py | head -6
echo "=== done $(date '+%F %H:%M') ==="
