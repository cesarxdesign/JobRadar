"""Re-judge the saved fixtures and report every verdict that moved.

A criteria refactor is supposed to say the same thing in fewer words. This is
how you know it did: batch1's verdicts were reviewed by Cesar and confirmed,
so any change there is a regression, not an improvement.

    python3 regress.py            # every validated fixture
    python3 regress.py batch1     # just one
"""
import json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criteria as c, read

ROOT = os.path.dirname(os.path.abspath(__file__))
T = {"open": "OPEN", "portugal": "PT", "unsure": "UN"}
tag = lambda cut, lane: "CUT" if cut else T.get(lane, "?")


def run(name):
    f = json.load(open(f"{ROOT}/data/fixtures/{name}.json"))
    cache, lock, out = read.load_cache(), threading.Lock(), {}
    done = [0]

    def one(i_r):
        i, r = i_r
        rec = {"title": r["title"], "company": r["company"], "source": r.get("source"),
               **{f: r.get(f) for f, _ in read.PANEL}}
        try:
            v, _ = read.read_one(rec, r["jd"], cache)
        except Exception as e:
            v = {"error": str(e)[:70]}
        with lock:
            out[i] = v
            done[0] += 1
            if done[0] % 15 == 0:
                print(f"  {done[0]}/{len(f['roles'])}", flush=True)

    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(one, enumerate(f["roles"])))
    read.save_cache(cache)

    moved = []
    for i, r in enumerate(f["roles"]):
        v = out[i]
        was = tag(r["l2"]["cut"], r["l2"]["lane"])
        now = "ERR" if v.get("error") else tag(v.get("cut"), v.get("lane"))
        if was != now:
            moved.append((r, was, now, v))
    print(f"\n{name}: {len(f['roles'])} roles, criteria was {f['criteria']}, now {c.VERSION}")
    print(f"  unchanged {len(f['roles'])-len(moved)}   MOVED {len(moved)}")
    for r, was, now, v in moved:
        print(f"    {was:>4} -> {now:<4}  {r['company'][:18]:<18} {r['title'][:44]:<44} "
              f"{(r.get('location') or '')[:26]}")
        print(f"          {(v.get('reason') or v.get('error') or '')[:98]}")
    return len(moved)


if __name__ == "__main__":
    names = sys.argv[1:] or ["batch1", "batch2", "batchA"]
    total = sum(run(n) for n in names)
    print(f"\n{total} verdicts moved across {len(names)} fixture(s)")
    raise SystemExit(1 if total else 0)
