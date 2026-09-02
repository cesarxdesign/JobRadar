"""match: his inbox x the pool -> data/applied_hints.json

Proof of application is an email: a confirmation, or a rejection (you cannot
be rejected from a role you did not apply to). Each email is parsed for the
company and, where stated, the role title; each is then matched to pool
postings by company and title. The board shows the matches in a temporary
"Applied?" tab for him to confirm - the email sits above the posting so he
can see it is the same role, and is marked when it is OLDER than the
posting, because a newer posting may be a new job.

Inputs (local only, gitignored):
    data/emails_raw.tsv   kind, date, from, email, subject, snippet, tid
    ~/Claude/radar/applications.json   the older confirmations (v1 extract)
Output: data/emails.json (merged), data/applied_hints.json {role_id: [hint]}
"""
import json, os, re, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge, pool as P

ROOT = os.path.dirname(os.path.abspath(__file__))
NOISE = re.compile(r"\b(hiring|talent|recruit\w*|team|no-?reply|careers?|hr|acquisition|the)\b|[.!]", re.I)
TITLE_RES = [
    r"(?:applying (?:for|to)|application for|position of|received your application for|for our|for the|as an?|apply for(?: our| the)?|interest in(?: the)?|for) (?:the |our )?(?P<t>[A-Z][^.!,\n]*?(?:Designer|Design(?: Lead| Engineer| Manager| Systems?| Strategist| Team Lead)?|Head of Design[^.!,\n]*|Director[^.!,\n]*|Builder)(?:[^.!,\n]{0,40}?)?)(?= (?:role|position|job|at|with|we|opening)\b|[.!,]|$)",
    r"^(?P<t>[A-Z][^-@|]*?(?:Designer|Design(?: Lead| Engineer| Manager)?|Strategist)[^-@|]*?) (?:-|@|\|) ",
    r"(?:Your|your) (?P<t>[A-Z][^.!,\n]*?(?:Designer|Design Lead|Design Manager|Design Team Lead)[^.!,\n]*?) [Aa]pplication",
    r"[Aa]pplication (?:for|to) (?:the |our )?(?P<t>[A-Z][^.!,\n]*?(?:Designer|Design Lead|Design Manager)[^.!,\n]*?)(?= (?:role|position|at)\b|[.!,]|$)",
]
COMPANY_RES = [
    r"(?:applying (?:to|at|for)|application (?:to|at|for)|interest (?:in|towards)|joining|join|welcome to|with us at|at|with|@|in regards to your application for) (?:the )?(?P<c>[A-Z][\w.&' ]{1,30}?)(?=[!.,)\-–—|:]| Cesar| Thank| We| Your| Hello| Here| team| for | - | and |$)",
    r"^(?P<c>[A-Z][\w.&' ]{1,30}?)(?: Application| - Confirmation| \| Application|: Your application| Hiring| Talent)",
    r" (?:-|–|—|@) (?P<c>[A-Z][\w.&' ]{1,30})$",
]
TITLEISH = re.compile(r"designer|design|strategist|engineer|manager|director|lead\b|application|interview", re.I)

# A board's own name for the company, taken from the posting URL. Written
# per board: a loose "<host>/([^/]+)" grabbed the "j" out of Workable's
# apply.workable.com/j/<id>, which then matched every company whose name
# contains a j - Plutus Media collected Jito, Jimdo and JetBrains.
SLUG_RES = [
    r"jobs\.ashbyhq\.com/([^/?#]+)/",
    r"greenhouse\.io/([^/?#]+)/jobs/",
    r"jobs\.lever\.co/([^/?#]+)/",
    r"apply\.workable\.com/([^/?#]+)/j/",
    r"([a-z0-9-]+)\.recruitee\.com/",
    r"([a-z0-9-]+)\.teamtailor\.com/",
    r"jobs\.smartrecruiters\.com/([^/?#]+)/",
]


def ats_slug(url):
    for rx in SLUG_RES:
        m = re.search(rx, url or "", re.I)
        if m:
            return squash(m.group(1))
    return None


def squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def parse_date(s):
    for fmt in ("%a, %b %d, %Y, %I:%M %p", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None

def company_of(e):
    for text in (e["subject"], e.get("body") or e["snippet"]):
        for rx in COMPANY_RES:
            for m in re.finditer(rx, text):
                c = re.split(r" (?:Cesar|Thank|We|Your|Hello|Here)\b", m.group("c"))[0].strip(" -–—:!.,")
                if 1 < len(c) <= 30 and not NOISE.search(c) and not TITLEISH.search(c) \
                        and squash(c) not in ("cesar", "us", "you", "our", "the", "join", "work"):
                    return c
    dom = e["email"].split("@")[-1]
    generic = ("ashbyhq", "greenhouse", "lever", "workablemail", "teamtailor", "pinpoint",
               "deel", "peopleforce", "recruitee", "candidates", "hire", "inbound", "ext", "team", "talent")
    sub = re.sub(r"\.(com|io|co|pt|to|eu|email|network|me)$", "", dom)
    parts = [p for p in sub.split(".") if p and not any(g in p for g in generic)]
    if parts:
        return parts[-1] if len(parts[-1]) > 2 else parts[0]
    frm = NOISE.sub(" ", e["from"]).strip()
    return frm.split(" - ")[0].strip() or dom


def title_of(e):
    text = e["subject"] + ". " + (e.get("body") or e["snippet"])
    for rx in TITLE_RES:
        m = re.search(rx, text)
        if m:
            t = re.sub(r"\s+", " ", m.group("t")).strip(" -–—:")
            if 5 < len(t) < 90:
                return t
    return None

STOP = {"senior", "sr", "lead", "staff", "principal", "head", "of", "the", "a", "and", "for",
        "product", "designer", "design", "ux", "ui", "remote", "m/f/d", "role", "position"}
def toks(t):
    return {w for w in re.findall(r"[a-z0-9/+-]+", (t or "").lower()) if w not in STOP}
def level(t):
    m = re.search(r"\b(senior|sr|staff|principal|lead|head|director|manager|founding|junior)\b", (t or "").lower())
    return m.group(1) if m else ""

def load_bodies():
    """data/emails_bodies_*.txt: '###<tid>' then the message text, as pulled
    from each thread's print view. Local only."""
    bodies, tid, buf = {}, None, []
    import glob
    for f in sorted(glob.glob(f"{ROOT}/data/emails_bodies_*.txt")):
        for line in open(f):
            if line.startswith("###"):
                if tid:
                    bodies[tid] = "".join(buf).strip()
                tid, buf = line[3:].strip(), []
            else:
                buf.append(line)
        if tid:
            bodies[tid] = "".join(buf).strip()
        tid, buf = None, []
    return bodies


def load_emails():
    bodies = load_bodies()
    out = []
    for line in open(f"{ROOT}/data/emails_raw.tsv"):
        f = line.rstrip("\n").split("\t")
        if len(f) < 7:
            continue
        e = dict(zip(("kind", "date_raw", "from", "email", "subject", "snippet", "tid"), f))
        e["date"] = parse_date(e["date_raw"])
        e["body"] = bodies.get(e["tid"], "")
        e["company"] = company_of(e)
        e["title"] = title_of(e)
        out.append(e)
    # The v1 extract stored company, date and role - no thread, so no body.
    # The real messages above supersede it wherever the same company appears.
    # A v1 row for a company with no real email is kept: it is still proof he
    # applied, and losing it would lose a hint.
    old = json.load(open(os.path.expanduser("~/Claude/radar/applications.json")))
    old = old if isinstance(old, list) else next(v for v in old.values() if isinstance(v, list))
    seen = {squash(e["company"]) for e in out}
    for o in old:
        if squash(o["company"]) in seen:
            continue
        out.append({"kind": "confirm", "date": o["date"], "from": o["company"], "email": "@" + (o.get("dom") or ""),
                    "subject": f"(v1 extract) application to {o['company']}", "snippet": "",
                    "tid": "", "company": o["company"], "title": o.get("role")})
    return out

def main():
    emails = load_emails()
    json.dump(emails, open(f"{ROOT}/data/emails.json", "w"), indent=1, ensure_ascii=False)
    # Only roles that PASSED the judge - the three lanes. Emails cleanse the
    # board he actually reviews; a role the judge cut is not on it, and
    # matching against the whole pool only invents work. It matched 1,954 L1
    # survivors before, which is the pool minus titles, not the judge's yes.
    verdicts = json.load(open(f"{ROOT}/data/verdicts.json"))["jobs"]
    def passed(j):
        v = verdicts.get(j["id"]) or {}
        return v.get("judged") and v.get("stage") == "L2" and not v.get("cut")
    jobs = [j for j in json.load(open(f"{ROOT}/data/pool.json"))["jobs"]
            if j.get("active") and passed(j)]
    by_co = {}
    for j in jobs:
        keys = {squash(j["company"])}
        s = ats_slug(j.get("url"))
        if s:
            keys.add(s)
        for k in keys:
            if len(k) >= 3:
                by_co.setdefault(k, []).append(j)
    hints, matched = {}, 0
    for e in emails:
        co = squash(e["company"])
        # Fall back to a partial name only when BOTH sides are long enough
        # to mean something. Guarding only one side let a 1-character key
        # match everything.
        cands = by_co.get(co) or ([j for k, js in by_co.items()
                                   if len(k) >= 5 and (co in k or k in co) for j in js]
                                  if len(co) >= 5 else [])
        if not cands:
            continue
        et = toks(e["title"]) if e["title"] else set()
        scored = []
        for j in cands:
            jt = toks(j["title"])
            if e["title"]:
                overlap = len(et & jt) / max(1, len(et | jt)) if (et or jt) else 1.0
                score = 0.5 + 0.5 * overlap - (0.15 if level(e["title"]) != level(j["title"]) else 0)
            else:
                score = 0.35     # company matched, the email named no role
            scored.append((score, j))
        scored.sort(key=lambda x: -x[0])
        for score, j in scored[:4]:
            if score < 0.3:
                continue
            posted = j.get("posted") or j.get("first_seen") or ""
            if isinstance(posted, (int, float)):        # some boards give epoch seconds
                posted = datetime.utcfromtimestamp(posted if posted < 1e11 else posted / 1000).strftime("%Y-%m-%d")
            posted = str(posted)[:10]
            hints.setdefault(j["id"], []).append({
                "kind": e["kind"], "date": e["date"], "from": e["from"], "subject": e["subject"],
                "domain": (e["email"].split("@")[-1] or "").lstrip("."),
                "snippet": e["snippet"], "body": e.get("body", ""),
                "company": e["company"], "title": e["title"],
                "score": round(score, 2), "older": bool(e["date"] and posted and e["date"] < posted),
                "posted": posted})
            matched += 1
    json.dump(hints, open(f"{ROOT}/data/applied_hints.json", "w"), indent=1, ensure_ascii=False)
    print(f"{len(emails)} emails ({sum(1 for e in emails if e['kind']=='reject')} rejections), "
          f"{sum(1 for e in emails if e['title'])} with a title; matched against "
          f"{len(jobs)} roles that passed the judge -> {len(hints)} hinted, {matched} pairs")
    nomatch = [e for e in emails if squash(e['company']) not in by_co]
    print(f"{len(nomatch)} emails with no company in the pool, e.g.: " +
          ", ".join(sorted({e['company'] for e in nomatch})[:12]))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
