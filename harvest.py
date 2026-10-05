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


def save(b):
    tmp = BOARDS + ".tmp"
    json.dump(b, open(tmp, "w"), separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, BOARDS)


def enumerate_boards():
    boards, today = load(), time.strftime("%Y-%m-%d")
    info = json.loads(get("https://index.commoncrawl.org/collinfo.json") or "[]")
    apis = [c["cdx-api"] for c in info[:SNAPSHOTS]]
    if not apis:
        print("the index did not answer; the list is left as it was")
        return boards
    print(f"asking {len(apis)} snapshots of the public web index for {len(PATTERNS)} kinds of board address", flush=True)
    for system, ask, rx, keyfmt in PATTERNS:
        rx, found = re.compile(rx, re.I), set()
        for api in apis:
            q = urllib.parse.quote(ask, safe="*./")
            n = get(f"{api}?url={q}&showNumPages=true")
            try:
                pages = min(json.loads(n)["pages"], MAX_PAGES)
            except Exception:
                continue
            def page(p):
                t = get(f"{api}?url={q}&fl=url&output=text&page={p}", tries=4)
                return {m.group(1) for m in rx.finditer(t or "")}
            with ThreadPoolExecutor(3) as ex:
                for got in ex.map(page, range(pages)):
                    found |= got
        keep = {s for s in found if 2 <= len(s) <= 60 and s.lower() not in NOT_A_BOARD and not s.startswith(("_", "."))
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%-]*", s)}
        mine = boards.setdefault(system, {})
        new = 0
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
        except Exception:
            rec["checked"] = today
            rec["dead"] = rec.get("dead", 0) + 1         # no such board, or it would not answer; three strikes and it is dropped
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

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(one, due))
    save(boards)
    tmp = SOURCES + ".tmp"
    json.dump(src, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, SOURCES)
    print(f"checked {n[0]} boards in {time.time() - t0:.0f}s: {len(added)} have a design role and were added to the nightly scrape")
    for sys_, k, d, t in added[:25]:
        print(f"  + {sys_}/{k}: {d} design · {t}")
    total = sum(len(v) for v in boards.values())
    print(f"{total} boards known in all; {sum(len(v) for v in watch.values())} scraped every night")


if __name__ == "__main__":
    args = sys.argv[1:]
    b = load()
    if not args or "enumerate" in args:
        b = enumerate_boards()
    if not args or "check" in args:
        check(b, int(args[args.index("--minutes") + 1]) if "--minutes" in args else None)
