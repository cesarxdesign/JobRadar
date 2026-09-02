"""deep: fetch the ORIGINAL posting for L1 survivors whose JD is thin.

Aggregators republish a summary. designjobsworld's JSON-LD description runs
about 270 characters - two sentences - and L2 was judging on that. But it
keeps the real ATS link, so the full posting is one request away.

Only L1 survivors are fetched, which is the whole point of judging cheaply
first. Results go into data/jd.json beside the rest.

    python3 deep.py            # enrich every thin survivor
    python3 deep.py --limit 60
"""
import json, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import criteria as c, pool as P

ROOT = Path(__file__).resolve().parent
THIN = 1200          # under this many characters, go and get the real thing


def api_url(u):
    """Prefer a board's API over scraping its HTML - cleaner text, no chrome."""
    m = re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", u or "")
    if m:
        return f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}", "gh"
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{16,})", u or "")
    if m:
        return f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}", "lever"
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{16,})", u or "")
    if m:
        # Ashby job pages are JS-rendered - the HTML has no description in it.
        # The board API does, so fetch the board and match on the job id.
        return (f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}"
                f"?includeCompensation=true#{m.group(2)}"), "ashby"
    return u, "html"


def _ashby(api):
    board, _, jid = api.partition("#")
    req = urllib.request.Request(board, headers=P.UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    for j in d.get("jobs", []):
        if jid and jid in (j.get("jobUrl") or ""):
            return P.strip_html(j.get("descriptionHtml") or j.get("descriptionPlain") or "")
    return ""


def fetch_original(url):
    api, kind = api_url(url)
    if kind == "ashby":
        return _ashby(api)
    req = urllib.request.Request(api, headers=P.UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", "replace")
    if kind == "gh":
        return P.strip_html(json.loads(raw).get("content") or "")
    if kind == "ashby":
        board, _, jid = api.partition("#")
        req2 = urllib.request.Request(board, headers=P.UA)
        with urllib.request.urlopen(req2, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        for j in d.get("jobs", []):
            if jid and jid in (j.get("jobUrl") or ""):
                return P.strip_html(j.get("descriptionHtml") or j.get("descriptionPlain") or "")
        return ""
    if kind == "lever":
        j = json.loads(raw)
        body = [j.get("descriptionPlain") or j.get("description") or ""]
        for sec in (j.get("lists") or []):
            body += [sec.get("text") or "", sec.get("content") or ""]
        body.append(j.get("additionalPlain") or "")
        return P.strip_html(" ".join(body))
    return P.strip_html(raw)


def survivors():
    pool = json.load(open(ROOT / "data" / "pool.json"))["jobs"]
    HAS, EXC = re.compile(c.L1_MUST_HAVE, re.I), re.compile(c.L1_EXCLUDE, re.I)
    JR, LEAD = re.compile(c.L1_JUNIOR, re.I), re.compile(c.L1_NOT_LEADERSHIP, re.I)
    LD = re.compile(c.L1_LEADERSHIP, re.I)
    lead = lambda t: bool(LD.search(t)) and not JR.search("") and not LEAD.search(t)
    out = []
    for x in pool:
        t = x.get("title") or ""
        if not (x.get("active") and HAS.search(t)):
            continue
        if EXC.search(t) and not lead(t):
            continue
        if re.search(c.L1_JUNIOR, t, re.I):
            continue
        out.append(x)
    return out


def main():
    jd = json.loads((ROOT / "data" / "jd.json").read_text())
    todo = [x for x in survivors() if len(jd.get(x["id"]) or "") < THIN and x.get("url")]
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else len(todo)
    todo = todo[:lim]
    print(f"{len(todo)} survivors with a JD under {THIN} chars — fetching the original", flush=True)
    lock, n, t0 = threading.Lock(), [0], time.time()
    got, failed = [0], []

    def one(x):
        try:
            t = fetch_original(x["url"])
        except Exception as e:
            t = None
            with lock:
                failed.append((x["company"], f"{type(e).__name__}"))
        with lock:
            n[0] += 1
            before = len(jd.get(x["id"]) or "")
            if t and len(t) > before:
                jd[x["id"]] = t[:20000]
                got[0] += 1
            if n[0] % 25 == 0 or n[0] == len(todo):
                print(f"  [{n[0]}/{len(todo)}] {got[0]} enriched, {len(failed)} failed, "
                      f"{time.time()-t0:.0f}s", flush=True)
                tmp = ROOT / "data" / "jd.tmp.json"
                tmp.write_text(json.dumps(jd, ensure_ascii=False))
                tmp.replace(ROOT / "data" / "jd.json")

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(one, todo))
    tmp = ROOT / "data" / "jd.tmp.json"
    tmp.write_text(json.dumps(jd, ensure_ascii=False))
    tmp.replace(ROOT / "data" / "jd.json")
    print(f"\nenriched {got[0]} of {len(todo)}; {len(failed)} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
