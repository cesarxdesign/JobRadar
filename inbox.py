"""inbox: new mail in his job-hunt inbox -> applications in the routing file.

The first sweep was done by hand in a session: every thread since June read
and classified. This keeps it current. It reads the Gmail tab he leaves open
in Chrome (tabs.py), takes only the threads it has not seen, has Claude read
each one and say what it is - an application received, a rejection, a
callback - and hands the lot to sweep.py, which turns threads into
applications and writes the routing file. "Applied before" on the board is
then true as of last night, not as of the last time someone remembered.

Nothing is sent, archived, marked read or deleted. The tab is put back on
the inbox when it is done. If the tab is not open, nothing happens.

    python3 inbox.py            # read what is new, update the routing file
    python3 inbox.py --dry      # read and classify, change nothing
"""
import datetime, glob, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tabs

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = f"{ROOT}/data/emails_raw.jsonl"
LIVE = f"{ROOT}/data/emails_class_live.json"          # data/emails* is gitignored: it is his inbox
ACCOUNT = "cesarxdesign@gmail.com"

GRAB = """JSON.stringify([...document.querySelectorAll('div[role=main] tr.zA')].map(tr=>{const s=tr.querySelector('.yP,.zF');
const t=tr.querySelector('[data-legacy-thread-id]');const d=tr.querySelector('td.xW span[title]');
return {from:s?s.getAttribute('name')||'':'',email:s?s.getAttribute('email')||'':'',subject:(tr.querySelector('.bog')||{}).textContent||'',
snippet:((tr.querySelector('.y2')||{}).textContent||'').replace(/\\s+/g,' '),date:d?d.getAttribute('title')||'':'',
tid:t?t.getAttribute('data-legacy-thread-id')||'':''};}))"""

BODY = """(()=>{const x=new XMLHttpRequest();x.open('GET',location.pathname+'?ui=2&view=pt&search=all&th=%s',false);x.send();
const h=x.responseText;const b=h.slice(h.indexOf('<body'));
return b.replace(/<style[\\s\\S]*?<\\/style>/gi,'').replace(/<script[\\s\\S]*?<\\/script>/gi,'').replace(/<(br|\\/p|\\/div|\\/tr|\\/td|\\/h\\d|\\/li|hr)[^>]*>/gi,'\\n')
.replace(/<[^>]+>/g,'').replace(/&nbsp;/g,' ').replace(/&amp;/g,'&').replace(/&#39;/g,"'").replace(/&quot;/g,'"').replace(/[ \\t]+/g,' ').replace(/\\n\\s*\\n+/g,'\\n').trim().slice(0,7000);})()"""

PROMPT = """You are classifying one Gmail thread from Cesar Garcia's job-application inbox (a senior product designer in Portugal).
Read the whole thread. Reply with ONE JSON object and nothing else:

{"tid": "%s",
 "company": "the hiring company as a person would write it - not the hiring system (greenhouse/ashby/lever/workable), not a job board; null if not job related",
 "role": "the exact role title as the email states it; null if it never does",
 "via_agency": false,
 "events": [{"type": "...", "date": "YYYY-MM-DD", "evidence": "short exact quote, under 20 words"}],
 "note": "one short sentence only when something is ambiguous"}

One event per message that means something; use each message's own date (all in 2026). Event types:
 applied             his application was received, or he emailed his CV to apply
 rejected            they are not moving forward, at any stage; or the position was filled/closed/put on hold
 callback_interview  he is invited to a call, screen or interview, or one is scheduled
 callback_assessment a test, take-home or questionnaire as a next step (say in note if it is automatic for everyone)
 callback_question   a recruiter replies personally asking for something as a real next step
 offer               a job offer
 inbound             a recruiter approaches him about a role he did not apply to
 withdrawn           he withdrew
 followup            a neutral status update, or he chased
 other_job           job related but none of the above: account creation, verification codes, job alerts, newsletters
 noise               not job related
A verification code is other_job, not applied. Never guess a company or role the text does not support.

--- THE THREAD ---
LIST: %s | %s <%s> | %s
%s
"""


def known():
    rows, last = set(), ""
    if os.path.exists(RAW):
        for line in open(RAW):
            try:
                d = json.loads(line)
            except Exception:
                continue
            for r in d.get("rows") or []:
                rows.add(r["tid"])
                m = re.search(r"(\w{3}) (\d+), (\d{4})", r.get("date") or "")
                if m:
                    iso = datetime.datetime.strptime(" ".join(m.groups()), "%b %d %Y").strftime("%Y-%m-%d")
                    last = max(last, iso)
    return rows, last or "2026-06-01"


def main():
    dry = "--dry" in sys.argv
    try:
        tab = tabs.find("mail.google.com")
        title = tabs.js(tab, "document.title")
    except tabs.NoTab as e:
        print(f"inbox not read: {e}")
        return 0
    if ACCOUNT not in title:
        print(f"inbox not read: the Gmail tab is not {ACCOUNT} ({title[:50]})")
        return 0
    seen, last = known()
    since = (datetime.date.fromisoformat(last) - datetime.timedelta(days=3)).strftime("%Y/%-m/%-d")
    rows = []
    try:
        for page in range(1, 9):
            q = f"after:{since}"
            tabs.js(tab, f"location.hash='#search/'+encodeURIComponent('{q}')" + (f"+'/p{page}'" if page > 1 else ""))
            time.sleep(5)
            got = json.loads(tabs.js(tab, GRAB) or "[]")
            rows += [r for r in got if r.get("tid")]
            if len(got) < 50:
                break
        new = [r for r in {r["tid"]: r for r in rows}.values() if r["tid"] not in seen]
        print(f"inbox: {len(rows)} threads since {since}, {len(new)} new")
        bodies = []
        for r in new:
            body = tabs.js(tab, BODY % r["tid"], timeout=60)
            if len(body) < 80:
                print(f"  text not fetched, left for next time: {r['subject'][:50]}")
                continue
            bodies.append({"tid": r["tid"], "body": body})
        new = [r for r in new if r["tid"] in {b["tid"] for b in bodies}]
    finally:
        try:
            tabs.js(tab, "location.hash='#inbox'")
        except Exception:
            pass
    if not new:
        return 0
    import vision
    live = json.load(open(LIVE)) if os.path.exists(LIVE) else []
    by = {b["tid"]: b["body"] for b in bodies}
    done = []
    for r in new:
        try:
            c = vision.ask(PROMPT % (r["tid"], r["date"], r["from"], r["email"], r["subject"], by.get(r["tid"], "")))
            c["tid"] = r["tid"]
            done.append(c)
            ev = ", ".join(e.get("type", "?") for e in c.get("events") or [])
            print(f"  {str(c.get('company'))[:24]:24} | {str(c.get('role'))[:40]:40} | {ev}")
        except Exception as e:
            print(f"  not classified: {r['subject'][:50]} ({e})")
    if dry:
        return 0
    with open(RAW, "a") as f:
        ok = {c["tid"] for c in done}
        f.write(json.dumps({"rows": [r for r in new if r["tid"] in ok]}) + "\n")
        f.write(json.dumps({"bodies": [b for b in bodies if b["tid"] in ok]}) + "\n")
    json.dump([c for c in live if c.get("tid") not in {d["tid"] for d in done}] + done, open(LIVE, "w"), indent=1, ensure_ascii=False)
    import sweep
    sys.argv = ["sweep.py"]
    sweep.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
