"""export: his decisions -> data/applied_history.{json,md}

Everything Radar knows about a role he acted on, in one file, so a Claude
session can read his history and look for patterns without touching the
pipeline. Applied first, discarded second: the pattern in what he skipped is
half the signal.

The routing file holds the decision and the date. The pool holds the posting,
the judge holds what it read out of it, and jd.json holds the words. This
joins them. A role whose posting has since come down keeps whatever the
routing file snapshotted at the time.

    python3 export.py
"""
import json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))
RR = os.path.expanduser("~/Desktop/RadarRouting.json")
OUT_JSON = f"{ROOT}/data/applied_history.json"
OUT_MD = f"{ROOT}/data/applied_history.md"
EXCERPT = 1200


def day(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return (str(s) or "")[:10] or None


def build():
    rr = json.load(open(RR))
    pool = {j["id"]: j for j in json.load(open(f"{ROOT}/data/pool.json"))["jobs"]}
    verdicts = json.load(open(f"{ROOT}/data/verdicts.json"))["jobs"]
    jd = json.load(open(f"{ROOT}/data/jd.json"))
    favs = set(rr.get("favorites") or [])
    rows = []
    for d in rr.get("decisions") or []:
        rec, v = pool.get(d["id"]) or {}, verdicts.get(d["id"]) or {}
        f = v.get("fields") or {}
        posted = day(rec.get("posted") or rec.get("first_seen"))
        decided = day(d.get("at"))
        age = None
        if posted and decided:
            try:
                age = (datetime.fromisoformat(decided) - datetime.fromisoformat(posted)).days
            except Exception:
                pass
        rows.append({
            "decision": d.get("decision"), "decided_on": decided,
            "favourite": d["id"] in favs,
            "company": rec.get("company") or d.get("company"),
            "title": rec.get("title") or d.get("title"),
            "url": rec.get("url") or d.get("url"),
            "source": rec.get("source") or d.get("source"),
            "posting_still_live": bool(rec.get("active")),
            "posted_on": posted, "days_open_when_he_applied": age,
            "location": rec.get("location") or d.get("location"),
            "workplace": rec.get("workplace") or d.get("workplace"),
            "employment_type": rec.get("employment_type"), "department": rec.get("department"),
            "judge": {"lane": v.get("lane"), "confidence": v.get("confidence"),
                      "reason": (v.get("why") or [None])[0]},
            "seniority": f.get("seniority") or d.get("seniority"),
            "remote": f.get("remote") or d.get("remote"),
            "countries": f.get("countries") or d.get("countries"), "portugal_ok": f.get("portugal_ok"),
            "salary": f.get("salary") or d.get("salary"), "years_xp": f.get("years_xp"),
            "reports_to": f.get("reports_to"), "language": f.get("language"),
            "description_excerpt": (jd.get(d["id"]) or "")[:EXCERPT] or None,
        })
    rows.sort(key=lambda r: (r["decision"] != "applied", r["decided_on"] or ""), reverse=False)
    rows.sort(key=lambda r: r["decision"] != "applied")
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "about": "Cesar's job-hunt decisions from Radar2. applied = he applied; "
                     "discarded = he saw it and passed. Fields after 'judge' were read "
                     "off the posting by the judge, not typed by him.",
            "counts": {k: sum(1 for r in rows if r["decision"] == k)
                       for k in ("applied", "discarded")},
            "roles": rows}


def markdown(doc):
    L = [f"# Job-hunt history\n", doc["about"], "",
         f"Generated {doc['generated_at'][:16].replace('T', ' ')} · "
         f"{doc['counts'].get('applied', 0)} applied · {doc['counts'].get('discarded', 0)} discarded", ""]
    for kind in ("applied", "discarded"):
        rows = [r for r in doc["roles"] if r["decision"] == kind]
        if not rows:
            continue
        L += [f"\n## {kind.capitalize()} ({len(rows)})\n",
              "| date | company | title | location | remote | seniority | salary | lane |",
              "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append("| " + " | ".join(str(x or "—").replace("|", "/")[:44] for x in
                     (r["decided_on"], r["company"], r["title"], r["location"],
                      r["remote"], r["seniority"], r["salary"], r["judge"]["lane"])) + " |")
    return "\n".join(L) + "\n"


def main():
    doc = build()
    for path, text in ((OUT_JSON, json.dumps(doc, indent=1, ensure_ascii=False)),
                       (OUT_MD, markdown(doc))):
        tmp = path + ".tmp"
        open(tmp, "w").write(text)
        os.replace(tmp, path)
    print(f"{doc['counts'].get('applied', 0)} applied and "
          f"{doc['counts'].get('discarded', 0)} discarded -> {OUT_JSON} and {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
