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
TRIED_FILE = ROOT / "data" / "boards_tried.json"      # boards --new-boards has already asked, so an empty one is not asked every cycle
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
    ("dover", re.compile(r"app\.dover\.com/apply/[^/]+/([0-9a-f]{8}-[0-9a-f-]{27})")),
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


def iso_date(v):
    """Every adapter's date, one shape. Boards print whatever they like -
    "2026-09-08T13:55:06Z", "Fri, 28 Aug 2026 13:26:53 +0000", "10-9-2026",
    "September 2, 2026" - and four shapes in one field means the board cannot
    sort or filter on it. Normalised here, at ingest, so no adapter has to
    remember and nothing downstream has to parse.

    Unparseable text is kept as-is rather than dropped: a date we cannot read
    is still something the page said."""
    v = (v or "").strip()
    if not v:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return v[:10]
    if re.fullmatch(r"\d{10}|\d{13}", v):      # epoch, seconds or milliseconds
        t = int(v) / (1000 if len(v) == 13 else 1)
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%d-%m-%Y", "%B %d, %Y", "%d %B %Y",
                "%Y/%m/%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return v


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
#     back thin. That is the deep fetch, and it waits for the parser.

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
# is the deep fetch and it waits for the parser.

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
    # Two shapes: www.careers-page.com/<slug>, with /job/<code> links, and a
    # company's own <name>.careers-page.com, with /jobs/<uuid> links (Mamo).
    base = f"https://{slug}/" if "." in slug else f"https://www.careers-page.com/{slug}"
    html = get_text(base)
    seen = set()
    for m in re.finditer(r'<a\b[^>]*href="([^"]*/jobs?/[A-Za-z0-9-]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
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


def from_dover(slug, cfg=None):
    """Dover (app.dover.com/jobs/<company>): a hiring system small startups
    use. He found MindFi on it by hand, 2026-10-05 - the job board's copy said
    "Remote", Dover's own page said hybrid in nine Asia-Pacific countries. The
    list gives titles and locations; the description is one call per job, and
    is fetched only for titles the parser would keep (a 40-job board is one
    call, not forty-one)."""
    import judge
    co = get_json(f"https://app.dover.com/api/v1/careers-page-slug/{slug}")
    d = get_json(f"https://app.dover.com/api/v1/careers-page/{co['id']}/jobs?limit=300")
    for j in d.get("results") or []:
        locs = j.get("locations") or []
        kinds = {(l.get("location_type") or "").lower() for l in locs}
        where = "; ".join(dict.fromkeys(l.get("name") or "" for l in locs if l.get("name")))
        kind = "hybrid" if "hybrid" in kinds else "remote" if kinds == {"remote"} else "onsite" if "in_office" in kinds or "onsite" in kinds else None
        text = None
        if judge.l1(j.get("title")) is None:
            try:
                one = get_json(f"https://app.dover.com/api/v1/inbound/application-portal-job/{j['id']}")
                text = strip_html(one.get("user_provided_description") or "")
            except Exception:
                pass
        yield {"title": j.get("title"), "company": co.get("name") or slug,
               "url": f"https://app.dover.com/apply/{slug}/{j['id']}",
               "location": (f"{kind.capitalize()} ({where})" if kind and where else where or kind),
               "workplace": kind, "remote": kind == "remote" or None, "jd_text": text}


ADAPTERS.update({"dover": from_dover})
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
    """The design category, off its listing pages. The site used to offer a
    REST API and closed it (401 "Not available") in autumn 2026; the pages a
    person reads are still there, 40 cards each, and a card carries the title,
    the company, the region the board prints, the type and the date."""
    seen, base = set(), "https://euremotejobs.com/job-category/design/"
    for page in range(1, 60):
        html = get_text(base if page == 1 else f"{base}page/{page}/")
        cards = re.findall(r'<a href="(https://euremotejobs\.com/job/[^"]+)" class="job-card-link">(.*?)</a>', html, re.S)
        fresh = 0
        for url, card in cards:
            if url in seen:
                continue
            seen.add(url)
            fresh += 1
            g = lambda rx: (lambda m: strip_html(m.group(1), 200).strip() if m else None)(re.search(rx, card, re.S))
            loc = g(r'class="meta-item meta-location">(.*?)</div>')
            when = re.search(r'<time datetime="(\d{4}-\d{2}-\d{2})', card)
            yield {"company": g(r'class="company-name">(.*?)</div>'), "title": g(r'class="job-title">(.*?)</h2>'),
                   "url": url, "location": loc, "posted": when.group(1) if when else None,
                   "employment_type": g(r'class="meta-item meta-type">(.*?)</div>'),
                   "remote": True, "workplace": "Remote"}
        if not fresh:
            break
        time.sleep(0.5)


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
    opinions, the parser does the filtering. Found from a LinkedIn lead, one of
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


def haystack_key():
    """Haystack's site reads its jobs from a public database feed, with a
    public key that ships in its own page script. The key is read from there
    each run, as a browser would get it, and kept nowhere."""
    html = get_text("https://haystack.cv/jobs")
    for src in re.findall(r'<script[^>]+src="([^"]+\.js)"', html):
        js = get_text(urllib.parse.urljoin("https://haystack.cv/", src))
        m = re.search(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{20,}", js)
        host = re.search(r"https://[a-z0-9]+\.supabase\.co", js)
        if m and host:
            return host.group(0), m.group(0)
    raise RuntimeError("haystack: the feed key was not found in the page script")


HN_ROLE = re.compile(
    r"((?:(?:senior|sr\.?|staff|lead|principal|founding|head of|director of|vp of|product|ux|ui|ux/ui|ui/ux|visual|"
    r"interaction|brand|design|experience)\s+){0,4}"
    r"(?:designers?|design engineers?|design leads?|design managers?|design directors?|head of design|ux engineers?|ui engineers?))", re.I)


def agg_hackernews(months=2):
    """Hacker News, "Ask HN: Who is hiring?" - one thread a month, a few
    hundred companies, each top-level comment one company's posting in its own
    words: "Acme | Senior Product Designer | Remote (EU) | https://...". Read
    through HN's public search feed. It is small and heavy on remote startup
    roles, many of which are on no job board at all. (His call, 2026-10-05,
    after seeing it in an application form's "where did you hear about us".)

    A comment that names no design role is left out: there is no title to put
    on it. One that names several gives one row each. The row's link is the
    comment itself, which is the posting; any hiring-system link inside it is
    what the employer finder follows."""
    threads = get_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=12")["hits"]
    threads = [t for t in threads if "who is hiring" in (t.get("title") or "").lower()][:months]
    for t in threads:
        tree = get_json(f"https://hn.algolia.com/api/v1/items/{t['objectID']}")
        for c in tree.get("children") or []:
            html = c.get("text") or ""
            if not html or not c.get("author"):
                continue
            text = strip_html(html.replace("<p>", "\n"))
            head = text.split("\n")[0][:300]
            parts = [p.strip() for p in re.split(r"\s*[|•·]\s*|\s+[-–—]\s+", head) if p.strip()]
            company = re.sub(r"\s*\(.*?\)\s*$", "", parts[0])[:60] if parts else None
            # Most open with the company's name. Some open with a sentence
            # ("At Tether (https://...) we...", "We're hiring software
            # engineers..."): then the name is taken from the sentence, or
            # from the first address in the comment, or the comment is left.
            if company and (len(company.split()) > 5 or re.match(r"(at |we're |we are |role:|hi\b|hello\b|hiring\b)", company, re.I)):
                m = re.match(r"At ([A-Z][\w.&' -]{1,40}?)[ ,(]", head) or re.search(r"\b([A-Z][\w.&'-]{1,30}(?: [A-Z][\w.&'-]{1,20})?) is (?:hiring|looking)", text)
                site = re.search(r"https?://(?:www\.|jobs\.|careers\.)?([a-z0-9-]+)\.[a-z.]{2,8}(?:/|\b)", html)
                company = (m.group(1).strip() if m else site.group(1).capitalize() if site and site.group(1) not in ("news", "docs", "github", "linkedin", "forms", "apply") else None)
            if not company or len(company) < 2:
                continue
            titles = list(dict.fromkeys(re.sub(r"\s+", " ", m.group(1)).strip().title() for m in HN_ROLE.finditer(text)))
            titles = [x for x in titles if len(x.split()) >= 2 or x.lower() in ("designer", "designers")]
            if any(len(x.split()) >= 2 for x in titles):          # a bare "Designer" beside "Senior Product Designer" is the same job
                titles = [x for x in titles if len(x.split()) >= 2]
            titles = titles[:4]
            if not titles:
                continue
            where = "; ".join(p for p in parts[1:] if re.search(
                r"remote|onsite|on-site|hybrid|europe|\beu\b|emea|worldwide|global|anywhere|usa?\b|uk\b|[A-Z][a-z]+, ?[A-Z]{2}\b|"
                r"london|berlin|paris|new york|nyc|sf\b|san francisco|lisbon|portugal|amsterdam|toronto", p, re.I))[:160]
            for title in titles:
                yield {"title": title[:-1] if title.lower().endswith("designers") or title.lower().endswith("engineers") else title,
                       "company": company, "url": f"https://news.ycombinator.com/item?id={c['id']}",
                       "location": where or None, "posted": (c.get("created_at") or "")[:10],
                       "remote": bool(re.search(r"\bremote\b", head, re.I)) or None, "jd_text": text}


def agg_haystack():
    """haystack.cv: half a million postings of every kind. Its feed is asked
    only for live roles with a design word in the title that are remote or in
    Portugal. Each row carries the link it sends applicants to, which is
    usually the employer's own hiring system - so the row lands on the
    employer's posting, not on a copy."""
    host, key = haystack_key()
    cols = "id,title,company,apply_url,city,state,country,work_mode,job_type,posted_at,activated_at,salary"
    # One plain question at a time: a combined query over half a million rows
    # times out on their side. Each title word, once for remote and once for Portugal.
    # A rare word makes their database read every row and give up, so a
    # question that times out is skipped, not fatal: "designer" carries
    # nearly every title that matters, and the rest are a bonus.
    words = ("designer", "design%20lead", "head%20of%20design", "design%20director", "design%20manager",
             "design%20engineer", "design", "ux", "ui/ux")
    seen = set()
    for where in ("work_mode=eq.remote", "country=eq.Portugal"):
        for w in words:
            for start in range(0, 12000, 500):
                req = urllib.request.Request(
                    f"{host}/rest/v1/jobs?select={cols}&is_active=eq.true&title=ilike.*{w}*&{where}&limit=500&offset={start}",
                    headers={"apikey": key, "Authorization": "Bearer " + key, **UA})
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        rows = json.loads(r.read().decode("utf-8", "replace"))
                except urllib.error.HTTPError as e:
                    if w == "designer" and where.startswith("work_mode") and start == 0:
                        raise                      # the one question that has to work
                    break
                for j in rows:
                    if j["id"] in seen:
                        continue
                    seen.add(j["id"])
                    place = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
                    mode = (j.get("work_mode") or "").lower()
                    yield {"company": j.get("company"), "title": j.get("title"),
                           "url": j.get("apply_url") or f"https://haystack.cv/jobs/{j['id']}",
                           "location": place or None, "remote": mode == "remote" or None,
                           "workplace": {"remote": "Remote", "hybrid": "Hybrid", "on-site": "On-site"}.get(mode),
                           "employment_type": j.get("job_type"), "salary": j.get("salary"),
                           "posted": (j.get("posted_at") or j.get("activated_at") or "")[:10] or None}
                if len(rows) < 500:
                    break
                time.sleep(0.3)


def agg_remoteio():
    """remote.io shows its listings to a person's browser and nothing to a
    script, so the pool cannot fetch it. tabs.py reads the listings off the
    tab he leaves open in Chrome and saves them; this hands them to the pool.
    A file older than three days means the tab has not been open: the source
    fails, and its roles are carried forward, not dropped."""
    path = ROOT / "data" / "remoteio_rows.json"
    if not path.exists():
        raise FileNotFoundError("no remote.io listings saved: open the tab in Chrome")
    d = json.loads(path.read_text())
    if d.get("at", "") < (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S"):
        raise RuntimeError("the remote.io listings are more than three days old")
    for r in d.get("rows") or []:
        tail = r.get("text", "")
        for part in (r.get("title") or "", r.get("company") or ""):
            tail = tail.replace(part, " ", 1)
        yield {"company": re.sub(r"[®™]", "", r.get("company") or "").strip(), "title": r.get("title"),
               "url": r.get("url"), "location": " ".join(tail.split())[:120] or None, "remote": True}


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


AGGREGATORS.update({"remoteio": agg_remoteio, "woodyjobs": agg_woodyjobs, "haystack": agg_haystack})
AGGREGATORS.update({"hackernews": agg_hackernews})


# ---- job boards found from a search for one role (2026-10-05): jobalert.world,
# kazialert.co.ke, theohub.global. All three print far more than design, so
# each is asked only for what CUT would keep, and a dated page is read once.
AGG_CACHE = Path(__file__).parent / "data" / "agg_cache.json"
AGG_WINDOW = 69            # days: older than this is the 69+ tab, not worth a page fetch


def _agg_cache():
    try:
        return json.loads(AGG_CACHE.read_text())
    except Exception:
        return {}


def ld_posting(url, timeout=30):
    """The JobPosting a board prints in its page head: title, company, place,
    date and text as the board states them."""
    safe = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=~-._%")
    req = urllib.request.Request(safe, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        html = r.read().decode("utf-8", "replace")
    for raw in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            d = json.loads(raw)
        except Exception:
            continue
        for x in (d if isinstance(d, list) else [d]):
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                loc = x.get("jobLocation") or {}
                loc = loc[0] if isinstance(loc, list) and loc else loc
                adr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
                place = ", ".join(str(adr[k]) for k in ("addressLocality", "addressRegion", "addressCountry")
                                  if isinstance(adr, dict) and adr.get(k))
                org = x.get("hiringOrganization") or {}
                return {"title": unescape(x.get("title") or "").strip() or None,
                        "company": unescape(org.get("name") or "").strip() if isinstance(org, dict) else None,
                        "location": place, "posted": str(x.get("datePosted") or "")[:10] or None,
                        "remote": True if x.get("jobLocationType") == "TELECOMMUTE" or re.search(r"remote", place, re.I) else None,
                        "employment_type": x.get("employmentType") if isinstance(x.get("employmentType"), str) else None,
                        "jd_text": strip_html(x.get("description") or "") or None}
    return None


def _ld_many(urls, cache):
    """Read each page once, six at a time; what was read is remembered
    (without the text) so the next run asks only for what is new."""
    from concurrent.futures import ThreadPoolExecutor
    def one(u):
        if u in cache:
            return u, cache[u]
        try:
            return u, ld_posting(u)
        except Exception:
            return u, None
    with ThreadPoolExecutor(6) as ex:
        got = dict(ex.map(one, urls))
    for u, rec in got.items():
        if rec and u not in cache:
            cache[u] = {k: v for k, v in rec.items() if k != "jd_text"}
    return got


def _too_old(posted):
    try:
        return (datetime.now() - datetime.strptime(posted[:10], "%Y-%m-%d")).days > AGG_WINDOW
    except Exception:
        return False


def agg_jobalert():
    """jobalert.world: /all-jobs is one page with every posting it has ever
    carried (37,000 on 2026-10-05), newest first, as "<role> at <company> -
    <place>". The apply link is behind its paywall, so the row keeps the
    board's page and the employer's own posting is found the usual way.
    Only titles CUT keeps are opened; the walk stops at the first run of 40
    postings older than AGG_WINDOW days."""
    import judge
    req = urllib.request.Request("https://jobalert.world/all-jobs", headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        html = r.read().decode("utf-8", "replace")
    keep = []
    for href, text in re.findall(r'<a href="(/jobs/[^"]+)"[^>]*>(.*?)</a>', html, re.S):
        role = unescape(re.sub(r"<[^>]+>", "", text)).rpartition(" at ")[0]
        if role and judge.l1(role) is None:
            keep.append("https://jobalert.world" + href)
    cache = _agg_cache()
    try:
        for i in range(0, len(keep), 40):
            chunk = keep[i:i + 40]
            got = _ld_many(chunk, cache)
            fresh = 0
            for u in chunk:
                rec = got.get(u)
                if not rec or not rec.get("title") or _too_old(rec.get("posted") or ""):
                    continue
                fresh += 1
                yield {**rec, "url": u}
            if not fresh and any(got.get(u) for u in chunk):
                break
    finally:
        AGG_CACHE.write_text(json.dumps(cache))


def agg_kazialert():
    """kazialert.co.ke: remote roles from European and US employers, sold to
    readers in Kenya. Its Design & UX category is 20 cards a page; the card
    has title and company, the job page has the date."""
    cache, seen = _agg_cache(), set()
    try:
        for page in range(1, 60):
            html = get_text("https://www.kazialert.co.ke/jobs?category=design-ux" + (f"&page={page}" if page > 1 else ""))
            cards = [(h, t, c) for h, t, c in re.findall(
                r'href="(/jobs/design-ux/[^"]+)">(.*?)</a>.*?<p class="text-sm text-gray-500[^"]*">(.*?)</p>', html, re.S)
                if h not in seen]
            if not cards:
                break
            seen.update(h for h, _, _ in cards)
            got = _ld_many(["https://www.kazialert.co.ke" + h for h, _, _ in cards], cache)
            for h, t, c in cards:
                u = "https://www.kazialert.co.ke" + h
                rec = got.get(u) or {}
                yield {**rec, "company": strip_html(c, 120).strip() or rec.get("company"),
                       "title": strip_html(t, 200).strip() or rec.get("title"),
                       "url": u, "location": "Remote", "remote": True}
    finally:
        AGG_CACHE.write_text(json.dumps(cache))


OHUB_HAVE = ("ARBEITNOW", "HIMALAYAS", "WE_WORK_REMOTELY")     # scraped here at the source already


def ohub_get(url):
    """The API refuses (429, no Retry-After) after about twenty quick calls.
    Three seconds between pages stays under it; a refusal is waited out."""
    for wait in (0, 60, 120, 240):
        time.sleep(wait or 3)
        try:
            return get_json(url)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
    raise RuntimeError("theohub: still refusing after 7 minutes")


def agg_theohub():
    """theohub.global: a UK board that also relays other boards and employers'
    own postings ("DIRECT", with the employer's link - the best kind of row).
    Its search API is asked for remote design roles, 50 a page; the boards
    this pool already reads at the source are left out."""
    seen = set()
    skip = "".join("&excludeSource=" + s for s in OHUB_HAVE)
    for q in ("designer", "ux", "product design"):
        for page in range(1, 40):
            d = ohub_get("https://www.theohub.global/api/jobs/external?limit=50&isRemote=true"
                         f"&q={urllib.parse.quote(q)}{skip}&page={page}")
            for j in d.get("jobs") or []:
                if j.get("id") in seen or not j.get("sourceUrl"):
                    continue
                seen.add(j["id"])
                lo, hi, cur = j.get("salaryMin"), j.get("salaryMax"), j.get("currency") or ""
                yield {"company": j.get("company"), "title": j.get("title"), "url": j["sourceUrl"],
                       "location": ", ".join(dict.fromkeys(x for x in (j.get("location"), j.get("country")) if x)),
                       "remote": True, "posted": str(j.get("postedAt") or "")[:10] or None,
                       "employment_type": j.get("jobType"), "department": j.get("category"),
                       "salary": f"{cur} {lo:,} - {hi:,}".strip() if lo and hi and not j.get("salaryPredicted") else None,
                       "jd_text": strip_html(j.get("description") or "") or None}
            if page >= ((d.get("pagination") or {}).get("pages") or 0):
                break


AGGREGATORS.update({"jobalert": agg_jobalert, "kazialert": agg_kazialert, "theohub": agg_theohub})


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
    # Titles carry en-dashes and accents, so the slug is not ASCII. urllib
    # will not send it raw and the fetch dies silently, leaving the row
    # dateless - which the board then renders as 0d.
    safe = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=~-._")
    try:
        html = uiux_get(safe, tries=2)
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


def uiux_get(url, tries=4):
    """uiuxjobsboard answers a few hundred requests and then refuses for a
    while. One refusal used to fail the whole source - 75 roles in, all
    thrown away, and nothing new from the board since. So: go slower, and
    when it refuses, wait and ask again."""
    for i in range(tries):
        try:
            time.sleep(0.6)
            return get_text(url)
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429, 500, 502, 503) or i == tries - 1:
                raise
            time.sleep(30 * (i + 1))


def agg_uiuxjobsboard():
    """uiuxjobsboard.com: a design-only board, so no keyword - every row is in
    discipline and L1 does the rest. Four scopes, 100 cards a page; the card
    carries the scope as its own links (Remote / Europe), which is what the
    page shows a person, so that is what we keep."""
    seen = set()
    for scope in UIUX_SCOPES:
        for page in range(1, 30):
            url = f"https://uiuxjobsboard.com/design-jobs/{scope}" + (f"?page={page}" if page > 1 else "")
            try:
                html = uiux_get(url)
            except urllib.error.HTTPError as e:
                # Past the last page the board answers 404, not an empty
                # page. That was the whole "block": every run died at the end
                # of the first scope and the source was thrown away.
                if e.code == 404 and page > 1:
                    break
                raise
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


NEW_BOARDS = None             # set by --new-boards: the labels to scrape, everything else untouched
SOURCE_LIMIT = 25 * 60        # seconds one source may take
BOARDS_AT_ONCE = 10           # company boards read at the same time
LEFT_BEHIND = []              # sources still running when their time was up


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
    if NEW_BOARDS is not None:        # --new-boards: only the boards the pool has never read; no job boards
        jobs = [j for j in jobs if f"{j[0]}/{j[1]}" in NEW_BOARDS]
        aggs = []
    total = len(jobs) + len(aggs)
    t_run = time.monotonic()

    def drain(label, gen):
        """Consume a reader, heartbeating inside slow ones."""
        rows, t0, last = [], time.monotonic(), time.monotonic()
        for r in gen:
            rows.append(normalise(r, label))
            now = time.monotonic()
            if now - t0 > SOURCE_LIMIT:
                # One slow board held a whole night's scrape. It fails soft:
                # its roles stay as they were and the rest of the night runs.
                raise TimeoutError(f"{label} took over {SOURCE_LIMIT // 60} minutes; {len(rows)} read, none kept")
            if now - last >= 5:
                print(f"          \u2026 {label}: {len(rows)} so far, {now - t0:.0f}s elapsed",
                      flush=True)
                last = now
        return rows, time.monotonic() - t0

    def bounded(label, gen):
        """drain(), but never longer than SOURCE_LIMIT. The check inside
        drain only runs when a row arrives, so a reader that waits between
        rows - uiuxjobsboard, refused and sleeping 30 seconds a page - never
        reached it: on 2026-10-05 one source held the scrape for eight hours
        and nothing was read that night. The reader runs in a thread; when its
        time is up the scrape moves on and the source fails soft."""
        import threading
        box = {}
        def run():
            try:
                box["r"] = drain(label, gen)
            except Exception as e:
                box["e"] = e
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(SOURCE_LIMIT + 30)
        if t.is_alive():
            LEFT_BEHIND.append(label)
            raise TimeoutError(f"{label} took over {SOURCE_LIMIT // 60} minutes; left behind")
        if "e" in box:
            raise box["e"]
        return box["r"]

    # Company boards are read several at a time. One at a time was fine for
    # 1,500 of them; the harvest (2026-10-05) lists every board on every
    # hiring system and the watchlist is several times that. A few systems
    # refuse a crowd, so those are held to two askers with a pause between.
    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock = threading.Lock()
    slow = {k: threading.Semaphore(2) for k in ("dover", "workable", "join", "rippling", "smartrecruiters")}

    def board(job):
        nonlocal done
        platform, slug, cfg = job
        label = f"{platform}/{slug}"
        fn = ADAPTERS.get(platform)
        if not fn:
            with lock:
                done += 1
                errors[platform] = "no adapter"
            return
        gate = slow.get(platform)
        if gate:
            gate.acquire()
        try:
            rows, dt = bounded(label, fn(slug, cfg))
            with lock:
                done += 1
                out.extend(rows)
                print(f"  [{done}/{total}] {label}: {len(rows)}  ({dt:.1f}s)  "
                      f"total {len(out)}  run {time.monotonic()-t_run:.0f}s", flush=True)
                if on_batch and done % 25 == 0:
                    on_batch(out)
        except Exception as e:
            with lock:
                done += 1
                errors[label] = f"{type(e).__name__}: {e}"
                print(f"  [{done}/{total}] {label}: FAILED {type(e).__name__}", flush=True)
        finally:
            if gate:
                time.sleep(0.3)
                gate.release()

    with ThreadPoolExecutor(BOARDS_AT_ONCE) as ex:
        list(ex.map(board, jobs))

    for agg in [a for a in aggs if a not in SKIP]:
        done += 1
        fn = AGGREGATORS.get(agg)
        if not fn:
            errors[agg] = "no adapter"
            continue
        try:
            rows, dt = bounded(agg, fn())
            out += rows
            print(f"  [{done}/{total}] {agg}: {len(rows)}  ({dt:.1f}s)  "
                  f"total {len(out)}  run {time.monotonic()-t_run:.0f}s", flush=True)
            if on_batch:
                on_batch(out)
        except Exception as e:
            errors[agg] = f"{type(e).__name__}: {e}"
            print(f"  [{done}/{total}] {agg}: FAILED {type(e).__name__}", flush=True)
    return out, errors


def update(previous, found, run_id, stamp, failed=(), keep_rest=False):
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
        # One choke point: every adapter's date lands here on its way in.
        for f in ("posted", "updated"):
            if rec.get(f) is not None:
                rec[f] = iso_date(str(rec[f]))
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
        if rid in seen or keep_rest:
            continue          # keep_rest: only new boards were read, so nothing else can be called gone
        src = (rec.get("source") or "").split("/")[0]
        if src in SKIP or src in failed or rec.get("source") in failed:
            continue      # not scraped this run, or its source did not answer -
                          # absence is not evidence it is gone. A board that timed
                          # out one night used to take all its roles off the board.
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


# What is kept of a posting the title cut drops. 150,000 of them were stored
# whole, description and all, and none will ever reach vision: the pool was
# 88MB and jd.json 580MB. One slim line each is enough to audit the title cut
# - the one filter he never sees - and to know a posting when it comes back.
SLIM = ("id", "title", "company", "source", "sources", "url",
        "first_seen", "first_run", "last_seen", "active")


def keep_whole():
    """Ids that stay whole whatever their title: anything vision has read and
    anything he has decided on."""
    ids = set()
    v = ROOT / "data" / "vision.json"
    if v.exists():
        ids |= set(json.loads(v.read_text()))
    for rr in (type(ROOT).home() / "Desktop" / "RadarRouting.json",
               ROOT / "data" / "backup.RadarRouting.json"):
        if rr.exists():
            doc = json.loads(rr.read_text())
            ids |= {d.get("id") for d in doc.get("decisions", [])}
            ids |= set(doc.get("favorites") or [])
    return ids


def slim(jobs):
    """Title-cut postings: gone once inactive, one slim line while active.
    Returns (jobs, ids slimmed, rows dropped)."""
    import judge
    whole, out, slimmed, dropped = keep_whole(), [], set(), 0
    for j in jobs:
        if j["id"] in whole or judge.l1(j.get("title")) is None:
            out.append(j)
        elif not j.get("active"):
            dropped += 1
        else:
            out.append({k: j[k] for k in SLIM if j.get(k) is not None})
            slimmed.add(j["id"])
    return out, slimmed, dropped


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
    if "--new-boards" in sys.argv:
        # The harvest adds company boards by the hundred while it runs. This
        # reads just those - a board with no row in the pool yet - and leaves
        # every other role exactly as it is, so the reader can start on the
        # new roles without waiting for a full scrape.
        global NEW_BOARDS
        have = {j.get("source") for j in previous} | {s for j in previous for s in (j.get("sources") or [])}
        tried = set(json.loads(TRIED_FILE.read_text())) if TRIED_FILE.exists() else set()
        NEW_BOARDS = {f"{p}/{k}" for p, sl in sources["watchlist"].items() for k in sl} - have - tried
        waiting = len(NEW_BOARDS)
        if "--boards" in sys.argv:          # a batch: this many boards now, the rest next round
            NEW_BOARDS = set(sorted(NEW_BOARDS)[:int(sys.argv[sys.argv.index("--boards") + 1])])
        print(f"new boards: {waiting} never read" + (f", {len(NEW_BOARDS)} in this batch" if len(NEW_BOARDS) < waiting else ""), flush=True)
        if not NEW_BOARDS:
            return 0
        TRIED_FILE.write_text(json.dumps(sorted(tried | NEW_BOARDS)))
    stamp = now()
    run_id = stamp
    print(f"pool run {run_id} - {len(previous)} roles carried in", flush=True)

    # Checkpoint after every source. A run that dies at source 590 keeps its
    # work, and the file on disk is never the half-written product of a crash.
    ckpt = ROOT / "data" / "pool.partial.json"

    def save(rows):
        ckpt.write_text(json.dumps({"generated_at": stamp, "run_id": run_id,
                                    "found": len(rows)}, indent=1))

    found, errors = ([], {}) if "--slim" in sys.argv else scrape(sources, on_batch=save)
    # --slim: no scrape, the pool on disk rewritten slim. update() would read
    # an empty scrape as every posting having gone.
    jobs, minted = (previous, 0) if "--slim" in sys.argv else update(previous, found, run_id, stamp, failed=set(errors), keep_rest=NEW_BOARDS is not None)
    active = sum(1 for j in jobs if j["active"])
    print(f"found {len(found)} postings -> {len(jobs)} roles "
          f"({active} active, {minted} newly minted ids)", flush=True)

    thin = [k for k, v in errors.items()]
    if thin:
        print(f"  {len(thin)} sources failed soft, their roles kept as they were: "
              + ", ".join(f"{k} ({v[:40]})" for k, v in sorted(errors.items())), flush=True)
    if "--dry" in sys.argv:
        print("  --dry: nothing written")
        return 0

    # Read the previous descriptions NOW, not at start: a judge run resolving
    # originals during a 40-minute scrape writes jd.json too, and a snapshot
    # taken at start would overwrite its work.
    previous_jd = json.loads(JD_FILE.read_text()) if JD_FILE.exists() else {}
    jobs, slimmed, dropped = slim(jobs)
    kept = {j["id"] for j in jobs} - slimmed
    previous_jd = {k: v for k, v in previous_jd.items() if k in kept}
    print(f"  title cut: {len(slimmed)} active postings kept as one slim line, "
          f"{dropped} dead ones dropped", flush=True)
    jd, carried, lost = merge_jd(jobs, previous_jd)
    if lost:
        print(f"ABORT - {len(lost)} active roles would lose their description; "
              f"nothing written", file=sys.stderr)
        return 3
    if carried:
        print(f"  {carried} descriptions carried forward for roles not fetched this run",
              flush=True)
    # The board's top line: when every source was last read, and when only some were.
    if "--slim" not in sys.argv:
        runs_f = ROOT / "data" / "runs.json"
        try:
            runs = json.loads(runs_f.read_text())
        except Exception:
            runs = {}
        runs["partial" if (SKIP or NEW_BOARDS is not None) else "full"] = stamp
        runs_f.write_text(json.dumps(runs))
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
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    if LEFT_BEHIND:               # a reader left running would keep the process from ending
        import os
        os._exit(rc or 0)
    raise SystemExit(rc)
