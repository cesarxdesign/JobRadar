"""deep: fetch the ORIGINAL posting for the parser survivors whose JD is thin.

Aggregators republish a summary. designjobsworld's JSON-LD description runs
about 270 characters - two sentences - and the judge was judging on that. But it
keeps the real ATS link, so the full posting is one request away.

Only the parser survivors are fetched, which is the whole point of judging cheaply
first. Results go into data/jd.json beside the rest.

    python3 deep.py            # enrich every thin survivor
    python3 deep.py --limit 60
"""
import json, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import criteria as c, pool as P
import contracts

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
    m = re.search(r"jobs\.smartrecruiters\.com/([^/]+)/(\d+)", u or "")
    if m:
        return f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}", "sr"
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{16,})", u or "")
    if m:
        # Ashby job pages are JS-rendered - the HTML has no description in it.
        # The board API does, so fetch the board and match on the job id.
        return (f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}"
                f"?includeCompensation=true#{m.group(2)}"), "ashby"
    m = re.search(r"welcometothejungle\.com/[a-z]{2}/companies/([^/]+)/jobs/([^/?#]+)", u or "")
    if m:
        return (f"https://api.welcometothejungle.com/api/v1/organizations/{m.group(1)}/jobs/{m.group(2)}",
                "wttj")
    m = re.search(r"workatastartup\.com/jobs/(\d+)", u or "")
    if m:
        # Inertia page: the posting is JSON in data-page, the HTML is a shell.
        return f"https://www.workatastartup.com/jobs/{m.group(1)}", "yc"
    m = re.search(r"europa\.eu/eures/portal/jv-se/jv-details/([^/?#]+)", u or "")
    if m:
        # The portal is a JS shell; this is the call it makes for the posting.
        return (f"https://europa.eu/eures/api/jv-searchengine/public/jv/id/{m.group(1)}"
                f"?requestLang=en&preferredLang=null"), "eures"
    m = re.search(r"uiuxjobsboard\.com/job/", u or "")
    if m:
        return u, "uiux"
    m = re.search(r"uxremotetalent\.com/ux-job/", u or "")
    if m:
        return u, "uxrt"
    m = re.search(r"net-empregos\.com/\d+/", u or "")
    if m:
        return u, "netempregos"
    return u, "html"


def _yc_job(raw):
    from html import unescape
    m = re.search(r'data-page="([^"]+)"', raw)
    if not m:
        return {}
    d = json.loads(unescape(m.group(1))).get("props", {})
    j, co = d.get("job") or {}, d.get("company") or {}
    return {"jd": P.strip_html("\n\n".join(filter(None, [j.get("descriptionHtml"),
                                                          j.get("interviewProcessHtml")]))),
            "location": j.get("location") or "", "employment_type": j.get("jobType"),
            "company": co.get("name")}


def _eures_job(raw):
    d = json.loads(raw)
    profiles = d.get("jvProfiles") or {}
    pref = d.get("preferredLanguage")
    prof = profiles.get(pref) or next(iter(profiles.values()), {}) or {}
    return {"jd": P.strip_html(prof.get("description") or ""),
            "company": ((prof.get("employer") or {}).get("name") or None)}


def _wttj_job(raw):
    j = json.loads(raw).get("job") or {}
    offices = [o for o in (j.get("offices") or [j.get("office")]) if isinstance(o, dict)]
    return {"jd": P.strip_html("\n\n".join(filter(None, [j.get("description"), j.get("profile"),
                                                          j.get("recruitment_process")]))),
            "location": "; ".join(dict.fromkeys(
                ", ".join(filter(None, [o.get("city"), o.get("country_code")])) for o in offices)),
            "workplace": P.WTTJ_REMOTE.get(j.get("remote")),
            "company": (j.get("organization") or {}).get("name")}


def _ashby(api):
    board, _, jid = api.partition("#")
    req = urllib.request.Request(board, headers=P.UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    for j in d.get("jobs", []):
        if jid and jid in (j.get("jobUrl") or ""):
            return P.strip_html(j.get("descriptionHtml") or j.get("descriptionPlain") or "")
    return ""


def fetch_posting(url):
    """The original posting: its text AND the panel it prints beside it.

    Resolving only the text left an aggregator's own location and workplace
    standing beside the original's description - the judge read Ashby's words
    under designjobsworld's location. Whatever the original board prints, the
    judge should see."""
    api, kind = api_url(url)
    if kind == "ashby":
        board, _, jid = api.partition("#")
        req = urllib.request.Request(board, headers=P.UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        for j in d.get("jobs", []):
            if jid and jid in (j.get("jobUrl") or ""):
                locs = [j.get("location")] + [(s or {}).get("location")
                                              for s in (j.get("secondaryLocations") or [])]
                return {"jd": P.strip_html(j.get("descriptionHtml") or j.get("descriptionPlain") or ""),
                        "location": "; ".join(dict.fromkeys(x for x in locs if x)),
                        "workplace": j.get("workplaceType"),
                        "employment_type": j.get("employmentType"),
                        "department": j.get("department") or j.get("team"),
                        "company": d.get("name")}
        return {}
    req = urllib.request.Request(api, headers={**P.UA, "Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        enc = r.headers.get_content_charset()
    if not enc:
        m = re.search(rb'charset=["\']?([\w-]+)', body[:4000], re.I)
        enc = m.group(1).decode() if m else None
    if not enc:
        # net-empregos declares nothing at all and is ISO-8859-1. Let the bytes
        # decide: utf-8 raises on a latin-1 accent, so a clean utf-8 decode is
        # proof, and a failure means fall back rather than blot the accents out.
        try:
            body.decode("utf-8")
            enc = "utf-8"
        except UnicodeDecodeError:
            enc = "cp1252"
    # net-empregos is ISO-8859-1; decoded as UTF-8 every accented Portuguese
    # company name comes back as replacement characters.
    raw = body.decode(enc, "replace")
    if kind == "wttj":
        return _wttj_job(raw)
    if kind == "yc":
        return _yc_job(raw)
    if kind == "eures":
        return _eures_job(raw)
    if kind == "gh":
        j = json.loads(raw)
        locs = [(j.get("location") or {}).get("name")]
        for o in (j.get("offices") or []):
            locs += [o.get("name"), o.get("location")]
        return {"jd": P.strip_html(j.get("content") or ""),
                "location": "; ".join(dict.fromkeys(x.strip() for x in locs if x and x.strip())),
                "department": "; ".join(d.get("name") for d in (j.get("departments") or []) if d.get("name")),
                "company": j.get("company_name")}
    if kind == "lever":
        j = json.loads(raw)
        body = [j.get("descriptionPlain") or j.get("description") or ""]
        for sec in (j.get("lists") or []):
            body += [sec.get("text") or "", sec.get("content") or ""]
        body.append(j.get("additionalPlain") or "")
        cat = j.get("categories") or {}
        locs = [cat.get("location")] + list(j.get("allLocations") or [])
        return {"jd": P.strip_html(" ".join(body)),
                "location": "; ".join(dict.fromkeys(x for x in locs if x)),
                "workplace": j.get("workplaceType"),
                "employment_type": cat.get("commitment"),
                "department": cat.get("department") or cat.get("team")}
    if kind == "sr":
        d = json.loads(raw)
        secs = d.get("jobAd", {}).get("sections", {})
        parts = []
        for k in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
            s = secs.get(k) or {}
            if s.get("text"):
                parts.append((s.get("title") or "") + "\n" + s["text"])
        return {"jd": P.strip_html("\n\n".join(parts)),
                "location": P.sr_location(d.get("location")),
                "company": (d.get("company") or {}).get("name")}
    # Everything else: the whole page, every word on it. A board prints what
    # matters wherever it likes - a staleness banner beside the header, the
    # scope in a sidebar, a deadline in the footer - and picking one container
    # means a new patch for every board. The judge reads the page like a
    # person does, chrome and all.
    return {"jd": P.strip_html(raw)}


def fetch_original(url):
    api, kind = api_url(url)
    if kind == "ashby":
        return _ashby(api)
    req = urllib.request.Request(api, headers={**P.UA, "Accept": "text/html,application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", "replace")
    if kind in ("wttj", "yc", "eures"):
        return {"wttj": _wttj_job, "yc": _yc_job, "eures": _eures_job}[kind](raw).get("jd", "")
    if kind == "gh":
        return P.strip_html(json.loads(raw).get("content") or "")
    if kind == "sr":
        # The page renders four titled sections. The API's remote/hybrid
        # booleans do NOT render on the page (checked 2026-09-02), so they
        # stay out - only what renders.
        secs = json.loads(raw).get("jobAd", {}).get("sections", {})
        parts = []
        for k in ("companyDescription", "jobDescription", "qualifications",
                  "additionalInformation"):
            s = secs.get(k) or {}
            if s.get("text"):
                parts.append((s.get("title") or "") + "\n" + s["text"])
        return P.strip_html("\n\n".join(parts))
    if kind == "lever":
        j = json.loads(raw)
        body = [j.get("descriptionPlain") or j.get("description") or ""]
        for sec in (j.get("lists") or []):
            body += [sec.get("text") or "", sec.get("content") or ""]
        body.append(j.get("additionalPlain") or "")
        return P.strip_html(" ".join(body))
    return P.strip_html(raw)


def survivors():
    pool = contracts.load_pool(ROOT / "data" / "pool.json")["jobs"]
    HAS, EXC = re.compile(c.PARSE_MUST_HAVE, re.I), re.compile(c.PARSE_EXCLUDE, re.I)
    JR, LEAD = re.compile(c.PARSE_JUNIOR, re.I), re.compile(c.PARSE_NOT_LEADERSHIP, re.I)
    LD = re.compile(c.PARSE_LEADERSHIP, re.I)
    lead = lambda t: bool(LD.search(t)) and not JR.search("") and not LEAD.search(t)
    out = []
    for x in pool:
        t = x.get("title") or ""
        if not (x.get("active") and HAS.search(t)):
            continue
        if EXC.search(t) and not lead(t):
            continue
        if re.search(c.PARSE_JUNIOR, t, re.I):
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
