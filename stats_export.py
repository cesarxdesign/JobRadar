"""stats_export: ~/Desktop/RadarRouting.json -> cxd-stats/public/data/radar.json

The applying numbers are shown on the cxd-stats page, beside the site visits.
That page is at a public address, so what goes there is dates and outcomes
only: no company, no role, no mail thread. Those stay in the routing file and
on the board's Applications tab.

An application is proven by an email (applications, written by sweep.py) or
by an "applied" click on the board that no email covers. A callback is a
person asking to talk or asking a question; a test sent to every applicant
(auto) is not one.

    python3 stats_export.py     # write, commit, push. Does nothing if unchanged.
"""
import json, os, subprocess, sys
from datetime import datetime, timezone

RR = os.path.expanduser("~/Desktop/RadarRouting.json")
REPO = os.path.expanduser("~/Claude/cxd-stats")
OUT = REPO + "/public/data/radar.json"


def git(*a):
    return subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True)


def build(d):
    apps = []
    for a in d.get("applications") or []:
        real = sorted(c["date"] for c in a.get("callbacks") or [] if not c.get("auto") and c.get("date"))
        apps.append({"applied": a.get("applied"), "approx": bool(a.get("approx")),
                     "callback": real[0] if real else None,
                     "rejected": a.get("rejected"), "withdrawn": a.get("withdrawn")})
    covered = {i for a in d.get("applications") or [] for i in a.get("role_ids") or []}
    for x in d["decisions"]:
        if x.get("decision") == "applied" and x["id"] not in covered:
            apps.append({"applied": str(x.get("at") or "")[:10] or None, "approx": False,
                         "callback": None, "rejected": None, "withdrawn": None})
    apps.sort(key=lambda a: (a["applied"] or "", a["callback"] or "", a["rejected"] or ""), reverse=True)
    return {"applications": apps,
            "inbound": sorted(str(i.get("date") or "") for i in d.get("inbound") or []),
            "milestones": sorted(({"date": m["date"], "kind": m.get("kind"), "label": m["label"]}
                                  for m in d.get("milestones") or []), key=lambda m: m["date"])}


def main():
    if not os.path.exists(RR):
        sys.exit("no " + RR)
    if not os.path.isdir(REPO + "/.git"):
        sys.exit("no cxd-stats repo at " + REPO)
    d = json.load(open(RR))
    if not isinstance(d.get("decisions"), list):
        sys.exit("not a routing file")
    new = build(d)
    try:
        old = json.load(open(OUT))
        old.pop("generated_at", None)
    except Exception:
        old = None
    if old != new:
        new = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **new}
        json.dump(new, open(OUT, "w"), indent=1, ensure_ascii=False)
    if "--no-push" in sys.argv:
        print("written, not committed" if old != new else "applying stats unchanged")
        return
    git("add", "public/data/radar.json")         # also picks up a file an earlier --no-push run left
    if git("diff", "--cached", "--quiet").returncode == 0:
        print("applying stats unchanged, nothing to export")
        return
    n = json.load(open(OUT))
    msg = "radar: %d applications, %d milestones" % (len(n["applications"]), len(n["milestones"]))
    git("commit", "-m", msg, "--", "public/data/radar.json")
    git("pull", "--rebase", "--autostash", "-q")  # the daily snapshot Action commits to the same branch
    p = git("push")
    print("exported: " + msg if p.returncode == 0 else "committed locally, PUSH FAILED: " + p.stderr.strip())


if __name__ == "__main__":
    main()
