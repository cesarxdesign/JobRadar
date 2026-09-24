# Done, archived from BACKLOG.md

## Archived 2026-09-15

## From the LinkedIn screenshot sweep, 2026-09-10
- [x] **Review and test the sources in `sweep.md`.** Done 2026-09-11: eleven boards added as
      aggregators, 238 company boards added (233 harvested from superjobs.design's company list),
      six written off with reasons, all recorded in `sweep.md`. Still in `sweep.md` for César: the
      seven leads, the pay-band note.
## Import before archiving `_archive/v1`
- [x] **Decision history, and the broken path it caused.** `_archive/history.json` (185 decisions,
      68 applied, 117 discarded) and `_archive/applications.json` (135 Gmail-proven applications,
      labelled "ground truth for L2 recall testing, L2 must not CUT any of these"). current's own
      `applied_history.json` carried only 51. Both files copied into `current/data/` and the three stale
      `~/Claude/radar/` references in `testl2.py` and `match.py` repointed. **Done 2026-09-08**
- [x] **`workingnomads` added to `sources.json`.** The adapter existed in `pool.py` but the name was
      missing from the list `scrape()` iterates, so it was never polled. 2026-09-08
- [x] **17 boards restored.** They were in v1's watchlist and absent from current. César's call: a
      board going blank usually means the company moved ATS provider, and checking costs almost
      nothing on a run that already polls 584 boards, so keep them. Greenhouse: Duolingo, Sword
      Health, Webflow, Elastic, Grafana Labs, Typeform, Contentful, Automattic. Lever: BlaBlaCar,
      Pipedrive. Ashby: PostHog, Raycast, Deel, Zapier, Back Market, Bolt, Spendesk. 2026-09-08
## Projects, not tasks
- [x] **Extract CvTuner.** Done 2026-09-08. It is now its own project at `~/Claude/CV-Tuner`.
      Not a fork, one iterated tool. See `CV-Tuner/README.md`
## Housekeeping

- [x] **Killed the launchd job.** 2026-09-08. One job existed, `com.cesar.jobradar.nightcv`, daily at
      07:00, calling `nightcv.py` at the old pre-move path. Booted out and its plist deleted. No tcv or
      tune job existed, and there was no crontab. Radar does not run daily, so it needs no cron
- [x] Test TCVS against MCV. Done: CV-Tuner's `.cvcheck` harness ran it across 51 tuned CVs

## Killed 2026-09-15

- ~~killed~~ **pool.json will hit GitHub's 100MB limit one day.** 82MB at 102k roles, 822 bytes a role.
      César's call 2026-09-12: leave it as one file until it is an actual problem. pool.py now
      prints a warning above 95MB. When it fires: shard into pool-N.json files of 60k roles with a
      load_pool() helper (keeps the cloud able to run), or stop tracking it (the board only needs
      results.json).
- ~~killed~~ **Nine boards answer 404.** ashby mach, intangible, jimdo, taxfix; greenhouse clickhouse,
      deepmind; lever pnlfin, quadcode, usmobile; freshteam a5labs; personio digital-growth-studio,
      peratera; comeet mwdn. Kept per César's rule (a blank board usually means a moved ATS), but
      worth a slug hunt.
- ~~killed~~ **`belongs_to()`, the wrong-page guard.** Uncommitted in `v1/nightjudge.py`, refined as
      `is_this_role()` in untracked `v1/parser.py`. Checks a fetched page contains 60%+ of the role
      title's words before judging on it. The comment records the bug it fixes: "Mayflower" resolved
      to a cruise company and a real design job was cut. `current/deep.py` trusts whatever HTML comes
      back. About 20 lines
- ~~killed~~ **`wp_norm()`, workplace aliases.** v1 normalised `fullyremote`, `anywhere`, `telecommute`,
      `in-office`, `on-location`. current's `normalise()` only matches exact `remote`/`onsite`/`hybrid`.
      **Relevant to the remote-filter bug below**
- ~~killed~~ **The judge prompt line v2 lost:** "IF A WORKPLACE TYPE IS GIVEN, IT IS THE ANSWER, it outranks
      the location string". Absent from `current/criteria.py`. **Also relevant to the remote-filter bug**
- ~~killed~~ **`JUNIOR` regex coverage.** v1 caught ~15 terms current's `L1_JUNIOR` misses: jnr, mid-level,
      midweight, intermediate, praktikum, werkstudent, alternance, estágio, becario. Plus a salary
      override keeping a "junior" title paying over 100k
- ~~killed~~ **`data/email_raw.json`.** 197 emails with full bodies, extracted links and platform. v2's
      `emails.json` keeps snippets only, and the links are how a confirmation resolves to a posting
- ~~killed~~ Fix the remote filter. Two of the import items above are direct causes
- ~~killed~~ Fix the UX filter
- ~~killed~~ Review sources, and the CV workings
- ~~killed~~ Test the morning run
- ~~killed~~ Test TCV integration
- ~~killed~~ Add x.com as a source
- ~~killed~~ Benchmark coverage against Remote Rocketship
- ~~killed~~ Parse email for applications versus rejections, confirm Radar caught those jobs
- ~~killed~~ **Retire `_archive/v1`**, once the import list above is empty
