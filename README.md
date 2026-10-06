# JobRadar

Live at **https://cesarxdesign.github.io/JobRadar/** on GitHub Pages; every push to `main`
redeploys it. (It was also on Vercel until 2026-09-25; that project is deleted.)

This is the only version. The first one (called Radar1 in comments here) was the `Radar`
repo; on 2026-09-24 it was merged in with its full history, every commit kept, under
`_archive/radar/`, and the `Radar` repo archived read-only. Every link it POOLed is in
SOURCE, `data/sources.json`.

## What it is for

Read this before changing anything. It is the owner's own account (2026-10-06).

1. The goal is to **find a job**. Not to run a service.
2. To find it he has to **apply a lot**. He applies to every role that fits.
3. To apply a lot he needs **options**.
4. Options come from looking everywhere: **every board, link and source there is**, checked
   **every day**. The biggest POOL possible. A company may hire for design once a year, and
   that day has to be caught.
5. Reading a job properly (VISION) costs **tokens, and tokens are limited per 5-hour session**.
   That is the only scarce thing here.

So the rules for anyone, person or agent, working on this:

- **Never look at less.** No resting links, no dropping links, no trimming SOURCE or POOL to
  save run time or traffic. Go faster or wider instead.
- **Anything that costs no tokens runs now, and in parallel.** Opening links, POOL, CUT,
  adding sources. Never queue it behind something else.
- **VISION is the bottleneck and must never idle while a session has tokens.** It starts in
  the first minute and is fed in rounds; when the limit hits, it waits for the reset and goes on.
- **Tokens go where they produce options.** CUT removes what he has ruled out before VISION
  sees it: non-design titles, intern and unpaid roles, and anything neither posted nor
  updated in 45 days.
- **The costly mistake is a job he could have applied to and never saw.** A wrong job shown
  costs him a glance.

The five words: **SOURCE** (the links that say where jobs are) → **POOL** (every job from
every link) → **CUT** (quick, on title and age) → **VISION** (reads what is left, on its real
page) → **RESULTS** (the jobs that fit him).

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
