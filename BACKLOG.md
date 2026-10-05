# JobRadar · backlog

What is next, in the order to do it. An empty backlog means finished, and that is information.

- [ ] TODAY. Nightly, one catch-all. The night run is `nightly.sh`, started by launchd at 02:00
      on this Mac. What is wrong with it as of 2026-10-05:
      - The scrape hung from 02:01 until it was stopped by hand at 10:07 on 2026-10-05. Nothing
        times it out, so one stuck source costs the whole night. Give every step a time limit.
      - `tabs.py` crashed on 2026-10-04 (the AppleScript call to Chrome timed out) and worked on
        2026-10-05. A tab that cannot be read must be skipped, not crash.
      - The harvest step was added on 2026-10-05 and has never run at night. It takes the
        nightly scrape from about 850 boards to 2,136; time it before trusting it.
      - Reading cost has no ceiling in the script: the 2026-10-04 night read 2,929 pages in
        5 hours, $102 at API prices.
      - `.github/workflows/nightly.yml` is the old pool, judge, results run and commits files
        that are no longer in git. Delete it.
      - Confirm launchd fires at 02:00 with the lid open; its last exit was the kill by hand.
- [ ] PRIORITY 2. Make a LinkedIn agent.
- [ ] Scan them all, what is left. Done 2026-10-05: `harvest.py` lists every board from Common
      Crawl's index files and, for Lever, the Internet Archive: 50,364 boards known across 16
      systems, Workable, SmartRecruiters, Rippling, Join and Dover included. Left: 6,643 boards
      not yet checked (mostly the systems that throttle), about 1,825 design-titled roles waiting
      for VISION when work stopped, and Gem, Polymer, Homerun, iCIMS and Jobvite not read at all.
      The night run is paused by `data/PAUSED`; delete that file to resume it.
- [ ] Employer page finder. Vision runs `employer.py` on every board role, and it finds the
      company's own page for 688 of 1,932 (36%). The other 1,244 are read on the board's copy.
