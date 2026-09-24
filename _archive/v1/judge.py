"""judge: data/pool.json -> data/verdicts.json

The only opinionated module. It reads roles as found and emits one verdict
per id. It writes nothing else and imports nothing from the scraper, so the
criteria can be rewritten - or the whole file swapped - without any other
module changing.

    verdict = {"bucket": pt|eu|ww|tiebreak, "judged": bool,
               "why": str, "cut": bool}

`cut` is the judge saying no. It is NOT `active`: a role the judge cut is a
different thing from a role the company took down, and only the pool may say
a listing is gone.

    python3 judge.py            # rebuild data/verdicts.json
    python3 judge.py --check    # diff against what is on disk, write nothing
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POOL_FILE = ROOT / "data" / "pool.json"
VERDICTS_FILE = ROOT / "data" / "verdicts.json"
JUDGED_FILE = ROOT / "data" / "judged.json"   # the JD-reading pass's own cache

# ---------- criteria ----------
PT_RE = re.compile(r"\b(portugal|portuguese|lisbon|lisboa|porto)\b", re.I)
EU_RE = re.compile(r"\b(europe|european|emea|eu|eea|cet|wet|gmt|utc)\b", re.I)
WW_RE = re.compile(r"\b(worldwide|world wide|anywhere|globally|global|international)\b", re.I)


def classify(location_text, remote=None, restrictions=None, timezones=None,
             workplace=None, elsewhere_re=None, eu_country_re=None, remote_re=None):
    """Bucket a role by Portugal hireability: pt | eu | ww | tiebreak | None.

    Drop ONLY on explicit negative evidence - a stated scope that excludes
    Portugal. Anything ambiguous survives as tiebreak and surfaces in Unsure.
    Negative evidence comes from location/restriction fields, never from a JD.
    """
    loc = (location_text or "").strip()
    if restrictions:
        joined = ", ".join(restrictions)
        if PT_RE.search(joined):
            return "pt"
        if EU_RE.search(joined):
            return "eu"
        if WW_RE.search(joined):
            return "ww"
        return None                      # explicit country list without Portugal
    if PT_RE.search(loc):
        return "pt"
    if EU_RE.search(loc):
        return "eu"
    if WW_RE.search(loc):
        return "ww"
    # Timezones are NOT a criterion (César, 2026-08-29): accepting Portugal but
    # wanting 10pm shifts is his call to make, not the radar's.
    if loc:
        if elsewhere_re and elsewhere_re.search(loc):
            if eu_country_re and eu_country_re.search(loc):
                if workplace == "remote" or (remote_re and remote_re.search(loc)):
                    return "eu"
                if workplace in ("onsite", "hybrid"):
                    return None          # stated office job outside Portugal
                return "tiebreak"
            return None                  # non-European scope, remote or not
        return "tiebreak"                # a place we can't read - surface it
    if remote is False:
        return None                      # explicitly on-site, somewhere unstated
    return "tiebreak"


PT_PLACE_RE = re.compile(r"portugal|lisbon|lisboa", re.I)
REMOTE_IN_LOC_RE = re.compile(r"remote", re.I)


def lane_for(bucket, location, facts):
    """bucket + evidence -> the lane the board renders.

    This used to live in index.html, which meant the view held criteria. A
    role is Portugal only when it is physically there: bucket pt AND the
    location names the place AND it is not a remote listing - remote-from-
    Portugal belongs in Open. A JD that confirms Portugal lifts a role out
    of Unsure, which is why the judge reads facts.json.
    """
    f = facts or {}
    if bucket == "tiebreak" and re.match(r"yes", f.get("portugal") or "", re.I):
        bucket = "eu"
    loc = location or ""
    if bucket == "pt" and PT_PLACE_RE.search(loc) and not REMOTE_IN_LOC_RE.search(loc):
        return "portugal"
    return "unsure" if bucket == "tiebreak" else "open"


def verdict_for(rec, llm, previous, facts=None):
    """One pool record -> one verdict. Pure: no I/O, no globals."""
    v = llm.get(rec["id"])
    if v:
        bucket = v.get("bucket")
        if bucket == "cut":
            keep = previous.get("bucket", "tiebreak")
            return {"lane": lane_for(keep, rec.get("location"), facts), "bucket": keep,
                    "judged": True, "why": v.get("why", ""), "cut": True}
        return {"lane": lane_for(bucket, rec.get("location"), facts), "bucket": bucket,
                "judged": True, "why": v.get("why", ""), "cut": False}
    # No JD verdict yet. Re-derive from evidence when the pool carries it;
    # otherwise keep what the last run concluded rather than inventing one.
    if "location" in rec and any(k in rec for k in ("remote", "restrictions", "workplace")):
        b = classify(rec.get("location"), rec.get("remote"), rec.get("restrictions"),
                     rec.get("timezones"), rec.get("workplace"))
        if b:
            return {"lane": lane_for(b, rec.get("location"), facts), "bucket": b,
                    "judged": False, "why": "", "cut": False}
    keep = previous.get("bucket", "tiebreak")
    return {"lane": lane_for(keep, rec.get("location"), facts), "bucket": keep,
            "judged": previous.get("judged", False),
            "why": previous.get("why", ""), "cut": previous.get("cut", False)}


def build(pool_doc, llm_doc, prev_doc, facts_doc=None):
    llm = llm_doc.get("jobs", {})
    prev = prev_doc.get("jobs", {})
    facts = facts_doc or {}
    return {"updated": pool_doc.get("generated_at"),
            "jobs": {r["id"]: verdict_for(r, llm, prev.get(r["id"], {}), facts.get(r["id"]))
                     for r in pool_doc["jobs"]}}


def main():
    pool_doc = json.loads(POOL_FILE.read_text())
    llm_doc = json.loads(JUDGED_FILE.read_text()) if JUDGED_FILE.exists() else {}
    prev_doc = json.loads(VERDICTS_FILE.read_text()) if VERDICTS_FILE.exists() else {}
    facts_file = ROOT / "data" / "facts.json"
    facts_doc = json.loads(facts_file.read_text()) if facts_file.exists() else {}
    built = build(pool_doc, llm_doc, prev_doc, facts_doc)
    if "--check" in sys.argv:
        old = prev_doc.get("jobs", {})
        diff = [(i, old.get(i), built["jobs"][i])
                for i in built["jobs"] if old.get(i) != built["jobs"][i]]
        print(f"{len(built['jobs'])} verdicts, {len(diff)} differ from disk")
        for i, a, b in diff[:6]:
            print(f"   {i}\n     was {a}\n     now {b}")
        return 1 if diff else 0
    VERDICTS_FILE.write_text(json.dumps(built, indent=1, ensure_ascii=False))
    from collections import Counter
    print(f"wrote {VERDICTS_FILE} - {Counter(v['bucket'] for v in built['jobs'].values())}"
          f" cut={sum(1 for v in built['jobs'].values() if v['cut'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
