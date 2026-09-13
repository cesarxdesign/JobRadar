"""ghostbuster: is the posting still there at all.

    pool        -> data/pool.json       every role found. no opinions.
    judge       -> data/verdicts.json   criteria cut the pool. the only opinions.
    fetcher     -> data/originals.json  the same role at the employer.
    ghostbuster -> data/links.json      which postings are dead.
    results     -> data/results.json    what survived, split into three lanes.
    decisions   -> RadarRouting.json    on the Mac. applied/discarded.

A board that sells job ads has no reason to take a posting down. uiuxjobsboard
serves roles from 2018 - Volkswagen, TUI, Cartrack - and 68% of everything on
the radar older than six months comes from that one site. Himalayas is worse
in its way: a removed posting is answered with a redirect to its index rather
than a 404, so the link resolves, the role looks alive, and clicking it lands
you on "103,141 Remote Jobs".

None of that needs a model to detect. One HTTP request per posting answers it,
twelve at a time, in about a minute for the whole board. The signals:

    404 or 410                  the honest ones
    redirect onto a listing     the link works and the job does not
    "no longer available"       the page stayed, the job left

A bot wall is not an answer and never counts as absence - "blocked" is its own
outcome, retried another day. Same for a timeout. The rule is only ever
applied to evidence, never to silence.

This is the cheap half of ghost hunting and it runs before the judge, so
nothing dead costs a token.
"""

import json
import pathlib
import re
import sys
import threading
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import random
import time

import pool as P
from fetcher import Blocked, get

ROOT = pathlib.Path(__file__).resolve().parent
POOL_FILE = ROOT / "data" / "pool.json"
LINKS_FILE = ROOT / "data" / "links.json"

WORKERS = 12
# Retry pass. A wall is usually the same host complaining about how fast we
# knocked, not about us knocking at all - 208 of the first sweep's refusals
# were 429s we caused ourselves. So the slow pass paces per host rather than
# globally: unrelated boards still run in parallel, and no single board sees
# two requests inside the gap.
RETRY_WORKERS = 4
HOST_GAP = 12.0          # seconds between two requests to the same host
JITTER = 0.4             # +/- of the gap, so the pattern is not a metronome
INDEX_PATHS = re.compile(r"^/(jobs|job-?board|careers|search|browse|remote-jobs)/?$", re.I)
DEAD_PHRASES = ("no longer available", "this job has expired", "position has been filled",
                "no longer accepting applications", "job has been closed",
                "this position is closed", "vaga encerrada", "oferta expirada")


def redirected_to_index(url, final):
    """A posting link that lands on a listing page: the job is gone."""
    if url == final:
        return False
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(final)
    return bool(INDEX_PATHS.match(b.path or "/")) and len(a.path) > len(b.path)


_host_at = {}
_host_lock = threading.Lock()


def pace(url):
    """Wait until this host has not been touched for HOST_GAP seconds."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    while True:
        with _host_lock:
            now = time.monotonic()
            gap = HOST_GAP * (1 + random.uniform(-JITTER, JITTER))
            last = _host_at.get(host, 0)
            if now - last >= gap:
                _host_at[host] = now
                return
            wait = gap - (now - last)
        time.sleep(min(wait, 5))


def check(rec, slow=False):
    """One posting, one request, one verdict about its link."""
    url = rec.get("url")
    if not url:
        return {"status": "no_url"}
    if slow:
        pace(url)
    try:
        html, final = get(url, timeout=20 if slow else 12)
    except Blocked:
        return {"status": "blocked", "url": url}
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return {"status": "gone", "url": url, "why": f"HTTP {e.code}"}
        # 403 is a bot wall and 429 is us knocking too hard - both are the
        # board refusing to answer, not the job being gone, and calling them
        # "error" makes 1,000 walls look like 1,000 broken postings.
        if e.code in (401, 403, 429, 503):
            return {"status": "blocked", "url": url, "why": f"HTTP {e.code}"}
        return {"status": "error", "url": url, "why": f"HTTP {e.code}"}
    except Exception as e:
        return {"status": "error", "url": url, "why": type(e).__name__}
    if redirected_to_index(url, final):
        return {"status": "gone", "url": url, "landed": final}
    text = P.strip_html(html, 4000).lower()
    for phrase in DEAD_PHRASES:
        if phrase in text:
            return {"status": "gone", "url": url, "why": phrase}
    return {"status": "alive", "url": url}


def main():
    import contracts
    import criteria

    pool_doc = contracts.load_pool(POOL_FILE)
    out = json.loads(LINKS_FILE.read_text()) if LINKS_FILE.exists() else {}
    must = re.compile(criteria.L1_MUST_HAVE, re.I)
    exc = re.compile(criteria.L1_EXCLUDE, re.I)

    todo = [r for r in pool_doc["jobs"]
            if r.get("active") and (r.get("title") or "")
            and must.search(r["title"]) and not exc.search(r["title"])]
    if "--lanes" in sys.argv:
        res = json.loads((ROOT / "data" / "results.json").read_text())
        ids = {i for k in ("open", "portugal", "unsure") for i in res["lanes"].get(k, [])}
        todo = [r for r in todo if r["id"] in ids]
    slow = "--retry" in sys.argv or "--slow" in sys.argv
    if "--retry" in sys.argv:
        # Only what refused to answer last time. Nothing here is known to be
        # alive or dead, so a wall is the one outcome worth paying to revisit.
        was = {k for k, v in out.items() if v.get("status") == "blocked"}
        todo = [r for r in todo if r["id"] in was]
        # Fewest-first by host, so the big offenders are spread through the run
        # instead of stacking at the front behind one 12-second gap.
        by_host = {}
        for r in todo:
            by_host.setdefault(urllib.parse.urlsplit(r.get("url") or "").netloc, []).append(r)
        todo, rings = [], sorted(by_host.values(), key=len, reverse=True)
        for i in range(max((len(v) for v in rings), default=0)):
            for ring in rings:
                if i < len(ring):
                    todo.append(ring[i])
    if "--limit" in sys.argv:
        todo = todo[:int(sys.argv[sys.argv.index("--limit") + 1])]

    lock, done, tally = threading.Lock(), [0], {}
    t0 = datetime.now(timezone.utc)

    def save():
        tmp = LINKS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        tmp.replace(LINKS_FILE)

    def one(rec):
        r = check(rec, slow=slow)
        r["when"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with lock:
            out[rec["id"]] = r
            done[0] += 1
            tally[r["status"]] = tally.get(r["status"], 0) + 1
            # Out loud as it goes, and on disk every twenty: a run you cannot
            # watch is a run you cannot stop.
            if done[0] % 20 == 0 or done[0] == len(todo):
                print(f"  [{done[0]}/{len(todo)}] {tally}  "
                      f"{(datetime.now(timezone.utc)-t0).seconds}s", flush=True)
                save()

    workers = RETRY_WORKERS if slow else WORKERS
    print(f"checking {len(todo)} links, {workers} at a time"
          + (f", {HOST_GAP:.0f}s between hits on the same host" if slow else ""), flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    save()
    dead = [k for k, v in out.items() if v.get("status") == "gone"]
    print(f"\n{tally}\n{len(dead)} postings are gone", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
