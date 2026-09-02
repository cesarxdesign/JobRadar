"""Judge pool survivors with L2 until there are enough of each to review.

Collects until CUTS_WANTED cuts exist, however many passes that takes, then
keeps the FIRST PASSES_WANTED passes. Writes data/review.json for the UI.
"""
import json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criteria as c, judge, pool as P, read

ROOT = os.path.dirname(os.path.abspath(__file__))
PASSES_WANTED, CUTS_WANTED = 30, 20
# No read cap and no board filter. Both existed once, both were structural
# decisions made without Cesar (a 250-read cap that starved batch B, and a
# greenhouse/ashby-only filter so the review iframe would render, which hid
# 337 ready roles). He removed both on 2026-09-02. The review UI falls back
# to the scraped text for boards that refuse to embed.


def check_pool_is_current():
    """A verdict made on stale scrape data is indistinguishable from a bad
    verdict. Refuse rather than produce one."""
    doc = json.load(open(f"{ROOT}/data/pool.json"))
    have = doc.get("adapter_version", 0)
    if have < P.ADAPTER_VERSION:
        print(f"ABORT - data/pool.json was scraped with adapter version {have}, "
              f"the code is at {P.ADAPTER_VERSION}.", file=sys.stderr)
        print("        Its locations and descriptions are missing fields the "
              "adapters now capture.", file=sys.stderr)
        print("        Run: python3 pool.py", file=sys.stderr)
        return False
    return True


def survivors():
    """Every active role that passes L1, via the judge. The old "already
    reviewed" exclusion is gone: Cesar put every test batch back into the pool
    on 2026-09-02, to be re-judged like everything else."""
    pool = json.load(open(f"{ROOT}/data/pool.json"))["jobs"]
    jd = json.load(open(f"{ROOT}/data/jd.json"))
    return judge.survivors(pool, jd)


def main():
    if not check_pool_is_current():
        return 2
    items = judge.resolve(survivors())
    print(f"{len(items)} L1 survivors with a JD. criteria {c.VERSION}", flush=True)
    print(f"reading until {CUTS_WANTED} cuts; keeping the first {PASSES_WANTED} passes\n", flush=True)
    cache = read.load_cache()
    lock = threading.Lock()
    passes, cuts, errs, n = [], [], [], [0]
    stop = threading.Event()
    t0 = time.time()

    def run(item):
        if stop.is_set():
            return
        rec, jd = item
        try:
            v, cached = read.read_one(rec, jd, cache)
        except read.Overloaded as e:
            with lock:
                errs.append((rec, str(e)))
                if not stop.is_set():
                    print(f"  STOPPING: {e}", flush=True)
                stop.set()
            return
        except read.NotResolved as e:
            with lock:
                errs.append((rec, f"skipped - {e}"))
            return
        except Exception as e:
            with lock:
                errs.append((rec, str(e)[:90]))
            return
        with lock:
            n[0] += 1
            if v.get("cut"):
                cuts.append((rec, v))
            elif len(passes) < PASSES_WANTED * 4:
                passes.append((rec, v))
            mark = "CUT " if v.get("cut") else "pass"
            print(f"  [{n[0]}] {mark} {len(passes):>3}p/{len(cuts):>2}c  "
                  f"{rec['company'][:20]:<20} {(rec['title'] or '')[:44]:<44} "
                  f"{time.time()-t0:.0f}s{' (cached)' if cached else ''}", flush=True)
            if n[0] % 10 == 0:
                read.save_cache(cache)
            if len(cuts) >= CUTS_WANTED and len(passes) >= PASSES_WANTED:
                stop.set()

    # 3, not 5: five concurrent one-shot CLI calls is what tipped a run into
    # a 363-failure cascade.
    with ThreadPoolExecutor(max_workers=3) as ex:
        for _ in ex.map(run, items):
            if stop.is_set():
                break
    read.save_cache(cache)

    keep_p, keep_c = passes[:PASSES_WANTED], cuts[:CUTS_WANTED]
    jdmap = json.load(open(f"{ROOT}/data/jd.json"))
    def row(i, rec, v, bucket):
        return {"n": i, "bucket": bucket, "company": rec["company"], "title": rec["title"],
                "url": rec.get("url"), "source": rec.get("source"),
                **{f: rec.get(f) for f, _ in read.PANEL},
                "l2": {"role": v.get("role_verdict"), "place": v.get("place_verdict"),
                       "cut": bool(v.get("cut")), "lane": v.get("lane"),
                       "confidence": v.get("confidence"), "reason": v.get("reason")},
                "fields": v.get("fields", {}), "jd": jdmap.get(rec["id"], "")}
    rows = ([row(i, r, v, "pass") for i, (r, v) in enumerate(keep_p, 1)]
            + [row(i, r, v, "cut") for i, (r, v) in enumerate(keep_c, 1)])
    json.dump({"title": "L2 batch review",
               "note": f"criteria {c.VERSION} — {len(keep_p)} passes, {len(keep_c)} cuts, "
                       f"drawn from {n[0]} roles read",
               "read": n[0], "roles": rows},
              open(f"{ROOT}/data/review.json", "w"), indent=1, ensure_ascii=False)
    print(f"\nread {n[0]} roles in {time.time()-t0:.0f}s — "
          f"{len(passes)} passed, {len(cuts)} cut, {len(errs)} errors")
    if errs:
        kinds = {}
        for _, e in errs:
            k = e.split(":")[0][:40]
            kinds[k] = kinds.get(k, 0) + 1
        for k, v in sorted(kinds.items(), key=lambda x: -x[1]):
            print(f"    {v:4d}  {k}")
    print(f"wrote data/review.json with {len(keep_p)} passes + {len(keep_c)} cuts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
