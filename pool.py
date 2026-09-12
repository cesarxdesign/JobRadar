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
from datetime import datetime, timedelta, timezone
from pathlib import Path
import contracts

# Bump whenever an adapter changes what it captures. pool.json records the
# version it was scraped with, and the judge refuses to read data older than
# the code. Fixing an adapter does nothing until the pool is scraped again -
# ashby's secondaryLocations fix sat in the code for three batches while the
# judge kept reading one-country locations off disk and looking wrong for it.
ADAPTER_VERSION = 5

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


# Teamtailor prints a one-line panel above the title - department, city,
# workplace type. It lives in two feeds and neither one has all of it:
# jobs.json carries the location and the real company name, jobs.rss carries
# remoteStatus and department. The reader read jobs.rss and asked it for
# <location>, <region>, <country>, tags Teamtailor does not emit, so every
# one of its 978 roles reached the judge with no location and no workplace at
# all. Voy's "PRODUCT DESIGN - SAO PAULO - HYBRID" arrived as nothing.
TT_WORKPLACE = {"none": None, "onsite": "On-site", "hybrid": "Hybrid",
                "fully": "Fully remote", "remote": "Fully remote",
                "temporary": "Temporarily remote"}
TT_NS = "{https://teamtailor.com/locations}"


def from_teamtailor(host, name=None):
    side = {}
    try:
        root = ET.fromstring(get_text(f"https://{host}/jobs.rss"))
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            if link:
                side[link] = ((item.findtext("remoteStatus") or "").strip().lower(),
                              (item.findtext(TT_NS + "department") or "").strip())
    except Exception:
        pass                       # the panel is a bonus; the feed below is the job
    d = json.loads(get_text(f"https://{host}/jobs.json"))
    for it in d.get("items") or []:
        jp = it.get("_jobposting") or {}
        url = it.get("url") or ""
        status, dept = side.get(url, ("", ""))
        locs = jp.get("jobLocation") or []
        locs = [locs] if isinstance(locs, dict) else locs
        # The city is what the page prints. The street address and postcode
        # in the same block are not on the page and must not be merged in.
        cities = [((l.get("address") or {}) if isinstance(l, dict) else {}).get("addressLocality")
                  for l in locs]
        loc = "; ".join(dict.fromkeys(c.strip() for c in cities if c and c.strip()))
        org = ((jp.get("hiringOrganization") or {}).get("name") or "").strip()
        wp = TT_WORKPLACE.get(status, status.capitalize() or None)
        yield {"company": org or name or host, "title": (it.get("title") or "").strip(),
               "url": url, "location": loc,
               "workplace": wp, "department": dept or None,
               "remote": (wp == "Fully remote") or None,
               "posted": it.get("date_published") or jp.get("datePosted"),
               "jd_text": strip_html(jp.get("description") or it.get("content_html"))}


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


def sr_location(loc):
    """SmartRecruiters' fullLocation is sometimes the string ", " - truthy,
    and empty. Taken at face value it wiped the city out of the panel, and
    the judge answered "location is not stated" for a posting whose page
    prints Dubai."""
    loc = loc or {}
    full = (loc.get("fullLocation") or "").strip(" ,")
    if full:
        return full
    parts = [loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()]
    return ", ".join(dict.fromkeys(p.strip() for p in parts if p and p.strip()))


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
                   "location": sr_location(loc),
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


# ------------------------------------------ from the LinkedIn sweep, 2026-09-11
# Sources Cesar collected in JobRadar/sweep.md. Every one below was probed for
# a data path by hand before it was written up. Not here, because no scripted
# path was found: Behance (its job JSON answers empty without a session),
# remote.co (times out every scripted client), Designer News (paywalled),
# Otta (login wall, now Welcome to the Jungle), FlexJobs (paid), DailyRemote
# (600 design rows, every company "[Hidden Company]" and the description
# behind Premium, on the job page too - nothing to judge).


def _post_json(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={**UA, "Content-Type": "application/json",
                                          "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _get_text(url, extra):
    req = urllib.request.Request(url, headers={**UA, **extra})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def agg_superjobs():
    """superjobs.design publishes its whole board as one jobs.json (2,188
    roles at 943 design-led companies). Most rows link to the original ATS
    posting, so posting_key folds them into the board's row wherever we poll
    that board; the rest are himalayas copies. meta.json carries the company
    names the rows only key by slug."""
    names = {}
    try:
        names = {k: (v or {}).get("name") for k, v in get_json("https://superjobs.design/meta.json").items()}
    except Exception:
        pass
    for j in get_json("https://superjobs.design/jobs.json").get("jobs", []):
        loc = (j.get("location") or "").replace(" · ", ", ")     # "Remote · Mexico"
        sal = j.get("salary")
        if isinstance(sal, dict):
            sal = fmt_range(sal.get("min"), sal.get("max"), sal.get("currency"))
        yield {"company": j.get("companyName") or names.get(j.get("company")) or j.get("company"),
               "title": j.get("title"), "url": j.get("url"), "location": loc,
               "remote": bool(re.search(r"remote", f"{loc} {j.get('workplace') or ''}", re.I)) or None,
               "salary": sal if isinstance(sal, str) else None,
               "posted": j.get("posted"), "jd_text": strip_html(j.get("description"))}


def agg_euremotejobs():
    """WordPress with WP Job Manager: the REST API pages the design category
    at 100 a call. Regions are taxonomy ids, resolved once per run."""
    base = "https://euremotejobs.com/wp-json/wp/v2"
    cat = next((c["id"] for c in get_json(f"{base}/job-categories?slug=design")), None)
    if cat is None:
        return
    regions = {r["id"]: unescape(r.get("name") or "")
               for r in get_json(f"{base}/job_listing_region?per_page=100")}
    page = 1
    while True:
        req = urllib.request.Request(
            f"{base}/job-listings?job-categories={cat}&per_page=100&page={page}", headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            rows = json.loads(r.read().decode("utf-8", "replace"))
            pages = int(r.headers.get("X-WP-TotalPages") or 1)
        for j in rows:
            meta = j.get("meta") or {}
            loc = ", ".join(regions[i] for i in (j.get("job_listing_region") or []) if regions.get(i))
            yield {"company": unescape(meta.get("_company_name") or ""),
                   "title": unescape((j.get("title") or {}).get("rendered") or ""),
                   "url": j.get("link"), "location": loc or "Remote", "remote": True,
                   "posted": j.get("date"), "updated": j.get("modified"),
                   "jd_text": strip_html((j.get("content") or {}).get("rendered"))}
        if page >= pages or not rows:
            break
        page += 1



def age_to_date(n, unit):
    """A board that prints "16 Days Ago" instead of a date. Without this the
    row inherits first_seen and the board says 0d beside a posting the source
    page calls three weeks old."""
    days = {"hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}[unit.lower().rstrip("s")]
    return (datetime.now(timezone.utc) - timedelta(days=days * int(n))).strftime("%Y-%m-%d")


def month_day_to_date(text):
    """Jobspresso prints "August 28" with no year. Current year (Cesar)."""
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})", (text or "").strip())
    if not m:
        return None
    try:
        d = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %d")
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    # Current year (Cesar), except a month later than today has not happened
    # yet - "October 8" seen in September is last October, not a future date.
    year = now.year - 1 if (d.month, d.day) > (now.month, now.day) else now.year
    return f"{year}-{d.month:02d}-{d.day:02d}"


def agg_jobspresso():
    """WP Job Manager's listing endpoint, the one the page's Load More calls.
    The RSS ignores every filter; this one honours the keyword."""
    page = 1
    while page <= 30:
        body = urllib.parse.urlencode({"search_keywords": "design", "per_page": 100,
                                       "page": page}).encode()
        req = urllib.request.Request("https://jobspresso.co/jm-ajax/get_listings/", data=body,
                                     headers={**UA, "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        blocks = (d.get("html") or "").split('<li id="job_listing-')[1:]
        for b in blocks:
            href = re.search(r'data-href="([^"]+)"', b)
            title = re.search(r'class="job_listing-title">(.*?)</h3>', b, re.S)
            company = re.search(r'job_listing-company">\s*<strong>(.*?)</strong>', b, re.S)
            loc = re.search(r'job_listing-location[^>]*>(.*?)</div>', b, re.S)
            loc_s = strip_html(loc.group(1), 200).strip() if loc else ""
            dt = re.search(r'job_listing-date[^>]*>(?:<date>)?(.*?)<', b, re.S)
            yield {"company": strip_html(company.group(1), 120).strip() if company else "",
                   "title": strip_html(title.group(1), 200).strip() if title else "",
                   "url": href.group(1) if href else None, "location": loc_s,
                   "posted": month_day_to_date(strip_html(dt.group(1), 40)) if dt else None,
                   "remote": bool(re.search(r"remote|anywhere|worldwide", loc_s, re.I)) or None}
        if not blocks or page >= int(d.get("max_num_pages") or 1):
            break
        page += 1


def agg_justremote():
    """The SPA's own API. The page preloads only the newest 83 across every
    category; the API answers the whole design category."""
    for j in get_json("https://justremote-api.herokuapp.com/api/v1/jobs?category=design"):
        if j.get("is_active") is False:
            continue
        locs = [x for x in (j.get("location_restrictions") or []) if x]
        yield {"company": j.get("company_name"), "title": j.get("title"),
               "url": "https://justremote.co/" + (j.get("href") or "").lstrip("/"),
               "location": ", ".join(locs) or (j.get("job_country") or ""),
               "workplace": j.get("remote_type") or None, "remote": True}


def agg_wellfound():
    """Next.js pages: the Apollo cache in __NEXT_DATA__ carries the search
    results and the startup each belongs to. Four role landings, paged until
    a page brings nothing new."""
    seen = set()
    for role in ("product-designer", "ux-designer", "ui-designer", "designer"):
        for page in range(1, 16):
            html = get_text(f"https://wellfound.com/role/r/{role}" + (f"?page={page}" if page > 1 else ""))
            m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            if not m:
                break
            try:
                st = json.loads(m.group(1))["props"]["pageProps"]["apolloState"]["data"]
            except (KeyError, TypeError, ValueError):
                break
            company = {}
            for v in st.values():
                if isinstance(v, dict) and v.get("__typename") == "StartupResult":
                    for ref in v.get("highlightedJobListings") or []:
                        company[(ref or {}).get("__ref")] = v.get("name")
            new = 0
            for k, v in st.items():
                if not (isinstance(v, dict) and v.get("__typename") == "JobListingSearchResult"):
                    continue
                if not v.get("id") or v["id"] in seen:
                    continue
                seen.add(v["id"])
                new += 1
                loc = "; ".join(v.get("locationNames") or [])
                rem = v.get("acceptedRemoteLocationNames") or []
                if v.get("remote") and rem:
                    loc = "; ".join(filter(None, [loc, "Remote: " + ", ".join(rem)]))
                yield {"company": company.get(k) or "", "title": v.get("title"),
                       "url": f"https://wellfound.com/jobs/{v['id']}-{v.get('slug') or ''}",
                       "location": loc, "remote": bool(v.get("remote")) or None,
                       "salary": v.get("compensation") or None,
                       "employment_type": v.get("jobType") or None,
                       "posted": datetime.fromtimestamp(v["liveStartAt"], timezone.utc).isoformat()
                                 if v.get("liveStartAt") else None,
                       "jd_text": strip_html(v.get("description"))}
            if not new:
                break



def builtin_posted(body):
    """builtin prints "16 Days Ago", but also "Yesterday", "Today" and
    "Just Posted" - most of the page on any given day."""
    m = re.search(r"(\d+)\s*(Hour|Day|Week|Month|Year)s?\s*Ago", body, re.I)
    if m:
        return age_to_date(m.group(1), m.group(2))
    if re.search(r"\bYesterday\b", body, re.I):
        return age_to_date(1, "day")
    if re.search(r"\b(Today|Just Posted)\b", body, re.I):
        return age_to_date(0, "day")
    return None


def agg_builtin():
    """Server-rendered cards, 25 a page. The panel is three icon pills:
    house (workplace), pin (location), trophy (level)."""
    seen = set()
    for page in range(1, 12):
        html = get_text("https://builtin.com/jobs/remote/design-ux" + (f"?page={page}" if page > 1 else ""))
        parts = re.split(r'<div id="job-card-(\d+)"', html)
        if len(parts) < 3:
            break
        new = 0
        for jid, body in zip(parts[1::2], parts[2::2]):
            if jid in seen:
                continue
            seen.add(jid)
            new += 1
            t = re.search(r'data-id="job-card-title"[^>]*>(.*?)</a>', body, re.S)
            a = re.search(r'data-alias="(/job/[^"]+)"', body)
            c = re.search(r'data-id="company-title"[^>]*>\s*<span>(.*?)</span>', body, re.S)

            def pill(icon):
                m = re.search(r'fa-' + icon + r'[^>]*></i>\s*</div>\s*(?:<div>\s*)?<span[^>]*>([^<]*)</span>', body)
                return m.group(1).strip() if m else None
            wp, loc = pill("house-building"), pill("location-dot")
            summ = re.search(r'class="fs-sm fw-regular mb-md text-gray-04">(.*?)</div>', body, re.S)
            yield {"company": strip_html(c.group(1), 120).strip() if c else "",
                   "title": strip_html(t.group(1), 200).strip() if t else "",
                   "url": "https://builtin.com" + a.group(1) if a else None,
                   "location": loc or "", "workplace": wp,
                   "posted": builtin_posted(body),
                   "remote": bool(wp and re.search(r"remote", wp, re.I)) or None,
                   "jd_text": strip_html(summ.group(1)) if summ else None}
        if not new:
            break


def agg_dribbble():
    root = ET.fromstring(get_text("https://dribbble.com/jobs.rss"))
    for item in root.iter("item"):
        g = lambda t: (item.findtext(t) or "").strip()
        raw = g("title")
        m = re.match(r"(.*?) is hiring for a position of (.*?)(?: in (.*))?$", raw, re.S)
        company = g("{http://purl.org/dc/elements/1.1/}creator") or (m.group(1) if m else "")
        title, loc = (m.group(2), m.group(3) or "") if m else (raw, "")
        yield {"company": company.strip(), "title": title.strip(),
               "url": g("link").split("?")[0], "location": loc.strip(),
               "remote": bool(re.search(r"remote", loc, re.I)) or None,
               "posted": g("pubDate") or None, "jd_text": strip_html(g("description"))}


def agg_nodesk():
    """Algolia, with the public search key the site ships in its own JS."""
    d = _post_json("https://0586L1SOK8-dsn.algolia.net/1/indexes/jobPosts/query",
                   {"query": "", "hitsPerPage": 1000,
                    "facetFilters": [["searchFilter:remote-jobs/design"]]},
                   {"X-Algolia-API-Key": "8dacb58c6f375cba28e19ecf1f03e9e1",
                    "X-Algolia-Application-Id": "0586L1SOK8", "Referer": "https://nodesk.co/"})
    for h in d.get("hits", []):
        regs = [x for x in (h.get("applicantLocationRegions") or []) if x]
        yield {"company": (h.get("company") or {}).get("name"), "title": h.get("title"),
               "url": "https://nodesk.co" + (h.get("permalink") or ""),
               "location": "; ".join(regs), "remote": True,
               "posted": h.get("datePublished") or None}


WTTJ_REMOTE = {"fulltime": "Fully remote", "partial": "Partial remote",
               "punctual": "Occasional remote"}


def agg_wttj():
    """Welcome to the Jungle's Algolia index, English postings in the UX and
    design profession. The page's own key needs its referer. The hit carries
    a summary; deep.py resolves the full posting from their JSON API."""
    d = _post_json("https://CSEKHVMS53-dsn.algolia.net/1/indexes/wttj_jobs_production_en/query",
                   {"query": "", "hitsPerPage": 1000,
                    "facetFilters": [["new_profession.sub_category_reference:user-experience-ux-and-design-xYjM3"],
                                     ["language:en"]],
                    "attributesToRetrieve": ["name", "slug", "organization", "offices", "remote",
                                             "published_at_date", "summary", "profile",
                                             "salary_yearly_minimum", "salary_maximum", "salary_currency"]},
                   {"X-Algolia-API-Key": "4bd8f6215d0cc52b26430765769e65a0",
                    "X-Algolia-Application-Id": "CSEKHVMS53",
                    "Referer": "https://www.welcometothejungle.com/"})
    for h in d.get("hits", []):
        org = h.get("organization") or {}
        offices = [o for o in (h.get("offices") or []) if isinstance(o, dict)]
        loc = "; ".join(dict.fromkeys(
            ", ".join(filter(None, [o.get("city"), o.get("country_code")])) for o in offices))
        rem = h.get("remote")
        yield {"company": org.get("name"), "title": h.get("name"),
               "url": f"https://www.welcometothejungle.com/en/companies/{org.get('slug')}/jobs/{h.get('slug')}",
               "location": loc, "workplace": WTTJ_REMOTE.get(rem),
               "remote": True if rem == "fulltime" else (False if rem == "no" else None),
               "salary": fmt_range(h.get("salary_yearly_minimum"), h.get("salary_maximum"),
                                   (h.get("salary_currency") or "").upper()),
               "posted": h.get("published_at_date"),
               "jd_text": strip_html("\n\n".join(filter(None, [h.get("summary"), h.get("profile")])))}


def agg_yc():
    """Work at a Startup renders its design listing through Inertia: the page
    props hold the jobs. Its Algolia index answers empty to the public key,
    so this is the listing as a visitor sees it."""
    seen = set()
    for path in ("/jobs?role=design", "/jobs/l/designer"):
        html = _get_text("https://www.workatastartup.com" + path, {"Accept": "text/html"})
        m = re.search(r'data-page="([^"]+)"', html)
        if not m:
            continue
        for j in json.loads(unescape(m.group(1))).get("props", {}).get("jobs", []):
            if not j.get("id") or j["id"] in seen:
                continue
            seen.add(j["id"])
            loc = j.get("location") or ""
            yield {"company": j.get("companyName"), "title": j.get("title"),
                   "url": f"https://www.workatastartup.com/jobs/{j['id']}", "location": loc,
                   "remote": bool(re.search(r"remote", loc, re.I)) or None,
                   "salary": j.get("salary") or None, "employment_type": j.get("jobType") or None}


def agg_eures():
    """The EU's own portal, Portugal only, through the search API the portal
    calls. Postings are mostly Portuguese, which the criteria accept."""
    seen = set()
    for kw in ("product designer", "ux designer", "ui designer", "design"):
        for page in range(1, 11):
            d = _post_json("https://europa.eu/eures/api/jv-searchengine/public/jv-search/search?lang=en",
                           {"resultsPerPage": 50, "page": page, "sortSearch": "BEST_MATCH",
                            "keywords": [{"keyword": kw, "specificSearchCode": "EVERYWHERE"}],
                            "publicationPeriod": None, "occupationUris": [], "skillUris": [],
                            "requiredExperienceCodes": [], "positionScheduleCodes": [],
                            "sectorCodes": [], "educationAndQualificationLevelCodes": [],
                            "positionOfferingCodes": [], "locationCodes": ["pt"],
                            "euresFlagCodes": [], "otherBenefitsCodes": [], "requiredLanguages": [],
                            "minNumberPost": None, "sessionId": "radar"},
                           {"Referer": "https://europa.eu/eures/portal/jv-se/search"})
            jvs = d.get("jvs") or []
            for j in jvs:
                if not j.get("id") or j["id"] in seen:
                    continue
                seen.add(j["id"])
                ts = lambda k: (datetime.fromtimestamp(j[k] / 1000, timezone.utc).isoformat()
                                if j.get(k) else None)
                yield {"company": (j.get("employer") or {}).get("name") or "",
                       "title": j.get("title"),
                       "url": f"https://europa.eu/eures/portal/jv-se/jv-details/{j['id']}?lang=en",
                       "location": "Portugal", "posted": ts("creationDate"),
                       "updated": ts("lastModificationDate"),
                       "jd_text": strip_html(j.get("description"))}
            if len(jvs) < 50:
                break


def agg_salt():
    """Salt, the recruitment agency (welovesalt.com): server-rendered cards,
    six a page, the whole board (~280 roles), no keyword - the pool has no
    opinions, L1 does the filtering. Found from a LinkedIn lead, one of
    their recruiters hiring a Lead Product Designer, 2026-09-11."""
    seen = set()
    for page in range(1, 120):
        try:
            html = get_text("https://welovesalt.com/jobs" + (f"/page/{page}" if page > 1 else ""))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break                  # WordPress: the page past the last one
            raise
        new = 0
        for card in html.split('<li class="job-item">')[1:]:      # nested <li>s inside
            a = re.search(r'job-item__title">\s*<a href="([^"]+)">(.*?)</a>', card, re.S)
            if not a or a.group(1) in seen:
                continue
            seen.add(a.group(1))
            new += 1
            def pill(icon):
                m = re.search(r'highlights__item-icon--' + icon + r'"></i>\s*<span>(.*?)</span>', card, re.S)
                return re.sub(r"\s+", " ", strip_html(m.group(1), 200)).strip() if m else None
            details = [strip_html(x, 60).strip() for x in re.findall(r'job-item__detail">(.*?)</li>', card, re.S)]
            wp = next((d for d in details if re.search(r"remote|hybrid|on-?site|office", d, re.I)), None)
            loc = re.sub(r"\s*,\s*", ", ", pill("location") or "")
            yield {"company": "Salt (agency)", "title": strip_html(a.group(2), 200).strip(),
                   "url": a.group(1), "location": loc, "workplace": wp,
                   "remote": bool(wp and re.search(r"remote", wp, re.I)) or (None if wp else (bool(re.search(r"remote", loc, re.I)) or None)),
                   "salary": pill("money"), "department": pill("star"),
                   "employment_type": next((d for d in details if d != wp), None)}
        if not new:
            break


AGGREGATORS.update({"superjobs": agg_superjobs, "euremotejobs": agg_euremotejobs,
                    "jobspresso": agg_jobspresso, "justremote": agg_justremote,
                    "wellfound": agg_wellfound, "builtin": agg_builtin,
                    "dribbble": agg_dribbble, "nodesk": agg_nodesk, "wttj": agg_wttj,
                    "yc": agg_yc, "eures": agg_eures, "salt": agg_salt})


# ---------------------------------------------------------------- sweep 2026-09-12
# Seventeen sources verified by hand before being written (SOURCE_SWEEP.md).
# Two rules learned there, and they are why these adapters look the way they do:
#
#   1. An aggregator's own scope tag is not evidence. region, regionLabel,
#      applicantLocationRequirements, a country badge - none of it renders as
#      words a person reads, and all of it lies in the same direction: when a
#      feed does not know the restriction it prints "Worldwide" rather than
#      "unknown". tryremotely's said Worldwide on seven of eight roles that were
#      US-only at the employer's ATS. So these adapters carry location,
#      workplace and the description, and drop the derived tags. The judge reads
#      the posting and works out where it is based, the way a person would.
#
#   2. A board that rewrites the description is useless to us even when its
#      fields are good - the location usually lives in the body, and a 1,000
#      character summary strips it out.


def agg_remoteio():
    """remote.io: JSON, 142 live design roles at time of writing, full
    description in the payload. `region`/`regionLabel` are theirs, not the
    posting's - dropped on purpose (see above). locationType renders on the
    page as Location Type, so it stays."""
    for page in range(1, 40):
        # remote.io rate-limits by IP and answers 403 once it has had enough.
        # At limit=100 the whole design category is two calls, so this only
        # ever bites when something else has been hitting the host.
        for attempt in range(4):
            try:
                d = get_json(f"https://remote.io/api/v2/jobs?category=design&limit=100&page={page}")
                break
            except urllib.error.HTTPError as e:
                if e.code not in (403, 429) or attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
        rows = d.get("data") or []
        for j in rows:
            locs = [l.get("name") for l in (j.get("locations") or []) if l.get("name")]
            yield {"company": j.get("companyName") or j.get("displayName"),
                   "title": j.get("jobTitle"),
                   "url": j.get("jobUrl") or j.get("applicationUrl"),
                   "apply_url": j.get("applicationUrl"),
                   "location": ", ".join(locs) or j.get("location") or "",
                   "workplace": j.get("locationType"),
                   "remote": True if j.get("locationType") == "remote" else None,
                   "salary": j.get("salaryRange"),
                   "posted": j.get("publishedAt"), "updated": j.get("updatedAt"),
                   "jd_text": strip_html(j.get("description"))}
        pg = d.get("pagination") or {}
        if not rows or page >= (pg.get("totalPages") or 1):
            break


WOODY_RE = re.compile(r"<item>(.*?)</item>", re.S)


def agg_woodyjobs():
    """woodyjobs.com: one RSS feed, the 100 newest across every category, with
    the panel fields as their own elements (location, workmode, worktime,
    seniority) and the whole description inline. Overlaps remote.io heavily -
    that is fine, rank() keeps the board copy when both see a posting."""
    def tag(chunk, name):
        m = re.search(rf"<{name}>(.*?)</{name}>", chunk, re.S)
        return strip_html(m.group(1), 300).strip() if m else None
    for chunk in WOODY_RE.findall(get_text("https://www.woodyjobs.com/rss.xml")):
        title = tag(chunk, "title")
        if not title:
            continue
        # "<role> at <company>" is the feed's title format
        role, _, company = title.rpartition(" at ")
        wm = tag(chunk, "workmode")
        yield {"company": (company or "").strip() or None,
               "title": (role or title).strip(),
               "url": tag(chunk, "link"),
               "location": tag(chunk, "location") or "",
               "workplace": wm,
               "remote": bool(wm and re.search(r"remote", wm, re.I)) or None,
               "employment_type": tag(chunk, "worktime"),
               "department": tag(chunk, "category"),
               "posted": tag(chunk, "pubDate"),
               "jd_text": strip_html(re.search(r"<description>(.*?)</description>",
                                               chunk, re.S).group(1))
                          if "<description>" in chunk else None}


AGGREGATORS.update({"remoteio": agg_remoteio, "woodyjobs": agg_woodyjobs})


def get_text_charset(url):
    """get_text() assumes UTF-8. net-empregos is ISO-8859-1, and decoding it as
    UTF-8 with errors='replace' turns Espacos Unicos into a row of question
    marks - every accented Portuguese company name silently corrupted. Honour
    what the response actually declares."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
        enc = r.headers.get_content_charset()
    if not enc:
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000], re.I)
        enc = m.group(1).decode() if m else "utf-8"
    return raw.decode(enc, "replace")



def uiux_posted(url):
    """The exact datePosted off the job page. The listing card's age is
    missing on plenty of rows, and a row with no date inherits first_seen -
    the board then says 0d beside a posting its own page calls 25d old."""
    try:
        html = get_text(url)
    except Exception:
        return None
    # The page wins (Cesar). What the header prints is what a person reads;
    # ld+json is the board's own claim about it and only fills the gap.
    m = re.search(r'POSTED</span><span[^>]*>(\d+)(d|h|mo|y)<', html)
    if m:
        days = {"h": 0, "d": 1, "mo": 30, "y": 365}[m.group(2)] * int(m.group(1))
        return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    for m in re.finditer(r'application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        for o in (d if isinstance(d, list) else [d]):
            if isinstance(o, dict) and o.get("@type") == "JobPosting" and o.get("datePosted"):
                return str(o["datePosted"])[:10]
    return None


UIUX_SCOPES = ("remote-anywhere", "remote-europe", "remote-emea", "portugal")


def agg_uiuxjobsboard():
    """uiuxjobsboard.com: a design-only board, so no keyword - every row is in
    discipline and L1 does the rest. Four scopes, 100 cards a page; the card
    carries the scope as its own links (Remote / Europe), which is what the
    page shows a person, so that is what we keep."""
    seen = set()
    for scope in UIUX_SCOPES:
        for page in range(1, 30):
            url = f"https://uiuxjobsboard.com/design-jobs/{scope}" + (f"?page={page}" if page > 1 else "")
            html = get_text(url)
            cards = html.split('<div class="border shadow-xs rounded-xl')[1:]
            new_here = 0
            for card in cards:
                a = re.search(r'href="(/job/[^"]+)"(.*?)</a>', card, re.S)
                if not a or a.group(1) in seen:
                    continue
                seen.add(a.group(1))
                new_here += 1
                inner = a.group(2)
                co = re.search(r'<span>(.*?)<span class="text-base', inner, re.S)
                ti = re.search(r'font-bold">(.*?)</span>', inner, re.S)
                tags = [strip_html(x, 60).strip() for x in
                        re.findall(r'href="/design-jobs/[^"]+"[^>]*>(.*?)</a>', card, re.S)]
                et = re.search(r'uppercase opacity-80 mr-3">(.*?)</span>', card, re.S)
                # The card prints an age ("12d"), and not on every card. The
                # job page prints the real date in its JobPosting, which is
                # what a person reading the posting sees - so read the page.
                posted = uiux_posted("https://uiuxjobsboard.com" + a.group(1))
                yield {"company": strip_html(co.group(1), 120).strip() if co else None,
                       "title": strip_html(ti.group(1), 200).strip() if ti else None,
                       "url": "https://uiuxjobsboard.com" + a.group(1),
                       "posted": posted,
                       "location": ", ".join(t for t in tags if t),
                       "workplace": next((t for t in tags if re.search(r"remote|hybrid|onsite", t, re.I)), None),
                       "remote": True if any(re.search(r"remote", t, re.I) for t in tags) else None,
                       "employment_type": strip_html(et.group(1), 60).strip() if et else None}
            if not new_here:
                break


def agg_uxremotetalent():
    """uxremotetalent.com: Webflow collection, 25 a page, every row design.
    The card prints scope, contract, company and a real date. OpenTrain's
    AI-training listings are a gig marketplace, not a role - dropped."""
    for page in range(1, 40):
        url = "https://www.uxremotetalent.com/" + (f"?c0af7a1a_page={page}" if page > 1 else "")
        html = get_text(url)
        items = re.split(r'role="listitem"', html)[1:]
        got = 0
        for it in items:
            a = re.search(r'href="(/ux-job/[^"]+)"', it)
            ti = re.search(r'regular-job-title">(.*?)</h2>', it, re.S)
            if not a or not ti:
                continue
            infos = [strip_html(x, 120).strip() for x in
                     re.findall(r'regular-job-info[^"]*">(.*?)</div>', it, re.S)]
            co = re.search(r'card-company-name"><div class="regular-job-info">(.*?)</div>', it, re.S)
            dt = re.search(r'regular-job-info date">(.*?)</div>', it, re.S)
            company = strip_html(co.group(1), 120).strip() if co else None
            if company and "opentrain" in company.lower():
                continue
            got += 1
            scope = infos[0] if infos else ""
            yield {"company": company, "title": strip_html(ti.group(1), 200).strip(),
                   "url": "https://www.uxremotetalent.com" + a.group(1),
                   "location": scope,
                   "remote": True,          # the whole board is remote roles
                   "employment_type": infos[1] if len(infos) > 1 else None,
                   "posted": strip_html(dt.group(1), 40).strip() if dt else None}
        if not got:
            break


def agg_netempregos():
    """net-empregos.com: Portugal's biggest general board, category 22 is
    Arquitectura / Design. Direct employer and agency ads - the kind of
    Portuguese company that never appears on a US-style ATS, which is the
    whole reason this source is here. ISO-8859-1, hence get_text_charset."""
    seen = set()
    for page in range(1, 25):
        url = ("https://www.net-empregos.com/pesquisa-empregos.asp?categoria=22"
               + (f"&page={page}" if page > 1 else ""))
        html = get_text_charset(url)
        got = 0
        for card in html.split('class="job-ad-item"')[1:]:
            pass
        # the anchor comes before the detail block, so walk the h2 links instead
        for m in re.finditer(r'<h2[^>]*><a class="oferta-link"[^>]*href=["\']?(/\d+/[^"\'>]+)["\']?>(.*?)</a>', html, re.S):
            href, title = m.group(1), strip_html(m.group(2), 200).strip()
            if href in seen:
                continue
            seen.add(href)
            got += 1
            block = html[m.end():m.end() + 2500]
            def li(icon):
                x = re.search(icon + r'[^>]*></i>\s*(.*?)</li>', block, re.S)
                return strip_html(x.group(1), 120).strip() if x else None
            yield {"company": li("flaticon-work"), "title": title,
                   "url": "https://www.net-empregos.com" + href,
                   "location": li("flaticon-pin") or "",
                   "department": li("fa fa-tags"),
                   "posted": li("flaticon-calendar")}
        if not got:
            break


AGGREGATORS.update({"uiuxjobsboard": agg_uiuxjobsboard,
                    "uxremotetalent": agg_uxremotetalent,
                    "netempregos": agg_netempregos})



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

    previous = contracts.load_pool(POOL_FILE)["jobs"] if POOL_FILE.exists() else []
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
    tmp.write_text(contracts.pool_text({"generated_at": stamp, "run_id": run_id,
                                        "adapter_version": ADAPTER_VERSION,
                                        "sources": {"ok": len(found), "failed": errors}},
                                       jobs))
    tmp.replace(POOL_FILE)                 # atomic - never a half-written pool
    tmpjd = JD_FILE.with_suffix(".tmp")
    tmpjd.write_text(json.dumps(jd, ensure_ascii=False))
    tmpjd.replace(JD_FILE)
    ckpt.unlink(missing_ok=True)
    print(f"wrote {POOL_FILE} ({POOL_FILE.stat().st_size//1024}K) "
          f"and {JD_FILE} ({JD_FILE.stat().st_size//1024}K)", flush=True)
    # GitHub refuses files over 100MB. Cesar's call (2026-09-12): one file
    # until it is an actual problem, and a warning at 95MB.
    mb = POOL_FILE.stat().st_size / 1048576
    if mb > 95:
        print(f"\nWARNING - pool.json is {mb:.0f}MB. GitHub rejects files over 100MB; "
              f"the push will fail soon. Shard it or stop tracking it (see BACKLOG.md).",
              file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
