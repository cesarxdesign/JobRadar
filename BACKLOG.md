# JobRadar · backlog

What is next, in the order to do it. An empty backlog means finished, and that is information.
Why any of it matters is at the top of `README.md`: read that first.

State on 2026-10-06, 13:16. Every line checked against the code and the data.

## Running or scheduled today

- [ ] SOURCE: the Internet Archive lookup for every system, adding names (about 62,000 new). Then
      those links are opened and the ones with a design job go to POOL. No tokens.
- [ ] SOURCE: every link opened today. 49,000 of 50,459 done; a second pass takes the Archive names.
- [ ] SOURCE: new hiring systems, a worker on branch `more-systems`: Workday first, then Gem,
      Polymer, Homerun, Jobvite, iCIMS, Trakstar, Recruiterbox, Paylocity, and the harder ones.
      To check on the Mac and merge when it reports.
- [ ] VISION, 14:13: the 517 old-rule rejections posted or updated in the last 30 days, read
      again under the current rules. A one-off; 45 days is the standing rule.
- [ ] The run (`sh nightly.sh`) has not been run for real in its new shape. The scheduled start is switched off: he triggers it himself this week.
      VISION pulling from the queue from the first second (501 jobs waiting now). Read the log
      in the morning: the clock per step, tokens, and whether the usage limit was reached.

## Next

- [ ] SOURCE: more job boards. Not started; needs a worker, so it spends tokens. By night, or
      when he says.
- [ ] SOURCE by day: the no-token part (open links, POOL, CUT) on a schedule through the day, so
      the queue is full when the night starts. Today it was run by hand. `source_loop.sh` exists
      and is parked; a run by day needs an entry in launchd.
- [ ] After the first night: if VISION never reached the usage limit, the script adds readers by
      itself (`data/vision_workers`). Check that it did the right thing.
- [ ] Dates: Rippling and JazzHR jobs carry no date (shown as "?", at the bottom of the list).
      Look for one on the job's own page, as was done for BambooHR.
- [ ] Employer page finder: about half the jobs that come from a job board are read on the
      board's copy, not the employer's page.
- [ ] Make a LinkedIn agent (priority 2 in `~/Claude/BACKLOG.md`).

## His, whenever

- [ ] For Reviewing: jobs where VISION's second read disagreed with the first.
- [ ] "Add Principal Designer as role": meaning not yet clarified.
