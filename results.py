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
import re
from pathlib import Path

from contracts import DEFAULT_VERDICT, LANES
import contracts
import judge
import criteria

ROOT = Path(__file__).resolve().parent
POOL_FILE = ROOT / "data" / "pool.json"
ORIGINALS_FILE = ROOT / "data" / "originals.json"
LINKS_FILE = ROOT / "data" / "links.json"
VERDICTS_FILE = ROOT / "data" / "verdicts.json"
RESULTS_FILE = ROOT / "data" / "results.json"
JD_FILE = ROOT / "data" / "jd.json"                   # descriptions, keyed by id
VISION_FILE = ROOT / "data" / "vision.json"           # the page, read in a browser
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


# The page wins on place. When a role's Location line names somewhere that is
# not Portugal, Europe, the EU, EMEA or worldwide, the role is remote WITHIN
# that place - "Remote" beside "United States" means the US. The judge kept
# reading the word "remote" and calling it worldwide: 157 of 575 Open roles
# were restricted to Paris, London, Berlin, the US, and 18 copies of one
# Jobgether posting were the same job listed once per country.
# This reads the rendered Location line, which is exactly what a person
# reads, and needs no model to do it.
PLACE_OK = re.compile(r"portugal|lisbon|lisboa|porto|europe|\beu\b|emea|worldwide|"
                      r"anywhere|global|international", re.I)
PLACE_BARE = re.compile(r"^\s*(remote|remote job|fully remote|100% remote)?\s*$", re.I)


def placed_elsewhere(rec):
    loc = str(rec.get("location") or "")
    return not PLACE_BARE.match(loc) and not PLACE_OK.search(loc)


def from_vision(v):
    """A vision verdict in the shape the board already draws. Where vision has
    read the page, its answer is the verdict: the old judge read a copy."""
    why = [v.get("reason")]
    sig = [x for x in v.get("place_signals") or [] if isinstance(x, dict) and x.get("says") != "says_nothing"]
    for x in sig:
        why.append(("Portugal in" if x.get("says") == "portugal_in" else "Portugal OUT") + " · " + str(x.get("where"))
                   + ': "' + str(x.get("quote")) + '"')
    if v.get("place_quote") and not sig:
        why.append('the page says: "' + v["place_quote"] + '"')
    if v.get("open_quote"):
        why.append('the page says: "' + str(v["open_quote"]) + '"')
    emp, board = v.get("employer") or {}, v.get("board") or {}
    return {"role": v.get("role_verdict"), "place": v.get("place_verdict"), "lane": v.get("lane"),
            "cut": v.get("lane") == "cut", "why": [w for w in why if w], "judged": True,
            "text": "employer's page" if v.get("read") == "employer" else "job board's copy",
            "stage": "vision", "confidence": v.get("confidence"), "fields": v.get("fields") or {},
            "inferred": v.get("inferred") or [], "read": v.get("read"), "read_url": v.get("read_url"),
            # for the box at the top of the preview: which of the two questions it failed, and the words
            "reason": v.get("reason"), "open": v.get("posting_open"), "language_ok": v.get("language_ok"),
            "language": v.get("language_of_the_posting"), "quote": v.get("place_quote"),
            "signals": [x for x in v.get("place_signals") or [] if isinstance(x, dict) and x.get("says") != "says_nothing"],
            "if_employer": v.get("lane_if_employer"), "found_by": v.get("found_by"),
            "shot": emp.get("shot") or board.get("shot"), "read_at": v.get("at")}


CO_JUNK = re.compile(r"\b(app|inc|llc|ltd|gmbh|labs|foundation|bank|ai|careers|group|the|technologies|software)\b", re.I)


def job_key(role):
    """One job, however many times it is listed: the company and the title's words."""
    v = role.get("verdict") or {}
    co = (v.get("fields") or {}).get("company") or role.get("company") or ""
    co = re.sub(r"[^a-z0-9]", "", CO_JUNK.sub(" ", co.lower()))
    title = re.sub(r"\([^)]*\)", " ", (role.get("title") or "").lower())       # (Remote), (m/f/d), (Spain)
    return co, " ".join(re.findall(r"[a-z0-9]+", title))


def fold(lanes, by_id):
    """Show a job once.

    The same job reaches the board several ways: through two or three job
    boards and the employer's own page, or as one posting per country. He
    wants one card. Which one:
      - the copy that is for Portugal, when the copies differ by place;
      - else the one read on the employer's own page;
      - else the most recently posted.
    The others are not shown as cards. They ride on the one that is, so the
    preview can list them with their links.
    """
    groups = {}
    for lane, ids in lanes.items():
        for i in ids:
            groups.setdefault(job_key(by_id[i]), []).append(i)
    order = {"portugal": 0, "open": 1, "unsure": 2}
    folded = 0
    for key, ids in groups.items():
        if len(ids) < 2 or not key[0] or not key[1]:
            continue

        def rank(i):
            r, v = by_id[i], by_id[i]["verdict"]
            where = f"{r.get('location') or ''} {' '.join(str(x.get('quote')) for x in v.get('signals') or [] if x.get('says') == 'portugal_in')}"
            return (order.get(v.get("lane"), 3), 0 if re.search(r"portugal|lisbo|porto\b", where, re.I) else 1,
                    0 if v.get("read") == "employer" else 1, "~" + str(r.get("posted") or r.get("first_seen") or "")[::-1])
        ids.sort(key=rank)
        ids.sort(key=lambda i: str(by_id[i].get("posted") or by_id[i].get("first_seen") or ""), reverse=True)
        ids.sort(key=lambda i: rank(i)[:3])
        keep, rest = ids[0], ids[1:]
        by_id[keep]["verdict"]["copies"] = [
            {"id": i, "url": by_id[i].get("url"), "read_url": by_id[i]["verdict"].get("read_url"),
             "source": by_id[i].get("source"), "posted": by_id[i].get("posted"), "location": by_id[i].get("location"),
             "lane": by_id[i]["verdict"].get("lane"), "read": by_id[i]["verdict"].get("read")} for i in rest]
        gone = set(rest)
        for lane in lanes:
            lanes[lane] = [i for i in lanes[lane] if i not in gone]
        folded += len(rest)
    return folded


def _co(s):
    return re.sub(r"[^a-z0-9]", "", CO_JUNK.sub(" ", (s or "").lower()))


def _title(t):
    return " ".join(re.findall(r"[a-z0-9]+", re.sub(r"\([^)]*\)", " ", (t or "").lower())))


def employers(pool_doc):
    """Company -> its active postings on its own hiring board, from the pool."""
    out = {}
    for j in pool_doc["jobs"]:
        if j.get("active") and "/" in (j.get("source") or "") and len(_co(j.get("company"))) > 2:
            out.setdefault(_co(j["company"]), []).append(j)
    return out


def evidence(rec, vis, emp, by_id):
    """Facts to weigh a call with, none of which decide anything: the date
    the board gives and the date the employer gives, what the employer's own
    board lists when only a board's copy was read, and the real company's
    page when an agency names who it is hiring for."""
    ev = {}
    own = by_id.get(vis.get("found") and vis["found"].get("pool_id") or vis.get("pool_id") or "")
    if "/" in (rec.get("source") or ""):
        ev["employer_posted"] = rec.get("posted")
    else:
        ev["board_posted"] = rec.get("posted")
        if own:
            ev["employer_posted"] = own.get("posted")
    if vis.get("employer_posted"):
        ev["employer_posted"] = vis["employer_posted"]
    if vis.get("read") == "board":
        theirs = emp.get(_co(rec.get("company")))
        if theirs:
            same = [j for j in theirs if _title(j["title"]) == _title(rec.get("title"))]
            ev["employer_board"] = {"source": theirs[0]["source"], "jobs": len(theirs),
                                    "listed": bool(same), "url": same[0]["url"] if same else None,
                                    "design": [j["title"] for j in theirs if judge.l1(j.get("title")) is None][:6]}
    who = vis.get("hiring_for")
    if who and isinstance(who, str) and _co(who) != _co(rec.get("company")):
        theirs = emp.get(_co(who))
        if theirs:
            same = [j for j in theirs if _title(j["title"]) == _title(rec.get("title"))]
            ev["hiring_for"] = {"company": who, "listed": bool(same), "url": same[0]["url"] if same else None,
                                "jobs": len(theirs), "source": theirs[0]["source"]}
    return {k: v for k, v in ev.items() if v}


def old_text_of(vis):
    """Read before the rules were rewritten on 2026-10-05: the statements carry no kind."""
    return str(vis.get("criteria") or "") < "2026-10-05"


def build(pool_doc, verdicts_doc, hints=None, jd=None, originals=None, vision=None):
    emp, by_id = employers(pool_doc), {j["id"]: j for j in pool_doc["jobs"]}
    hints = hints or {}
    vision = vision or {}
    closed, vcut, agency, unread, review = [], [], [], [], []
    verdicts = verdicts_doc.get("jobs", {})
    roles, lanes, cut, title_cuts, unjudged = [], {k: [] for k in LANES}, [], 0, 0
    ghosts = 0
    for rec in pool_doc["jobs"]:
        if not rec.get("active"):
            continue
        if is_ghost(rec, originals):
            ghosts += 1
            continue
        vis = vision.get(rec["id"])
        # The parser reads the title as it is TODAY. An id outlives a retitle,
        # so a role that was a design title when vision read it and is now
        # "Frontend Leaning Engineer" is out, whatever was said before.
        if vis and judge.l1(rec.get("title")) is not None:
            title_cuts += 1
            continue
        if vis:
            # Vision decides, and nothing it saw is dropped: a closed posting
            # and a cut each get a list the board can open.
            role = dict(rec)
            role["verdict"] = from_vision(vis)
            role["verdict"]["evidence"] = evidence(rec, vis, emp, by_id)
            roles.append(role)
            lane = vis.get("lane")
            # Readings made under the rewritten rules keep everything the
            # reader reported, so the lane is worked out again here, by the
            # one function that decides it. A change to how statements are
            # weighed reaches every such role without reading a page again.
            if not old_text_of(vis) and vis.get("stage") == "vision" and lane != "closed" and isinstance(vis.get("place_signals"), list):
                again, place, why = criteria.lane_from_reading({**vis, "place_verdict": vis.get("reader_place") or vis.get("place_verdict"),
                                                                    "listed": {"title": rec.get("title"), "company": rec.get("company"),
                                                                               "own_page": vis.get("read_url") == vis.get("pool_url")}})
                # "closed" only where the reader had called it another job and was overruled: the page says it is closed
                if again != lane and again in ("open", "portugal", "unsure", "cut") + (("closed",) if vis.get("same_job") == "no" else ()):
                    lane = again
                    role["verdict"].update({"lane": lane, "cut": lane == "cut", "place": place,
                                            "reason": ((why + " · ") if why else "") + str(vis.get("reason") or "").split(" · ")[-1]})
            # A rule that changes how the evidence is weighed should not need
            # every page read again: the statements the reader listed are on
            # file, so the newest rule is applied to them here.
            old_text = str(vis.get("criteria") or "") < "2026-10-05"     # read before the rules were rewritten
            if old_text and lane == "unsure" and vis.get("stage") == "vision" and vis.get("role_verdict") != "no" \
                    and vis.get("posting_open") == "yes" and criteria.top_line_out(vis.get("place_signals")):
                # Spain was the one exception, held in Unsure. No longer (his
                # call, 2026-10-04): Spain is cut like anywhere else.
                lane = "cut"
                role["verdict"].update({"lane": "cut", "cut": True, "place": "no",
                                        "reason": "the line at the top of the page says where; the wider words "
                                                  "lower down are boilerplate · " + str(vis.get("reason") or "")})
            # "Anything else, cut it" (his call, 2026-10-04): a design role
            # held in Unsure only because the reader was not confident of a
            # place cut. When every statement the page makes about place rules
            # Portugal out and none lets it in, that is a cut. With no
            # statement at all there is nothing to cut on, and it stays.
            says = [s.get("says") for s in vis.get("place_signals") or [] if isinstance(s, dict)]
            if old_text and lane == "unsure" and str(vis.get("reason") or "").startswith("cut on place, but not sure of it") \
                    and "portugal_out" in says and "portugal_in" not in says:
                lane = "cut"
                role["verdict"].update({"lane": "cut", "cut": True, "place": "no",
                                        "reason": str(vis.get("reason") or "").replace("cut on place, but not sure of it · ", "")})
            # Judged on the data there is (his call, 2026-10-03): a role that
            # passed on a job board's copy was being held in Unsure only for
            # being a copy. It goes to the lane the reading gave it.
            if lane == "unsure" and vis.get("lane_if_employer") in lanes:
                lane = vis["lane_if_employer"]
                role["verdict"].update({"lane": lane, "reason": str(vis.get("reason") or "").replace(
                    "only the job board's copy could be read · ", "")})
            # Unsure means it was read and the answer is not clear. A page that
            # could not be read at all is a different thing and gets its own
            # list, so Unsure holds only roles worth his judgement.
            if lane == "unsure" and (vis.get("posting_open") == "unreadable"
                                     or "could not be read" in str(vis.get("reason"))):
                # Tried on two runs and the page still will not open: cut,
                # with that as the reason (his call, 2026-10-05). Until then
                # it waits in Not read and goes into the next run.
                if (vis.get("unread_tries") or 1) >= 2:
                    role["verdict"].update({"lane": "cut", "cut": True,
                                            "reason": "the page would not open on two runs · " + str(vis.get("reason") or "")})
                    vcut.append(rec["id"])
                else:
                    unread.append(rec["id"])
                continue
            # Nothing is sent to a lane of its own for being an agency any
            # more (2026-10-05): every role sits in the lane its reading gave
            # it, and he moves a company to Bundlers himself, from the pane.
            # Who an agency is hiring for is still shown.
            if vis.get("posted_by") == "agency":
                role["verdict"]["hiring_for"] = vis.get("hiring_for")
            # One cut in ten is read a second time (vision.audit). A cut the
            # second reading would not have made is brought to him.
            aud = vis.get("audit") or {}
            if lane == "cut" and aud and not aud.get("agrees"):
                role["verdict"]["audit"] = aud
                review.append(rec["id"])
            (lanes[lane] if lane in lanes else closed if lane == "closed" else vcut).append(rec["id"])
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
            lane = v["lane"]
            if not v["cut"] and lane in ("open", "unsure") and placed_elsewhere(rec):
                cut.append(rec["id"])          # remote, but somewhere he is not
                continue
            (cut if v["cut"] else lanes[lane]).append(rec["id"])
    folded = fold(lanes, {r["id"]: r for r in roles})
    # The board fetches this file. 47,000 title cuts would make it 25MB for
    # rows no lane shows; they stay in verdicts.json with their reasons.
    # The description of every lane role rides along, so a board served as
    # static files (GitHub Pages) can show it. Cuts keep needing the local
    # server: 2,600 of them would triple the file for rows no tab lists.
    jd = jd or {}
    lane_ids = [i for lane in lanes.values() for i in lane]
    return {
        # The board no longer prints the description: he reads a posting on
        # its own page, and the pane is for the verdict. So none is shipped.
        "jd": {},
        "generated_at": pool_doc.get("generated_at"),
        "built_at": datetime.datetime.now().astimezone().isoformat(timespec="minutes"),
        "run_id": pool_doc.get("run_id"),
        **{"last_" + k: v for k, v in _runs().items() if k in ("full", "partial")},
        "criteria": verdicts_doc.get("criteria"),
        "model": verdicts_doc.get("model"),
        "counts": {**{k: len(v) for k, v in lanes.items()}, "ghosts": ghosts,
                   "cut": len(cut), "closed": len(closed), "vision_cut": len(vcut), "agency": len(agency), "not_read": len(unread), "folded": folded,
                   "vision_read": len(vision), "title_cuts": title_cuts,
                   # what the board's top line says: design-titled roles, and how many vision has read
                   "design": sum(1 for r in pool_doc["jobs"] if r.get("active") and judge.l1(r.get("title")) is None),
                   "waiting": sum(1 for r in pool_doc["jobs"] if r.get("active") and judge.l1(r.get("title")) is None
                                  and r["id"] not in vision), "unjudged": unjudged,
                   "active": sum(1 for r in pool_doc["jobs"] if r.get("active")),
                   "total": len(pool_doc["jobs"])},
        "lanes": lanes,
        "cut": cut,
        "closed": closed,
        "vcut": vcut,
        "agency": agency,
        "review": review,
        "unread": unread,
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


def _runs():
    """data/runs.json, written by pool.py: the last full and the last partial scrape."""
    try:
        return json.loads((Path(__file__).parent / "data" / "runs.json").read_text())
    except Exception:
        return {}


def main():
    built = build(contracts.load_pool(POOL_FILE),
                  json.loads(VERDICTS_FILE.read_text()),
                  json.loads(HINTS_FILE.read_text()) if HINTS_FILE.exists() else {},
                  json.loads(JD_FILE.read_text()) if JD_FILE.exists() else {},
                  merged_evidence(),
                  json.loads(VISION_FILE.read_text()) if VISION_FILE.exists() else {})
    fresh = remember_shipped(built)
    RESULTS_FILE.write_text(json.dumps(built, indent=1, ensure_ascii=False))
    print(f"RESULTS: wrote {RESULTS_FILE} - {built['counts']}")
    print(f"  RESULTS: {fresh} roles he had never been shown before")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
