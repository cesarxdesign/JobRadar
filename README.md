# JobRadar

Live at **https://cesar-jobradar.vercel.app** (its own Vercel project; every push to `main`
redeploys it). Also on GitHub Pages at https://cesarxdesign.github.io/JobRadar/.

This is the only version. The first one (called Radar1 in comments here) was the `Radar`
repo; on 2026-09-24 it was merged in with its full history, every commit kept, under
`_archive/radar/`, and the `Radar` repo archived read-only. Every source it scraped is in
`data/sources.json`.

Four modules. Each writes one file. None reaches into another.

    pool.py      the internet      -> data/pool.json      every role found, no opinions
    judge.py     data/pool.json    -> data/verdicts.json  criteria. the only opinions
    results.py   pool x verdicts   -> data/results.json   three lanes, cuts kept
    index.html   data/results.json                        renders. decides nothing

    RadarRouting.json   on the Desktop, never in this repo. applied/discarded.

## The lanes

Two independent axes, and a lane is a function of both:

    role   is this a role for him?         yes | no | unclear
    place  can he take it, from Portugal?  remote | pt_onsite | no | unclear

    Open      role yes + place remote      a role for him he can do remotely
    Portugal  role yes + place pt_onsite   a role for him, in Portugal, not remote
    Unsure    neither axis says no, but at least one is not clear
    cut       either axis says no          kept, with a reason. never deleted

Unsure is deliberately generous: it means "we cannot say it isn't", not "we
think probably not". Only explicit negative evidence cuts.

## Rules Radar1 broke

- `cut` is not `active`. A role the judge rejected and a role the company took
  down are different facts. Only the pool may set `active`.
- Ids are minted once, on first sight, and never recomputed. Radar1 rebuilt
  `sha1(company|title)` every run, so a retitle minted a second role and
  orphaned the decision pointing at the first.
- The pool persists the evidence the judge reasons over. Radar1 did not, so
  the judge could not be re-run from the pool - which is why `rejudge.py` had
  to exist.
- The view holds no criteria. Radar1's `index.html` decided lanes itself.

## Run

    python3 pool.py && python3 judge.py && python3 results.py
    python3 -m http.server 8123     # then open http://localhost:8123

The board needs Chrome for RadarRouting: writing back to a file on the
Desktop needs the File System Access API, which Safari does not have.
