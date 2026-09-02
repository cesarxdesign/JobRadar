"""judge: data/pool.json -> data/verdicts.json

The second leg. Reads the pool, never writes it. Holds no criteria - those
live in criteria.py - and writes nothing but its own file.

    L1   title-only word rules (criteria.L1_*). Cheap, binary, readable.
    resolve   every survivor with a thin or missing description gets the
              original posting fetched (deep.py) before anyone judges it.
    L2   Claude reads the full posting as it renders (read.py), with the
         criteria from criteria.py, and answers ROLE and PLACE.

Every active role gets a verdict, keyed by id. Cuts are kept with their
reason. A survivor whose original could not be resolved is recorded as
unread - never judged on nothing, never dropped silently.

Reads are cached on the exact text shown (read.key_for), so a second run
costs only the roles that are new or changed. verdicts.json is written every
few reads; a run that dies keeps its work and the next one resumes for free.

    python3 judge.py            # judge the pool
    python3 judge.py --dry      # count what a run would read, call nothing
    python3 judge.py --explain <id-prefix>
"""
import json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contracts, criteria as c, deep, pool as P, read

ROOT = os.path.dirname(os.path.abspath(__file__))
POOL_FILE = f"{ROOT}/data/pool.json"
JD_FILE = f"{ROOT}/data/jd.json"
VERDICTS_FILE = f"{ROOT}/data/verdicts.json"

HAS, EXC = re.compile(c.L1_MUST_HAVE, re.I), re.compile(c.L1_EXCLUDE, re.I)
JR, LEAD, NOT = (re.compile(c.L1_JUNIOR, re.I), re.compile(c.L1_LEADERSHIP, re.I),
                 re.compile(c.L1_NOT_LEADERSHIP, re.I))


# ---------------------------------------------------------------- L1
def l1(title):
    """None when the title passes, else the reason it was cut. Title only."""
    t = title or ""
    if not HAS.search(t):
        return "title has no design / ui / ux"
    m = EXC.search(t)
    if m and not (LEAD.search(t) and not NOT.search(t)):
        return f"title: {m.group(0)}"
    m = JR.search(t)
    if m:
        return f"title: {m.group(0)}"
    return None


def survivors(jobs, jd):
    """Active roles that pass L1, with whatever description is on file."""
    return [(x, jd.get(x["id"]) or "") for x in jobs
            if x.get("active") and l1(x.get("title")) is None]


# ---------------------------------------------------------------- resolve
def resolve(items):
    """Every thin survivor is resolved to the original before L2 sees it.
    Aggregators republish a summary; some boards (SmartRecruiters, Workday)
    list postings without a body at all. This is a pipeline step, not a thing
    to remember: pool -> L1 -> resolve -> L2. Skipping it is how a whole
    batch got judged on summaries once."""
    todo = [(rec, jd) for rec, jd in items
            if len(jd or "") < read.THIN and rec.get("url")]
    if not todo:
        return items
    print(f"resolving {len(todo)} thin rows to their original posting", flush=True)
    store = json.load(open(JD_FILE))
    lock, done, got, t0 = threading.Lock(), [0], [0], time.time()

    def save():
        tmp = f"{JD_FILE}.tmp"
        open(tmp, "w").write(json.dumps(store, ensure_ascii=False))
        os.replace(tmp, JD_FILE)

    def one(pair):
        rec, _ = pair
        try:
            t = deep.fetch_original(rec["url"])
        except Exception:
            t = None
        with lock:
            if t and len(t) > len(store.get(rec["id"]) or ""):
                store[rec["id"]] = t[:20000]
                got[0] += 1
            done[0] += 1
            if done[0] % 25 == 0 or done[0] == len(todo):
                print(f"  [{done[0]}/{len(todo)}] {got[0]} resolved, "
                      f"{time.time()-t0:.0f}s", flush=True)
                save()

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, todo))
    save()
    return [(rec, store.get(rec["id"], jd)) for rec, jd in items]


# ---------------------------------------------------------------- verdicts
def l1_verdict(reason):
    return {"role": "no", "place": "unclear", "lane": "unsure", "cut": True,
            "why": [reason], "judged": True, "stage": "L1"}


def l2_verdict(v):
    return {"role": v.get("role_verdict") or "unclear",
            "place": v.get("place_verdict") or "unclear",
            "lane": v.get("lane") or "unsure", "cut": bool(v.get("cut")),
            "why": [v.get("reason") or ""], "judged": True, "stage": "L2",
            "confidence": v.get("confidence"), "fields": v.get("fields") or {},
            "inferred": v.get("inferred") or []}


def unread_verdict(reason):
    # Not a judgement. The board can show these as unread; whether they sit
    # in Unsure or elsewhere is Cesar's call, and results.py applies it.
    return {"role": "unclear", "place": "unclear", "lane": "unsure", "cut": False,
            "why": [f"unread: {reason}"], "judged": False, "stage": "unread"}


def write(doc, jobs_verdicts):
    doc["jobs"] = jobs_verdicts
    from collections import Counter
    doc["counts"] = dict(Counter(
        ("cut-L1" if v["stage"] == "L1" else "cut-L2" if v["cut"]
         else "unread" if v["stage"] == "unread" else v["lane"])
        for v in jobs_verdicts.values()))
    tmp = f"{VERDICTS_FILE}.tmp"
    open(tmp, "w").write(json.dumps(doc, indent=1, ensure_ascii=False))
    os.replace(tmp, VERDICTS_FILE)


def main():
    pool_doc = json.load(open(POOL_FILE))
    if pool_doc.get("adapter_version", 0) < P.ADAPTER_VERSION:
        print(f"ABORT - pool scraped with adapter version "
              f"{pool_doc.get('adapter_version', 0)}, code is at {P.ADAPTER_VERSION}. "
              f"Run: python3 pool.py", file=sys.stderr)
        return 2
    jobs = pool_doc["jobs"]
    jd = json.load(open(JD_FILE))
    # Only this judge's own verdicts count as history. The file on disk may
    # be from the old L1-only engine (no "stage"); that is not a verdict.
    previous = (json.load(open(VERDICTS_FILE)).get("jobs", {})
                if os.path.exists(VERDICTS_FILE) else {})
    previous = {k: v for k, v in previous.items() if isinstance(v, dict) and "stage" in v}

    if "--explain" in sys.argv:
        wanted = sys.argv[sys.argv.index("--explain") + 1]
        rec = next(r for r in jobs if r["id"].startswith(wanted))
        print(json.dumps({k: rec.get(k) for k in ("company", "title", "location",
                                                   "workplace", "url")}, indent=1))
        print(json.dumps(previous.get(rec["id"], "(no verdict yet)"), indent=1,
                         ensure_ascii=False))
        return 0

    out = {}
    active = [x for x in jobs if x.get("active")]
    for x in jobs:
        if not x.get("active"):
            if x["id"] in previous:       # history of a role that went away
                out[x["id"]] = previous[x["id"]]
            continue
        r = l1(x.get("title"))
        if r:
            out[x["id"]] = l1_verdict(r)
    items = survivors(jobs, jd)
    thin = sum(1 for _, t in items if len(t or "") < read.THIN)
    cache = read.load_cache()
    hits = sum(1 for rec, t in items if t and read.key_for(rec, t) in cache)
    print(f"{len(active)} active roles: {len(out)} cut at L1, {len(items)} survive "
          f"({thin} thin or empty, to resolve). criteria {c.VERSION}, {read.MODEL}",
          flush=True)
    print(f"  L2: {hits} already read, about {len(items)-hits} reads to make", flush=True)
    if "--dry" in sys.argv:
        print("  --dry: nothing fetched, nothing read, nothing written")
        return 0

    items = resolve(items)
    doc = {"generated_at": P.now(), "pool_run_id": pool_doc.get("run_id"),
           "criteria": c.VERSION, "model": read.MODEL}
    lock, n, t0 = threading.Lock(), [0], time.time()
    stop = threading.Event()
    tally = {"open": 0, "portugal": 0, "unsure": 0, "cut": 0, "unread": 0}

    def run(item):
        if stop.is_set():
            return
        rec, text = item
        try:
            v, cached = read.read_one(rec, text, cache)
            verdict = l2_verdict(v)
        except read.NotResolved as e:
            verdict, cached = unread_verdict(str(e)), True
        except read.Overloaded as e:
            with lock:
                if not stop.is_set():
                    print(f"  STOPPING: {e} - verdicts so far are saved, rerun to resume",
                          flush=True)
                stop.set()
            return
        except Exception as e:
            verdict, cached = unread_verdict(f"error: {str(e)[:80]}"), True
        with lock:
            out[rec["id"]] = verdict
            n[0] += 1
            key = ("unread" if verdict["stage"] == "unread" else
                   "cut" if verdict["cut"] else verdict["lane"])
            tally[key] += 1
            if not cached:
                print(f"  [{n[0]}/{len(items)}] {key:<8} "
                      f"open {tally['open']} pt {tally['portugal']} unsure {tally['unsure']} "
                      f"cut {tally['cut']} unread {tally['unread']}  "
                      f"{rec['company'][:20]:<20} {(rec['title'] or '')[:40]:<40} "
                      f"{time.time()-t0:.0f}s", flush=True)
            if n[0] % 10 == 0:
                read.save_cache(cache)
                write(doc, out)

    # 3 workers: five concurrent one-shot CLI calls once tipped a run into a
    # 363-failure cascade.
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(run, items))
    read.save_cache(cache)
    write(doc, out)
    print(f"\n{n[0]} survivors judged in {time.time()-t0:.0f}s: {tally}")
    print(f"wrote {VERDICTS_FILE}: {doc['counts']}")
    return 1 if stop.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(main())
