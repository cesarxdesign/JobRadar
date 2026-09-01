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


def build(pool_doc, verdicts_doc):
    verdicts = verdicts_doc.get("jobs", {})
    roles, lanes, cut = [], {k: [] for k in LANES}, []
    for rec in pool_doc["jobs"]:
        v = dict(DEFAULT_VERDICT)
        v.update(verdicts.get(rec["id"], {}))
        role = dict(rec)
        role["verdict"] = v
        roles.append(role)
        if not rec.get("active"):
            continue
        (cut if v["cut"] else lanes[v["lane"]]).append(rec["id"])
    return {
        "generated_at": pool_doc.get("generated_at"),
        "run_id": pool_doc.get("run_id"),
        "counts": {**{k: len(v) for k, v in lanes.items()},
                   "cut": len(cut),
                   "active": sum(1 for r in pool_doc["jobs"] if r.get("active")),
                   "total": len(roles)},
        "lanes": lanes,
        "cut": cut,
        "sources": pool_doc.get("sources", {}),
        "roles": roles,
    }


def main():
    built = build(json.loads(POOL_FILE.read_text()),
                  json.loads(VERDICTS_FILE.read_text()))
    RESULTS_FILE.write_text(json.dumps(built, indent=1, ensure_ascii=False))
    print(f"wrote {RESULTS_FILE} - {built['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
