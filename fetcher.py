"""fetcher: the employer's own posting, not the board's copy of it.

    pool      -> data/pool.json       every role found. no opinions.
    fetcher   -> data/originals.json  the same role at the source. no opinions.
    judge     -> data/verdicts.json   criteria cut the pool. the only opinions.
    results   -> data/results.json    what survived, split into three lanes.

Why this exists. A board that sells job ads has an interest in every posting
looking fresh and looking remote. Coursera's "Staff Product Designer" is the
worked example and every claim below is from one run:

    welcometothejungle  Ottawa, CA · Fully remote · posted 2026-09-12
    uxremotetalent      India Only                · posted 2026-09-03
    careers.coursera.com            Canada        · posted 2026-08-11

Two aggregators, two contradictory locations, and a month of freshness
invented out of nothing. The judge read the first one, believed "fully
remote", and filed a Canada-only role under Open. It was not wrong; it was
lied to.

So: find the company's own careers page, find the role on it, and let the
judge amend its verdict from the original.

The hard part is not fetching. It is knowing you have the right company.
"Whatever Inc" resolves to a cruise line, and a confident wrong match is far
worse than no match - it feeds the judge a different job's description. The
disambiguator is already in hand: the posting says what the company does, and
that is the one thing a board has no reason to distort. Location sells, dates
sell, "we are an online education platform" does not. So every candidate site
is scored against the business the posting describes, and anything that does
not clearly match is refused.

An API is taken when a board offers one and ignored when it lies - WTTJ
returned an apply_url pointing at Udemy's job board for the Coursera role.
Nothing here depends on one.
"""

import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pool as P

ROOT = pathlib.Path(__file__).resolve().parent
POOL_FILE = ROOT / "data" / "pool.json"
JD_FILE = ROOT / "data" / "jd.json"
ORIGINALS_FILE = ROOT / "data" / "originals.json"
# Discovery is the expensive half and the answer does not change week to week,
# so what we learn about a company is kept and reused by every later run.
SITES_FILE = ROOT / "data" / "company_sites.json"

TIMEOUT = 15
# How much of what the posting says about the business has to turn up on the
# site before it is the same company. Coursera's own site clears this on the
# WTTJ copy; the Romanian clera.io does not, at 0.067.
BUSINESS_FLOOR = 0.13
TLDS = (".com", ".io", ".co", ".org", ".ai", ".dev", ".app", ".xyz", ".net",
        ".tech", ".design", ".jobs", ".pt", ".eu")
CAREER_WORDS = r"career|careers|jobs|join-us|join_us|work-with-us|workwithus|hiring|vagas|emprego|recrutamento"
# Boards we already know how to read. If a company's careers page is one of
# these, the posting is structured and the match is exact.
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
             "smartrecruiters.com", "teamtailor.com", "recruitee.com",
             "bamboohr.com", "personio.com", "myworkdayjobs.com",
             "pinpointhq.com", "applytojob.com", "breezy.hr", "comeet.com",
             "join.com", "workday.com", "careerpuck.com")

STOP = {"inc", "inc.", "llc", "ltd", "ltd.", "limited", "gmbh", "bv", "b.v.",
        "sa", "s.a.", "lda", "plc", "co", "corp", "corporation", "company",
        "group", "holdings", "the", "and", "labs", "technologies", "tech"}


class Blocked(Exception):
    """A bot wall answered instead of the page. Not evidence of anything."""


def slug(name):
    """A company name as it tends to appear in a domain or a board slug."""
    s = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    words = [w for w in s.split() if w and w not in STOP]
    return "".join(words)


def words(text, n=4000):
    """The vocabulary of a piece of text, for comparing one page to another."""
    s = re.sub(r"[^a-z0-9 ]+", " ", (text or "")[:n].lower())
    return {w for w in s.split() if len(w) > 3 and w not in STOP}


def get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={**P.UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        enc = r.headers.get_content_charset()
        final = r.geturl()
        status = r.status
    if not enc:
        m = re.search(rb'charset=["\']?([\w-]+)', body[:4000], re.I)
        enc = m.group(1).decode() if m else None
    if not enc:
        try:
            body.decode("utf-8")
            enc = "utf-8"
        except UnicodeDecodeError:
            enc = "cp1252"
    html = body.decode(enc, "replace")
    if is_challenge(html, status):
        raise Blocked(final)
    return html, final


CHALLENGE = re.compile(
    r"awsWafCookie|awswaf|Just a moment|cf-browser-verification|__cf_chl|"
    r"cf_chl_opt|Checking your browser|DataDome|datadome|px-captcha|"
    r"Enable JavaScript and cookies to continue", re.I)


def is_challenge(html, status=200):
    """A bot wall, not an answer.

    careers.coursera.com serves AWS WAF a 202 with a JavaScript cookie test
    once it has seen a few requests. Mistaking that for the page is how you
    conclude a job has no original when it plainly has one, so a challenge is
    its own outcome and gets retried later rather than recorded as absence."""
    return status == 202 or (len(html) < 6000 and bool(CHALLENGE.search(html)))


INDEX_PATHS = re.compile(r"^/(jobs|job-?board|careers|search|browse|remote-jobs)/?$", re.I)


def redirected_to_index(url, final):
    """A posting link that lands on a listing page: the job is gone.

    Himalayas answers a removed posting with a redirect to its index rather
    than a 404, so the link still resolves and drops you on "103,141 Remote
    Jobs". superjobs relays those URLs, so the role looks alive on the board
    long after the employer stopped hiring. A 404 is honest; this is not, and
    it has to be read as absence either way."""
    if url == final:
        return False
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(final)
    return bool(INDEX_PATHS.match(b.path or "/")) and len(a.path) > len(b.path)


def head_ok(url):
    """Does anything answer here at all."""
    try:
        get(url, timeout=8)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ 1. sites
def candidate_sites(company, jd, hint_urls=()):
    """Every plausible home for this company, best guess first.

    Several methods on purpose. A homepage that links its careers page is the
    happy path and not a rule - plenty of companies do not, and plenty of names
    do not resolve to the obvious domain. Coursera is coursera.org, not .com.
    """
    out, seen = [], set()

    def add(u):
        if not u:
            return
        host = urllib.parse.urlsplit(u if "//" in u else "https://" + u).netloc.lower()
        host = host.removeprefix("www.")
        if host and host not in seen and "." in host:
            seen.add(host)
            out.append(host)

    # a url the posting itself printed - the company usually names its own site
    for u in hint_urls:
        add(u)
    for m in re.finditer(r'https?://([a-z0-9.-]+\.[a-z]{2,})', (jd or "")[:20000], re.I):
        host = m.group(1).lower().removeprefix("www.")
        if any(h in host for h in ATS_HOSTS) or slug(company)[:6] in host.replace(".", ""):
            add(host)

    s = slug(company)
    if s:
        for tld in TLDS:
            add(s + tld)
        # "get<name>.com" and hyphenated multi-word names
        parts = [w for w in re.sub(r"[^a-z0-9 ]+", " ", company.lower()).split()
                 if w not in STOP]
        if len(parts) > 1:
            add("-".join(parts) + ".com")
    return out[:14]


# ------------------------------------------------------------ 2. is it them
def verify_site(host, company, profile_words):
    """Is this domain the company the posting describes, or a namesake?

    The name matching on its own is what lands you on a cruise line. What the
    company does is the evidence, and the posting already told us. A site has
    to look like the same business before anything on it is believed.
    """
    try:
        html, final = get("https://" + host)
    except Exception:
        return None
    text = P.strip_html(html, 20000)
    site_words = words(text)
    if not site_words:
        return None

    name_bits = [w for w in re.sub(r"[^a-z0-9 ]+", " ", company.lower()).split()
                 if w not in STOP]
    named = sum(1 for w in name_bits if w in text.lower()) / max(len(name_bits), 1)
    overlap = len(site_words & profile_words) / max(len(profile_words) or 1, 1)

    # A parked domain or a holding page says almost nothing and must not pass
    # on the strength of its own name appearing in it.
    if len(text) < 400:
        return None

    # The name is the weakest signal here, because a namesake matches it
    # perfectly - clera.io is a Romanian marketing site and scored 1.0 on
    # "Clera" while the posting describes a fintech doing digital identity.
    # So the business is the gate and the name only corroborates: below the
    # floor, no amount of name agreement gets in.
    if overlap < BUSINESS_FLOOR or named < 0.5:
        return None
    score = min(overlap * 3.0, 1.0) * 0.7 + named * 0.3
    return {"host": urllib.parse.urlsplit(final).netloc.lower(), "score": round(score, 3),
            "named": round(named, 2), "overlap": round(overlap, 3), "html": html}


# ---------------------------------------------------------- 3. careers page
def careers_urls(host, html=None):
    """Where this site keeps its jobs. Links first, then the usual places."""
    out, seen = [], set()

    def add(u):
        if not u:
            return
        u = urllib.parse.urljoin("https://" + host + "/", u)
        if u not in seen and urllib.parse.urlsplit(u).scheme in ("http", "https"):
            seen.add(u)
            out.append(u)

    if html:
        # a link in the nav or the footer, which is how a person finds it
        for m in re.finditer(r'href="([^"#]*(?:' + CAREER_WORDS + r')[^"#]*)"', html, re.I):
            u = m.group(1)
            if not re.search(r"career-(certificate|quiz|academy)|/resources/", u, re.I):
                add(u)
        for m in re.finditer(r'href="(https?://[^"]*(?:' + "|".join(
                h.replace(".", r"\.") for h in ATS_HOSTS) + r')[^"]*)"', html, re.I):
            add(m.group(1))
    base = host.removeprefix("www.")
    root = ".".join(base.split(".")[-2:]) if base.count(".") >= 1 else base
    # A path on the domain we already verified beats a guessed subdomain: it is
    # far likelier to exist, and three dead DNS lookups ahead of it cost the
    # whole role. Subdomains last.
    for path in ("/careers", "/jobs", "/about/careers", "/company/careers",
                 "/join-us", "/work-with-us", "/careers/jobs", "/about/jobs"):
        add(path)
    for sub in ("careers.", "jobs.", "work."):
        add("https://" + sub + root)
    return out[:14]


# -------------------------------------------------------------- 4. the role
def norm_title(t):
    t = re.sub(r"\(.*?\)", " ", (t or "").lower())
    t = re.sub(r"\b(sr\.?|snr)\b", "senior", t)
    t = re.sub(r"\b(jr\.?)\b", "junior", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    drop = {"remote", "hybrid", "onsite", "fulltime", "full", "time", "contract",
            "emea", "eu", "europe", "worldwide", "anywhere", "m", "f", "d", "x"}
    return [w for w in t.split() if w and w not in drop and w not in STOP]


def title_match(a, b):
    """How close two titles are, ignoring the decoration boards bolt on."""
    A, B = set(norm_title(a)), set(norm_title(b))
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def find_job(careers, title):
    """The posting for this role on the company's own careers surface.

    Returns the best match and its score. The caller decides whether it is good
    enough; a confident wrong match is the one failure this module must not
    produce, so nothing here rounds a maybe up to a yes.
    """
    best = None
    for page in careers:
        try:
            html, final = get(page)
        except Exception:
            continue
        host = urllib.parse.urlsplit(final).netloc
        links = {}
        for m in re.finditer(r'href="([^"#]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
            href, label = m.group(1), P.strip_html(m.group(2), 200).strip()
            if not label or len(label) > 120:
                continue
            if not re.search(r"/job|/position|/opening|/vacanc|/careers/|/o/|gh_jid", href, re.I):
                continue
            links.setdefault(urllib.parse.urljoin(final, href), label)
        for url, label in links.items():
            s = title_match(title, label)
            if not best or s > best["score"]:
                best = {"url": url, "label": label, "score": round(s, 3),
                        "careers": page, "host": host}
        # a sitemap is the reliable way in when the listing is client-rendered
        if not best or best["score"] < 0.8:
            for sm in (urllib.parse.urljoin(final, "/sitemap.xml"),):
                try:
                    xml, _ = get(sm)
                except Exception:
                    continue
                for loc in re.findall(r"<loc>(.*?)</loc>", xml)[:4000]:
                    if not re.search(r"/job|/position|/opening", loc, re.I):
                        continue
                    label = urllib.parse.unquote(loc.rstrip("/").split("/")[-1]).replace("-", " ")
                    s = title_match(title, label)
                    if not best or s > best["score"]:
                        best = {"url": loc, "label": label, "score": round(s, 3),
                                "careers": sm, "host": urllib.parse.urlsplit(loc).netloc}
        if best and best["score"] >= 0.95:
            break
    return best


# --------------------------------------------------------- 5. what it says
def read_original(url):
    """The posting as the employer publishes it: text, and the facts it states.

    JobPosting metadata is taken when it is there and never trusted over the
    words on the page - it is the same field a board would fake. Where both
    exist and disagree, the page wins, as it does everywhere else here.
    """
    html, final = get(url, timeout=25)
    out = {"url": final, "jd": P.strip_html(html)}
    for m in re.finditer(r'application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            d = json.loads(m.group(1))
        except Exception:
            continue
        for o in (d if isinstance(d, list) else [d]):
            if not isinstance(o, dict) or o.get("@type") != "JobPosting":
                continue
            if o.get("datePosted"):
                out["posted"] = P.iso_date(str(o["datePosted"]))
            if o.get("validThrough"):
                out["closes"] = P.iso_date(str(o["validThrough"]))
            locs = []
            for L in (o.get("jobLocation") or []) if isinstance(o.get("jobLocation"), list) \
                    else [o.get("jobLocation")]:
                a = ((L or {}).get("address") or {})
                locs.append(", ".join(x for x in (a.get("addressLocality"),
                                                  a.get("addressRegion"),
                                                  a.get("addressCountry")) if x))
            locs = [x for x in locs if x]
            if locs:
                out["location"] = "; ".join(dict.fromkeys(locs))
            alr = o.get("applicantLocationRequirements")
            if alr:
                names = [a.get("name") for a in (alr if isinstance(alr, list) else [alr])
                         if isinstance(a, dict) and a.get("name")]
                # A 173-country list is a board's boilerplate, not a restriction
                # anyone wrote. Over a handful it says nothing.
                if 0 < len(names) <= 8:
                    out["restrictions"] = "; ".join(names)
            if o.get("employmentType"):
                t = o["employmentType"]
                out["employment_type"] = ", ".join(t) if isinstance(t, list) else str(t)
            if o.get("title"):
                out["title"] = o["title"]
    return out


def diff_facts(rec, orig):
    """Where the board and the employer disagree, field by field.

    Absence is the point. A board claiming "Fully remote" over a posting that
    never says it is the common lie, and nothing was added - something was
    missing. So every field is reported as a pair, including when one side is
    empty, rather than left to a text diff to notice.
    """
    out = {}
    for f in ("location", "workplace", "posted", "employment_type", "restrictions"):
        a = str(rec.get(f) or "").strip()
        b = str(orig.get(f) or "").strip()
        if a.lower() != b.lower() and (a or b):
            out[f] = {"board": a or None, "original": b or None}
    return out


def text_changed(a, b):
    """Did the description say something materially different, or just sit in
    different furniture. Cheap gate: a re-judge costs a model call, and most
    originals will say what their copy said."""
    A, B = words(a, 12000), words(b, 12000)
    if not A or not B:
        return True
    return len(A & B) / max(len(A | B), 1) < 0.75


# ------------------------------------------------------------------ the run
def fetch_one(rec, jd_text, sites=None):
    """The whole chain for one role: company -> site -> careers -> the posting.

    Every outcome is named. "blocked" and "no_site" and "no_match" are three
    different things and collapsing them into a bare failure is how a module
    like this quietly rots - you cannot tell a company that has no careers page
    from one that put a bot wall in front of it.
    """
    sites = sites if sites is not None else {}
    company = (rec.get("company") or "").strip()
    title = (rec.get("title") or "").strip()
    if not company or not title:
        return {"status": "no_company"}

    # Cheapest question first, and no model anywhere near it: is the posting
    # the board pointed at still there. A 404, or a redirect onto a listing
    # page, settles the role without hunting for the company at all.
    url = rec.get("url")
    if url:
        try:
            html, final = get(url, timeout=12)
            if redirected_to_index(url, final):
                return {"status": "gone", "url": url, "landed": final}
        except Blocked:
            pass                       # a bot wall says nothing either way
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return {"status": "gone", "url": url, "why": f"HTTP {e.code}"}
        except Exception:
            pass

    profile = words(jd_text)
    key = company.lower()
    learned = sites.get(key)

    verified = None
    if learned and learned.get("host"):
        # what we worked out on an earlier run, believed until it stops resolving
        try:
            html, final = get("https://" + learned["host"])
            verified = {"host": learned["host"], "html": html, "score": learned.get("score", 1.0)}
        except Blocked:
            return {"status": "blocked", "at": learned["host"]}
        except Exception:
            verified = None

    if not verified:
        blocked = False
        for host in candidate_sites(company, jd_text):
            try:
                v = verify_site(host, company, profile)
            except Blocked:
                blocked = True
                continue
            if v and v["score"] >= 0.55:
                verified = v
                break
        if not verified:
            return {"status": "blocked" if blocked else "no_site"}
        sites[key] = {"host": verified["host"], "score": verified["score"],
                      "found": datetime.now(timezone.utc).strftime("%Y-%m-%d")}

    careers = (([learned["careers"]] if learned and learned.get("careers") else [])
               + careers_urls(verified["host"], verified.get("html")))
    try:
        best = find_job(careers, title)
    except Blocked:
        return {"status": "blocked", "at": verified["host"]}
    if not best or best["score"] < 0.5:
        # the company is real and reachable; this role is not on its board
        return {"status": "no_match", "site": verified["host"],
                "careers": careers[0] if careers else None,
                "best": best["label"] if best else None,
                "best_score": best["score"] if best else 0}
    sites[key]["careers"] = best["careers"]

    try:
        orig = read_original(best["url"])
    except Blocked:
        return {"status": "blocked", "at": best["host"]}
    except Exception as e:
        return {"status": "unreadable", "url": best["url"], "why": type(e).__name__}

    return {"status": "found", "site": verified["host"], "match": best["score"],
            "matched_label": best["label"], **orig,
            "diff": diff_facts(rec, orig),
            "changed": text_changed(jd_text, orig.get("jd") or "")}


def load(path, default):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except Exception:
        return default


def main():
    import contracts
    import criteria

    pool_doc = contracts.load_pool(POOL_FILE)
    jd = load(JD_FILE, {})
    out = load(ORIGINALS_FILE, {})
    sites = load(SITES_FILE, {})

    must = re.compile(criteria.L1_MUST_HAVE, re.I)
    exc = re.compile(criteria.L1_EXCLUDE, re.I)
    # Only what survives L1. A role the title already ruled out does not need
    # its original found - that is the whole reason this runs after L1.
    todo = [r for r in pool_doc["jobs"]
            if r.get("active") and (r.get("title") or "")
            and must.search(r["title"]) and not exc.search(r["title"])
            and out.get(r["id"], {}).get("status") not in ("found", "no_site", "no_company")]
    if "--old" in sys.argv:
        # The roles whose absence at the employer actually means something:
        # over ten weeks, and therefore droppable if nobody is hiring for them.
        import results as R
        todo = [r for r in todo if (R.age_days(r) or 0) > R.GHOST_DAYS]
        todo.sort(key=lambda r: -(R.age_days(r) or 0))
    if "--lanes" in sys.argv:
        # Only what is actually on the board: the three lanes, minus the 69+
        # shelf. L1 survivors are 3,500 roles he will never read; these are the
        # ones in front of him.
        import results as R
        res = json.loads((ROOT / "data" / "results.json").read_text())
        ids = {i for k in ("open", "portugal", "unsure") for i in res["lanes"].get(k, [])}
        todo = [r for r in todo if r["id"] in ids
                and (R.age_days(r) or 10**6) <= R.GHOST_DAYS]
        todo.sort(key=lambda r: R.age_days(r) or 0)
    if "--lanes" in sys.argv:
        # Only what is actually on the board: the three lanes, minus the 69+
        # shelf. L1 survivors are 3,500 roles he will never read; these are the
        # ones in front of him.
        import results as R
        res = json.loads((ROOT / "data" / "results.json").read_text())
        ids = {i for k in ("open", "portugal", "unsure") for i in res["lanes"].get(k, [])}
        todo = [r for r in todo if r["id"] in ids
                and (R.age_days(r) or 10**6) <= R.GHOST_DAYS]
        todo.sort(key=lambda r: R.age_days(r) or 0)
    if "--fresh" in sys.argv:
        # The live half: young enough that a miss means "serve source only",
        # not "drop it". Newest first, because those are the ones he is reading.
        import results as R
        todo = [r for r in todo if (R.age_days(r) or 10**6) <= R.GHOST_DAYS]
        todo.sort(key=lambda r: R.age_days(r) or 0)
    if "--limit" in sys.argv:
        todo = todo[:int(sys.argv[sys.argv.index("--limit") + 1])]

    print(f"{len(todo)} roles to look up ({len(out)} already known, "
          f"{len(sites)} company sites learned)", flush=True)
    tally = {}
    t0 = datetime.now(timezone.utc)

    def save():
        for path, doc in ((ORIGINALS_FILE, out), (SITES_FILE, sites)):
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
            tmp.replace(path)

    for n, rec in enumerate(todo, 1):
        try:
            r = fetch_one(rec, jd.get(rec["id"]) or "", sites)
        except Exception as e:                      # never let one role stop the run
            r = {"status": "error", "why": f"{type(e).__name__}: {e}"[:120]}
        r["when"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out[rec["id"]] = r
        tally[r["status"]] = tally.get(r["status"], 0) + 1
        # Per-role, out loud: a silent batch that saves at the end is a batch
        # you cannot stop, cannot resume and cannot watch.
        print(f"  [{n}/{len(todo)}] {r['status']:11} "
              f"{(rec.get('company') or '')[:24]:24} "
              f"{(r.get('matched_label') or r.get('site') or '')[:38]}"
              f"  {(datetime.now(timezone.utc)-t0).seconds}s", flush=True)
        if n % 10 == 0:
            save()
    save()
    print(f"\n{ORIGINALS_FILE.name}: {tally}", flush=True)
    found = [v for v in out.values() if v.get("status") == "found"]
    lied = [v for v in found if v.get("diff")]
    print(f"{len(found)} originals, {len(lied)} disagree with the board they came from",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
