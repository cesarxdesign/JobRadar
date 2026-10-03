"""battery: what he has told the board, held against what the filter says now.

Every action of his on the board is a known answer:

    applied      he applied to it          -> the filter must show it, never cut it
    discarded    he saw it and passed      -> nothing: that is taste, not a filter error
    wrong?       he challenged a reason    -> that part of the reasoning was wrong
    moved        he re-laned a role        -> the lane he gave is the right one
    email        an application his inbox proves, matched to its posting -> as applied

This holds those against the verdicts on file and lists every disagreement.
It reads nothing and costs nothing. Run it before and after any change to
criteria.py: a change that makes this list longer does not ship.

    python3 battery.py              # the report
    python3 battery.py --replay     # re-read each battery role's saved page under today's rules (costs tokens)

The answers live in the routing file on the Desktop and the report in
data/battery/, neither of which is ever committed: they are his applications.
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contracts, criteria, judge

ROOT = os.path.dirname(os.path.abspath(__file__))
RR = os.path.expanduser("~/Desktop/RadarRouting.json")
OUT = f"{ROOT}/data/battery"
PAGES = f"{ROOT}/data/pages"
SHOWN = ("open", "portugal", "unsure")


def lane_now(rid, vision, old, title):
    """What the filter says today, and who said it."""
    if title is not None and judge.l1(title) is not None:
        return "cut", "parser", judge.l1(title)
    v = vision.get(rid)
    if v:
        # the lane the board actually shows: results.py applies the newest rules to what vision recorded
        return BOARD.get(rid, v.get("lane")), "vision", v.get("reason")
    o = old.get(rid)
    if o and o.get("judged"):
        return ("cut" if o.get("cut") else o.get("lane")), "old judge", "; ".join(o.get("why") or [])
    return None, None, None


BOARD = {}


def board_lanes():
    r = json.load(open(f"{ROOT}/data/results.json"))
    for lane, ids in r["lanes"].items():
        BOARD.update({i: lane for i in ids})
    BOARD.update({i: "closed" for i in r.get("closed") or []})
    BOARD.update({i: "cut" for i in r.get("vcut") or []})
    BOARD.update({i: "unsure" for i in r.get("unread") or []})
    for x in r["roles"]:
        if x["id"] not in BOARD and (x.get("verdict") or {}).get("stage") == "vision":
            BOARD[x["id"]] = x["verdict"].get("lane")       # folded copies and Multihire keep their own lane


def main():
    board_lanes()
    rr = json.load(open(RR))
    vision = json.load(open(f"{ROOT}/data/vision.json"))
    old = json.load(open(f"{ROOT}/data/verdicts.json"))["jobs"] if os.path.exists(f"{ROOT}/data/verdicts.json") else {}
    jobs = {j["id"]: j for j in contracts.load_pool(f"{ROOT}/data/pool.json")["jobs"]}
    if "--replay" in sys.argv:
        return replay(rr, vision, jobs)

    cases, fails, untested = 0, [], 0
    # 1. everything he applied to must be shown
    applied = {d["id"]: d for d in rr["decisions"] if d["decision"] == "applied"}
    for a in rr.get("applications") or []:
        for i in a.get("role_ids") or []:
            applied.setdefault(i, {"id": i, "company": a["company"], "title": a.get("role"), "by": "email"})
    for i, d in applied.items():
        title = (jobs.get(i) or {}).get("title") or d.get("title")
        lane, who, why = lane_now(i, vision, old, title)
        if lane is None:
            untested += 1
            continue
        cases += 1
        if lane not in SHOWN:
            fails.append({"kind": "applied, but the filter " + ("calls it closed" if lane == "closed" else "cuts it"),
                          "company": d.get("company"), "title": title, "lane": lane, "by": who, "why": why,
                          "url": d.get("url") or (jobs.get(i) or {}).get("url"), "id": i,
                          "soft": lane == "closed"})
    # 2. a challenged reason must have changed
    part = {"role": "role_verdict", "location": "place_verdict"}
    for f in rr.get("flags") or []:
        v = vision.get(f["id"])
        for w in f.get("wrong") or []:
            if w not in part:
                continue
            cases += 1
            was = f.get("role") if w == "role" else f.get("place")
            now = (v or {}).get(part[w])
            lane = BOARD.get(f["id"], (v or {}).get("lane"))
            if v is None or (now == was and lane == f.get("label")):
                fails.append({"kind": f"he called the {w} reasoning wrong, and it is unchanged", "company": f.get("company"),
                              "title": f.get("title"), "lane": lane, "by": "vision", "why": (v or {}).get("reason") or f.get("reason"),
                              "url": f.get("url"), "id": f["id"]})
    # 3. a role he moved belongs where he put it
    for t in rr.get("retags") or []:
        cases += 1
        lane, who, why = lane_now(t["id"], vision, old, (jobs.get(t["id"]) or {}).get("title"))
        if lane != t["to"]:
            fails.append({"kind": f"he moved it from {t['from']} to {t['to']}; the filter still says {lane}", "company": t.get("company"),
                          "title": t.get("title"), "lane": lane, "by": who, "why": why, "url": t.get("url"), "id": t["id"]})

    hard = [f for f in fails if not f.get("soft")]
    os.makedirs(OUT, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    report = {"at": stamp, "criteria": criteria.VERSION, "cases": cases, "untested": untested,
              "failing": len(hard), "closed_since": len(fails) - len(hard), "fails": fails}
    json.dump(report, open(f"{OUT}/report.json", "w"), indent=1, ensure_ascii=False)
    with open(f"{OUT}/history.jsonl", "a") as h:
        h.write(json.dumps({k: report[k] for k in ("at", "criteria", "cases", "untested", "failing", "closed_since")}) + "\n")
    print(f"battery {stamp} · criteria {criteria.VERSION}")
    print(f"  {cases} known answers checked, {untested} not checkable (the role has not been read)")
    print(f"  {len(hard)} where the filter disagrees with him; {len(fails) - len(hard)} he applied to that have since closed")
    kinds = {}
    for f in hard:
        kinds.setdefault(f["kind"], []).append(f)
    for k, v in sorted(kinds.items(), key=lambda x: -len(x[1])):
        print(f"\n  {k}: {len(v)}")
        for f in v[:40]:
            print(f"    {str(f['company'])[:22]:22} | {str(f['title'])[:44]:44} | {f['by']:9} | {str(f['why'])[:90]}")
    return 1 if hard else 0


def replay(rr, vision, jobs):
    """Re-read each battery role from the page saved when it was first read,
    under the rules as they are now. This is how a rule change is tried
    without touching the board: same pages, new rules, and the battery says
    whether it got better or worse."""
    import vision as V
    ids = {d["id"] for d in rr["decisions"] if d["decision"] == "applied"} | {f["id"] for f in rr.get("flags") or []} \
        | {t["id"] for t in rr.get("retags") or []}
    have = [i for i in ids if os.path.exists(f"{PAGES}/{i}.txt") and i in jobs]
    print(f"replay: {len(have)} of {len(ids)} battery roles have a saved page")
    out = {}
    for i in have:
        rec = jobs[i]
        page = {"url": rec["url"], "title": rec["title"], "text": open(f"{PAGES}/{i}.txt").read()}
        a = V.reader(rec, page)
        place, _ = criteria.place_from_signals(a.get("place_signals"), a.get("workplace_as_posted"), a.get("place_verdict"))
        lane = "closed" if a.get("posting_open") == "no" else (criteria.lane_for(a.get("role_verdict"), place) or "cut")
        was = (vision.get(i) or {}).get("lane")
        out[i] = {"was": was, "now": lane}
        print(f"  {'=' if was == lane else '≠'} {rec['company'][:20]:20} | {rec['title'][:40]:40} | {was} -> {lane}")
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(f"{OUT}/replay.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
