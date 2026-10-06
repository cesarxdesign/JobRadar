"""discover: a company seen on a job board -> its own hiring board, added to the pool's sources.

A job board's copy of a posting is second-hand: stale, re-tagged "remote
anywhere", often already closed. The posting itself lives in the company's
hiring system - Ashby, Greenhouse, Lever, Workable and the rest - and every
one of those publishes a company's open jobs at an address made from the
company's name. That is how job boards themselves are built, and it needs no
search engine and no Apply button.

So: for every company that only reaches the pool through a board, try its
name against each hiring system. A board that answers AND lists a title the
job board showed for that company is that company's - confirmed by the job,
not by the name. It goes into data/sources.json, and from then on pool.py
reads that company at the source every night: its real location, its real
dates, and every other design role it has open, not just the one a board
happened to copy.

    python3 discover.py            # probe, report, add confirmed boards to sources.json
    python3 discover.py --dry      # probe and report only
"""
import json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contracts, judge, pool as P

ROOT = os.path.dirname(os.path.abspath(__file__))
SOURCES = f"{ROOT}/data/sources.json"
FOUND = f"{ROOT}/data/discovered.json"        # every probe's answer, so a company is asked once

# name -> how the slug becomes that platform's key. Most take the slug bare.
PLATFORMS = [("ashby", "{s}"), ("greenhouse", "{s}"), ("lever", "{s}"), ("workable", "{s}"),
             ("recruitee", "{s}"), ("teamtailor", "{s}.teamtailor.com"), ("smartrecruiters", "{s}"),
             ("bamboohr", "{s}"), ("breezy", "{s}"), ("join", "{s}"), ("personio", "{s}.jobs.personio.com"),
             ("rippling", "{s}"), ("pinpoint", "{s}"), ("jazzhr", "{s}"),
             ("manatal", "{s}.careers-page.com"), ("manatal", "{s}")]
JUNK = re.compile(r"\b(inc|llc|ltd|limited|gmbh|sa|s\.a\.|lda|plc|co|corp|corporation|company|group|the)\b\.?", re.I)


def squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def words(t):
    return [w for w in re.findall(r"[a-z0-9]+", (t or "").lower())]


def slugs(company):
    """The few ways a company name becomes an address."""
    name = JUNK.sub(" ", company or "")
    parts = re.findall(r"[a-z0-9]+", name.lower())
    out = []
    for s in ("".join(parts), "-".join(parts), parts[0] if parts else "",
              squash(company), "".join(parts) + "hq", "".join(parts) + "-2"):
        if len(s) >= 3 and s not in out:
            out.append(s)
    return out[:4]


def probe(company, titles):
    """-> {"platform", "key", "jobs", "match"} for the first board that is certainly theirs, or None."""
    want = [words(t) for t in titles]
    seen = []
    for s in slugs(company):
        for platform, shape in PLATFORMS:
            key = shape.format(s=s)
            try:
                rows = list(P.ADAPTERS[platform](key))
            except Exception:
                continue
            if not rows:
                continue
            got = [words(r.get("title")) for r in rows]
            match = next((r.get("title") for r, g in zip(rows, got) if g in want), None)
            if match:
                return {"platform": platform, "key": key, "jobs": len(rows), "match": match,
                        "design": [r.get("title") for r in rows if judge.l1(r.get("title")) is None]}
            seen.append({"platform": platform, "key": key, "jobs": len(rows)})
    return {"unconfirmed": seen} if seen else None


URL_BOARDS = [("ashby", re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)/", re.I)),
              ("greenhouse", re.compile(r"greenhouse\.io/([^/?#]+)/jobs/", re.I)),
              ("lever", re.compile(r"jobs\.lever\.co/([^/?#]+)/", re.I)),
              ("workable", re.compile(r"apply\.workable\.com/([^/?#]+)/j/", re.I)),
              ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([^/?#]+)/", re.I)),
              ("recruitee", re.compile(r"https?://([a-z0-9-]+)\.recruitee\.com/", re.I)),
              ("teamtailor", re.compile(r"https?://([a-z0-9.-]+\.teamtailor\.com)/", re.I))]


def from_links(jobs, src):
    """A job board often links a posting straight to the company's hiring
    system, and that address names the company's whole board. No guessing:
    every design-titled role whose link is one of these gives up its board."""
    added = 0
    for j in jobs:
        if not j.get("active") or "/" in (j.get("source") or "") or judge.l1(j.get("title")) is not None:
            continue
        for platform, rx in URL_BOARDS:
            m = rx.search(j.get("url") or "")
            if not m:
                continue
            key = m.group(1)
            lst = src["watchlist"].setdefault(platform, {})
            if key.lower() not in {str(k).lower() for k in lst} and key.lower() not in ("embed", "jobs", "j", "o"):
                lst[key] = j.get("company") or key
                added += 1
            break
    return added


def main():
    dry = "--dry" in sys.argv
    jobs = contracts.load_pool(f"{ROOT}/data/pool.json")["jobs"]
    src = json.load(open(SOURCES))
    known = {squash(j["company"]) for j in jobs if "/" in j["source"]}
    known |= {squash(str(k).split(".")[0]) for v in src["watchlist"].values() for k in v}
    done = json.load(open(FOUND)) if os.path.exists(FOUND) else {}
    todo = {}
    for j in jobs:
        if j.get("active") and "/" not in j["source"] and judge.l1(j["title"]) is None:
            c = j["company"] or ""
            if len(squash(c)) >= 3 and squash(c) not in known and c not in done:
                todo.setdefault(c, set()).add(j["title"])
    if "--limit" in sys.argv:
        todo = dict(list(todo.items())[:int(sys.argv[sys.argv.index("--limit") + 1])])
    linked = from_links(jobs, src)
    if linked and not dry:
        json.dump(src, open(SOURCES, "w"), indent=1, ensure_ascii=False)
    print(f"SOURCE: {linked} company boards read straight off posting links", flush=True)
    print(f"SOURCE: {len(todo)} companies seen only on job boards, {len(done)} already asked", flush=True)
    lock, n, t0 = threading.Lock(), [0], time.time()

    def one(item):
        c, titles = item
        try:
            r = probe(c, titles)
        except Exception as e:
            r = {"error": str(e)}
        with lock:
            done[c] = r
            n[0] += 1
            if r and r.get("platform"):
                print(f"  [{n[0]}/{len(todo)}] {c[:28]:28} -> {r['platform']}/{r['key']}  {r['jobs']} jobs, "
                      f"{len(r['design'])} design · matched \"{r['match']}\"", flush=True)
            if n[0] % 25 == 0:
                json.dump(done, open(FOUND, "w"), indent=1, ensure_ascii=False)

    with ThreadPoolExecutor(12) as ex:
        list(ex.map(one, todo.items()))
    json.dump(done, open(FOUND, "w"), indent=1, ensure_ascii=False)
    hits = {c: r for c, r in done.items() if r and r.get("platform")}
    unconf = sum(1 for r in done.values() if r and r.get("unconfirmed"))
    added = 0
    for c, r in hits.items():
        lst = src["watchlist"].setdefault(r["platform"], [] if isinstance(src["watchlist"].get(r["platform"], []), list) else {})
        if isinstance(lst, list):
            if r["key"] not in lst:
                lst.append(r["key"])
                added += 1
        elif r["key"] not in lst:
            lst[r["key"]] = c
            added += 1
    print(f"SOURCE: {len(hits)} companies found at their own hiring board ({sum(len(r['design']) for r in hits.values())} design roles there), "
          f"{unconf} with a board of that name but no matching title (not added), in {time.time() - t0:.0f}s")
    if not dry and added:
        json.dump(src, open(SOURCES, "w"), indent=1, ensure_ascii=False)
        print(f"SOURCE: added {added} links to data/sources.json; POOL reads them from the next run")


if __name__ == "__main__":
    main()
