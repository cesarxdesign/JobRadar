"""batch: pull a review sample aside from the roles the judge just ruled on.

Cesar sense-checks a fresh batch each morning: PASSES_WANTED that passed and
CUTS_WANTED that were cut, drawn at random from roles he has not been shown
before. He marks the wrong ones in the board's batch view and presses
Complete; the batch is then archived as a fixture (validated ground truth for
regress.py) and its roles rejoin the general population.

    python3 batch.py            # draw a new batch
    python3 batch.py --complete # archive the open batch and release its roles
"""
import json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criteria as c, judge, pool as P, read

ROOT = os.path.dirname(os.path.abspath(__file__))
BATCH = f"{ROOT}/data/batch.json"
SEEN = f"{ROOT}/data/batched.json"        # ids already sampled, so a batch never repeats
PASSES_WANTED, CUTS_WANTED = 30, 20


def load(p, default):
    return json.load(open(p)) if os.path.exists(p) else default


def write(path, doc):
    tmp = path + ".tmp"
    json.dump(doc, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def draw():
    pool = {j["id"]: j for j in json.load(open(f"{ROOT}/data/pool.json"))["jobs"]}
    vdoc = json.load(open(f"{ROOT}/data/verdicts.json"))
    jd = json.load(open(f"{ROOT}/data/jd.json"))
    seen = set(load(SEEN, []))
    passes, cuts = [], []
    for rid, v in vdoc["jobs"].items():
        rec = pool.get(rid)
        if not rec or not rec.get("active") or rid in seen:
            continue
        if v.get("stage") != "L2" or not v.get("judged"):
            continue        # a title cut is not a judgement worth reviewing
        (cuts if v["cut"] else passes).append((rec, v))
    random.shuffle(passes); random.shuffle(cuts)
    keep_p, keep_c = passes[:PASSES_WANTED], cuts[:CUTS_WANTED]

    def row(i, rec, v, bucket):
        return {"n": i, "bucket": bucket, "id": rec["id"], "company": rec["company"],
                "title": rec["title"], "url": rec.get("url"), "source": rec.get("source"),
                "sources": rec.get("sources"), "posted": rec.get("posted"),
                "first_seen": rec.get("first_seen"),
                **{f: rec.get(f) for f, _ in read.PANEL},
                "l2": {"role": v.get("role"), "place": v.get("place"), "cut": bool(v["cut"]),
                       "lane": v.get("lane"), "confidence": v.get("confidence"),
                       "reason": (v.get("why") or [""])[0]},
                "fields": v.get("fields", {}), "jd": jd.get(rec["id"], "")}
    rows = ([row(i, r, v, "pass") for i, (r, v) in enumerate(keep_p, 1)]
            + [row(i, r, v, "cut") for i, (r, v) in enumerate(keep_c, 1)])
    write(BATCH, {"drawn_at": P.now(), "criteria": c.VERSION, "model": read.MODEL,
                  "pool_run": vdoc.get("pool_run_id"), "wanted": [PASSES_WANTED, CUTS_WANTED],
                  "available": [len(passes), len(cuts)], "roles": rows})
    print(f"batch of {len(keep_p)} passes and {len(keep_c)} cuts "
          f"(from {len(passes)} passed and {len(cuts)} cut, never shown before)")
    return 0


def complete():
    """Archive the open batch as a fixture and release its roles."""
    if not os.path.exists(BATCH):
        print("no open batch", file=sys.stderr)
        return 1
    b = json.load(open(BATCH))
    marks = {m["key"] for m in load(f"{ROOT}/data/marks.json", []) if m.get("key")}
    stamp = b["drawn_at"][:10].replace("-", "")
    name = f"batch{stamp}"
    for r in b["roles"]:
        r["wrong"] = f"{r['company']}|{r['title']}".lower() in marks
    write(f"{ROOT}/data/fixtures/{name}.json",
          {"name": name, "criteria": b["criteria"],
           "note": f"reviewed by Cesar; {sum(1 for r in b['roles'] if r['wrong'])} marked wrong",
           "roles": b["roles"]})
    seen = set(load(SEEN, [])) | {r["id"] for r in b["roles"]}
    write(SEEN, sorted(seen))
    os.remove(BATCH)
    write(f"{ROOT}/data/marks.json", [])
    print(f"archived data/fixtures/{name}.json; {len(b['roles'])} roles released to the board")
    return 0


if __name__ == "__main__":
    raise SystemExit(complete() if "--complete" in sys.argv else draw())
