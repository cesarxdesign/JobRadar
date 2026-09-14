"""results: pool (x) verdicts -> data/results.json

A pure merge. No criteria, no thresholds, no opinions - it only asks the
verdict which lane a role is in and files it there. The board reads this file
and nothing else, so the view never applies criteria of its own.

Cuts are kept, with their reasons. A role the judge rejected stays visible and
recoverable; it is never deleted and never confused with `active`, which only
the pool may set - a role the company took down is a different fact.

    python3 results.py
"""
import datetime
import json
from pathlib import Path

from contracts import DEFAULT_VERDICT, LANES
import contracts

ROOT = Path(__file__).resolve().parent
POOL_FILE = ROOT / "data" / "pool.json"
ORIGINALS_FILE = ROOT / "data" / "originals.json"
LINKS_FILE = ROOT / "data" / "links.json"
VERDICTS_FILE = ROOT / "data" / "verdicts.json"
RESULTS_FILE = ROOT / "data" / "results.json"
JD_FILE = ROOT / "data" / "jd.json"                   # descriptions, keyed by id
HINTS_FILE = ROOT / "data" / "applied_hints.json"     # local only, from match.py
SHIPPED_FILE = ROOT / "data" / "shipped.json"         # every id ever put on the board


# A posting the aggregator still lists, that the employer's own site does not
# have, that is also older than ten weeks, is a ghost. uiuxjobsboard serves
# roles from 2018 - Volkswagen, TUI, Cartrack - and fetcher finds none of them
# at the company. Under ten weeks the same absence proves nothing: plenty of
# real jobs sit on boards fetcher cannot read. So the age and the miss have to
# agree before anything is dropped.
GHOST_DAYS = 69
GHOST_STATUS = ("no_site", "no_match", "unreadable")
# "gone" is not the same claim. The others mean we could not find the role at
# the employer; this means the board's own link is dead - a 404, or a redirect
# onto a listing page. That is direct evidence about this posting, so it drops
# at any age rather than waiting for the ten-week rule.
DEAD_STATUS = ("gone",)


def age_days(rec, today=None):
    p = str(rec.get("posted") or rec.get("first_seen") or "")[:10]
    try:
        d = datetime.date(*map(int, p.split("-")))
    except Exception:
        return None
    return ((today or datetime.date.today()) - d).days


def is_ghost(rec, originals):
    """Old, and not at the employer. Never on a role fetcher has not reached:
    a bot wall or an unrun lookup is missing evidence, not evidence."""
    o = (originals or {}).get(rec["id"])
    if not o:
        return False
    # ghostbuster's answer is about this posting's own link, so it stands on
    # its own at any age. fetcher's misses are about finding the employer,
    # which only means something once the role is old.
    link = o.get("link") or {}
    if link.get("status") in DEAD_STATUS:
        # Whose link died decides what it proves. The employer's own board
        # going 404 is the job being gone, from the only source that would
        # know. An aggregator's copy dying means that board dropped it - the
        # company may still be hiring, and only fetcher can ask. So an
        # aggregator's dead link drops the role only once fetcher has also
        # failed to find it at the employer.
        if link.get("link_of") == "employer":
            return True
        # fetcher's silence is not evidence. It finds the employer 13% of the
        # time, so "I could not find this company's careers page" says
        # something about fetcher and nothing about the job - and trusting it
        # dropped 258 roles, halving the Portugal lane, on nothing.
        return o.get("status") == "gone"
    if o.get("status") in DEAD_STATUS:
        return True          # fetcher saw the employer's page and it was gone
    # The ten-week rule used to drop an old role fetcher could not find at the
    # employer. It is gone: the rule was only ever as good as fetcher, and
    # fetcher is not good. Nothing is dropped now without a posting that
    # actually answered "I am not here" - a 404, or a page saying so.
    return False


def merged_evidence():
    """What fetcher and ghostbuster each concluded, per role, side by side.

    Two files, two different questions - is the role at the employer, and is
    the board's own link alive - so neither may overwrite the other.
    """
    out = json.loads(ORIGINALS_FILE.read_text()) if ORIGINALS_FILE.exists() else {}
    links = json.loads(LINKS_FILE.read_text()) if LINKS_FILE.exists() else {}
    for rid, link in links.items():
        out.setdefault(rid, {})["link"] = link
    return out


def build(pool_doc, verdicts_doc, hints=None, jd=None, originals=None):
    hints = hints or {}
    verdicts = verdicts_doc.get("jobs", {})
    roles, lanes, cut, title_cuts, unjudged = [], {k: [] for k in LANES}, [], 0, 0
    ghosts = 0
    for rec in pool_doc["jobs"]:
        if not rec.get("active"):
            continue
        if is_ghost(rec, originals):
            ghosts += 1
            continue
        v = dict(DEFAULT_VERDICT)
        v.update(verdicts.get(rec["id"], {}))
        if v.get("stage") == "parse":
            title_cuts += 1          # kept, with its reason, in verdicts.json
            continue
        if not v.get("judged"):
            unjudged += 1            # the judge has not reached it yet
            continue
        role = dict(rec)
        role.update({k: x for k, x in (v.get("panel") or {}).items() if x})
        role["verdict"] = v
        roles.append(role)
        if v.get("judged") and v.get("stage") != "parse":
            (cut if v["cut"] else lanes[v["lane"]]).append(rec["id"])
    # The board fetches this file. 47,000 title cuts would make it 25MB for
    # rows no lane shows; they stay in verdicts.json with their reasons.
    # The description of every lane role rides along, so a board served as
    # static files (GitHub Pages) can show it. Cuts keep needing the local
    # server: 2,600 of them would triple the file for rows no tab lists.
    jd = jd or {}
    lane_ids = [i for lane in lanes.values() for i in lane]
    return {
        "jd": {i: jd[i][:14000] for i in lane_ids if jd.get(i)},
        "generated_at": pool_doc.get("generated_at"),
        "run_id": pool_doc.get("run_id"),
        "criteria": verdicts_doc.get("criteria"),
        "model": verdicts_doc.get("model"),
        "counts": {**{k: len(v) for k, v in lanes.items()}, "ghosts": ghosts,
                   "cut": len(cut), "title_cuts": title_cuts, "unjudged": unjudged,
                   "active": sum(1 for r in pool_doc["jobs"] if r.get("active")),
                   "total": len(pool_doc["jobs"])},
        "lanes": lanes,
        "cut": cut,
        "sources": pool_doc.get("sources", {}),
        "roles": roles,
    }


def remember_shipped(built):
    """A role is "seen" once it has stood in one of the three lanes. Cuts are
    shipped so the board can explain them, but no tab shows them, so they are
    not seen and stay eligible for a review batch."""
    before = set(json.loads(SHIPPED_FILE.read_text())) if SHIPPED_FILE.exists() else set()
    now = before | {i for lane in built["lanes"].values() for i in lane}
    tmp = SHIPPED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(now)))
    tmp.replace(SHIPPED_FILE)
    return len(now) - len(before)


def main():
    built = build(contracts.load_pool(POOL_FILE),
                  json.loads(VERDICTS_FILE.read_text()),
                  json.loads(HINTS_FILE.read_text()) if HINTS_FILE.exists() else {},
                  json.loads(JD_FILE.read_text()) if JD_FILE.exists() else {},
                  merged_evidence())
    fresh = remember_shipped(built)
    RESULTS_FILE.write_text(json.dumps(built, indent=1, ensure_ascii=False))
    print(f"wrote {RESULTS_FILE} - {built['counts']}")
    print(f"  {fresh} lane roles he had never been shown before")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
