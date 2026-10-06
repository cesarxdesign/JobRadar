#!/bin/sh
# SOURCE, all day: every link opened every day, however long that takes.
# His call, 2026-10-06: "if it takes a whole day to check, we make it a
# continuous check. We need to check every day." It opens every link not yet
# opened today, hands the ones with a design job to POOL, and starts again;
# after midnight every link is due once more. No tokens: plain web requests.
# One copy only. The night run leaves its own check out while this is alive.
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
[ "$(pgrep -f 'source_loop.sh' | wc -l)" -gt 2 ] && { echo "source_loop: already running"; exit 0; }
exec >>data/source_loop.log 2>&1
while :; do
  echo "=== SOURCE pass $(date '+%F %H:%M') ==="
  T0=$(date +%s)
  python3 harvest.py check | tail -3 | cut -c1-200
  echo "pass took $(( ($(date +%s) - T0) / 60 )) min"
  # the links that just turned out to have a design job, into POOL (unless POOL is busy; it will pick them up itself)
  pgrep -f "pool.py" >/dev/null || python3 pool.py --new-boards 2>&1 | grep -v "^  \[\|^   *…" | tail -2 | cut -c1-200
  # nothing left to open today: wait, then look again (a new day makes every link due)
  [ $(( $(date +%s) - T0 )) -lt 300 ] && sleep 900
done
