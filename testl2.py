"""Recall tests for the judge. Cesar applied to every role in these sets, so a CUT is
a proven false-cut - the one error that is invisible in production.

    python3 testl2.py applied   52 v1-applied roles, matched into the pool, WITH JDs
    python3 testl2.py emails    135 roles from application emails, title only

The email set has no JD, so it tests the ROLE axis alone. the judge must not cut on
place without evidence; if it does, that is a bug in the criteria.
"""
import json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pool as P, read, criteria
import contracts

ROOT = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~/Claude/JobRadar/current/data")


def load_applied():
    rr = json.load(open(os.path.join(HOME, "history.json")))
    pj = contracts.load_pool(f"{ROOT}/data/pool.json")["jobs"]
    jd = json.load(open(f"{ROOT}/data/jd.json"))
    by = {}
    for r in pj:
        by.setdefault(P.identity(r["company"], r["title"]), r)
    out = []
    for d in rr["decisions"]:
        if d["decision"] != "applied":
            continue
        k = d.get("variant_key") or P.identity(d.get("company", ""), d.get("title", ""))
        r = by.get(k)
        if r and jd.get(r["id"]):
            out.append((r, jd[r["id"]]))
    return out


def load_emails():
    apps = json.load(open(os.path.join(HOME, "applications.json")))["applications"]
    return [({"title": a["role"], "company": a["company"], "location": None}, None)
            for a in apps if a.get("role")]


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "applied"
    items = load_applied() if which == "applied" else load_emails()
    print(f"the judge recall test: {which} - {len(items)} roles, criteria {criteria.VERSION}", flush=True)
    print("every one of these was applied to, so any CUT is a false cut\n", flush=True)

    cache = read.load_cache()
    lock = threading.Lock()
    done = [0]
    t0 = time.time()
    results = []

    def run(item):
        rec, jd = item
        try:
            v, cached = read.read_one(rec, jd, cache)
        except Exception as e:
            v, cached = {"error": str(e)[:120], "cut": None}, False
        with lock:
            done[0] += 1
            n = done[0]
            results.append((rec, v))
            mark = "CUT " if v.get("cut") else ("ERR " if v.get("error") else "pass")
            print(f"  [{n}/{len(items)}] {mark} {rec['company'][:22]:<22} "
                  f"{(rec['title'] or '')[:42]:<42} {time.time()-t0:.0f}s"
                  f"{' (cached)' if cached else ''}", flush=True)
            if n % 10 == 0:
                read.save_cache(cache)
        return v

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(run, items))
    read.save_cache(cache)

    cuts = [(r, v) for r, v in results if v.get("cut")]
    errs = [(r, v) for r, v in results if v.get("error")]
    ok = len(results) - len(cuts) - len(errs)
    print(f"\n{'='*70}")
    print(f"passed        : {ok}/{len(results)}   ({100*ok/max(1,len(results)):.1f}%)")
    print(f"FALSE CUTS    : {len(cuts)}")
    print(f"errors        : {len(errs)}")
    for r, v in cuts:
        print(f"\n  CUT  {r['company']} — {r['title']}")
        print(f"       role={v.get('role_verdict')} place={v.get('place_verdict')} "
              f"conf={v.get('confidence')}")
        print(f"       {v.get('reason')}")
    for r, v in errs[:5]:
        print(f"  ERR  {r['company']} — {v.get('error')}")
    json.dump([{"company": r["company"], "title": r["title"], "verdict": v}
               for r, v in results],
              open(f"{ROOT}/data/test_{which}.json", "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
