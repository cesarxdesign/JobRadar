# JobRadar · backlog

What is next, in the order to do it. An empty backlog means finished, and that is information.

## Next

- [ ] Scan them all: list every company board on every hiring system (Ashby, Greenhouse, Lever,
      Workable, Dover and the rest) from a public web index, instead of finding companies one
      by one through job boards. A first probe of Common Crawl listed 272 Ashby boards on one
      page of one snapshot; we scrape 549 today. Add the hiring systems not yet read (Dover, Gem,
      Polymer, Homerun, iCIMS, Jobvite...). Title cut is free, so the scrape can be wide; the
      reading cost is what to measure first.
- [ ] Make a LinkedIn agent.
- [ ] Add Principal Designer as a role.
- [ ] Move Stats into cxd-stats, so applications sent can be read against folio traffic.
- [ ] Night run reads the Gmail and remote.io tabs from the scheduler reliably (worked on 2026-10-05; failed on 2026-10-04).
- [ ] Employer page finder: most board-only roles still do not get their company's own page.

## Done, kept for the record

## 1. RadarRouting: rebuild the lost file

- [x] Email sweep: `sweep.py` rebuilds the routing file from the inbox, one application to one posting.
- [x] Stats tab on the board, shown only while the routing file is attached.
- [x] Backup of the routing file to its own private repo, by hand (`backup_rr.py`).
- [ ] Make the sweep repeatable without a Claude session reading every thread.

## 2. Judge: measure it, then fix it

- [ ] Find out whether the checking still works: run `regress.py` on the four fixtures (batch1, batch2, batchA, batchB; 154 reviewed roles) and `testl2.py applied` / `testl2.py emails`. `test_applied.json` and `test_emails.json` are gitignored and may be gone with the routing file.
- [ ] Write down what "shit" means with examples: wrong roles in Open, good roles cut, or wrong place. Draw a fresh batch (`batch.py`) and mark it in `review.html`.
- [ ] Fix `criteria.py` against those examples (current version 2026-09-03.1) and re-run the fixtures until nothing regresses.
- [ ] Test a stronger model: the judge runs on haiku (`RADAR_MODEL` in `read.py`). Compare haiku vs sonnet on the fixtures before paying for a full re-judge of 4,856 roles.

## 3. Fetcher and ghostbuster

- [ ] Fetcher: `data/originals.json` does not exist, so results has no employer postings to check dates and remoteness against. Run it on the Open lane only, see what breaks, fix or cut it.
- [ ] Ghostbuster: `data/links.json` does not exist and the last run reports 0 ghosts out of 85,762 active roles. Run it on the three lanes and see whether it finds dead postings.
- [ ] Decide whether either belongs in the nightly run, or runs only on the ~500 roles that survive the judge.

## 4. Nightly run

- [ ] Last run was 2026-09-25, by hand. Dispatch the GitHub Action once manually and confirm it finishes inside the 300-minute limit and commits.
- [ ] Check the `CLAUDE_CODE_OAUTH_TOKEN` secret is still valid.
- [ ] Re-arm the schedule (`cron: "0 22 * * *"` in `.github/workflows/nightly.yml`) once the judge is trusted.

## Housekeeping

- [ ] Confirm the Sep 12 sources.json is still the latest: 839 companies across 20 ATS platforms, 26 aggregators, 282 company sites.
- [ ] Commit the recovered files: SOURCE_SWEEP.md, relay.html, data/applied_history.md, emails_bodies_0-5, _archive/.
- [ ] Decide whether the generated data (pool.json 52M, verdicts.json 29M, reads.json 10M) stays committed or gets gitignored.
