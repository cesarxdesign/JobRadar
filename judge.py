"""judge: data/pool.json -> data/verdicts.json

The second leg. Reads the pool, never writes it. Holds no criteria - those
live in criteria.py - and writes nothing but its own file.

    the parser   title-only word rules (criteria.PARSE_*). Cheap, binary, readable.
    resolve   every survivor with a thin or missing description gets the
              original posting fetched (deep.py) before anyone judges it.
    the judge   Claude reads the full posting as it renders (read.py), with the
         criteria from criteria.py, and answers ROLE and PLACE.

Every active role gets a verdict, keyed by id. Cuts are kept with their
reason. The original posting is preferred; when it cannot be fetched the
summary on hand is judged, and with no text at all the criteria judge from
the title and panel. Each verdict says which ("text": original / summary /
none). Errors record nothing and are retried next run.

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

HAS, EXC = re.compile(c.PARSE_MUST_HAVE, re.I), re.compile(c.PARSE_EXCLUDE, re.I)
JR, LEAD, NOT = (re.compile(c.PARSE_JUNIOR, re.I), re.compile(c.PARSE_LEADERSHIP, re.I),
                 re.compile(c.PARSE_NOT_LEADERSHIP, re.I))


# ---------------------------------------------------------------- the parser
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
    """Active roles that pass the parser, with whatever description is on file."""
    return [(x, jd.get(x["id"]) or "") for x in jobs
            if x.get("active") and l1(x.get("title")) is None]


# ---------------------------------------------------------------- resolve
def resolve(items):
    """Every thin survivor is resolved to the original before the judge sees it.
    Aggregators republish a summary; some boards (SmartRecruiters, Workday)
    list postings without a body at all. This is a pipeline step, not a thing
    to remember: pool -> the parser -> resolve -> the judge. Skipping it is how a whole
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

    panels = {}

    def one(pair):
        rec, _ = pair
        try:
            d = deep.fetch_posting(rec["url"])
        except Exception:
            d = {}
        t = d.get("jd")
        with lock:
            if t and len(t) > len(store.get(rec["id"]) or ""):
                store[rec["id"]] = t[:20000]
                got[0] += 1
                # The original board's panel replaces the aggregator's guess.
                p = {k: d[k] for k in ("location", "workplace", "employment_type",
                                       "department", "company") if d.get(k)}
                if p:
                    panels[rec["id"]] = p
            done[0] += 1
            if done[0] % 25 == 0 or done[0] == len(todo):
                print(f"  [{done[0]}/{len(todo)}] {got[0]} resolved, "
                      f"{time.time()-t0:.0f}s", flush=True)
                save()

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, todo))
    save()
    out = []
    for rec, jd in items:
        p = panels.get(rec["id"])
        if p:
            rec = {**rec, **p, "panel": p}      # judged on the original's panel
        out.append((rec, store.get(rec["id"], jd)))
    print(f"  {len(panels)} of them replaced the aggregator's panel with the original's",
          flush=True)
    return out


# ---------------------------------------------------------------- verdicts
def l1_verdict(reason):
    return {"role": "no", "place": "unclear", "lane": "unsure", "cut": True,
            "why": [reason], "judged": True, "stage": "parse"}


def l2_verdict(v, text):
    return {"text": text,"role": v.get("role_verdict") or "unclear",
            "place": v.get("place_verdict") or "unclear",
            "lane": v.get("lane") or "unsure", "cut": bool(v.get("cut")),
            "why": [v.get("reason") or ""], "judged": True, "stage": "judge",
            "confidence": v.get("confidence"), "fields": v.get("fields") or {},
            "inferred": v.get("inferred") or []}


def write(doc, jobs_verdicts):
    doc["jobs"] = jobs_verdicts
    from collections import Counter
    doc["counts"] = dict(Counter(
        ("cut-parse" if v["stage"] == "parse" else "cut-judge" if v["cut"] else v["lane"])
        for v in jobs_verdicts.values()))
    tmp = f"{VERDICTS_FILE}.tmp"
    open(tmp, "w").write(json.dumps(doc, indent=1, ensure_ascii=False))
    os.replace(tmp, VERDICTS_FILE)


def main():
    pool_doc = contracts.load_pool(POOL_FILE)
    if pool_doc.get("adapter_version", 0) < P.ADAPTER_VERSION:
        print(f"ABORT - pool scraped with adapter version "
              f"{pool_doc.get('adapter_version', 0)}, code is at {P.ADAPTER_VERSION}. "
              f"Run: python3 pool.py", file=sys.stderr)
        return 2
    jobs = pool_doc["jobs"]
    jd = json.load(open(JD_FILE))
    # Only this judge's own verdicts count as history. The file on disk may
    # be from the old the parser-only engine (no "stage"); that is not a verdict.
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
    if "--lanes" in sys.argv:
        # Re-read only what is on the board. A criteria change that only makes
        # PLACE stricter cannot rescue a role that was already cut, so every
        # survivor outside the three lanes keeps the verdict it has and costs
        # nothing - this is complete, not a sample.
        res = json.load(open(os.path.join(ROOT, "data", "results.json")))
        on_board = {i for k in ("open", "portugal", "unsure") for i in res["lanes"].get(k, [])}
        for rec, _ in items:
            if rec["id"] not in on_board and rec["id"] in previous:
                out[rec["id"]] = previous[rec["id"]]
        items = [(rec, t) for rec, t in items if rec["id"] in on_board]
    thin = sum(1 for _, t in items if len(t or "") < read.THIN)
    cache = read.load_cache()
    hits = sum(1 for rec, t in items if t and read.key_for(rec, t) in cache)
    print(f"{len(active)} active roles: {len(out)} cut at the parser, {len(items)} survive "
          f"({thin} thin or empty, to resolve). criteria {c.VERSION}, {read.MODEL}",
          flush=True)
    print(f"  the judge: {hits} already read, about {len(items)-hits} reads to make", flush=True)
    if "--dry" in sys.argv:
        print("  --dry: nothing fetched, nothing read, nothing written")
        return 0

    items = resolve(items)
    doc = {"generated_at": P.now(), "pool_run_id": pool_doc.get("run_id"),
           "criteria": c.VERSION, "model": read.MODEL}
    lock, n, t0 = threading.Lock(), [0], time.time()
    stop = threading.Event()
    tally = {"open": 0, "portugal": 0, "unsure": 0, "cut": 0, "error": 0}
    kinds = {"original": 0, "summary": 0, "none": 0}

    def run(item):
        if stop.is_set():
            return
        rec, text = item
        try:
            v, cached = read.read_one(rec, text, cache)
            verdict = l2_verdict(v, read.text_kind(rec, text))
            if rec.get("panel"):
                verdict["panel"] = rec["panel"]   # what the board should show
        except read.Overloaded as e:
            with lock:
                if not stop.is_set():
                    print(f"  STOPPING: {e} - verdicts so far are saved, rerun to resume",
                          flush=True)
                stop.set()
            return
        except Exception as e:
            # Not a verdict. Nothing recorded, so the next run retries it.
            with lock:
                n[0] += 1
                tally["error"] += 1
                print(f"  [{n[0]}/{len(items)}] error    {rec['company'][:20]:<20} "
                      f"{(rec['title'] or '')[:40]:<40} {str(e)[:60]}", flush=True)
            return
        with lock:
            out[rec["id"]] = verdict
            n[0] += 1
            key = "cut" if verdict["cut"] else verdict["lane"]
            tally[key] += 1
            kinds[verdict["text"]] += 1
            if not cached:
                print(f"  [{n[0]}/{len(items)}] {key:<8} "
                      f"open {tally['open']} pt {tally['portugal']} unsure {tally['unsure']} "
                      f"cut {tally['cut']} err {tally['error']}  "
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
    print(f"judged on: {kinds}")
    print(f"wrote {VERDICTS_FILE}: {doc['counts']}")
    return 1 if stop.is_set() else 0


if __name__ == "__main__":
    raise SystemExit(main())
