# JobRadar

Live at **https://cesarxdesign.github.io/JobRadar/** on GitHub Pages; every push to `main`
redeploys it. (It was also on Vercel until 2026-09-25; that project is deleted.)

This is the only version. The first one (called Radar1 in comments here) was the `Radar`
repo; on 2026-09-24 it was merged in with its full history, every commit kept, under
`_archive/radar/`, and the `Radar` repo archived read-only. Every link it POOLed is in
SOURCE, `data/sources.json`.

## What it is for

Getting a job. Everything else is judged against this chain:

    a job           needs interviews
    interviews      need applications that get called back
    applications    need roles, found and shown
    roles           are only worth showing if he can apply to them, so the criteria must be right

He applies to every role that fits. A company's Staff, Senior and Lead postings are three
jobs and three applications. So an application matches one posting or none: a similar title
at the same company is not a match, and a role that is not certainly applied to stays live.
A role shown twice costs a glance. A role wrongly hidden costs an application.

Five words name the pipeline, and the logs and the board use no others for these:

    SOURCE   the file of links (company hiring boards, job boards) that says where the jobs are
    POOL     going through SOURCE and getting every job from every link
    CUT      the quick pass on POOL that drops jobs by title alone
    VISION   reads what survives CUT on its real page and passes a job or rejects it
    RESULTS  only the jobs fit for him, with a level of confidence

Four modules. Each writes one file. None reaches into another.

    pool.py      SOURCE            -> data/pool.json      POOL: every role found, no opinions
    judge.py     data/pool.json    -> data/verdicts.json  criteria. the only opinions (CUT is its title pass)
    results.py   pool x verdicts   -> data/results.json   RESULTS: three lanes, rejections kept
    index.html   data/results.json                        renders. decides nothing

VISION (`vision.py`) reads what survives CUT and writes `data/vision.json`; its second read of
a tenth of its rejections is the audit. SOURCE is kept up to date by `harvest.py` and `discover.py`.

    RadarRouting.json   on the Desktop, never in this repo. applied/discarded.

## The lanes

Two independent axes, and a lane is a function of both:

    role   is this a role for him?         yes | no | unclear
    place  can he take it, from Portugal?  remote | pt_onsite | no | unclear

    Open      role yes + place remote      a role for him he can do remotely
    Portugal  role yes + place pt_onsite   a role for him, in Portugal, not remote
    Unsure    neither axis says no, but at least one is not clear
    cut       either axis says no          kept, with a reason. never deleted
              (the stored lane name; CUT is the title pass, VISION rejects)

Unsure is deliberately generous: it means "we cannot say it isn't", not "we
think probably not". Only explicit negative evidence cuts or rejects.

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
