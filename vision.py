"""vision: the judge's second pass. A real page, read whole.

    pool        -> data/pool.json      every role found. no opinions.
    parser      -> (judge.l1)          title only. free.
    vision      -> data/vision.json    the page, in a browser, read by Claude.
    results     -> data/results.json   lanes.

For each role: load its posting in Chrome (render.py). If the row came from a
job board, press Apply and load the employer's own page too - that is the
page that is true. Then Claude reads every word on screen and answers, in
this order: is it still open, is it a design role, can he do it from Portugal.

Three things the old judge got wrong and this does not do:
  - it never reads pasted-together fields. It reads the rendered page.
  - a role only reaches Open when the EMPLOYER's page was read. A board's
    copy alone lands in Unsure, with the reason.
  - nothing is dropped. A closed posting goes to a Closed lane, a cut keeps
    its reason and the words on the page that decided it.

    python3 vision.py --lanes            # every role in the current lanes
    python3 vision.py --new              # parser survivors never read by vision
    python3 vision.py --ids a,b,c        # these
    python3 vision.py --fresh            # --new, minus roles the old judge cut on employer text
    python3 vision.py --limit 50         # at most this many
    python3 vision.py --employer         # roles judged on a board's copy: try again for the company's page
    python3 vision.py --again            # re-read even if already read
"""
import json, os, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contracts, criteria, employer, judge, read, render

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = f"{ROOT}/data/vision.json"
MODEL = os.environ.get("RADAR_VISION_MODEL", "sonnet")
WORKERS = 6
MAX_CHARS = 30000          # a long posting is ~10k; this is the page, menus and all
# A page costs about 6,500 tokens to read. The old judge spent 30,000 on each
# because it sent the CLI's whole system prompt and tool list along, and nobody
# measured it. This is measured every run, and a run that drifts above the
# ceiling stops itself rather than spend his tokens on a mistake.
CEILING = 12000            # tokens per page, in + out, averaged
RUNS_LOG = f"{ROOT}/data/vision_runs.jsonl"

# A page that is certainly gone needs no reader. Only what cannot be argued
# with: the server said gone, or the page is nothing but the sentence.
GONE = employer.GONE
UIUX_GONE = "This role is no longer available!"
# "Performing security verification" was missing from this list, so 115 of
# these screens were handed to the reader as if they were postings.
WALL = re.compile(r"(?i)just a moment|checking your browser|verify you are human|enable javascript and cookies|access denied|"
                  r"performing security verification|security service to protect|this site can.t be reached|ERR_[A-Z0-9_]{4,}")

_lock = threading.Lock()
_usage = {"calls": 0, "in": 0, "out": 0, "usd": 0.0}


# The wording that got past the first version, word for word: "You've hit your
# session limit · resets 3pm (Europe/Lisbon)". It was not recognised, 25 roles
# failed in a row, and the run stopped five hours before he came back. Any
# mention of a limit or a reset is a limit.
LIMIT = re.compile(r"(?i)\blimit\b|\bresets?\b|quota|out of (extra )?usage|overloaded|too many requests|\b429\b")


class ReaderDown(Exception):
    """The reader could not answer. Not a fact about the posting: the role stays unread."""


def wait_for_reset(msg):
    """His plan's usage ran out. Nothing is wrong with the run, so it does not
    end and it does not guess: it sleeps, asks a one-word question every ten
    minutes, and carries on from the same role the moment an answer comes."""
    with _limit_lock:                      # one sleeper; the other readers queue behind it
        if time.time() - _limit["cleared"] < 120:
            return                         # another reader has just seen it come back
        m = re.search(r"\|(\d{10})\b", msg or "")
        until = int(m.group(1)) if m else None
        _paused_at = time.time()
        print(f"PAUSED {time.strftime('%H:%M')}: usage limit ({str(msg)[:90]}). "
              + (f"Resets about {time.strftime('%H:%M', time.localtime(until))}. " if until else "")
              + "Waiting; the run picks up by itself.", flush=True)
        while True:
            time.sleep(max(60, min(600, (until - time.time()) + 30)) if until and until > time.time() else 600)
            try:
                r = subprocess.run(["claude", "-p", "Reply with the word ok.", "--output-format", "json", "--model", MODEL,
                                    "--system-prompt", "Reply with one word.", "--tools", "", "--strict-mcp-config",
                                    "--setting-sources", ""], capture_output=True, text=True, timeout=120,
                                   env=read.cli_env(), cwd="/tmp")
                if not json.loads(r.stdout).get("is_error"):
                    break
            except Exception:
                pass
        _usage["waited"] = _usage.get("waited", 0) + (time.time() - _paused_at)
        _limit["cleared"] = time.time()
        print(f"RESUMED {time.strftime('%H:%M')}", flush=True)


_limit_lock, _limit = threading.Lock(), {"cleared": 0}


SYSTEM = "You read one job posting and answer with one JSON object."


def ask(prompt, system=None):
    """One page, one answer. The CLI's own system prompt and tools are 30,000
    tokens a call and none of it is needed to read a page, so they are off."""
    last = None
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "json", "--model", MODEL,
                 "--system-prompt", system or SYSTEM,
                 "--tools", "", "--strict-mcp-config", "--setting-sources", ""],
                capture_output=True, text=True, timeout=240, env=read.cli_env(), cwd="/tmp")
            env = json.loads(r.stdout)
            if env.get("is_error"):
                last = "api: " + str(env.get("result"))[:160]
                if LIMIT.search(str(env.get("result"))):
                    wait_for_reset(str(env.get("result")))
                    return ask(prompt, system)
                time.sleep(4 * 2 ** attempt)
                continue
            u = env.get("usage") or {}
            with _lock:
                _usage["calls"] += 1
                _usage["in"] += (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) \
                    + (u.get("cache_read_input_tokens") or 0)
                _usage["out"] += u.get("output_tokens") or 0
                _usage["usd"] += env.get("total_cost_usd") or 0
                if _usage["calls"] >= 10 and (_usage["in"] + _usage["out"]) / _usage["calls"] > CEILING:
                    _usage["stop"] = _usage["over"] = True
            return read.parse(env.get("result") or "")
        except subprocess.TimeoutExpired:
            last = "timeout"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
    raise ReaderDown(last)


def gone(page):
    """The words that prove this page is a dead posting, or None."""
    if not page:
        return None
    text = page.get("text") or ""
    if page.get("status") in (404, 410):
        return f"the server answered {page['status']}: " + " ".join(text.split())[:120]
    if UIUX_GONE in text:
        return UIUX_GONE
    if len(text) < 1500:
        m = GONE.search(text)
        if m:
            return " ".join(text.split())[:160]
    return None


def off_the_posting(rec, page):
    """The board sent us somewhere else: its home page, a list of jobs. An
    expired listing often redirects instead of saying so."""
    return page.get("url") != page.get("asked") and not employer.has_title(rec["title"], page)


LISTING = re.compile(r"(?i)open positions|current openings|job openings|open roles|all jobs|view all (open )?(jobs|positions|roles)|"
                     r"search (for )?jobs|filter by|\d+ (jobs|positions|openings)\b")


def unread(page):
    text = (page or {}).get("text") or ""
    return len(text) < 200 or bool(WALL.search(text[:600]))


def employer_page(br, rec, first):
    """The employer's posting, tried the ways that actually fail in practice.

    221 roles sat in Unsure as "page could not be read", and almost none of
    them were a robot check - a visible browser reads them no better than a
    hidden one. What was really happening:
      - a company's careers site shows a Greenhouse posting inside a frame
        (ionq.com/job?gh_jid=..., psiquantum.com/apply?gh_jid=...). The words
        are in the frame, not the page, so the page read as empty. The same
        posting is on Greenhouse's own address, in the open.
      - a slow careers site had not finished drawing when it was read.
      - the posting was gone and its link opened the company's list of jobs,
        which is not unreadable: it is the employer saying the job is closed.
    Returns (page, gone) - gone is the sentence that says the posting is closed.
    """
    page, title = first, rec.get("title")
    ok = lambda p: not unread(p) and employer.has_title(title, p)
    src = rec.get("source") or ""
    m = re.search(r"gh_jid=(\d+)|greenhouse\.io/[^/]+/jobs/(\d+)", rec.get("url") or "")
    framed = bool(m) and "greenhouse.io" not in (rec.get("url") or "")     # the title is in the menu, the posting in a frame
    if ok(page) and not framed:
        return page, None
    if m and src.startswith("greenhouse/"):
        jid, slug = m.group(1) or m.group(2), src.split("/", 1)[1]
        for host in ("job-boards.greenhouse.io", "job-boards.eu.greenhouse.io", "boards.greenhouse.io"):
            alt = br.page(f"https://{host}/{slug}/jobs/{jid}", shot=render.shot_path(rec["id"]))
            if ok(alt):
                return alt, None
            if not unread(alt) and (alt.get("status") in (404, 410) or "error=true" in (alt.get("url") or "")
                                    or LISTING.search((alt.get("text") or "")[:3000])):
                return alt, "the employer's board no longer has this posting: its link opens the list of open jobs"
    if ok(page) and len(page.get("text") or "") > 2500:
        return page, None                  # the company's own page did carry the posting after all
    if unread(page) or not employer.has_title(title, page):
        slow = br.page(rec["url"], shot=render.shot_path(rec["id"]), settle=8)      # a slow site, given time
        if ok(slow):
            return slow, None
        if not unread(slow):
            page = slow
    # On a hiring system, a posting's own address that now shows a list of jobs is a closed posting.
    if not unread(page) and not employer.has_title(title, page) and employer.ATS.search(page.get("url") or "") \
            and LISTING.search((page.get("text") or "")[:3000]):
        return page, "the employer's board no longer has this posting: its link opens the list of open jobs"
    return page, None


def greenhouse_feed(rec):
    """A posting's own text from Greenhouse's public feed, for a link that
    carries a Greenhouse job number (…?gh_jid=123) but opens a page we cannot
    read - VML's careers site sits behind a security screen, and a job board
    gave us the link with a two-line summary. The feed is the employer's
    hiring system speaking, so this is the employer's posting."""
    import urllib.request
    m = re.search(r"gh_jid=(\d+)", rec.get("url") or "")
    if not m:
        return None
    name = re.findall(r"[a-z0-9]+", (rec.get("company") or "").lower())
    for slug in dict.fromkeys(["".join(name), "-".join(name), name[0] if name else ""]):
        if len(slug) < 2:
            continue
        try:
            req = urllib.request.Request(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{m.group(1)}",
                                         headers={"User-Agent": "Mozilla/5.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
        except Exception:
            continue
        import pool as P
        body = P.strip_html(d.get("content") or "")
        offices = "; ".join(o.get("name") or "" for o in d.get("offices") or [])
        if len(body) > 400 and employer.has_title(rec.get("title"), {"title": d.get("title"), "text": ""}):
            return {"url": d.get("absolute_url") or rec["url"], "title": d.get("title"),
                    "text": f"{d.get('title')}\n{rec.get('company')}\n\nLocation\n{(d.get('location') or {}).get('name') or ''}\n"
                            + (f"\nOffices\n{offices}\n" if offices else "") + "\n" + body}
    return None


def _get(url, timeout=20):
    """(status, parsed json or None). 0 when the network failed: that is not an answer."""
    import urllib.request, urllib.error
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout).read()
        return 200, json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code == 429 and timeout != -1:              # asked too fast: wait, ask once more
            time.sleep(20)
            code, d = _get(url, 30)
            return (0, None) if code == 429 else (code, d)
        return e.code, None
    except Exception:
        return 0, None


def _gh_boards(_c={}):
    """Greenhouse board names the pool already scrapes."""
    if "b" not in _c:
        try:
            _c["b"] = list(json.load(open(f"{ROOT}/data/sources.json"))["watchlist"].get("greenhouse") or [])
        except Exception:
            _c["b"] = []
    return _c["b"]


GONE_AT_SOURCE = "the employer's hiring system no longer has this posting"


def ats_feed(rec):
    """The hiring system itself, asked about this one posting.

    148 roles sat in "Not read". Most were on a hiring system whose page the
    browser was shown wrong: the posting's own address drew the company's list
    of jobs, or only the application form, or an empty frame on the company's
    site. The systems all answer a plain question - is this posting up, and
    what does it say - and a posting that is gone answers 404. Asked, Lever
    and Workable said postings were live whose pages had drawn as a list, so
    a list on screen is not proof a job is closed; this is.

    Returns ("open", page) with the employer's own words, ("gone", sentence),
    or None when the system could not be asked or did not answer plainly."""
    import pool as P
    url, title = rec.get("url") or "", rec.get("title")
    src = rec.get("source") or ""
    page = lambda u, t, where, body: ("open", {"url": u or url, "title": t,
            "text": f"{t}\n{rec.get('company')}\n\nLocation\n{where}\n\n{body}"})
    named = lambda t: employer.has_title(title, {"title": t, "text": ""})

    m = re.search(r"greenhouse\.io/([^/?#]+)/jobs/(\d+)", url)
    jid = m.group(2) if m else (re.search(r"gh_jid=(\d+)", url) or [None, None])[1]
    if jid:
        sure = [m.group(1)] if m and m.group(1) != "embed" else []
        if src.startswith("greenhouse/"):
            sure.append(src.split("/", 1)[1])
        name = re.findall(r"[a-z0-9]+", (rec.get("company") or "").lower())
        guess = ["".join(name), "-".join(name), name[0] if name else ""]
        guess += [g for g in _gh_boards() if name and g.startswith(name[0]) and len(name[0]) > 3][:6]   # digitalocean98
        for slug in dict.fromkeys(sure + guess):
            if len(slug) < 2:
                continue
            code, d = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}")
            if code == 200 and d and named(d.get("title")):
                offices = "; ".join(o.get("name") or "" for o in d.get("offices") or [])
                where = ((d.get("location") or {}).get("name") or "") + (f"\n\nOffices\n{offices}" if offices else "")
                body = P.strip_html(d.get("content") or "")
                if len(body) > 400:
                    return page(d.get("absolute_url"), d.get("title"), where, body)
            if code == 404 and slug in sure:
                return "gone", GONE_AT_SOURCE
        return None

    m = re.search(r"jobs\.(eu\.)?lever\.co/([^/?#]+)/([0-9a-f-]{36})", url)
    if m:
        # Lever's answer for one posting includes unlisted ones whose page is
        # a 404 (aircall, fresha): nobody can apply to those. The company's
        # published list is what is open.
        code, rows = _get(f"https://api.{m.group(1) or ''}lever.co/v0/postings/{m.group(2)}?mode=json", timeout=40)
        if code == 404:
            return "gone", GONE_AT_SOURCE
        if code != 200 or not isinstance(rows, list):
            return None
        d = next((x for x in rows if x.get("id") == m.group(3)), None)
        if d is None:
            return "gone", GONE_AT_SOURCE
        if named(d.get("text")):
            c = d.get("categories") or {}
            where = "; ".join(c.get("allLocations") or [c.get("location") or ""]) \
                + (f"\n\nLocation Type\n{d.get('workplaceType')}" if d.get("workplaceType") else "") \
                + (f"\n\nEmployment Type\n{c.get('commitment')}" if c.get("commitment") else "")
            body = "\n\n".join([d.get("descriptionPlain") or ""]
                               + [f"{l.get('text')}\n{P.strip_html(l.get('content') or '')}" for l in d.get("lists") or []]
                               + [d.get("additionalPlain") or ""])
            return page(d.get("hostedUrl"), d.get("text"), where, body)
        return None

    m = re.search(r"apply\.workable\.com/([^/?#]+)/j/([0-9A-F]+)", url)
    if m:
        code, d = _get(f"https://apply.workable.com/api/v2/accounts/{m.group(1)}/jobs/{m.group(2)}")
        if code == 404:
            return "gone", GONE_AT_SOURCE
        if code == 200 and d and named(d.get("title")):
            l = d.get("location") or {}
            where = ", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x) \
                + f"\n\nLocation Type\n{d.get('workplace') or ('remote' if d.get('remote') else 'not stated')}"
            body = "\n\n".join(P.strip_html(d.get(k) or "") for k in ("description", "requirements", "benefits"))
            return page(url, d.get("title"), where, body)
        return None

    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url)
    if m:
        code, d = _get(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}", timeout=40)
        if code != 200 or not d or not d.get("jobs"):
            return None
        j = next((x for x in d["jobs"] if x.get("id") == m.group(2)), None)
        if not j:
            return "gone", GONE_AT_SOURCE
        if named(j.get("title")):
            more = "; ".join(x.get("location") or "" for x in j.get("secondaryLocations") or [])
            where = (j.get("location") or "") + (f"; {more}" if more else "") \
                + f"\n\nLocation Type\n{j.get('workplaceType') or ('Remote' if j.get('isRemote') else 'not stated')}" \
                + (f"\n\nEmployment Type\n{j.get('employmentType')}" if j.get("employmentType") else "")
            return page(j.get("jobUrl"), j.get("title"), where, j.get("descriptionPlain") or P.strip_html(j.get("descriptionHtml") or ""))
    return None


def himalayas_feed(rec):
    """A himalayas posting, from himalayas' own feed. Its pages show a script
    a security screen, but its search feed answers with the full description,
    the countries it is restricted to, the time zones, and the link it sends
    applicants to. Everything the page would have said."""
    import urllib.request, urllib.parse
    if "himalayas.app" not in (rec.get("url") or ""):
        return None
    # Asked by title and company the feed missed most postings. Asked by the
    # company's name alone it lists what that company has up on himalayas.
    m = re.search(r"himalayas\.app/companies/([^/]+)/jobs/", rec["url"])
    slug = m.group(1) if m else ""
    base, rows, listed = rec["url"].rstrip("/"), [], False
    for q in (slug.replace("-", " "), rec.get("company") or "", f"{rec.get('title')} {rec.get('company')}"):
        code, d = _get(f"https://himalayas.app/jobs/api/search?q={urllib.parse.quote(q)}&limit=50", 25)
        got = (d or {}).get("jobs") or []
        rows += got
        mine = [x for x in got if f"/companies/{slug}/jobs/" in (x.get("guid") or "")]
        listed = listed or (bool(mine) and (d.get("totalCount") or 0) <= len(got))      # the whole answer, and the company is in it
        if any((x.get("guid") or "").rstrip("/").startswith(base) for x in got):
            break
    j = next((x for x in rows if (x.get("guid") or "").rstrip("/") == base), None) \
        or next((x for x in rows if (x.get("guid") or "").startswith(base)), None)
    if not j:
        if listed:
            return {"gone": "himalayas lists this company's jobs and this posting is no longer among them"}
        return None
    import pool as P
    where = ", ".join(j.get("locationRestrictions") or []) or "no country restriction listed"
    tz = j.get("timezoneRestrictions")
    return {"url": rec["url"], "title": j.get("title"), "apply": j.get("applicationLink"),
            "text": f"{j.get('title')}\n{j.get('companyName')}\n\nLocation\nRemote · open to: {where}\n"
                    + (f"\nTime zones\n{tz}\n" if tz else "")
                    + (f"\nEmployment Type\n{j.get('employmentType')}\n" if j.get("employmentType") else "")
                    + "\n" + P.strip_html(j.get("description") or "")}


_jd = {}


def stored_text(rid):
    """The description the pool scraped for a role. Loaded once, when first needed: the file is large."""
    with _jd_lock:
        if "all" not in _jd:
            path = f"{ROOT}/data/jd.json"
            _jd["all"] = json.load(open(path)) if os.path.exists(path) else {}
    return _jd["all"].get(rid) or ""


_jd_lock = threading.Lock()


def reader(rec, page):
    """One page, read under criteria.VISION_RULES. The rules go in the system
    slot, which is the same for every call, so the model keeps them between
    calls and only the page is new each time: the rules are loaded once, and
    the roles run through them."""
    prompt = (f"The pool lists this role as: {rec.get('title')} at {rec.get('company')}."
              + f"\nPage address: {page.get('url')}\nPage title: {page.get('title')}"
              + "\n\n--- EVERY WORD VISIBLE ON THE PAGE ---\n" + (page.get("text") or "")[:MAX_CHARS])
    return ask(prompt, system=criteria.VISION_RULES)


def see(finder, rec):
    """Everything vision knows about one role."""
    br = finder.br
    is_board = "/" not in (rec.get("source") or "") and not employer.ATS.search(rec.get("url") or "")
    first = br.page(rec["url"], shot=render.shot_path(rec["id"]))
    listed_gone = feed_gone = None
    fed_by_system = False
    if not is_board:
        first, listed_gone = employer_page(br, rec, first)
        # The page is the posting when it drew as one. When it did not - a
        # list of jobs, a bare form, an empty frame - the hiring system is
        # asked, and its answer stands over whatever the browser was shown.
        text0 = (first or {}).get("text") or ""
        # A page that itself answers "gone" is believed: Lever's feed still
        # lists postings whose page is a 404, and nobody can apply to those.
        if not gone(first) and (listed_gone or unread(first) or not employer.has_title(rec.get("title"), first or {}) or len(text0) < 1500):
            said = ats_feed(rec)
            if said and said[0] == "gone":
                listed_gone = said[1]
            elif said and len(said[1]["text"]) > 600:
                first, listed_gone, fed_by_system = {**(first or {}), **said[1]}, None, True
    board, emp, found, tried = (first, None, None, []) if is_board else (None, first, None, [])
    feed = None
    if is_board:
        # a board whose page is behind a security screen still has a feed, and
        # the feed names the link it sends applicants to: the way to the employer
        feed = himalayas_feed(rec) if unread(board) else None
        feed_gone = (feed or {}).pop("gone", None) if feed else None
        feed = feed or None
        found, tried = finder.find(rec, board, hint=(feed or {}).get("apply"))
        emp = found and found["page"]
    if is_board and not found and rec["id"] in PREV:
        return {**PREV[rec["id"]], "looked": tried, "looked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}   # still only the board's copy: nothing new to read
    keep = ("url", "status", "shot", "error")
    v = {"id": rec["id"], "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "criteria": criteria.VERSION,
         "model": MODEL, "pool_url": rec["url"],
         "board": board and {k: board.get(k) for k in keep},
         "employer": emp and {k: emp.get(k) for k in keep},
         "found_by": found and found["how"], "looked": tried}
    if fed_by_system:
        v["fed"] = "hiring system"

    # The employer's page is the posting; the board's is a copy of it. So the
    # employer decides whether the job is open - a board calling it closed is
    # wrong about one in eight that the employer still lists.
    if found and found.get("gone"):
        return {**v, "lane": "closed", "posting_open": "no", "closed_by": "employer", "read": "employer",
                "read_url": emp.get("url"), "open_quote": found["gone"], "stage": "render",
                "reason": "the employer says it is closed"}
    if not is_board and (listed_gone or gone(emp)):
        return {**v, "lane": "closed", "posting_open": "no", "closed_by": "employer", "read": "employer",
                "read_url": emp.get("url"), "open_quote": listed_gone or gone(emp), "stage": "render",
                "reason": "the employer says it is closed"}
    if is_board and not found:
        dead = feed_gone or gone(board) or (off_the_posting(rec, board) and "the board sent the link somewhere else: " + str(board.get("url")))
        if dead:
            return {**v, "lane": "closed", "posting_open": "no", "closed_by": "board", "read": "board",
                    "read_url": board.get("url"), "open_quote": dead, "stage": "render",
                    "reason": "the board says it is closed, and the employer's posting was not found"}

    page = emp if emp and len(emp.get("text") or "") > 200 else board
    v["read"] = "employer" if emp is not None and page is emp else "board"
    v["read_url"] = page.get("url") if page else None
    text = (page or {}).get("text") or ""
    shell = not is_board and (len(text) < 200 or WALL.search(text[:600]) or not employer.has_title(rec.get("title"), page or {})
                              or len(text) < 1500)
    if shell:
        # A company page that frames its posting, or will not load. The pool
        # read this posting from the employer's own hiring system, so the
        # employer's words are on file: the description and the location as
        # the system gives them. That is the employer's posting, not a copy.
        fed = stored_text(rec["id"])
        if len(fed) > 400:
            panel = "\n".join(f"{k}\n{rec.get(f)}\n" for f, k in (("location", "Location"), ("workplace", "Location Type"),
                              ("employment_type", "Employment Type"), ("department", "Department")) if rec.get(f))
            page = {"url": rec["url"], "title": rec.get("title"),
                    "text": f"{rec.get('title')}\n{rec.get('company')}\n\n{panel}\n{fed}"}
            text, v["read"], v["read_url"], v["fed"] = page["text"], "employer", rec["url"], True
    if (len(text) < 200 or WALL.search(text[:600])) and "gh_jid=" in (rec.get("url") or ""):
        fed = greenhouse_feed(rec)
        if fed:
            page, text = fed, fed["text"]
            v["read"], v["read_url"], v["fed"] = "employer", fed["url"], True
    if (len(text) < 200 or WALL.search(text[:600])) and is_board and not found:
        fed = feed
        if fed and len(fed["text"]) > 400:
            page, text = fed, fed["text"]
            v["read"], v["read_url"], v["fed"] = "board", rec["url"], True
    if (len(text) < 200 or WALL.search(text[:600])) and is_board and not found:
        # The board will not show its page to a script (himalayas, behind a
        # security check). The pool still holds what the board's own feed
        # said about the job. That is a board's copy - never enough for Open -
        # but it is enough to cut what is plainly not for him, and to say why
        # the rest is Unsure, instead of leaving all of it as "not read".
        fed = stored_text(rec["id"])
        if len(fed) > 400:
            page = {"url": rec["url"], "title": rec.get("title"),
                    "text": f"{rec.get('title')}\n{rec.get('company')}\n\nLocation\n{rec.get('location') or ''}\n\n{fed}"}
            text, v["read"], v["read_url"], v["fed"] = page["text"], "board", rec["url"], True
    if len(text) < 200 or WALL.search(text[:600]):
        return {**v, "lane": "unsure", "posting_open": "unreadable", "stage": "render",
                "open_quote": " ".join(text.split())[:160] or (page or {}).get("error"),
                "reason": "the page could not be read in the browser"}
    # The page as it was read, kept so the battery can try a new rule on the
    # same words later, and so a wrong call can be traced to what was on screen.
    try:
        os.makedirs(f"{ROOT}/data/pages", exist_ok=True)
        open(f"{ROOT}/data/pages/{rec['id']}.txt", "w").write(text[:MAX_CHARS])
    except Exception:
        pass
    a = reader(rec, page)              # ReaderDown goes up: the role stays unread, for the next run
    v.update(a)
    v["stage"] = "vision"
    # The reader reports; criteria.lane_from_reading() decides. Every rule
    # about weighing what the page says is in that one function.
    lane, place, why = criteria.lane_from_reading({**a, "listed": {"title": rec.get("title"), "company": rec.get("company"),
                                                                    "own_page": v.get("read_url") == v.get("pool_url")}})
    v["lane"] = lane
    if place is not None:
        v["reader_place"], v["place_verdict"] = a.get("place_verdict"), place
    if why:
        v["reason"] = why + " · " + str(a.get("reason") or "")
    if lane == "closed":
        v["closed_by"] = v["read"]
    # A role is judged on what there is. Plenty of companies have no careers
    # page, and a posting that reads as a role for him, doable from Portugal,
    # is Open even when the only copy is a job board's (his call, 2026-10-03).
    # The board says which it was: the SOURCE tag is grey.
    return v


def save(out):
    """Whole file or nothing: results.py reads this while a run is still going."""
    # One writer at a time, each with a file of its own: two threads sharing
    # "vision.json.tmp" stopped a run on 2026-10-05 - one renamed the file
    # away while the other was still about to.
    with _save_lock:
        tmp = f"{OUT}.{os.getpid()}.{threading.get_ident()}.tmp"
        json.dump(dict(out), open(tmp, "w"), indent=1, ensure_ascii=False)
        os.replace(tmp, OUT)


_save_lock = threading.Lock()
UNREAD_TRIES = 2   # runs a page gets to open before the role is cut as unreadable
AUDIT_SHARE = 0.10 # of each run's cuts, read a second time


def audit(out, jobs, since=None, share=AUDIT_SHARE):
    """A second look at one cut in ten, to keep the cutting honest.

    Cuts are the error he cannot see, so after every run a tenth of them are
    read again, from the page as it was saved, by a reader that is not told
    what the first one said. A cut that survives is left alone. One that does
    not is his to look at: results.py lists it under "review" and the board
    shows it in For Reviewing. (His instruction, 2026-10-05.)"""
    import random
    cuts = [i for i, d in out.items() if d.get("lane") == "cut" and d.get("stage") == "vision" and not d.get("audit")
            and (since is None or str(d.get("at") or "") >= since) and i in jobs
            and os.path.exists(f"{ROOT}/data/pages/{i}.txt")]
    random.seed(time.strftime("%Y-%m-%d"))
    take = random.sample(sorted(cuts), min(len(cuts), max(1, round(len(cuts) * share)))) if cuts else []
    print(f"VISION: second read of {len(take)} of {len(cuts)} rejections", flush=True)
    wrong = [0]
    def one(i):
        rec = jobs[i]
        page = {"url": out[i].get("read_url") or rec["url"], "title": rec.get("title"), "text": open(f"{ROOT}/data/pages/{i}.txt").read()}
        a = reader(rec, page)
        lane, place, why = criteria.lane_from_reading({**a, "listed": {"title": rec.get("title"), "company": rec.get("company"),
                                                                        "own_page": out[i].get("read_url") == out[i].get("pool_url")}})
        with _lock:
            out[i]["audit"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "criteria": criteria.VERSION, "lane": lane,
                               "agrees": lane in ("cut", "closed"), "role": a.get("role_verdict"), "place": place,
                               "reason": ((why + " · ") if why else "") + str(a.get("reason") or ""),
                               "signals": [x for x in a.get("place_signals") or [] if isinstance(x, dict) and x.get("says") != "says_nothing"]}
            if lane not in ("cut", "closed"):
                wrong[0] += 1
                print(f"  ≠ {rec['company'][:22]} | {rec['title'][:40]} | VISION second read: {lane} | {str(a.get('reason'))[:90]}", flush=True)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(WORKERS) as ex:
        for n, _ in enumerate(ex.map(lambda i: _try(one, i), take), 1):
            if n % 25 == 0:
                save(out)
    save(out)
    print(f"VISION second read done: {len(take) - wrong[0]} rejections confirmed, {wrong[0]} for him to review", flush=True)


def _try(fn, i):
    try:
        fn(i)
    except ReaderDown as e:
        print(f"  VISION could not read {i} a second time: {str(e)[:80]}", flush=True)


SHOWN = {"cut": "rejected"}     # a lane value is stored as "cut"; the log says what VISION did
PREV = {}          # --employer: the verdicts already made on a board's copy, kept unless the employer's page turns up


LEFT = [0]            # roles pick() held back because of --limit


def pick(jobs, done):
    args = sys.argv
    if "--employer" in args:           # roles judged on a board's copy: look for the company's own page again
        rows = [j for j in jobs if j["id"] in done and done[j["id"]].get("read") == "board"
                and done[j["id"]].get("stage") == "vision" and done[j["id"]].get("lane") in ("open", "portugal", "unsure")
                and "/" not in (j.get("source") or "")]
        PREV.update({j["id"]: done[j["id"]] for j in rows})
        return rows
    if "--unread" in args:             # the roles filed "page could not be read", to try again
        rows = [j for j in jobs if j["id"] in done and (done[j["id"]].get("posting_open") == "unreadable"
                or "could not be read" in str(done[j["id"]].get("reason")))]
        if "--limit" in args:
            rows = rows[:int(args[args.index("--limit") + 1])]
        return rows
    if "--ids" in args:
        want = set(args[args.index("--ids") + 1].split(","))
        rows = [j for j in jobs if j["id"] in want]
    elif "--lanes" in args:
        res = json.load(open(f"{ROOT}/data/results.json"))
        want = {i for v in res["lanes"].values() for i in v} | set(res.get("agency") or [])
        rows = [j for j in jobs if j["id"] in want]
    else:   # --new: the freshest first, they are the ones worth applying to
        rows = [j for j in jobs if j.get("active") and judge.cut(j) is None]      # CUT: the title, then 45 days
        # Where a job is most likely hiding, first: roles nothing has ever
        # judged; then roles the old judge cut on a job board's copy, which
        # it could not trust; last the ones it cut on the employer's own
        # text. Newest first within each.
        old = json.load(open(f"{ROOT}/data/verdicts.json"))["jobs"] if os.path.exists(f"{ROOT}/data/verdicts.json") else {}
        rank = lambda j: 0 if not old.get(j["id"], {}).get("judged") else 1 if "/" not in j["source"] else 2
        # the freshest first, and fresh means last updated: the newest of the site's
        # updated date, the day the pool saw it change, and the posting date
        rows.sort(key=lambda j: max([str(j[k])[:10] for k in ("updated", "changed", "posted") if j.get(k)]
                                    or [str(j.get("first_seen") or "")[:10]]), reverse=True)
        rows.sort(key=rank)
        if "--fresh" in args:              # everything except what the old judge cut on the employer's own text
            rows = [j for j in rows if rank(j) < 2]
    if "--again" not in args:
        # Not read is not an answer. A page that would not open goes into the
        # next run once more ("add those to next batch run. if they dont open
        # again, cut them" - 2026-10-05); results.py cuts it after that.
        again = lambda d: d.get("posting_open") == "unreadable" and (d.get("unread_tries") or 1) < UNREAD_TRIES
        rows = [j for j in rows if j["id"] not in done or again(done[j["id"]])]
    if "--limit" in args:
        cap = int(args[args.index("--limit") + 1])
        LEFT[0] = max(0, len(rows) - cap)      # the night run caps the read (--limit 1000); the rest waits for tomorrow
        rows = rows[:cap]
    return rows


def main():
    jobs = contracts.load_pool(f"{ROOT}/data/pool.json")["jobs"]
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if "--audit" in sys.argv:          # --audit: a tenth of the last day's cuts; --audit --all: of every cut not yet checked
        since = None if "--all" in sys.argv else time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 86400))
        audit(out, {j["id"]: j for j in jobs}, since)
        u = _usage
        if u["calls"]:
            print(f"{u['calls']} pages read by {MODEL}: {(u['in'] + u['out']) // u['calls']:,} tokens per page, ${u['usd']:.2f} at API prices")
            with open(RUNS_LOG, "a") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "audit": True, "pages_read": u["calls"],
                                    "tokens_per_page": (u["in"] + u["out"]) // u["calls"], "model": MODEL,
                                    "criteria": criteria.VERSION}) + "\n")
        return
    rows = pick(jobs, out)
    print(f"VISION: {len(rows)} roles to read, model {MODEL}, {WORKERS} at a time", flush=True)
    if LEFT[0]:
        print(f"VISION: --limit leaves {LEFT[0]} roles unread for the next run", flush=True)
    if not rows:
        return
    br, t0, n = render.Browser(), time.time(), [0]
    finder = employer.Finder(br, jobs)

    def one(rec):
        if _usage.get("stop"):
            return
        try:
            v = see(finder, rec)
        except render.BrowserDown as e:
            _usage["stop"] = True
            print(f"STOPPED: {e}", flush=True)
            return
        except Exception as e:
            # Whatever went wrong went wrong with us, not with the posting.
            # No verdict is written; the role is read again next time. A long
            # streak of these means something is broken, and the run stops.
            with _lock:
                n[0] += 1
                _usage["failed"] = _usage.get("failed", 0) + 1
                _usage["streak"] = _usage.get("streak", 0) + 1
                print(f"  [{n[0]}/{len(rows)}] NOT READ {rec['company'][:22]} | {rec['title'][:38]} | {type(e).__name__}: {str(e)[:80]}", flush=True)
                if _usage["streak"] >= 25:
                    _usage["stop"] = True
                    print("STOPPED: 25 roles in a row could not be read.", flush=True)
            return
        with _lock:
            _usage["streak"] = 0
            if v.get("posting_open") == "unreadable":
                was = out.get(rec["id"]) or {}
                v["unread_tries"] = (was.get("unread_tries") or (1 if was.get("posting_open") == "unreadable" else 0)) + 1
            out[rec["id"]] = v
            n[0] += 1
            print(f"  [{n[0]}/{len(rows)}] {SHOWN.get(v['lane'], v['lane']):8} {v.get('read', '-'):8} {str(v.get('found_by') or ''):7} {rec['company'][:22]:22} | "
                  f"{rec['title'][:38]:38} | {str(v.get('place_quote') or v.get('open_quote') or v.get('reason'))[:70]}", flush=True)
            if n[0] % 10 == 0:
                save(out)

    try:
        with ThreadPoolExecutor(WORKERS) as ex:
            list(ex.map(one, rows))
    finally:
        br.close()
        save(out)
    import collections
    c = collections.Counter(out[r["id"]]["lane"] for r in rows if r["id"] in out)
    u = _usage
    shown = {SHOWN.get(k, k): n for k, n in c.items()}
    print(f"done in {time.time() - t0:.0f}s: {shown}")
    if u["calls"]:
        print(f"{u['calls']} pages read by {MODEL}: {u['in']:,} tokens in, {u['out']:,} out, "
              f"{(u['in'] + u['out']) // u['calls']:,} per page, ${u['usd']:.2f} at API prices")
        with open(RUNS_LOG, "a") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "roles": len(rows), "pages_read": u["calls"],
                                "seconds": round(time.time() - t0), "waited": round(u.get("waited", 0)),
                                "tokens_per_page": (u["in"] + u["out"]) // u["calls"], "model": MODEL,
                                "criteria": criteria.VERSION, "lanes": dict(c)}) + "\n")
    if u.get("over"):
        print(f"STOPPED: reading a page was costing more than {CEILING:,} tokens. Something is wrong with the call.")
        sys.exit(3)
    if u.get("stop"):
        sys.exit(4)


if __name__ == "__main__":
    main()
