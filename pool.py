"""pool: the internet -> data/pool.json

Every role we can find, as found. The pool has NO opinions: it does not decide
what is a design job, what is remote, or what is worth showing. It observes,
normalises the handful of fields everything downstream needs, and remembers.

Identity is the pool's one real job. An id is minted ONCE, on first sight, and
never recomputed - so a company retitling a post does not mint a second role
and orphan a decision that pointed at the first. Radar1 recomputed
sha1(company|title) every run; 21 roles ended up with more than one id.

    python3 pool.py              # scrape and update data/pool.json
    python3 pool.py --dry        # scrape, report, write nothing
"""
import json
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POOL_FILE = ROOT / "data" / "pool.json"
JD_FILE = ROOT / "data" / "jd.json"
SOURCES_FILE = ROOT / "data" / "sources.json"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"}
TIMEOUT = 20


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def identity(company, title):
    """What makes two postings the same role. Parentheticals - (Remote),
    (FTC), (m/f/d) - are decoration, not identity."""
    return norm(company) + "|" + norm(re.sub(r"\([^)]*\)", " ", title or ""))


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


TAG_RE = re.compile(r"<[^>]+>")
CODE_EL_RE = re.compile(r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1\s*>|<!--.*?-->",
                        re.I | re.S)


def strip_html(s, limit=20000):
    from html import unescape
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub(" ", CODE_EL_RE.sub(" ", s or "")))).strip()[:limit]


# --------------------------------------------------------------- adapters
# Each returns raw dicts. Normalisation happens once, below, so a new source
# only has to answer: title, company, url, location, posted, jd_text.

def from_greenhouse(slug):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for j in d.get("jobs", []):
        yield {"title": j.get("title"), "company": slug,
               "url": j.get("absolute_url"),
               "location": (j.get("location") or {}).get("name"),
               "posted": j.get("updated_at") or j.get("first_published"),
               "jd_text": strip_html(j.get("content"))}


def from_ashby(slug):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    for j in d.get("jobs", []):
        yield {"title": j.get("title"), "company": slug,
               "url": j.get("jobUrl"), "location": j.get("location"),
               "posted": j.get("publishedAt"),
               "remote": j.get("isRemote"),
               "salary": (j.get("compensation") or {}).get("summary"),
               "jd_text": strip_html(j.get("descriptionHtml") or j.get("descriptionPlain"))}


def from_lever(slug):
    d = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    for j in d:
        cat = j.get("categories") or {}
        yield {"title": j.get("text"), "company": slug,
               "url": j.get("hostedUrl"), "location": cat.get("location"),
               "workplace": (cat.get("workplaceType") or "").lower() or None,
               "posted": j.get("createdAt"),
               "jd_text": strip_html(j.get("descriptionPlain") or j.get("description"))}


ADAPTERS = {"greenhouse": from_greenhouse, "ashby": from_ashby, "lever": from_lever}


# --------------------------------------------------------------- normalise
XP_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*years?", re.I)
REPORTS_RE = re.compile(r"report(?:s|ing)?\s+(?:directly\s+)?to\s+(?:the\s+)?([A-Z][\w /&-]{2,40})")
REMOTE_RE = re.compile(r"\bremote\b", re.I)
# Most boards give no salary field at all, so it has to come out of the text.
SAL_RE = re.compile(
    r"(?:[€$£]\s?\d{1,3}(?:[,.]\d{3})+\s?(?:-|–|—|to|a)\s?[€$£]?\s?\d{1,3}(?:[,.]\d{3})+"
    r"|[€$£]\s?\d{2,3}[,.]\d{3}\b"
    r"|\d{2,3}\s?[kK]\s?(?:-|–|—|to)\s?[€$£]?\s?\d{2,3}\s?[kK])")
ONSITE_RE = re.compile(r"\bon-?site\b|\bhybrid\b|\bin[- ]office\b", re.I)


def normalise(raw, source):
    """Raw source dict -> the fields everything downstream is allowed to see."""
    loc = raw.get("location") or ""
    jd = raw.get("jd_text") or ""
    remote = raw.get("remote")
    if remote is None:
        wp = raw.get("workplace")
        if wp == "remote":
            remote = True
        elif wp in ("onsite", "on-site", "hybrid"):
            remote = False
        elif REMOTE_RE.search(loc):
            remote = True
        elif ONSITE_RE.search(loc):
            remote = False
    xp = None
    m = XP_RE.search(jd)
    if m:
        try:
            xp = int(m.group(1))
        except ValueError:
            xp = None
    rep = REPORTS_RE.search(jd)
    salary = raw.get("salary")
    if not salary:
        m = SAL_RE.search(jd)
        salary = m.group(0).strip() if m else None
    return {
        "title": (raw.get("title") or "").strip(),
        "company": (raw.get("company") or "").strip(),
        "url": raw.get("url"), "apply_url": raw.get("apply_url"),
        "source": source,
        "remote": remote,
        "country": raw.get("country"),
        "location": loc.strip() or None,
        "salary": salary,
        "years_xp": xp,
        "reports_to": rep.group(1).strip() if rep else None,
        "posted": raw.get("posted"), "updated": raw.get("updated"),
        "restrictions": raw.get("restrictions"),
        "timezones": raw.get("timezones"),
        "workplace": raw.get("workplace"),
        "jd_text": jd or None,
        "jdhash": f"{len(jd)}" if jd else None,
    }


# --------------------------------------------------------------- the run
def scrape(sources):
    out, errors = [], {}
    for platform, slugs in sources["watchlist"].items():
        fn = ADAPTERS.get(platform)
        if not fn:
            errors[platform] = "no adapter"
            continue
        for slug in slugs:
            try:
                got = list(fn(slug))
                out += [normalise(r, f"{platform}/{slug}") for r in got]
            except Exception as e:            # a dead slug must not stop the run
                errors[f"{platform}/{slug}"] = f"{type(e).__name__}: {e}"
    return out, errors


def update(previous, found, run_id, stamp):
    """Fold this run's findings into the pool, minting ids only for new roles."""
    by_id = {r["id"]: r for r in previous}
    by_identity, by_url = {}, {}
    for r in previous:
        by_identity[identity(r["company"], r["title"])] = r["id"]
        if r.get("url"):
            by_url[r["url"]] = r["id"]

    seen, minted = set(), 0
    for rec in found:
        rid = by_url.get(rec.get("url")) or by_identity.get(identity(rec["company"], rec["title"]))
        if rid is None:
            rid = uuid.uuid4().hex[:16]
            minted += 1
            by_id[rid] = {"id": rid, "first_seen": stamp, "first_run": run_id}
            by_identity[identity(rec["company"], rec["title"])] = rid
        prev = by_id[rid]
        prev.update(rec)
        prev["id"] = rid                       # identity is the pool's, not the source's
        prev.setdefault("first_seen", stamp)
        prev.setdefault("first_run", run_id)
        prev["last_seen"] = stamp
        prev["active"] = True
        seen.add(rid)
    for rid, rec in by_id.items():
        if rid not in seen:
            rec["active"] = False              # gone from source. NOT a judgement.
    return list(by_id.values()), minted


def main():
    sources = json.loads(SOURCES_FILE.read_text())
    previous = json.loads(POOL_FILE.read_text())["jobs"] if POOL_FILE.exists() else []
    stamp = now()
    run_id = stamp
    found, errors = scrape(sources)
    jobs, minted = update(previous, found, run_id, stamp)
    active = sum(1 for j in jobs if j["active"])
    print(f"found {len(found)} postings -> {len(jobs)} roles "
          f"({active} active, {minted} newly minted ids)")
    if errors:
        print(f"  {len(errors)} sources failed soft:")
        for k, v in list(errors.items())[:6]:
            print(f"    {k}: {v[:70]}")
    if "--dry" in sys.argv:
        print("  --dry: nothing written")
        return 0
    # JD text is bulk evidence for the judge, not a field of the role. Kept
    # beside the pool so pool.json stays small enough to commit every night.
    jd = {j["id"]: j.pop("jd_text") for j in jobs if j.get("jd_text")}
    POOL_FILE.write_text(json.dumps(
        {"generated_at": stamp, "run_id": run_id,
         "sources": {"ok": len(found), "failed": errors}, "jobs": jobs},
        indent=1, ensure_ascii=False))
    JD_FILE.write_text(json.dumps(jd, ensure_ascii=False))
    print(f"wrote {POOL_FILE} ({POOL_FILE.stat().st_size//1024}K) "
          f"and {JD_FILE} ({JD_FILE.stat().st_size//1024}K)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
