"""Re-judge the exact roles in data/review.json under the current criteria,
and show what moved. The batch is fixed; only the verdicts change."""
import json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criteria as c, pool as P, read
import contracts

ROOT = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(f"{ROOT}/data/review.json"))
pj = {x["id"]: x for x in contracts.load_pool(f"{ROOT}/data/pool.json")["jobs"]}
ident = {}
for x in pj.values():
    ident.setdefault(P.identity(x["company"], x["title"]), x)
marks = {}
if os.path.exists(f"{ROOT}/data/marks.json"):
    for m in json.load(open(f"{ROOT}/data/marks.json")):
        marks[(m["bucket"], m["n"])] = True

cache, lock, out = read.load_cache(), threading.Lock(), {}
done = [0]

def one(r):
    src = ident.get(P.identity(r["company"], r["title"])) or {}
    rec = {"title": r["title"], "company": r["company"], "location": r["location"],
           "source": r["source"], "workplace": src.get("workplace"),
           "restrictions": src.get("restrictions"),
           "employment_type": src.get("employment_type"),
           "department": src.get("department"), "salary": src.get("salary")}
    try:
        v, _ = read.read_one(rec, r["jd"], cache)
    except Exception as e:
        v = {"error": str(e)[:70], "cut": None}
    with lock:
        out[(r["bucket"], r["n"])] = v
        done[0] += 1
        if done[0] % 10 == 0:
            print(f"  {done[0]}/{len(d['roles'])}", flush=True)

with ThreadPoolExecutor(max_workers=5) as ex:
    list(ex.map(one, d["roles"]))
read.save_cache(cache)

print(f"\ncriteria {c.VERSION}\n")
hdr = "%-4s %-3s %-20s %-42s %-9s %-9s %s"
print(hdr % ("tab", "#", "company", "title", "was", "now", "you"))
print("-" * 118)
moved = agree = 0
for r in d["roles"]:
    k = (r["bucket"], r["n"])
    v = out[k]
    was = "CUT" if r["l2"]["cut"] else r["l2"]["lane"]
    now = "ERR" if v.get("error") else ("CUT" if v.get("cut") else v.get("lane"))
    you = "WRONG" if marks.get(k) else ""
    if was != now:
        moved += 1
    # you marked it wrong and it moved = we fixed what you flagged
    if marks.get(k) and was != now:
        agree += 1
    flag = "  <-- moved" if was != now else ""
    print(hdr % (r["bucket"], r["n"], r["company"][:20], r["title"][:42], was, now, you + flag))
print()
print(f"{moved} of {len(d['roles'])} moved")
print(f"you flagged {len(marks)}; {agree} of those moved")
still = [k for k in marks if out[k] and (("CUT" if out[k].get("cut") else out[k].get("lane"))
        == ("CUT" if dict(((r['bucket'],r['n']),r) for r in d['roles'])[k]["l2"]["cut"]
            else dict(((r['bucket'],r['n']),r) for r in d['roles'])[k]["l2"]["lane"]))]
print(f"still unchanged after you flagged them: {len(still)}")
