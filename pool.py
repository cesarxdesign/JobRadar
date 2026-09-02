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
import urllib.parse
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from html import unescape
from datetime import datetime, timezone
from pathlib import Path

# Bump whenever an adapter changes what it captures. pool.json records the
# version it was scraped with, and the judge refuses to read data older than
# the code. Fixing an adapter does nothing until the pool is scraped again -
# ashby's secondaryLocations fix sat in the code for three batches while the
# judge kept reading one-country locations off disk and looking wrong for it.
ADAPTER_VERSION = 4

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
    """Fallback identity for a row with no url at all. Parentheticals -
    (Remote), (FTC), (m/f/d) - are decoration, not identity."""
    return norm(company) + "|" + norm(re.sub(r"\([^)]*\)", " ", title or ""))


# One row per posting (Cesar, 2026-09-02). A posting is identified by where it
# lives, and the same posting has one address whatever page linked to it:
# Stripe's careers site says stripe.com/jobs/search?gh_jid=7532733 and
# designjobsworld's apply link says boards.greenhouse.io/stripe/jobs/7532733.
# Both are greenhouse job 7532733.
KEY_RES = [
    ("greenhouse", re.compile(r"gh_jid=(\d+)|greenhouse\.io/[^/]+/jobs/(\d+)")),
    ("ashby", re.compile(r"ashbyhq\.com/[^/]+/([0-9a-f]{8}-[0-9a-f-]{27})")),
    ("lever", re.compile(r"lever\.co/[^/]+/([0-9a-f]{8}-[0-9a-f-]{27})")),
    ("smartrecruiters", re.compile(r"smartrecruiters\.com/[^/]+/(\d+)")),
    ("workable", re.compile(r"workable\.com/[^/]+/j/([A-Za-z0-9]+)")),
    ("teamtailor", re.compile(r"teamtailor\.com/jobs/(\d+)")),
    ("recruitee", re.compile(r"([a-z0-9-]+)\.recruitee\.com/o/([a-z0-9-]+)")),
]


def posting_key(url):
    """The address of a posting, the same from every page that links to it.
    Falls back to the url itself, stripped of tracking. None without a url."""
    u = (url or "").strip()
    if not u:
        return None
    for name, rx in KEY_RES:
        m = rx.search(u)
        if m:
            return name + ":" + "/".join(g for g in m.groups() if g)
    u = re.sub(r"[?&](utm_[a-z]+|ref|source|src|gh_src)=[^&#]*", "", u)
    u = re.sub(r"\?$", "", u.split("#")[0]).rstrip("/").lower()
    return re.sub(r"^https?://(www\.)?", "", u)


ATS_KEYS = tuple(name + ":" for name, _ in KEY_RES)


def copy_key(company, title):
    """Second tier, for aggregators that link to their own page and not to
    the original (Jobicy, Arbeitnow, Remotive): the same company and title as
    a posting a board reported THIS run is a copy of that posting. Company
    names are squashed - "Eight Sleep" and the slug "eightsleep" are one."""
    return (re.sub(r"[^a-z0-9]", "", (company or "").lower()),
            norm(re.sub(r"\([^)]*\)", " ", title or "")))


def rank(source):
    """A company board is the original; an aggregator republishes it. When
    both report the same posting the board's fields win and the aggregator
    is recorded as another place it was seen. Never the other way round -
    that is how 110 board rows were overwritten by designjobsworld's copy."""
    return 1 if (source or "").split("/")[0] in AGGREGATORS else 2


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


TAG_RE = re.compile(r"<[^>]+>")
CODE_EL_RE = re.compile(r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1\s*>|<!--.*?-->",
                        re.I | re.S)


BLOCK_RE = re.compile(r"</(p|div|li|ul|ol|h[1-6]|section|tr|table|blockquote)\s*>"
                      r"|<br\s*/?>|<(p|div|li|h[1-6])\b[^>]*>", re.I)
LI_RE = re.compile(r"<li\b[^>]*>", re.I)


def strip_html(s, limit=20000):
    """Keep the block structure. Collapsing every tag to a space turned a job
    description into one unbroken 8,000-character paragraph - unreadable for a
    person, and it loses the headings that say what a section is."""
    from html import unescape
    # Unescape FIRST. Greenhouse returns entity-encoded HTML, so stripping
    # tags before unescaping turned &lt;div&gt; into a literal <div> in the
    # text - the tags came back after they had been removed.
    t = unescape(s or "")
    t = CODE_EL_RE.sub(" ", t)
    t = LI_RE.sub("\n\u2022 ", t)              # bullets stay bullets
    t = BLOCK_RE.sub("\n", t)
    t = unescape(TAG_RE.sub(" ", t))
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()[:limit]


# --------------------------------------------------------------- adapters
# Each returns raw dicts. Normalisation happens once, below, so a new source
# only has to answer: title, company, url, location, posted, jd_text.

def from_greenhouse(slug, cfg=None):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for j in d.get("jobs", []):
        # `location` is the primary office only; `offices` holds the rest.
        locs = [(j.get("location") or {}).get("name")]
        for o in (j.get("offices") or []):
            locs += [o.get("name"), o.get("location")]
        yield {"title": j.get("title"), "company": slug,
               "url": j.get("absolute_url"),
               "location": "; ".join(dict.fromkeys(
                   x.strip() for x in locs if x and x.strip())),
               "posted": j.get("updated_at") or j.get("first_published"),
               "department": "; ".join(d.get("name") for d in (j.get("departments") or [])
                                       if d.get("name")) or None,
               "jd_text": strip_html(j.get("content"))}


def from_ashby(slug, cfg=None):
    """Ashby splits locations across THREE fields. `location` holds only the
    primary one: a role listed as Remote Germany; Remote Portugal; Remote
    Netherlands returns "Remote Germany" there and the rest in
    secondaryLocations. Reading only `location` made every multi-location
    Ashby role look single-country, and the judge cut them on that."""
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    for j in d.get("jobs", []):
        locs = [j.get("location")]
        for sec in (j.get("secondaryLocations") or []):
            if isinstance(sec, dict):
                # sec["location"] is the string the side panel renders. Its
                # address block is not shown, and appending it added bare
                # country names that appear nowhere on the page.
                locs.append(sec.get("location"))
        # NOT j["address"]: that is the company's registered mailing address,
        # not a hiring location. Circle's is a Delaware agent address, so
        # appending it turned "Remote" into "Remote; United States" and the
        # judge cut the role on a restriction that was never on the page.
        loc = "; ".join(dict.fromkeys(x.strip() for x in locs if x and x.strip()))
        yield {"title": j.get("title"), "company": slug,
               "url": j.get("jobUrl"), "location": loc,
               "posted": j.get("publishedAt"),
               "workplace": (j.get("workplaceType") or "").lower() or None,
               "employment_type": j.get("employmentType"),
               "department": j.get("department") or j.get("team"),
               "remote": j.get("isRemote"),
               "salary": (j.get("compensation") or {}).get("summary"),
               "jd_text": strip_html(j.get("descriptionHtml") or j.get("descriptionPlain"))}


def from_lever(slug, cfg=None):
    d = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    for j in d:
        cat = j.get("categories") or {}
        # allLocations is the full list; `location` is just the first.
        locs = [cat.get("location")] + list(cat.get("allLocations") or [])
        # Lever splits a posting across four fields. descriptionPlain is only
        # the intro; `lists` carries "What you'll do" and "Who you are" - the
        # actual role. Taking descriptionPlain alone gave the judge 20% of the
        # posting. workplaceType is top-level, NOT inside categories.
        body = [j.get("descriptionPlain") or j.get("description") or ""]
        for sec in (j.get("lists") or []):
            body += [sec.get("text") or "", sec.get("content") or ""]
        body.append(j.get("additionalPlain") or j.get("additional") or "")
        yield {"title": j.get("text"), "company": slug,
               "url": j.get("hostedUrl"),
               "location": "; ".join(dict.fromkeys(
                   x.strip() for x in locs if x and x.strip())),
               "workplace": (j.get("workplaceType") or "").lower() or None,
               "employment_type": cat.get("commitment"),
               "department": cat.get("department") or cat.get("team"),
               "posted": j.get("createdAt"),
               "jd_text": strip_html(" ".join(body))}


ADAPTERS = {"greenhouse": from_greenhouse, "ashby": from_ashby, "lever": from_lever}


# --------------------------------------------------------- ported from v1
# These are Radar1's readers, kept as they were. Two things removed from each:
#   - title_ok(): Radar1 filtered by title mid-scrape. Pool does not filter.
#   - per-job enrichment: Radar1 fetched the original page when a listing came
#     back thin. That is the deep fetch, and it waits for L1.

def fmt_range(lo, hi, cur=""):
    def f(n):
        try:
            n = float(n)
        except (TypeError, ValueError):
            return None
        return f"{int(n/1000)}k" if n >= 1000 else str(int(n))
    lo, hi = f(lo), f(hi)
    sym = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(cur, cur or "")
    if lo and hi and lo != hi:
        return f"{sym}{lo}\u2013{hi}"
    return f"{sym}{lo or hi}" if (lo or hi) else None


def get_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def from_recruitee(slug, name=None):
    for o in get_json(f"https://{slug}.recruitee.com/api/offers/").get("offers", []):
        yield {"company": name or slug.title(), "title": o.get("title"),
               "url": o.get("careers_url") or o.get("url"),
               "location": o.get("location") or "", "remote": bool(o.get("remote")),
               "posted": o.get("published_at"), "updated": o.get("updated_at"),
               "jd_text": strip_html(o.get("description"))}


def from_workable(slug, name=None):
    d = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    for j in d.get("jobs", []):
        locs = j.get("locations") or []
        loc = ", ".join(dict.fromkeys(
            ", ".join(filter(None, [l.get("city"), l.get("country")]))
            for l in locs if isinstance(l, dict))) or \
            ", ".join(filter(None, [j.get("city"), j.get("country")]))
        yield {"company": d.get("name") or name or slug, "title": j.get("title"),
               "url": j.get("url"), "location": loc,
               "remote": bool(j.get("telecommuting")) or None,
               "posted": j.get("published_on") or j.get("created_at"),
               "jd_text": strip_html(j.get("description"))}


def from_pinpoint(slug, name=None):
    d = get_json(f"https://{slug}.pinpointhq.com/postings.json")
    for j in (d.get("data") if isinstance(d, dict) else d) or []:
        loc = j.get("location") or {}
        loc_s = loc.get("name") if isinstance(loc, dict) else str(loc or "")
        wt = (j.get("workplace_type") or "").lower()
        # The page prints a panel - Workplace type, Employment Type,
        # Department, Reporting To - and a body in four titled sections. Only
        # the first section was read, and the panel not at all, so a posting
        # whose panel says "Fully remote" reached the judge as bare "Portugal"
        # and came back unclear.
        body = []
        for head, text in (("", j.get("description")),
                           (j.get("key_responsibilities_header"), j.get("key_responsibilities")),
                           (j.get("skills_knowledge_expertise_header"), j.get("skills_knowledge_expertise")),
                           (j.get("benefits_header"), j.get("benefits"))):
            if text:
                body.append(((head or "").strip() + "\n" + strip_html(text)).strip())
        yield {"company": name or slug, "title": (j.get("title") or "").strip(),
               "url": j.get("url") or f"https://{slug}.pinpointhq.com/en/postings/{j.get('id')}",
               "location": loc_s or "",
               "workplace": (j.get("workplace_type_text") or "").strip() or None,
               "employment_type": (j.get("employment_type_text") or "").strip() or None,
               "department": ((j.get("job") or {}).get("department") or {}).get("name"),
               "reports_to": (j.get("reporting_to") or "").strip() or None,
               "remote": ("remote" in wt) or bool(re.search(r"remote", loc_s or "", re.I)) or None,
               "salary": (j.get("compensation") or "").strip() or None,
               "posted": j.get("published_at") or j.get("created_at"),
               "jd_text": "\n\n".join(body)}


def from_freshteam(slug, name=None):
    d = get_json(f"https://{slug}.freshteam.com/hire/widgets/jobs.json")
    for j in d.get("jobs", []):
        if j.get("deleted") or str(j.get("status", "")).lower() in ("closed", "on_hold"):
            continue
        remote = str(j.get("remote", "")).lower() == "true"
        locs = j.get("preferred_remote_job_locations") or ""
        yield {"company": name or slug, "title": j.get("title"), "url": j.get("url"),
               "location": (locs if isinstance(locs, str) else ", ".join(map(str, locs)))
                           or ("Remote" if remote else ""),
               "remote": remote or None, "posted": j.get("created_at"),
               "jd_text": strip_html(unescape(j.get("description") or ""))}


def from_personio(host, name=None):
    """XML feed, with search.json as the fallback some sites need."""
    try:
        root = ET.fromstring(get_text(f"https://{host}/xml"))
    except Exception:
        for j in get_json(f"https://{host}/search.json"):
            loc = ", ".join(dict.fromkeys(j.get("offices") or []))
            yield {"company": (j.get("subcompany") or "").strip() or name or host,
                   "title": (j.get("name") or "").strip(),
                   "url": f"https://{host}/job/{j.get('id')}", "location": loc,
                   "remote": bool(re.search(r"remote", loc, re.I)) or None,
                   "jd_text": strip_html(j.get("description"))}
        return
    for pos in root.iter("position"):
        loc = ", ".join(dict.fromkeys(o.text.strip() for o in pos.iter("office") if o.text))
        raw = " ".join(x.findtext("value") or "" for x in pos.iter("jobDescription"))
        yield {"company": (pos.findtext("subcompany") or "").strip() or name or host,
               "title": (pos.findtext("name") or "").strip(),
               "url": f"https://{host}/job/{(pos.findtext('id') or '').strip()}",
               "location": loc,
               "remote": bool(re.search(r"remote", loc, re.I)) or None,
               "posted": (pos.findtext("createdAt") or "").strip() or None,
               "jd_text": strip_html(raw)}


def from_teamtailor(host, name=None):
    root = ET.fromstring(get_text(f"https://{host}/jobs.rss"))
    for item in root.iter("item"):
        g = lambda t: (item.findtext(t) or "").strip()
        loc = ", ".join(filter(None, [g("location"), g("region"), g("country")]))
        title = g("title")
        yield {"company": name or host, "title": title, "url": g("link"),
               "location": loc,
               "remote": bool(re.search(r"remote", f"{title} {loc}", re.I)) or None,
               "posted": g("pubDate") or None, "jd_text": strip_html(g("description"))}


# ---- aggregators: many companies per feed, company comes from the data ----

def agg_remotive():
    for j in get_json("https://remotive.com/api/remote-jobs?category=design").get("jobs", []):
        yield {"company": j.get("company_name"), "title": j.get("title"),
               "url": j.get("url"), "location": j.get("candidate_required_location"),
               "remote": True, "salary": (j.get("salary") or "").strip() or None,
               "posted": j.get("publication_date"),
               "jd_text": strip_html(j.get("description"))}


def agg_jobicy():
    for j in get_json("https://jobicy.com/api/v2/remote-jobs?count=200&tag=design").get("jobs", []):
        yield {"company": j.get("companyName"), "title": j.get("jobTitle"),
               "url": j.get("url"), "location": j.get("jobGeo"), "remote": True,
               "salary": fmt_range(j.get("annualSalaryMin"), j.get("annualSalaryMax"),
                                   j.get("salaryCurrency")),
               "posted": j.get("pubDate"), "jd_text": strip_html(j.get("jobDescription"))}


def agg_workingnomads():
    for j in get_json("https://www.workingnomads.com/api/exposed_jobs/"):
        if (j.get("category_name") or "").lower() != "design":
            continue
        yield {"company": j.get("company_name"), "title": j.get("title"),
               "url": j.get("url"), "location": j.get("location"), "remote": True,
               "posted": j.get("pub_date"), "jd_text": strip_html(j.get("description"))}


def agg_remoteok():
    for j in get_json("https://remoteok.com/api"):
        if not isinstance(j, dict) or not j.get("position"):
            continue
        lo, hi = j.get("salary_min") or 0, j.get("salary_max") or 0
        yield {"company": j.get("company"), "title": j.get("position"),
               "url": j.get("url"), "location": j.get("location"), "remote": True,
               "salary": fmt_range(lo, hi, "USD") if (lo or hi) else None,
               "posted": j.get("date"), "jd_text": strip_html(j.get("description"))}


def agg_arbeitnow():
    for j in get_json("https://www.arbeitnow.com/api/job-board-api").get("data", []):
        yield {"company": j.get("company_name"), "title": j.get("title"),
               "url": j.get("url"), "location": j.get("location"),
               "remote": bool(j.get("remote")),
               "posted": datetime.fromtimestamp(j["created_at"], timezone.utc).isoformat()
                         if j.get("created_at") else None,
               "jd_text": strip_html(j.get("description"))}


def agg_landingjobs():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for j in get_json("https://landing.jobs/api/v1/jobs?limit=200"):
        if (j.get("expires_at") or "9999") < today:
            continue
        m = re.search(r"landing\.jobs/at/([^/]+)/", j.get("url") or "")
        locs = j.get("locations") or []
        loc = ", ".join(l.get("city") or l.get("name") or l.get("country") or ""
                        if isinstance(l, dict) else str(l) for l in locs) \
              if isinstance(locs, list) else str(locs)
        yield {"company": m.group(1).replace("-", " ").title() if m else "",
               "title": j.get("title"), "url": j.get("url"),
               "location": loc or "Portugal", "remote": bool(j.get("remote")),
               "salary": fmt_range(j.get("gross_salary_low"), j.get("gross_salary_high"),
                                   j.get("currency_code")),
               "posted": j.get("published_at"), "updated": j.get("updated_at"),
               "jd_text": strip_html(j.get("role_description"))}


def agg_wwr():
    root = ET.fromstring(get_text("https://weworkremotely.com/categories/remote-design-jobs.rss"))
    for item in root.iter("item"):
        g = lambda t: (item.findtext(t) or "").strip()
        raw = g("title")
        company, _, title = raw.partition(":")
        if not title:
            company, title = "", raw
        yield {"company": company.strip(), "title": title.strip(), "url": g("link"),
               "location": g("region"), "remote": True, "posted": g("pubDate") or None,
               "jd_text": strip_html(g("description"))}


ADAPTERS.update({"recruitee": from_recruitee, "workable": from_workable,
                 "pinpoint": from_pinpoint, "freshteam": from_freshteam,
                 "personio": from_personio, "teamtailor": from_teamtailor})
AGGREGATORS = {"remotive": agg_remotive, "jobicy": agg_jobicy,
               "workingnomads": agg_workingnomads, "remoteok": agg_remoteok,
               "arbeitnow": agg_arbeitnow, "landingjobs": agg_landingjobs,
               "weworkremotely": agg_wwr}



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
    import contracts
    contracts.check_rendered(raw)
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
        # These render in the side panel and contracts.RENDERED says the judge
        # may read them. The adapters were yielding them and normalise was
        # dropping them on the floor, so Employment Type and Department have
        # been blank in every prompt ever sent.
        "employment_type": raw.get("employment_type"),
        "department": raw.get("department"),
        "years_xp": xp,
        "reports_to": raw.get("reports_to") or (rep.group(1).strip() if rep else None),
        "posted": raw.get("posted"), "updated": raw.get("updated"),
        "restrictions": raw.get("restrictions"),
        "timezones": raw.get("timezones"),
        "workplace": raw.get("workplace"),
        "jd_text": jd or None,
        "jdhash": f"{len(jd)}" if jd else None,
    }


# --------------------------------------------------------------- the run
# ------------------------------------------------- the remaining 12, ported
# Listing calls only. Radar1 detail-fetched each role during the scrape; that
# is the deep fetch and it waits for L1.

def _name(cfg):
    return cfg.get("name") if isinstance(cfg, dict) else cfg


def from_bamboohr(slug, cfg=None):
    for j in get_json(f"https://{slug}.bamboohr.com/careers/list").get("result") or []:
        loc = j.get("atsLocation") or j.get("location") or {}
        loc_s = ", ".join(filter(None, [loc.get("city"), loc.get("state"), loc.get("country")]))
        title = j.get("jobOpeningName")
        remote = j.get("isRemote")
        if remote is None:
            remote = bool(re.search(r"remote", f"{title} {loc_s}", re.I)) or None
        yield {"company": _name(cfg) or slug, "title": title,
               "url": f"https://{slug}.bamboohr.com/careers/{j['id']}",
               "location": loc_s, "remote": remote}


def from_breezy(slug, cfg=None):
    for j in get_json(f"https://{slug}.breezy.hr/json"):
        loc = j.get("location") or {}
        yield {"company": _name(cfg) or slug, "title": j.get("name"), "url": j.get("url"),
               "location": loc.get("name") or "", "remote": bool(loc.get("is_remote")) or None,
               "salary": (j.get("salary") or "").strip() or None,
               "posted": j.get("published_date"), "jd_text": strip_html(j.get("description"))}


def from_smartrecruiters(slug, cfg=None):
    """Page until the board is exhausted. Radar1 stopped at 5 pages; Bosch
    alone has 4784 postings, so that cap hid ~20k roles across 18 companies."""
    offset = 0
    for _ in range(200):
        d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
                     f"?limit=100&offset={offset}")
        items = d.get("content") or []
        for j in items:
            loc = j.get("location") or {}
            yield {"company": (j.get("company") or {}).get("name") or _name(cfg) or slug,
                   "title": j.get("name"),
                   "url": f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                   "location": loc.get("fullLocation") or ", ".join(
                       filter(None, [loc.get("city"), (loc.get("country") or "").upper()])),
                   "remote": bool(loc.get("remote")) or None, "posted": j.get("releasedDate")}
        offset += 100
        if not items or offset >= (d.get("totalFound") or 0):
            break


def from_rippling(slug, cfg=None):
    try:
        d = get_json(f"https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs")
    except Exception:
        html = get_text(f"https://ats.rippling.com/{slug}/jobs")
        m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return
        def find_items(o):
            if isinstance(o, dict):
                v = o.get("items")
                if isinstance(v, list) and v and isinstance(v[0], dict) and "name" in v[0]:
                    return v
                for x in o.values():
                    r = find_items(x)
                    if r:
                        return r
            elif isinstance(o, list):
                for x in o:
                    r = find_items(x)
                    if r:
                        return r
        for j in find_items(json.loads(m.group(1))) or []:
            locs = [l for l in (j.get("locations") or []) if isinstance(l, dict)]
            loc = ", ".join(dict.fromkeys(filter(None, [
                ", ".join(filter(None, [l.get("city"), l.get("country")])) or l.get("name")
                for l in locs])))
            yield {"company": _name(cfg) or slug, "title": j.get("name"), "url": j.get("url"),
                   "location": loc,
                   "remote": any((l.get("workplaceType") or "").upper() == "REMOTE"
                                 for l in locs) or None}
        return
    for j in d if isinstance(d, list) else []:
        loc = (j.get("workLocation") or {}).get("label") or ""
        yield {"company": _name(cfg) or slug, "title": j.get("name"), "url": j.get("url"),
               "location": loc, "remote": bool(re.search(r"remote", loc, re.I)) or None}


def from_jazzhr(slug, cfg=None):
    html = get_text(f"https://{slug}.applytojob.com/apply")
    for block in re.findall(r'class="list-group-item"[\s\S]*?</ul>', html):
        am = re.search(r'<a[^>]*href="([^"]*/apply/[A-Za-z0-9]+/[^"]*)"[^>]*>([\s\S]*?)</a>', block)
        if not am:
            continue
        lm = re.search(r"fa-map-marker[^>]*></i>\s*([^<]{0,80})", block)
        loc = lm.group(1).strip() if lm else ""
        yield {"company": _name(cfg) or slug,
               "title": re.sub(r"\s+", " ", strip_html(am.group(2), 150)).strip(),
               "url": am.group(1), "location": loc,
               "remote": bool(re.search(r"remote", loc, re.I)) or None}


def from_manatal(slug, cfg=None):
    base = f"https://www.careers-page.com/{slug}"
    html = get_text(base)
    seen = set()
    for m in re.finditer(r'<a\b[^>]*href="([^"]*/job/[A-Za-z0-9]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        u = urllib.parse.urljoin(base, m.group(1))
        if u in seen:
            continue
        seen.add(u)
        yield {"company": _name(cfg) or slug,
               "title": re.sub(r"\s+", " ", strip_html(m.group(2), 200)).strip(),
               "url": u, "location": ""}


def from_join(slug, cfg=None):
    html = get_text(f"https://join.com/companies/{slug}")
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return
    try:
        items = json.loads(m.group(1))["props"]["pageProps"]["initialState"]["jobs"]["items"]
    except (KeyError, TypeError, ValueError):
        return
    for j in items:
        city = j.get("city") or {}
        loc = ", ".join(filter(None, [city.get("cityName"), city.get("countryName")]))
        if (j.get("remoteType") or "").upper() == "ANYWHERE":
            loc = ", ".join(filter(None, [loc, "Worldwide"]))
        yield {"company": _name(cfg) or slug, "title": j.get("title"),
               "url": f"https://join.com/companies/{slug}/{j['idParam']}" if j.get("idParam") else None,
               "location": loc,
               "remote": ((j.get("workplaceType") or "").upper() == "REMOTE") or None,
               "posted": j.get("createdAt")}


def from_zoho(key, cfg=None):
    c = cfg if isinstance(cfg, dict) else {}
    sub, tld = c.get("sub", key), c.get("tld", "com")
    html = get_text(f"https://{sub}.zohorecruit.{tld}/jobs/Careers")
    m = (re.search(r'value="([^"]*)"\s*id="jobs"', html)
         or re.search(r'id="jobs"[^>]*value="([^"]*)"', html))
    if not m:
        return
    data = json.loads(unescape(m.group(1)))
    for j in (data if isinstance(data, list) else data.get("jobs", [])):
        if str(j.get("Publish", "true")).lower() == "false":
            continue
        title = j.get("Job_Opening_Name") or ""
        jid = j.get("id") or j.get("Id")
        loc = ", ".join(filter(None, [j.get("City"), j.get("State"), j.get("Country")]))
        yield {"company": _name(cfg) or sub, "title": title,
               "url": f"https://{sub}.zohorecruit.{tld}/jobs/Careers/{jid}/"
                      f"{re.sub(r'[^A-Za-z0-9]+', '-', title).strip('-')}",
               "location": loc,
               "remote": bool(re.search(r"remote", f"{title} {j.get('Job_Type') or ''} {loc}", re.I)) or None,
               "posted": j.get("Date_Opened")}


def from_workday(key, cfg=None):
    c = cfg if isinstance(cfg, dict) else {}
    tenant, host, site = c.get("tenant", key), c.get("host"), c.get("site")
    if not (host and site):
        return
    seen = set()
    for q in ("design", "ux"):
        offset = 0
        for _ in range(5):
            body = json.dumps({"appliedFacets": {}, "limit": 20,
                               "offset": offset, "searchText": q}).encode()
            req = urllib.request.Request(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                                         data=body, headers={**UA,
                                         "Content-Type": "application/json",
                                         "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            for pst in d.get("jobPostings") or []:
                ep = pst.get("externalPath")
                if not ep or ep in seen:
                    continue
                seen.add(ep)
                loc = pst.get("locationsText") or ""
                yield {"company": _name(cfg) or tenant, "title": pst.get("title"),
                       "url": f"https://{host}/{site}{ep}", "location": loc,
                       "remote": bool(re.search(r"remote", loc, re.I)) or None}
            offset += 20
            if offset >= (d.get("total") or 0):
                break


def from_successfactors(key, cfg=None):
    c = cfg if isinstance(cfg, dict) else {}
    host, loc = c.get("host", key), c.get("loc", "")
    seen = set()
    for kw in ("designer", "design", "UX designer", "UX analyst", "user experience"):
        try:
            html = get_text(f"https://{host}/search/?q={urllib.parse.quote(kw)}"
                            f"&locationsearch={urllib.parse.quote(loc)}")
        except Exception:
            continue
        for m in re.finditer(r'href="(/job/[^"]+/(\d+)/?)"[^>]*class="jobTitle-link"[^>]*>(.*?)</a>',
                             html, re.S):
            path, jid, title = m.group(1), m.group(2), strip_html(m.group(3), 200).strip()
            if jid in seen or not title:
                continue
            seen.add(jid)
            yield {"company": _name(cfg) or host, "title": title,
                   "url": f"https://{host}{path}", "location": loc.title() if loc else ""}


def from_comeet(slug, cfg=None):
    for j in get_json(f"https://www.comeet.co/careers-api/2.0/company/{slug}/positions?details=true"):
        loc = j.get("location") or {}
        loc_s = ", ".join(filter(None, [loc.get("city"), loc.get("country")])) if isinstance(loc, dict) else str(loc or "")
        yield {"company": _name(cfg) or slug, "title": j.get("name"),
               "url": j.get("url_comeet_hosted_page") or j.get("url_active_page"),
               "location": loc_s, "remote": bool(re.search(r"remote", loc_s, re.I)) or None,
               "jd_text": strip_html(" ".join(d.get("value") or "" for d in (j.get("details") or [])))}


def agg_himalayas():
    url = "https://himalayas.app/jobs/api?limit=100"
    for _ in range(20):
        d = get_json(url)
        for j in d.get("jobs", []):
            sal = fmt_range(j.get("minSalary"), j.get("maxSalary"), j.get("currency"))
            if sal and j.get("salaryPeriod") == "hourly":
                sal += "/h"
            yield {"company": j.get("companyName"), "title": j.get("title"),
                   "url": j.get("applicationLink") or j.get("guid"),
                   "location": ", ".join(j.get("locationRestrictions") or []),
                   "remote": True, "salary": sal,
                   "restrictions": j.get("locationRestrictions") or None,
                   "timezones": j.get("timezoneRestrictions") or None,
                   "posted": datetime.fromtimestamp(j["pubDate"], timezone.utc).isoformat()
                             if j.get("pubDate") else None,
                   "jd_text": strip_html(j.get("description"))}
        cur = d.get("nextCursor")
        if not cur:
            break
        url = f"https://himalayas.app/jobs/api?limit=100&cursor={cur}"


DJW_ATS_RE = re.compile(
    r"https?://(?:[\w.-]*\.)?(?:greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|"
    r"recruitee\.com|teamtailor\.com|bamboohr\.com|breezy\.hr|smartrecruiters\.com)/[^\"'\s]+")


def agg_designjobsworld():
    """active_jobs.xml is the live set (1904). recent_jobs.xml is a 412-url
    window, and Radar1 sliced that to 250 - so this source ran at 13%."""
    xml = get_text("https://designjobs.world/active_jobs.xml")
    urls = re.findall(r"<loc>(https://designjobs\.world/jobs/[^<]+)</loc>", xml)
    # 1,904 independent page fetches. Sequentially that is 35 minutes and it
    # was the whole reason a scrape took 45; concurrently it is a couple.
    from concurrent.futures import ThreadPoolExecutor
    def _page(u):
        try:
            return get_text(u)
        except Exception:
            return None
    # Yield each posting as its page lands, so drain() heartbeats and the
    # run is never dark. Collecting all 1,904 into a list first was a black
    # box for the whole 40 minutes - nothing printed until the last page.
    from concurrent.futures import as_completed
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(_page, u) for u in urls]
        for fut in as_completed(futs):
            h = fut.result()
            if not h:
                continue
            ld = None
            for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
                try:
                    dd = json.loads(x)
                    if dd.get("@type") == "JobPosting":
                        ld = dd
                        break
                except Exception:
                    pass
            if not ld or not ld.get("title"):
                continue
            pa = ld.get("potentialAction") or {}
            tgt = (pa.get("target") or {}) if isinstance(pa, dict) else {}
            apply_to = tgt.get("urlTemplate") if isinstance(tgt, dict) else None
            m = DJW_ATS_RE.search(h)
            if m:
                apply_to = m.group(0)
            locs = ld.get("jobLocation") or []
            if isinstance(locs, dict):
                locs = [locs]
            parts = []
            for l in locs:
                a = (l.get("address") or {}) if isinstance(l, dict) else {}
                if isinstance(a, dict):
                    parts += [a.get("addressLocality"), a.get("addressCountry")]
            alr = ld.get("applicantLocationRequirements") or []
            if isinstance(alr, dict):
                alr = [alr]
            parts += [x.get("name") for x in alr if isinstance(x, dict)]
            loc = ", ".join(dict.fromkeys(str(x) for x in parts if x))
            yield {"company": (ld.get("hiringOrganization") or {}).get("name") or "?",
                   "title": ld.get("title"),
                   "url": apply_to or (ld.get("url") or ""), "location": loc,
                   "remote": bool(re.search(r"remote|anywhere|telecommute",
                                            f"{loc} {ld.get('jobLocationType') or ''}", re.I)) or None,
                   "posted": ld.get("datePosted"), "jd_text": strip_html(ld.get("description"))}


ADAPTERS.update({"bamboohr": from_bamboohr, "breezy": from_breezy,
                 "smartrecruiters": from_smartrecruiters, "rippling": from_rippling,
                 "jazzhr": from_jazzhr, "manatal": from_manatal, "join": from_join,
                 "zoho": from_zoho, "workday": from_workday,
                 "successfactors": from_successfactors, "comeet": from_comeet})
AGGREGATORS.update({"himalayas": agg_himalayas, "designjobsworld": agg_designjobsworld})


SKIP = set()          # sources deliberately not scraped this run


def scrape(sources, on_batch=None):
    """Every source, failing soft, reporting as it goes.

    Readers are generators, so items are counted as they arrive rather than
    when a source finishes. A source that makes 1900 internal requests
    (designjobsworld) heartbeats every 5s instead of going dark for 20 minutes.
    on_batch(rows) is called after each source so the caller can checkpoint.
    """
    out, errors, done = [], {}, 0
    # SKIP applies to company boards too. It only ever filtered aggregators,
    # so --skip greenhouse would have scraped greenhouse anyway.
    jobs = [(p, s_, cfg) for p, sl in sources["watchlist"].items() if p not in SKIP
            for s_, cfg in sl.items()]
    aggs = list(sources.get("aggregators", []))
    total = len(jobs) + len(aggs)
    t_run = time.monotonic()

    def drain(label, gen):
        """Consume a reader, heartbeating inside slow ones."""
        rows, t0, last = [], time.monotonic(), time.monotonic()
        for r in gen:
            rows.append(normalise(r, label))
            now = time.monotonic()
            if now - last >= 5:
                print(f"          \u2026 {label}: {len(rows)} so far, {now - t0:.0f}s elapsed",
                      flush=True)
                last = now
        return rows, time.monotonic() - t0

    for platform, slug, cfg in jobs:
        done += 1
        label = f"{platform}/{slug}"
        fn = ADAPTERS.get(platform)
        if not fn:
            errors[platform] = "no adapter"
            continue
        try:
            rows, dt = drain(label, fn(slug, cfg))
            out += rows
            print(f"  [{done}/{total}] {label}: {len(rows)}  ({dt:.1f}s)  "
                  f"total {len(out)}  run {time.monotonic()-t_run:.0f}s", flush=True)
            if on_batch:
                on_batch(out)
        except Exception as e:
            errors[label] = f"{type(e).__name__}: {e}"
            print(f"  [{done}/{total}] {label}: FAILED {type(e).__name__}", flush=True)

    for agg in [a for a in aggs if a not in SKIP]:
        done += 1
        fn = AGGREGATORS.get(agg)
        if not fn:
            errors[agg] = "no adapter"
            continue
        try:
            rows, dt = drain(agg, fn())
            out += rows
            print(f"  [{done}/{total}] {agg}: {len(rows)}  ({dt:.1f}s)  "
                  f"total {len(out)}  run {time.monotonic()-t_run:.0f}s", flush=True)
            if on_batch:
                on_batch(out)
        except Exception as e:
            errors[agg] = f"{type(e).__name__}: {e}"
            print(f"  [{done}/{total}] {agg}: FAILED {type(e).__name__}", flush=True)
    return out, errors


def update(previous, found, run_id, stamp):
    """Fold this run's findings into the pool, minting ids only for new
    postings. One row per posting, matched by posting_key; company+title only
    identifies a row that has no url."""
    by_id = {r["id"]: r for r in previous}
    by_key, by_identity, collisions = {}, {}, 0
    for r in previous:
        k = posting_key(r.get("url"))
        if k:
            if k in by_key:
                collisions += 1           # two old rows, one posting: first wins
            by_key.setdefault(k, r["id"])
        else:
            by_identity.setdefault(identity(r["company"], r["title"]), r["id"])
    if collisions:
        print(f"  {collisions} previous rows shared a posting with another; "
              f"folded into one", flush=True)

    seen, minted, merged = set(), 0, 0
    by_copy = {}                              # this run's board postings, by company+title
    for rec in found:
        k = posting_key(rec.get("url"))
        rid = None
        if rank(rec["source"]) == 1 and not (k or "").startswith(ATS_KEYS):
            rid = by_copy.get(copy_key(rec["company"], rec["title"]))      # tier 2
        if rid is None:
            rid = by_key.get(k) if k else by_identity.get(identity(rec["company"], rec["title"]))
        if rid is None:
            rid = uuid.uuid4().hex[:16]
            minted += 1
            by_id[rid] = {"id": rid, "first_seen": stamp, "first_run": run_id}
            if k:
                by_key[k] = rid
            else:
                by_identity[identity(rec["company"], rec["title"])] = rid
        prev = by_id[rid]
        sources = set(prev.get("sources") or ([prev["source"]] if prev.get("source") else []))
        if not prev.get("source") or rank(rec["source"]) >= rank(prev["source"]):
            prev.update(rec)              # the original, or the latest copy of a copy
        else:
            merged += 1                   # a copy of a posting the board reported: noted, not applied
        sources.add(rec["source"])
        prev["sources"] = sorted(sources)
        if rank(rec["source"]) == 2:
            by_copy.setdefault(copy_key(rec["company"], rec["title"]), rid)
        prev["id"] = rid                       # identity is the pool's, not the source's
        prev.setdefault("first_seen", stamp)
        prev.setdefault("first_run", run_id)
        prev["last_seen"] = stamp
        prev["active"] = True
        seen.add(rid)
    if merged:
        print(f"  {merged} postings seen at more than one source, one row each", flush=True)
    for rid, rec in by_id.items():
        if rid in seen:
            continue
        src = (rec.get("source") or "").split("/")[0]
        if src in SKIP:
            continue      # not scraped this run - absence is not evidence it is gone
        rec["active"] = False                  # gone from source. NOT a judgement.
    return list(by_id.values()), minted


def merge_jd(jobs, previous_jd):
    """jd.json is rebuilt every run from the roles fetched THIS run. A role
    carried forward - its source skipped with --skip, or failed soft - keeps
    its row but used to lose its description: 801 designjobsworld roles came
    out of the 2026-09-02 skip run with no text at all. Carry the previous
    description forward for every role that did not get a fresh one.
    Returns (jd, carried, lost). lost must be 0 - the caller aborts if not."""
    jd = {j["id"]: j.pop("jd_text") for j in jobs if j.get("jd_text")}
    carried = 0
    for j in jobs:
        if j["id"] not in jd and previous_jd.get(j["id"]):
            jd[j["id"]] = previous_jd[j["id"]]
            carried += 1
    lost = [j["id"] for j in jobs if j["active"] and j["id"] not in jd
            and previous_jd.get(j["id"])]
    return jd, carried, lost


def main():
    if "--skip" in sys.argv:
        SKIP.update(sys.argv[sys.argv.index("--skip") + 1].split(","))
        print(f"skipping (roles kept active): {', '.join(sorted(SKIP))}", flush=True)
    sources = json.loads(SOURCES_FILE.read_text())
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
        every = set(sources["watchlist"]) | set(sources.get("aggregators", []))
        unknown = only - every
        if unknown:
            print(f"ABORT - --only names no such source: {', '.join(sorted(unknown))}",
                  file=sys.stderr)
            return 2
        SKIP.update(every - only)
        print(f"scraping only {', '.join(sorted(only))}; every other source's roles "
              f"and descriptions carried forward", flush=True)

    # A missing reader is not a soft failure. Radar1's readers were silently
    # dropped twice by edits to this file, and each time the run "succeeded"
    # while marking 20k roles inactive because their source never ran. Fail
    # loudly instead: the pool is either complete or it is not a pool.
    gaps = ([f"{p} ({len(v)} companies)" for p, v in sources["watchlist"].items()
             if p not in ADAPTERS]
            + [a for a in sources.get("aggregators", []) if a not in AGGREGATORS])
    if gaps:
        print("ABORT - no reader for: " + ", ".join(gaps), file=sys.stderr)
        return 2

    previous = json.loads(POOL_FILE.read_text())["jobs"] if POOL_FILE.exists() else []
    stamp = now()
    run_id = stamp
    print(f"pool run {run_id} - {len(previous)} roles carried in", flush=True)

    # Checkpoint after every source. A run that dies at source 590 keeps its
    # work, and the file on disk is never the half-written product of a crash.
    ckpt = ROOT / "data" / "pool.partial.json"

    def save(rows):
        ckpt.write_text(json.dumps({"generated_at": stamp, "run_id": run_id,
                                    "found": len(rows)}, indent=1))

    found, errors = scrape(sources, on_batch=save)
    jobs, minted = update(previous, found, run_id, stamp)
    active = sum(1 for j in jobs if j["active"])
    print(f"found {len(found)} postings -> {len(jobs)} roles "
          f"({active} active, {minted} newly minted ids)", flush=True)

    thin = [k for k, v in errors.items()]
    if thin:
        print(f"  {len(thin)} sources failed soft")
    if "--dry" in sys.argv:
        print("  --dry: nothing written")
        return 0

    # Read the previous descriptions NOW, not at start: a judge run resolving
    # originals during a 40-minute scrape writes jd.json too, and a snapshot
    # taken at start would overwrite its work.
    previous_jd = json.loads(JD_FILE.read_text()) if JD_FILE.exists() else {}
    jd, carried, lost = merge_jd(jobs, previous_jd)
    if lost:
        print(f"ABORT - {len(lost)} active roles would lose their description; "
              f"nothing written", file=sys.stderr)
        return 3
    if carried:
        print(f"  {carried} descriptions carried forward for roles not fetched this run",
              flush=True)
    tmp = POOL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"generated_at": stamp, "run_id": run_id,
                               "adapter_version": ADAPTER_VERSION,
                               "sources": {"ok": len(found), "failed": errors},
                               "jobs": jobs}, indent=1, ensure_ascii=False))
    tmp.replace(POOL_FILE)                 # atomic - never a half-written pool
    tmpjd = JD_FILE.with_suffix(".tmp")
    tmpjd.write_text(json.dumps(jd, ensure_ascii=False))
    tmpjd.replace(JD_FILE)
    ckpt.unlink(missing_ok=True)
    print(f"wrote {POOL_FILE} ({POOL_FILE.stat().st_size//1024}K) "
          f"and {JD_FILE} ({JD_FILE.stat().st_size//1024}K)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
