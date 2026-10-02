"""employer: a job board's copy -> the employer's own posting.

A board that sells job ads has every reason to keep a posting up and call it
remote. The employer's page is the one that says "Germany only", or "this job
is closed". This finds it the way Cesar does by hand, cheapest first:

    1 pool      Radar already scrapes hundreds of companies' own boards. The
                same company with the same title there IS the posting.
    2 link      the board's page often links the hiring system or the
                company's site directly.
    3 search    the exact title and the company, in a search engine: the
                careers link or the hiring-system link is usually on top.
    4 careers   the company's site -> its careers page -> the role.
    5 apply     the board's Apply button, last: boards use it to push their
                own sign-up, and adverts dress up as it.

Nothing is accepted on trust. A page counts only when it names the company
and carries the title; a page that is somebody else's job is refused. A
posting hosted on Ashby, Greenhouse, Lever and the like is the employer's own:
plenty of startups have no careers page and hire straight from there.

fetcher.py tried to guess the company's domain from its name and found the
employer 13% of the time. This replaces it.
"""
import re, urllib.parse

import render

# Hiring systems. A posting here belongs to the employer.
ATS = re.compile(r"greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|recruitee\.com|teamtailor\.com|"
                 r"smartrecruiters\.com|bamboohr\.com|personio\.(com|de)|join\.com|breezy\.hr|applytojob\.com|"
                 r"pinpointhq\.com|rippling\.com|myworkdayjobs\.com|jobs\.gem\.com|jobvite\.com|icims\.com|"
                 r"homerun\.co|factorialhr\.com|zohorecruit\.com|freshteam\.com|comeet\.com|dover\.com|"
                 r"workatastartup\.com|polymer\.co|notion\.site|inhire\.app|gupy\.io", re.I)
# Boards, social sites and adverts. Never the employer, whatever they say.
NOT_EMPLOYER = re.compile(r"uiuxjobsboard|uxremotetalent|euremotejobs|jobspresso|himalayas|jobicy|remoteok|remotive|"
                          r"weworkremotely|workingnomads|superjobs|justremote|wellfound|builtin|dribbble|nodesk|"
                          r"welcometothejungle|remote\.io|woodyjobs|net-empregos|landing\.jobs|eures|europa\.eu|"
                          r"linkedin|indeed\.|glassdoor|ziprecruiter|toptal|jooble|talent\.com|simplyhired|"
                          r"google\.|facebook|twitter|x\.com|instagram|youtube|tiktok|whatsapp|t\.me|apple\.com|"
                          r"designjobsworld|remoterocketship|jobgether|flexjobs|crossover|turing\.com|brave\.com|"
                          r"duckduckgo|bing\.com|wikipedia|crunchbase|medium\.com|github\.com", re.I)
GONE = re.compile(r"(?i)job not found|no longer available|no longer accepting|position (has been|is) (filled|closed)|"
                  r"this job (is|has) (closed|expired)|job (has )?expired|posting (has )?(expired|closed)|"
                  r"job .{0,40}was archived|this position is closed")
STOP = {"the", "a", "an", "and", "for", "of", "to", "in", "at", "remote", "m", "f", "d", "x", "w", "h", "mfd", "fmd"}


def squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def words(t):
    return [w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if w not in STOP]


def has_title(title, page):
    """Most of the title's words, near the top of the page."""
    want = set(words(title))
    if not want:
        return False
    seen = set(words((page.get("title") or "") + " " + (page.get("text") or "")[:6000]))
    return len(want & seen) / len(want) >= .75


def has_company(company, page):
    c = squash(company)
    if len(c) < 3:
        return False
    return c in squash(page.get("url")) or c in squash((page.get("title") or "") + (page.get("text") or "")[:8000])


def is_gone(page):
    """The employer's own page saying the job is gone, in so many words."""
    text = page.get("text") or ""
    if page.get("status") in (404, 410):
        return f"the employer's page answered {page['status']}"
    if len(text) < 1500:
        m = GONE.search(text)
        if m:
            return " ".join(text.split())[:160]
    return None


class Finder:
    def __init__(self, br, jobs):
        self.br = br
        self.pool = {}
        for j in jobs:
            if "/" in (j.get("source") or ""):                    # a company's own board
                self.pool.setdefault(squash(j["company"]), []).append(j)

    def load(self, url, shot_id):
        return self.br.page(url, shot=render.shot_path(shot_id, "employer"))

    def judge(self, rec, page, how, tried):
        """Is this page the employer's posting for this job? -> a result, or None."""
        url = page.get("url") or ""
        tried.append(f"{how}: {url[:90]}")
        if NOT_EMPLOYER.search(urllib.parse.urlparse(url).hostname or ""):
            return None
        if not has_company(rec["company"], page):
            return None
        gone = is_gone(page)
        if gone and ATS.search(url):
            return {"page": page, "how": how, "gone": gone}
        if len(page.get("text") or "") < 400 or not has_title(rec["title"], page):
            return None
        # an application form is one level below the posting it belongs to
        up = re.sub(r"/(apply|application)/?(\?.*)?$", "", url)
        if up != url:
            par = self.load(up, rec["id"])
            if len(par.get("text") or "") > len(page["text"]) and has_title(rec["title"], par):
                page = par
        return {"page": page, "how": how, "gone": is_gone(page)}

    def find(self, rec, board):
        """The employer's posting for a board row, or None. `tried` says where it looked."""
        tried, rid = [], rec["id"]
        co, title = squash(rec["company"]), words(rec["title"])

        # 1 the pool
        same = [j for j in self.pool.get(co, []) if words(j["title"]) == title]
        live = [j for j in same if j.get("active")]
        if live:
            r = self.judge(rec, self.load(live[0]["url"], rid), "pool", tried)
            if r:
                r["pool_id"] = live[0]["id"]
                return r, tried
        elif same:
            # The employer's own feed listed this job and no longer does.
            tried.append("pool: " + same[0]["url"][:90])
            return {"page": {"url": same[0]["url"], "status": None},
                    "how": "pool", "gone": "the employer's own board no longer lists it"}, tried

        links = [a for a in (board or {}).get("links") or []]
        host = lambda a: urllib.parse.urlparse(a["href"]).hostname or ""

        # 2 a link on the board's page: the hiring system first, then the company's site
        ats = [a for a in links if ATS.search(host(a)) and not NOT_EMPLOYER.search(host(a))]
        for a in ats[:3]:
            r = self.judge(rec, self.load(a["href"], rid), "link", tried)
            if r:
                return r, tried

        # 3 search: the exact title and the company
        q = urllib.parse.quote(f'"{rec["title"]}" {rec["company"]}')
        sr = self.br.page("https://search.brave.com/search?q=" + q, settle=1.5)
        hits = [a for a in sr.get("links") or [] if not NOT_EMPLOYER.search(host(a))]
        hits.sort(key=lambda a: (not ATS.search(host(a)), co not in squash(a["href"])))
        sites = []
        for a in hits[:4]:
            if not (ATS.search(host(a)) or co in squash(a["href"])):
                continue
            page = self.load(a["href"], rid)
            r = self.judge(rec, page, "search", tried)
            if r:
                return r, tried
            if has_company(rec["company"], page):
                sites.append(page)

        # 4 the company's own site: a link on the board, or what search turned up
        for a in links:
            if co and co in squash(host(a)) and not NOT_EMPLOYER.search(host(a)) and len(sites) < 3:
                sites.append(self.load(a["href"], rid))
        for sp in sites[:3]:
            role = [a for a in sp.get("links") or [] if len(set(title) & set(words(a["text"]))) >= max(1, .75 * len(set(title)))]
            careers = [a for a in sp.get("links") or [] if re.search(r"career|jobs|join|hiring|vagas|work-with", a["href"] + a["text"], re.I)]
            for a in role[:2]:
                r = self.judge(rec, self.load(a["href"], rid), "careers", tried)
                if r:
                    return r, tried
            for c in careers[:2]:
                cp = self.load(c["href"], rid)
                for a in [a for a in cp.get("links") or []
                          if len(set(title) & set(words(a["text"]))) >= max(1, .75 * len(set(title)))][:2]:
                    r = self.judge(rec, self.load(a["href"], rid), "careers", tried)
                    if r:
                        return r, tried

        # 5 the Apply button
        for a in [a for a in (board or {}).get("apply") or [] if not NOT_EMPLOYER.search(host(a)) or not a["external"]][:2]:
            page = self.load(a["href"], rid)
            if render.site(page.get("url") or "") != render.site((board or {}).get("url") or ""):
                r = self.judge(rec, page, "apply", tried)
                if r:
                    return r, tried
        return None, tried
