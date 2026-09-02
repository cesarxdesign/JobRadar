"""results: pool (x) verdicts -> data/results.json

A pure merge. No criteria, no thresholds, no opinions - it only asks the
verdict which lane a role is in and files it there. The board reads this file
and nothing else, so the view never applies criteria of its own.

Cuts are kept, with their reasons. A role the judge rejected stays visible and
recoverable; it is never deleted and never confused with `active`, which only
the pool may set - a role the company took down is a different fact.

    python3 results.py
"""
import json
from pathlib import Path

from contracts import DEFAULT_VERDICT, LANES

ROOT = Path(__file__).resolve().parent
POOL_FILE = ROOT / "data" / "pool.json"
VERDICTS_FILE = ROOT / "data" / "verdicts.json"
RESULTS_FILE = ROOT / "data" / "results.json"
HINTS_FILE = ROOT / "data" / "applied_hints.json"     # local only, from match.py


def build(pool_doc, verdicts_doc, hints=None):
    hints = hints or {}
    verdicts = verdicts_doc.get("jobs", {})
    roles, lanes, cut, title_cuts, unjudged = [], {k: [] for k in LANES}, [], 0, 0
    for rec in pool_doc["jobs"]:
        if not rec.get("active"):
            continue
        v = dict(DEFAULT_VERDICT)
        v.update(verdicts.get(rec["id"], {}))
        if v.get("stage") == "L1":
            title_cuts += 1          # kept, with its reason, in verdicts.json
            continue
        if not v.get("judged"):
            unjudged += 1            # the judge has not reached it yet
            continue
        role = dict(rec)
        role["verdict"] = v
        if rec["id"] in hints:
            role["hints"] = hints[rec["id"]]   # his inbox says he may have applied
        roles.append(role)
        if v.get("judged") and v.get("stage") != "L1":
            (cut if v["cut"] else lanes[v["lane"]]).append(rec["id"])
    # The board fetches this file. 47,000 title cuts would make it 25MB for
    # rows no lane shows; they stay in verdicts.json with their reasons.
    return {
        "generated_at": pool_doc.get("generated_at"),
        "run_id": pool_doc.get("run_id"),
        "criteria": verdicts_doc.get("criteria"),
        "model": verdicts_doc.get("model"),
        "counts": {**{k: len(v) for k, v in lanes.items()},
                   "cut": len(cut), "title_cuts": title_cuts, "unjudged": unjudged,
                   "active": sum(1 for r in pool_doc["jobs"] if r.get("active")),
                   "total": len(pool_doc["jobs"])},
        "lanes": lanes,
        "cut": cut,
        "sources": pool_doc.get("sources", {}),
        "roles": roles,
    }


def main():
    built = build(json.loads(POOL_FILE.read_text()),
                  json.loads(VERDICTS_FILE.read_text()),
                  json.loads(HINTS_FILE.read_text()) if HINTS_FILE.exists() else {})
    RESULTS_FILE.write_text(json.dumps(built, indent=1, ensure_ascii=False))
    print(f"wrote {RESULTS_FILE} - {built['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
