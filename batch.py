"""Judge pool survivors with L2 until there are enough of each to review.

Collects until CUTS_WANTED cuts exist, however many passes that takes, then
keeps the FIRST PASSES_WANTED passes. Writes data/review.json for the UI.
"""
import json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criteria as c, deep, pool as P, read

ROOT = os.path.dirname(os.path.abspath(__file__))
PASSES_WANTED, CUTS_WANTED = 30, 20
MAX_READS = 250        # a budget. Without one, a run with a low pass rate
                       # grinds through every survivor looking for 30 passes.

# Boards that allow their page to be embedded, so the review UI can show the
# real posting instead of our reconstruction. Stripe, Jobicy, Datadog and
# SmartRecruiters send frame-ancestors self/none and come up blank.
EMBEDDABLE = ("greenhouse.io", "ashbyhq.com")


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


def already_reviewed():
    """Identities Cesar has already been shown. A second batch that repeats
    the first teaches nothing."""
    f = f"{ROOT}/data/reviewed.json"
    return set(json.load(open(f))) if os.path.exists(f) else set()


def survivors():
    pool = json.load(open(f"{ROOT}/data/pool.json"))["jobs"]
    jd = json.load(open(f"{ROOT}/data/jd.json"))
    HAS, EXC = re.compile(c.L1_MUST_HAVE, re.I), re.compile(c.L1_EXCLUDE, re.I)
    JR, LEAD = re.compile(c.L1_JUNIOR, re.I), re.compile(c.L1_LEADERSHIP, re.I)
    NOT = re.compile(c.L1_NOT_LEADERSHIP, re.I)
    lead = lambda t: bool(LEAD.search(t)) and not NOT.search(t)
    seen = already_reviewed()
    out = []
    for x in pool:
        if P.identity(x.get("company") or "", x.get("title") or "") in seen:
            continue
        t = x.get("title") or ""
        if not (x.get("active") and HAS.search(t)):
            continue
        if EXC.search(t) and not lead(t):
            continue
        if JR.search(t):
            continue
        text = jd.get(x["id"]) or ""
        if not text:
            continue
        # Only fully-resolved postings. A company board IS the original; an
        # aggregator row counts only once it has been resolved to the real one.
        src = (x.get("source") or "").split("/")[0]
        if src in read.AGGREGATORS and len(text) < read.THIN:
            continue
        host = (x.get("url") or "").split("/")[2] if x.get("url") else ""
        if not any(e in host for e in EMBEDDABLE):
            continue
        out.append((x, text))
    return out


def resolve_first(items):
    """Aggregator rows must be resolved to the original before L2 sees them.
    This is a pipeline step, not a thing to remember: pool -> L1 -> resolve
    originals -> L2. Skipping it is how a whole batch got judged on summaries."""
    todo = [(rec, jd) for rec, jd in items
            if len(jd or "") < read.THIN
            and (rec.get("source") or "").split("/")[0] in read.AGGREGATORS
            and rec.get("url")]
    if not todo:
        return items
    print(f"resolving {len(todo)} aggregator rows to their original posting", flush=True)
    store = json.load(open(f"{ROOT}/data/jd.json"))
    done = [0]
    def one(pair):
        rec, _ = pair
        try:
            t = deep.fetch_original(rec["url"])
        except Exception:
            t = None
        if t and len(t) > len(store.get(rec["id"]) or ""):
            store[rec["id"]] = t[:20000]
        done[0] += 1
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, todo))
    tmp = f"{ROOT}/data/jd.tmp.json"
    open(tmp, "w").write(json.dumps(store, ensure_ascii=False))
    os.replace(tmp, f"{ROOT}/data/jd.json")
    print(f"resolved {done[0]}", flush=True)
    return [(rec, store.get(rec["id"], jd)) for rec, jd in items]


def main():
    if not check_pool_is_current():
        return 2
    items = resolve_first(survivors())
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
        with lock:
            if n[0] >= MAX_READS:
                stop.set()
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
