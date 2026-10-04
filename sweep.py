"""sweep: his inbox, read -> ~/Desktop/RadarRouting.json

match.py guessed company and title out of each email with regexes, and the
guesses were the weak point. Here every thread has been READ (by Claude, one
judgement per thread, in data/emails_class_*.json: company, role and a dated
event per message that means something) and this file only does the
bookkeeping: threads -> applications -> pool roles -> the routing file.

    data/emails_raw.jsonl       every thread since 1 June, list row and body
    data/emails_class_*.json    what each thread is: applied / rejected /
                                callback_* / inbound / withdrawn / followup
    data/applied_history.json   the decisions exported before the routing
                                file was lost (2026-09-03)

It writes three things into the routing file and touches nothing else in it:
    applications  one per application, with what came back. The Stats tab.
    inbound       recruiters who approached him. Not applications.
    decisions     "applied" for the ONE posting an application was certainly
                  sent to (see match). His own clicks are never changed.

Close the board before running this: the board holds the routing file in
memory and writes the whole file back on the next click.

    python3 sweep.py            # write the routing file
    python3 sweep.py --dry      # report only
"""
import glob, json, os, re, shutil, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contracts

ROOT = os.path.dirname(os.path.abspath(__file__))
RR = os.path.expanduser("~/Desktop/RadarRouting.json")
BACKUP = f"{ROOT}/data/backup.RadarRouting.json"   # gitignored: *.RadarRouting.json

# Which companies he applied to is his, and this repo is public. The spelling
# fixes (two names for one employer), the talent marketplaces to skip, and the
# hand-added applications live beside the emails, out of git.
_OV = json.load(open(f"{ROOT}/data/sweep_overrides.json")) if os.path.exists(f"{ROOT}/data/sweep_overrides.json") else {}
ALIAS, SKIP, EXTRA = _OV.get("alias", {}), set(_OV.get("skip", [])), _OV.get("extra", [])
CALLBACK = {"callback_interview", "callback_assessment", "callback_question", "offer"}


def squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def same_co(a, b):
    """The email's name for a company against the pool's slug for it."""
    a, b = (squash(ALIAS.get(squash(x), x)) for x in (a, b))
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))


STOP = {"the", "a", "and", "for", "of", "remote", "mfd", "fmd", "mfx", "role", "position", "eu", "emea", "europe"}


def toks(t):
    t = re.sub(r"\([^)]*\)", " ", (t or "").lower()).replace("sr.", "senior").replace("ui/ux", "ux/ui")
    return {w for w in re.findall(r"[a-z0-9]+", t) if w not in STOP}


def sim(a, b):
    """0 when two titles are different jobs, 1 when they are the same words.
    A missing title is compatible with anything, weakly."""
    if not a or not b:
        return 0.4
    x, y = toks(a), toks(b)
    return len(x & y) / max(1, len(x | y))


def days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def load_threads():
    out = []
    for f in sorted(glob.glob(f"{ROOT}/data/emails_class_*.json")):
        out += json.load(open(f))
    return out


def build(threads):
    """Threads -> applications, one company at a time, in date order."""
    by_co, names = {}, {}
    for t in threads:
        ev = [e for e in t["events"] if e["type"] not in ("noise", "other_job", "followup")]
        if not ev:
            continue
        k = squash(t.get("company")) or "unknown" + t["tid"]
        if k in ALIAS:
            k, name = squash(ALIAS[k]), ALIAS[k]
        else:
            name = t.get("company") or "Unknown company"
        if k in SKIP:
            continue
        names.setdefault(k, name)
        auto = "automatic" in (t.get("note") or "").lower() or "templated" in (t.get("note") or "").lower()
        for e in ev:
            by_co.setdefault(k, []).append({**e, "role": t.get("role"), "tid": t["tid"],
                                            "agency": bool(t.get("via_agency")),
                                            "auto": auto and e["type"] in ("callback_assessment", "callback_question")})
    apps, inbound = [], []
    order = {"inbound": 0, "applied": 1}
    for k, evs in by_co.items():
        evs.sort(key=lambda e: (e["date"], order.get(e["type"], 2)))
        mine = []          # this company's applications, oldest first
        cold = any(e["type"] == "inbound" for e in evs) and not any(e["type"] == "applied" for e in evs)

        def new(e, applied):
            a = {"company": names[k], "role": e["role"], "applied": applied, "rejected": None,
                 "withdrawn": None, "callbacks": [], "via_agency": e["agency"], "tids": [e["tid"]]}
            mine.append(a)
            return a

        def touch(a, e):
            if e["tid"] not in a["tids"]:
                a["tids"].append(e["tid"])
            if e["role"] and (not a["role"] or len(e["role"]) > len(a["role"]) and sim(a["role"], e["role"]) > .5):
                a["role"] = e["role"]
            a["via_agency"] = a["via_agency"] or e["agency"]

        def best(e, pool):
            pool = [a for a in pool if (a["applied"] or "") <= e["date"]]
            return max(pool, key=lambda a: (sim(a["role"], e["role"]), a["applied"] or ""), default=None)

        for e in evs:
            still = [a for a in mine if not a["rejected"] and not a["withdrawn"]]
            if e["type"] == "inbound":
                continue
            if e["type"] == "applied":
                # A second receipt for the same application (the company's and
                # the ATS's, or a resend) lands within days and names the same
                # role. Anything later, or naming another role, is a new one.
                dup = [a for a in still if a["applied"] and days(a["applied"], e["date"]) <= 3
                       and (not a["role"] or not e["role"] or sim(a["role"], e["role"]) > .6)]
                # A callback that arrived before the receipt belongs to it.
                early = [a for a in still if not a["applied"]]
                if dup:
                    touch(dup[-1], e)
                elif early:
                    early[-1]["applied"] = e["date"]
                    touch(early[-1], e)
                else:
                    new(e, e["date"])
            elif e["type"] == "rejected":
                a = best(e, [a for a in still if sim(a["role"], e["role"]) > .25])
                if a:
                    a["rejected"] = e["date"]
                    touch(a, e)
                    continue
                again = [a for a in mine if (a["rejected"] or a["withdrawn"])
                         and days(a["rejected"] or a["withdrawn"], e["date"]) <= 7
                         and sim(a["role"], e["role"]) > .25]
                if again:                       # the same no sent twice, or a no after he had already left
                    touch(again[-1], e)
                else:                           # the yes-we-got-it predates June, or never came
                    new(e, None)["rejected"] = e["date"]
            elif e["type"] == "withdrawn":
                a = best(e, still) or new(e, None)
                a["withdrawn"] = e["date"]
                touch(a, e)
            elif e["type"] in CALLBACK:
                a = best(e, still)
                if not a:
                    if e["auto"]:
                        continue                # a test sent to everyone, tied to nothing
                    a = new(e, None)
                touch(a, e)
                if not any(c["type"] == e["type"] and c["date"] == e["date"] for c in a["callbacks"]):
                    a["callbacks"].append({"type": e["type"].replace("callback_", ""), "date": e["date"],
                                           **({"auto": True} if e["auto"] else {})})
        if cold:
            first = next(e for e in evs if e["type"] == "inbound")
            for a in mine or [new(first, None)]:
                inbound.append({**a, "date": first["date"]})
        else:
            if any(e["type"] == "inbound" for e in evs):
                for a in mine:
                    a["inbound"] = True
            apps += mine
    apps += [dict(a) for a in EXTRA]
    for a in apps:
        # No receipt in the inbox, only what came back. The answer's date
        # stands in for the send date, marked approx, so the application
        # still falls in a period: it was sent on or before that day.
        if not a["applied"]:
            a["applied"] = min([c["date"] for c in a["callbacks"]] + [d for d in (a["rejected"], a["withdrawn"]) if d])
            a["approx"] = True
    for a in apps + inbound:
        # one interview is invited, confirmed and put in the calendar: once
        seen, cb = set(), []
        for c in sorted(a["callbacks"], key=lambda c: c["date"]):
            if (c["type"], c["date"]) not in seen:
                seen.add((c["type"], c["date"]))
                cb.append(c)
        a["callbacks"] = cb
    return apps, inbound


def words(t):
    """A title as its words, in order. Case, dashes, emoji and a trailing dot
    are typography; every word is identity. "Product Designer (Contract)" is
    not "Product Designer", and "Sr" is not "Senior"."""
    return re.findall(r"[a-z0-9]+", (t or "").lower())


def match(apps, jobs):
    """Application -> the one posting it was sent to. One to one, or nothing.

    He applies to every role that fits, so a company's Staff, Senior and Lead
    postings are three jobs and an application to one says nothing about the
    others. A role only leaves Open when it is certain he applied to THAT one:
    same company, the same title word for word, the posting already up on the
    day he applied, and no second posting that fits as well. Anything less
    certain stays live - a role shown twice costs a glance, a role wrongly
    hidden costs an application. Those are kept as maybe_ids and never written
    as decisions."""
    by_co = {}
    for j in jobs:
        by_co.setdefault(squash(j["company"]), []).append(j)
    sure = maybe = 0
    for a in apps:
        k = squash(a["company"])
        cands = by_co.get(k) or by_co.get(squash(re.sub(r"\b(bank|labs|foundation|technologies|software)\b", "", a["company"].lower()))) or []
        a["role_ids"], a["maybe_ids"] = [], []
        if not a["role"]:
            continue
        same = [j for j in cands if words(j["title"]) == words(a["role"])]
        up = [j for j in same if (j.get("posted") or j["first_seen"][:10]) <= a["applied"]]
        # Two rows can be one job: the same posting listed twice, one of them
        # already taken down. A dead copy must not stop the live one matching -
        # that is how "Senior Product Designer (UX)" at Moniepoint, applied to
        # and rejected, sat in Open. So when several fit, the live ones decide.
        # But two postings on the SAME hiring board are two jobs, not copies:
        # Clera had "Product Designer" remote and "Product Designer" in Berlin
        # on its own board the day he applied. He applied to the remote one,
        # it came down, and the Berlin one was marked applied in its place.
        # Copies come from different sources; only then does the live one decide.
        if len(up) > 1 and len([j for j in up if j.get("active")]) == 1 \
                and len({j.get("source") for j in up}) == len(up):
            up = [j for j in up if j.get("active")]
        if len(up) == 1 and not a.get("approx"):
            a["role_ids"] = [up[0]["id"]]
            sure += 1
        elif same:
            a["maybe_ids"] = [j["id"] for j in same]
            maybe += 1
    return sure, maybe


def snapshot(j, decision, at):
    return {"id": j["id"], "decision": decision, "company": j["company"], "title": j["title"], "at": at,
            "url": j.get("url"), "location": j.get("location"), "workplace": j.get("workplace"),
            "source": j.get("source"), "posted": j.get("posted")}


def main():
    dry = "--dry" in sys.argv
    apps, inbound = build(load_threads())
    jobs = contracts.load_pool(f"{ROOT}/data/pool.json")["jobs"]
    by_id = {j["id"]: j for j in jobs}
    sure, maybe = match(apps, jobs)

    rr = json.load(open(RR)) if os.path.exists(RR) else {"decisions": [], "favorites": []}
    # Its own earlier guesses are redone every run; his clicks are never touched.
    rr["decisions"] = [d for d in rr["decisions"] if d.get("by") != "sweep"]
    decided = {d["id"] for d in rr["decisions"]}
    added = 0
    # What he had decided on the board before the file was lost.
    hist = f"{ROOT}/data/applied_history.json"
    if os.path.exists(hist):
        by_url = {j["url"]: j for j in jobs if j.get("url")}
        for h in json.load(open(hist))["roles"]:
            j = by_url.get(h.get("url"))
            if j and j["id"] not in decided:
                rr["decisions"].append(snapshot(j, h["decision"], h["decided_on"] + "T12:00:00.000Z"))
                decided.add(j["id"])
                added += 1
    # A board click and an email for the same application are one application:
    # same company, within days. The email may not name the role at all.
    linked = {i for a in apps for i in a["role_ids"]}
    for d in rr["decisions"]:
        if d["decision"] != "applied" or d["id"] in linked:
            continue
        # The date on a board decision is when he clicked, which for the ones
        # imported in bulk is long after he applied. So: on or before it.
        near = [a for a in apps if same_co(a["company"], d["company"])
                and a["applied"] <= d["at"][:10] and sim(a["role"], d["title"]) >= .4]
        if near:
            a = max(near, key=lambda a: sim(a["role"], d["title"]))
            a["role_ids"].append(d["id"])
            a["role"] = a["role"] or d["title"]
            linked.add(d["id"])
    for a in apps:
        for i in a["role_ids"]:
            if i not in decided:
                rr["decisions"].append({**snapshot(by_id[i], "applied", a["applied"] + "T12:00:00.000Z"), "by": "sweep"})
                decided.add(i)
                added += 1
    rr["applications"] = sorted(apps, key=lambda a: a["applied"] or a["rejected"] or "", reverse=True)
    rr["inbound"] = inbound
    rr.setdefault("milestones", [])
    rr["updated"] = date.today().isoformat()

    real = lambda a: [c for c in a["callbacks"] if not c.get("auto")]
    print(f"{len(apps)} applications: {sum(1 for a in apps if real(a))} called back, "
          f"{sum(1 for a in apps if a['rejected'])} rejected, "
          f"{sum(1 for a in apps if not a['rejected'] and not real(a))} no reply, "
          f"{sum(1 for a in apps if a.get('approx'))} with no receipt (send date approximate)")
    print(f"{len(inbound)} recruiters reached out")
    print(f"{sure} applications matched to pool roles, {added} decisions added, {len(rr['decisions'])} decisions in the file")
    print(f"{maybe} applications with a same-titled posting that is not certainly the one: left live")
    if dry:
        return
    if os.path.exists(RR):
        shutil.copy(RR, f"{ROOT}/data/before.RadarRouting.json")   # gitignored too
    json.dump(rr, open(RR, "w"), indent=1, ensure_ascii=False)
    shutil.copy(RR, BACKUP)
    print("wrote", RR, "and a copy at", BACKUP)


if __name__ == "__main__":
    main()
