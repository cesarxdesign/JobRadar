# JobRadar · backlog

What is next, in the order to do it. An empty backlog means finished, and that is information.

Inventory taken 2026-10-06, every line checked against the code and the data that morning.
Goal for the day: clear A and B so the 02:00 night run goes end to end and can be clocked.

## A. The night run itself (`nightly.sh`, launchd, 02:00)

- [ ] A1. It is paused. `data/PAUSED` makes `nightly.sh` exit at once. Delete the file to arm it.
- [ ] A2. It has never run end to end with today's sources. The last night that started (2026-10-05
      02:01) hung in the scrape until it was stopped by hand at 10:07. Since then `pool.py` gives
      each job board 25 minutes (`SOURCE_LIMIT`), but company boards and the other steps (tabs,
      discover, inbox) have no limit, and this Mac has no `timeout` command. Give every step one.
- [ ] A3. The second scrape reads everything twice. `pool.py --only "$ATS"` after discover scrapes
      all 4,087 company boards again, not the handful discover just added. Use `--new-boards`.
- [ ] A4. No ceiling on a night's reading. `vision.py` stops when one page costs over 12,000 tokens,
      but nothing caps the pages in a night: 2,929 pages on 2026-10-04. Add a cap per night.
- [ ] A5. Nothing clocks the run. The log has a start and an end and no time per step. Print the
      time and the tokens of each step, so the first full night gives real numbers.
- [ ] A6. The full scrape is unproven at this size: 4,087 boards and 31 job boards, against about
      600 the last time a full scrape finished. Run it once by day (no tokens) before the night.
- [ ] A7. `.github/workflows/nightly.yml` is the old pool, judge, results run. It is manual-only
      and commits files that are no longer in git. Delete it.
- [ ] A8. `tabs.py` lets an AppleScript timeout escape as a traceback (2026-10-04). The night
      carries on, but a tab that cannot be read should be one log line.
- [ ] A9. Confirm launchd fires with the lid open. It is loaded (`com.cesarxdesign.jobradar`,
      02:00, last exit 0), and the 2026-10-06 firing did reach the PAUSED check.

## B. Data owed before a clean night

- [ ] B1. Full POOL scrape. The last one was 2026-10-05 13:53; everything since was partial. The
      3,200 boards the harvest added were each read once and never refreshed. Same run as A6.
- [ ] B2. 253 boards on the nightly list have no row in the POOL. Some are dead (404); the rest
      include the 46 boards the last check added. B1 reads them; drop the ones that stay dead.
- [ ] B3. 5,090 boards never checked for a design role: Workable 2,328, BambooHR 1,159, Ashby 485,
      Greenhouse 396, Personio 227, Manatal 160. No tokens, hours of waiting on throttled systems.
      The night gives the check 40 minutes, so left to the night this takes more than a week.
- [ ] B4. Whatever B1 to B3 find goes to VISION, about 7,000 tokens a role. Read it by day, or
      the first clocked night is a catch-up night and its numbers mean nothing.
- [ ] B5. 4,666 active rejections were read on 2026-10-02 and 2026-10-03, before the rules were
      rewritten on 2026-10-05. Only the live lanes were read again. Reading all of them again is
      about 33M tokens; the audit has read about one in ten. Decide: all, a sample, or leave.
- [ ] B6. Five roles still carry an old-judge verdict (non-design titles, e.g. "Commercial Account
      Executive, EMEA" at Gong). They fail CUT today and should leave the board's data.

## C. Waiting on him

- [ ] C1. For Reviewing: 8 roles, 7 of them rejections the audit disagreed with.
- [ ] C2. Unsure: 94, up from 57. 67 of them came in with the harvest. 80 are "design role, place
      unclear": 30 name a list of countries, 20 have a page that says both, 30 other.
- [ ] C3. Battery: 130 known answers, 1 where the filter disagrees with him.
- [ ] C4. The live page. GitHub Actions was down on the night of 2026-10-05 and Pages did not
      deploy. He checks it and says when; nothing here polls it.
- [ ] C5. Went with the 2026-10-05 layout: search box, reload button, Stats tab with its milestone
      editor. The code behind them is still in `index.html`. Bring back, or delete the code.

## D. Later, not today

- [ ] D1. Make a LinkedIn agent (priority 2 in `~/Claude/BACKLOG.md`).
- [ ] D2. Names: POOL, CUT, VISION are agreed but not yet in the code, the board or the logs, and
      the later steps (audit, results, battery, sweep) have no names yet.
- [ ] D3. Employer page finder. Of 2,124 active roles that came from a job board, VISION read the
      employer's own page for 994 (47%) and the board's copy for 1,130.
- [ ] D4. Hiring systems not read at all: Gem, Polymer, Homerun, iCIMS, Jobvite.
- [ ] D5. "Add Principal Designer as role": meaning not yet clarified.
- [ ] D6. Loose files in `data/`: `reread_rules.txt`, `rr_from_page.json` (untracked), and the old
      pipeline's `verdicts.json`, `reads.json`, `batch.json`, `review*.json`.
