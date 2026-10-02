"""backup_rr: ~/Desktop/RadarRouting.json -> the PRIVATE repo cesarxdesign/RadarRouting

The routing file is the one thing here that cannot be rebuilt: it was lost
once (2026-09) and took every decision with it. JobRadar is a public repo, so
the file never goes in it. It goes in its own private repo, checked out at
~/Claude/RadarRouting, one commit per change, so every past state is kept.

    python3 backup_rr.py        # copy, commit, push. Does nothing if unchanged.
"""
import json, os, shutil, subprocess, sys

RR = os.path.expanduser("~/Desktop/RadarRouting.json")
REPO = os.path.expanduser("~/Claude/RadarRouting")


def git(*a):
    return subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True)


def main():
    if not os.path.exists(RR):
        sys.exit("no " + RR)
    if not os.path.isdir(REPO + "/.git"):
        sys.exit("no private repo at " + REPO)
    d = json.load(open(RR))                     # a half-written file must not replace a good backup
    if not isinstance(d.get("decisions"), list):
        sys.exit("not a routing file")
    shutil.copy(RR, REPO + "/RadarRouting.json")
    git("add", "RadarRouting.json")
    if git("diff", "--cached", "--quiet").returncode == 0:
        print("routing file unchanged, nothing to back up")
        return
    msg = "%d decisions, %d applications, %d milestones" % (
        len(d["decisions"]), len(d.get("applications") or []), len(d.get("milestones") or []))
    git("commit", "-m", msg)
    p = git("push")
    print("backed up: " + msg if p.returncode == 0 else "committed locally, PUSH FAILED: " + p.stderr.strip())


if __name__ == "__main__":
    main()
