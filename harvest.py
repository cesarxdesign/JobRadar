"""harvest: every company board on every hiring system, not just the ones a job board led to.

discover.py learns a company exists when one of its roles turns up on a job
board. That leaves out every company no board happened to copy - he found
MindFi's real posting on Dover by hand. The hiring systems publish no list of
their customers, but every company board has an address of one shape
(jobs.ashbyhq.com/<company>, boards.greenhouse.io/<company>, ...), and Common
Crawl - a free public index of the web - can be asked for every address it
has seen under each of them. That is the list.

    enumerate   ask the index, over its latest snapshots, for every board
                address of every system  ->  data/boards.json
    check       open each board through pool.py's own reader and count its
                jobs and its design-titled jobs. A board with a design role
                goes into data/sources.json and is scraped every night from
                then on. A board with none is asked again in a week, so a
                company that opens a design role later is picked up.

    python3 harvest.py enumerate            # refresh the list (weekly is plenty)
    python3 harvest.py check                # check every board that is due
    python3 harvest.py check --minutes 40   # ...for at most 40 minutes (the night run)
    python3 harvest.py                      # both

His call, 2026-10-05: "the cost is not seeing roles that might hire me. add
all of them." The title cut is free, so the scan is wide; only design-titled
roles are ever read.
"""
import json, os, re, sys, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge, pool as P

ROOT = os.path.dirname(os.path.abspath(__file__))
BOARDS = f"{ROOT}/data/boards.json"
SOURCES = f"{ROOT}/data/sources.json"
SNAPSHOTS = 4                 # latest Common Crawl snapshots asked; each sees a different part of the web
MAX_PAGES = 400               # per address pattern per snapshot
RECHECK_DAYS = 7
# systems that refuse a crowd: this many askers at a time, with a pause between
SLOW = {k: threading.Semaphore(2) for k in ("dover", "workable", "join", "rippling")}
WORKERS = 12

# system, what to ask the index for, how a board's name is read out of an
# address, and how that name is written as the key pool.py's reader takes.
PATTERNS = [
    ("ashby",           "jobs.ashbyhq.com/*",            r"jobs\.ashbyhq\.com/([^/?#]+)",                 "{s}"),
    ("greenhouse",      "boards.greenhouse.io/*",        r"boards\.greenhouse\.io/([^/?#]+)",             "{s}"),
    ("greenhouse",      "job-boards.greenhouse.io/*",    r"job-boards\.greenhouse\.io/([^/?#]+)",         "{s}"),
    ("greenhouse",      "job-boards.eu.greenhouse.io/*", r"job-boards\.eu\.greenhouse\.io/([^/?#]+)",     "{s}"),
    ("lever",           "jobs.lever.co/*",               r"jobs\.lever\.co/([^/?#]+)",                    "{s}"),
    ("lever",           "jobs.eu.lever.co/*",            r"jobs\.eu\.lever\.co/([^/?#]+)",                "{s}"),
    ("workable",        "apply.workable.com/*",          r"apply\.workable\.com/([^/?#]+)",               "{s}"),
    ("smartrecruiters", "jobs.smartrecruiters.com/*",    r"jobs\.smartrecruiters\.com/([^/?#]+)",         "{s}"),
    ("smartrecruiters", "careers.smartrecruiters.com/*", r"careers\.smartrecruiters\.com/([^/?#]+)",      "{s}"),
    ("rippling",        "ats.rippling.com/*",            r"ats\.rippling\.com/([^/?#]+)",                 "{s}"),
    ("join",            "join.com/companies/*",          r"join\.com/companies/([^/?#]+)",                "{s}"),
    ("dover",           "app.dover.com/jobs/*",          r"app\.dover\.com/jobs/([^/?#]+)",               "{s}"),
    ("dover",           "app.dover.com/apply/*",         r"app\.dover\.com/apply/([^/?#]+)",              "{s}"),
    ("recruitee",       "*.recruitee.com",               r"//([a-z0-9-]+)\.recruitee\.com",               "{s}"),
    ("teamtailor",      "*.teamtailor.com",              r"//([a-z0-9-]+)\.teamtailor\.com",              "{s}.teamtailor.com"),
    ("personio",        "*.jobs.personio.com",           r"//([a-z0-9-]+)\.jobs\.personio\.com",          "{s}.jobs.personio.com"),
    ("personio",        "*.jobs.personio.de",            r"//([a-z0-9-]+)\.jobs\.personio\.de",           "{s}.jobs.personio.de"),
    ("breezy",          "*.breezy.hr",                   r"//([a-z0-9-]+)\.breezy\.hr",                   "{s}"),
    ("pinpoint",        "*.pinpointhq.com",              r"//([a-z0-9-]+)\.pinpointhq\.com",              "{s}"),
    ("jazzhr",          "*.applytojob.com",              r"//([a-z0-9-]+)\.applytojob\.com",              "{s}"),
    ("bamboohr",        "*.bamboohr.com",                r"//([a-z0-9-]+)\.bamboohr\.com",                "{s}"),
    ("manatal",         "*.careers-page.com",            r"//([a-z0-9-]+)\.careers-page\.com",            "{s}.careers-page.com"),
]
NOT_A_BOARD = {"www", "app", "api", "embed", "jobs", "job", "careers", "career", "static", "assets", "cdn", "help", "support",
               "docs", "blog", "status", "login", "signup", "sitemap", "robots.txt", "favicon.ico", "search", "about",
               "privacy", "terms", "legal", "internal", "sso", "auth", "mail", "email", "go", "info", "apply", "dashboard",
               "admin", "widget", "widgets", "partners", "developers", "dev", "test", "demo", "staging", "sandbox", "en",
               "de", "fr", "es", "pt", "nl", "it", "undefined", "null", "index.html", "_next", "images", "img", "css", "js"}


def get(url, timeout=90, tries=5):
    """The index is slow and drops requests; it is asked again, patiently."""
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "JobRadar harvest (personal job search)"}),
                                          timeout=timeout).read().decode("utf-8", "replace")
        except Exception as e:
            code = getattr(e, "code", None)
            if code == 404:
                return ""
            time.sleep(6 * (i + 1))
    return None


def load():
    return json.load(open(BOARDS)) if os.path.exists(BOARDS) else {}


_save_lock = threading.Lock()


def save(b):
    """Merged into what is on disk, not written over it: the list and the
    check run at the same time, and each used to erase the other's work."""
    with _save_lock:
        disk = load()
        for system, d in disk.items():
            mine = b.setdefault(system, {})
            for k, v in d.items():
                if k not in mine:
                    mine[k] = v
                elif (v.get("checked") or "") > (mine[k].get("checked") or ""):
                    mine[k] = {**mine[k], **v}
        tmp = BOARDS + f".{os.getpid()}.tmp"
        json.dump(b, open(tmp, "w"), separators=(",", ":"), ensure_ascii=False)
        os.replace(tmp, BOARDS)


# The index as plain files. index.commoncrawl.org, the query server, dropped
# most of what it was asked (Workable, SmartRecruiters, Rippling, Join: no
# answer at all). The same index is published as static files: cluster.idx
# says which block of which file holds each stretch of addresses, sorted by
# reversed host name, and a block is fetched with one ranged request. Nothing
# to time out, nothing to throttle.
CC = "https://data.commoncrawl.org/cc-index/collections/{snap}/indexes/"
SURT = {  # the address pattern, as the index sorts it
    "jobs.ashbyhq.com/*": "com,ashbyhq,jobs)/", "boards.greenhouse.io/*": "io,greenhouse,boards)/",
    "job-boards.greenhouse.io/*": "io,greenhouse,job-boards)/", "job-boards.eu.greenhouse.io/*": "io,greenhouse,eu,job-boards)/",
    "jobs.lever.co/*": "co,lever,jobs)/", "jobs.eu.lever.co/*": "co,lever,eu,jobs)/",
    "apply.workable.com/*": "com,workable,apply)/", "jobs.smartrecruiters.com/*": "com,smartrecruiters,jobs)/",
    "careers.smartrecruiters.com/*": "com,smartrecruiters,careers)/", "ats.rippling.com/*": "com,rippling,ats)/",
    "join.com/companies/*": "com,join)/companies/", "app.dover.com/jobs/*": "com,dover,app)/jobs/",
    "app.dover.com/apply/*": "com,dover,app)/apply/", "*.recruitee.com": "com,recruitee,",
    "*.teamtailor.com": "com,teamtailor,", "*.jobs.personio.com": "com,personio,jobs,", "*.jobs.personio.de": "de,personio,jobs,",
    "*.breezy.hr": "hr,breezy,", "*.pinpointhq.com": "com,pinpointhq,", "*.applytojob.com": "com,applytojob,",
    "*.bamboohr.com": "com,bamboohr,", "*.careers-page.com": "com,careers-page,",
}


def _raw(url, rng=None, tries=6, timeout=120):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JobRadar harvest (personal job search)",
                                                       **({"Range": f"bytes={rng[0]}-{rng[1]}"} if rng else {})})
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception:
            time.sleep(4 * (i + 1))
    return None


def cluster(snap):
    """cluster.idx for one snapshot: the sorted first key of every block. 100MB, kept on disk."""
    os.makedirs(f"{ROOT}/data/cc", exist_ok=True)
    path = f"{ROOT}/data/cc/{snap}.cluster.idx"
    if not os.path.exists(path) or os.path.getsize(path) < 50_000_000:
        print(f"  fetching the block list of {snap} (100MB, once)", flush=True)
        raw = _raw(CC.format(snap=snap) + "cluster.idx", timeout=900)
        if not raw:
            return None, None
        open(path, "wb").write(raw)
    keys, rows = [], []
    for line in open(path, encoding="utf-8", errors="replace"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 4:
            keys.append(p[0].split(" ")[0])
            rows.append((p[1], int(p[2]), int(p[3])))
    return keys, rows


def enumerate_static(only=None, snapshots=SNAPSHOTS):
    import bisect, gzip
    boards, today = load(), time.strftime("%Y-%m-%d")
    info = json.loads(get("https://index.commoncrawl.org/collinfo.json") or "[]")
    snaps = [c["id"] for c in info[:snapshots]] or ["CC-MAIN-2026-39"]
    found = {i: set() for i in range(len(PATTERNS))}
    for snap in snaps:
        keys, rows = cluster(snap)
        if not keys:
            print(f"  {snap}: block list not fetched, skipped", flush=True)
            continue
        for i, (system, ask, rx, keyfmt) in enumerate(PATTERNS):
            if only and system not in only:
                continue
            pre, rxc = SURT[ask], re.compile(rx, re.I)
            lo = max(bisect.bisect_left(keys, pre) - 1, 0)
            hi = bisect.bisect_right(keys, pre + "\uffff")
            def block(j):
                f, off, ln = rows[j]
                raw = _raw(CC.format(snap=snap) + f, (off, off + ln - 1))
                if not raw:
                    return None
                try:
                    text = gzip.decompress(raw).decode("utf-8", "replace")
                except Exception:
                    return None
                return {m.group(1) for line in text.splitlines() if line.startswith(pre) for m in rxc.finditer(line)}
            lost = 0
            with ThreadPoolExecutor(8) as ex:
                for got in ex.map(block, range(lo, hi)):
                    if got is None:
                        lost += 1
                    else:
                        found[i] |= got
            print(f"  {snap} {system:16} {ask:30} {hi - lo:5} blocks, {len(found[i]):6} names so far" + (f", {lost} blocks lost" if lost else ""), flush=True)
    for i, (system, ask, rx, keyfmt) in enumerate(PATTERNS):
        if only and system not in only:
            continue
        keep = {s for s in found[i] if 2 <= len(s) <= 60 and s.lower() not in NOT_A_BOARD and not s.startswith(("_", "."))
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%-]*", s)}
        mine, new = boards.setdefault(system, {}), 0
        for s in keep:
            k = keyfmt.format(s=s if system == "smartrecruiters" else s.lower())
            if k not in mine:
                mine[k] = {"seen": today}
                new += 1
        print(f"  {system:16} {ask:32} {len(keep):6} names, {new:6} new  ({len(mine)} known)", flush=True)
    save(boards)
    return boards


def enumerate_boards(only=None):
    """only: the systems to ask for; None for all. The index drops requests
    under load - Workable, SmartRecruiters and Lever came back empty on the
    first pass - so a pattern that got no answer says so, and can be asked
    again on its own:  python3 harvest.py enumerate lever workable"""
    boards, today = load(), time.strftime("%Y-%m-%d")
    info = json.loads(get("https://index.commoncrawl.org/collinfo.json") or "[]")
    apis = [c["cdx-api"] for c in info[:SNAPSHOTS]]
    if not apis:
        print("the index did not answer; the list is left as it was")
        return boards
    print(f"asking {len(apis)} snapshots of the public web index for {len(PATTERNS)} kinds of board address", flush=True)
    for system, ask, rx, keyfmt in PATTERNS:
        if only and system not in only:
            continue
        rx, found, answered, lost = re.compile(rx, re.I), set(), 0, 0
        for api in apis:
            q = urllib.parse.quote(ask, safe="*./")
            n = get(f"{api}?url={q}&showNumPages=true", tries=8)
            try:
                pages = min(json.loads(n)["pages"], MAX_PAGES)
            except Exception:
                continue
            answered += 1
            for p in range(pages):                       # one at a time: in parallel the index answers 503
                t = get(f"{api}?url={q}&fl=url&output=text&page={p}", tries=8)
                if t is None:
                    lost += 1
                    continue
                found |= {m.group(1) for m in rx.finditer(t)}
        if not answered:
            print(f"  {system:16} {ask:32} THE INDEX DID NOT ANSWER - ask again: harvest.py enumerate {system}", flush=True)
            continue
        keep = {s for s in found if 2 <= len(s) <= 60 and s.lower() not in NOT_A_BOARD and not s.startswith(("_", "."))
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%-]*", s)}
        mine = boards.setdefault(system, {})
        new = 0
        for s in keep:
            k = keyfmt.format(s=s if system == "smartrecruiters" else s.lower())
            if k not in mine:
                mine[k] = {"seen": today}
                new += 1
        print(f"  {system:16} {ask:32} {len(keep):6} names, {new:6} new  ({len(mine)} known)"
              + (f"  [{answered}/{len(apis)} snapshots answered, {lost} pages lost]" if answered < len(apis) or lost else ""), flush=True)
        save(boards)
    return boards


def wayback(only=None, since="2025"):
    """A second list, from the Internet Archive. Lever tells crawlers to keep
    out, so Common Crawl holds 28 of its boards; the Archive holds thousands.
    Its index is walked from A to Z, 150,000 addresses a request, picking up
    where the last request stopped."""
    boards, today = load(), time.strftime("%Y-%m-%d")
    for system, ask, rx, keyfmt in PATTERNS:
        if (only and system not in only) or ask.startswith("*."):
            continue
        rxc, found, key, n = re.compile(rx, re.I), set(), None, 0
        while n < 80:
            q = {"url": ask, "fl": "original", "collapse": "urlkey", "from": since, "limit": "150000", "showResumeKey": "true"}
            if key:
                q["resumeKey"] = key
            t = get("http://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(q), timeout=300, tries=6)
            if not t or t.lstrip().startswith("<"):
                print(f"  {system}: the Archive did not answer after {n} requests; keeping what there is", flush=True)
                break
            lines = t.rstrip("\n").split("\n")
            key = None
            if len(lines) >= 2 and lines[-2] == "":
                key, lines = lines[-1], lines[:-2]
            found |= {m.group(1) for line in lines for m in [rxc.search(line)] if m}
            n += 1
            print(f"  {system} {ask}: request {n}, {len(found)} names so far", flush=True)
            if not key:
                break
        keep = {s for s in found if 2 <= len(s) <= 60 and s.lower() not in NOT_A_BOARD and not s.startswith(("_", "."))
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", s)}
        mine, new = boards.setdefault(system, {}), 0
        for s in keep:
            k = keyfmt.format(s=s if system == "smartrecruiters" else s.lower())
            if k not in mine:
                mine[k] = {"seen": today}
                new += 1
        print(f"  {system:16} {ask:32} {len(keep):6} names, {new:6} new  ({len(mine)} known)", flush=True)
        save(boards)
    return boards


def check(boards, minutes=None):
    """Open each board that is due. Never-checked first, then the oldest."""
    src = json.load(open(SOURCES))
    watch = src["watchlist"]
    today, t0 = time.strftime("%Y-%m-%d"), time.time()
    stale = time.strftime("%Y-%m-%d", time.localtime(time.time() - RECHECK_DAYS * 86400))
    due = [(sys_, k) for sys_, d in boards.items() if sys_ in P.ADAPTERS for k, v in d.items()
           if k not in watch.get(sys_, {}) and (v.get("checked") or "") < stale and not v.get("dead", 0) >= 3]
    due.sort(key=lambda x: boards[x[0]][x[1]].get("checked") or "")
    print(f"check: {len(due)} boards due" + (f", {minutes} minutes allowed" if minutes else ""), flush=True)
    lock, n, added, stop = threading.Lock(), [0], [], [False]

    def one(item):
        if stop[0]:
            return
        sys_, k = item
        rec = boards[sys_][k]
        if sys_ in SLOW:
            SLOW[sys_].acquire()
        try:
            rows = list(P.ADAPTERS[sys_](k, None))
            design = [r for r in rows if judge.l1(r.get("title")) is None]
            rec.update({"checked": today, "jobs": len(rows), "design": len(design)})
            rec.pop("dead", None)
            if design:
                name = next((r.get("company") for r in rows if r.get("company") and r["company"] != k), None) or k
                with lock:
                    watch.setdefault(sys_, {})[k] = name
                    added.append((sys_, k, len(design), design[0].get("title")))
        except Exception as e:
            # Only "no such page" says the board is gone. Dover answered
            # "slow down" to twelve askers at once and 1,410 of its 1,442
            # boards were written off as missing; five of eight tried by hand
            # were there. Anything but a 404 leaves the board unchecked, to be
            # asked again.
            if getattr(e, "code", None) in (404, 410):
                rec["checked"] = today
                rec["dead"] = rec.get("dead", 0) + 1     # three strikes and it is dropped
            else:
                rec["asked"] = today
                if getattr(e, "code", None) in (403, 429, 503):
                    time.sleep(8)
        finally:
            if sys_ in SLOW:
                time.sleep(0.4)
                SLOW[sys_].release()
        with lock:
            n[0] += 1
            if n[0] % 500 == 0:
                save(boards)
                tmp = SOURCES + ".tmp"
                json.dump(src, open(tmp, "w"), indent=1, ensure_ascii=False)
                os.replace(tmp, SOURCES)
                print(f"  {n[0]}/{len(due)} checked, {len(added)} boards with a design role so far, {time.time() - t0:.0f}s", flush=True)
            if minutes and time.time() - t0 > minutes * 60:
                stop[0] = True

    # The systems that refuse a crowd get two askers each, on their own. In
    # one queue, ten of the twelve askers stood waiting behind Workable while
    # 20,000 boards on the quick systems went unasked.
    quick = [d for d in due if d[0] not in SLOW]
    lanes = [quick] + [[d for d in due if d[0] == k] for k in SLOW]
    def run(items, workers):
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, items))
    threads = [threading.Thread(target=run, args=(items, WORKERS if i == 0 else 2)) for i, items in enumerate(lanes) if items]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    save(boards)
    tmp = SOURCES + ".tmp"
    json.dump(src, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, SOURCES)
    print(f"checked {n[0]} boards in {time.time() - t0:.0f}s: {len(added)} have a design role and were added to the nightly scrape")
    for sys_, k, d, t in added[:25]:
        print(f"  + {sys_}/{k}: {d} design · {t}")
    total = sum(len(v) for v in boards.values())
    print(f"{total} boards known in all; {sum(len(v) for v in watch.values())} scraped every night")


BATCH = 5000                  # POOL roles per handover to CUT and VISION


def batch(minutes=10):
    """How much POOL to hand to VISION at a time.

    POOL fills far faster than VISION reads (16,000 postings in 90 seconds
    against about 17 roles a minute), so the batch is sized from VISION's
    end: enough new roles that what survives CUT keeps VISION busy until the
    next handover, and no more - anything beyond that only sits in a queue.

        X = VISION's roles per minute x minutes between handovers / share that survives CUT

    All three are measured, from the last runs and the last day's pool."""
    runs = [json.loads(l) for l in open(f"{ROOT}/data/vision_runs.jsonl") if l.strip()] if os.path.exists(f"{ROOT}/data/vision_runs.jsonl") else []
    timed = [r for r in runs if r.get("seconds") and r.get("roles", 0) >= 30 and not r.get("audit")][-4:]
    speed = sum(r["roles"] for r in timed) / max(1, sum(r["seconds"] - r.get("waited", 0) for r in timed)) * 60 if timed else 17.0
    import contracts
    since = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - 86400))
    new = [j for j in contracts.load_pool(f"{ROOT}/data/pool.json")["jobs"] if (j.get("first_seen") or "") >= since and "/" in (j.get("source") or "")]
    survive = (sum(1 for j in new if judge.l1(j.get("title")) is None) / len(new)) if len(new) > 500 else 0.042
    per_board = len(new) / max(1, len({j["source"] for j in new})) if len(new) > 500 else 43
    # His call, 2026-10-05: "overhead is a bitch, send to cut then vision, at
    # every 5k that reach pool." X is fixed; what it means in boards and in
    # reads is still worked out from the measurements.
    x = BATCH
    reads = max(60, round(x * max(survive, 0.005)))
    boards = max(10, round(x / per_board))
    print(f"batch: X = {x} POOL roles = {boards} boards; {survive * 100:.1f}% survive CUT = {reads} for VISION, "
          f"which reads {speed:.1f} a minute: about {reads / max(speed, 1):.0f} minutes a round")
    print(f"BOARDS={boards} READS={reads}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "batch" in args:
        batch()
        raise SystemExit(0)
    b = load()
    if not args or "enumerate" in args:
        named = {a for a in args if a in {p[0] for p in PATTERNS}}
        b = enumerate_boards(named or None) if "--server" in args else enumerate_static(named or None)
    if "wayback" in args:
        b = wayback({a for a in args if a in {p[0] for p in PATTERNS}} or None)
    if not args or "check" in args:
        check(b, int(args[args.index("--minutes") + 1]) if "--minutes" in args else None)
