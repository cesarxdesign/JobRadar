"""judge: data/pool.json -> data/verdicts.json

Runs the criteria over every role and records what each rule said. It holds no
criteria itself - those live in criteria.py - and it writes nothing but its own
file. Rewrite every rule and this file does not change.

    python3 judge.py            # rebuild verdicts
    python3 judge.py --explain <id>
"""
import json
import sys
from collections import Counter
from pathlib import Path

from contracts import DEFAULT_VERDICT, lane_for
import criteria

ROOT = Path(__file__).resolve().parent
POOL_FILE = ROOT / "data" / "pool.json"
VERDICTS_FILE = ROOT / "data" / "verdicts.json"


def resolve(rules, rec):
    """Run one axis' rules. -> (verdict, [why]) with every firing rule named."""
    said, why = [], []
    for name, fn in rules:
        try:
            out = fn(rec)
        except Exception as e:                      # a broken rule must not
            why.append(f"{name}: ERRORED {e}")      # decide anything
            continue
        if out is None:
            continue
        said.append(out)
        why.append(f"{name}: {out}")
    if "no" in said:
        return "no", why            # explicit negative evidence always wins
    for v in said:
        if v not in ("unclear",):
            return v, why           # yes, or a place verdict like pt_onsite
    return "unclear", why


def verdict_for(rec):
    role, rwhy = resolve(criteria.ROLE_RULES, rec)
    place, pwhy = resolve(criteria.PLACE_RULES, rec)
    lane = lane_for(role, place)
    return {"role": role, "place": place,
            "lane": lane or "unsure", "cut": lane is None,
            "why": rwhy + pwhy,
            "judged": bool(criteria.ROLE_RULES or criteria.PLACE_RULES)}


def build(pool_doc):
    return {"updated": pool_doc.get("generated_at"),
            "rules": {"role": [n for n, _ in criteria.ROLE_RULES],
                      "place": [n for n, _ in criteria.PLACE_RULES]},
            "jobs": {r["id"]: verdict_for(r) for r in pool_doc["jobs"]}}


def main():
    pool_doc = json.loads(POOL_FILE.read_text())
    if "--explain" in sys.argv:
        wanted = sys.argv[sys.argv.index("--explain") + 1]
        rec = next(r for r in pool_doc["jobs"] if r["id"].startswith(wanted))
        v = verdict_for(rec)
        print(f"{rec['company']} — {rec['title']}")
        print(f"  role={v['role']}  place={v['place']}  "
              f"lane={'CUT' if v['cut'] else v['lane']}")
        for w in v["why"] or ["  (no rule had anything to say)"]:
            print("   ", w)
        return 0
    built = build(pool_doc)
    VERDICTS_FILE.write_text(json.dumps(built, indent=1, ensure_ascii=False))
    lanes = Counter("cut" if v["cut"] else v["lane"] for v in built["jobs"].values())
    print(f"{len(built['jobs'])} judged by "
          f"{len(criteria.ROLE_RULES)} role + {len(criteria.PLACE_RULES)} place rules")
    print(" ", dict(lanes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
