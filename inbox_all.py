"""inbox_all: application emails from every Gmail tab he has open, not just the applications account.

He applies from more than one address. The sweep only ever read
cesarxdesign@gmail.com, so an application sent from another account looked
like a role he had never touched (Ruby Labs, 2026-10-05).

These other inboxes are personal. His instruction: be strict - an application
email may be opened, nothing else. So:
  - Gmail is asked only for mail that uses application language, since
    2026-06-01. The inbox itself is never listed.
  - of what comes back, a thread is kept only if its sender, subject or
    preview line reads like a job application. Everything else is dropped
    unread and nothing about it is written anywhere.
  - only kept threads have their text fetched, and only those are stored
    (data/emails_*, never committed).

    python3 inbox_all.py --dry     # count per account; fetch no text, store nothing
    python3 inbox_all.py           # fetch, classify, store, run the sweep
"""
import json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inbox, tabs

SINCE = "2026/6/1"
QUERY = ('after:%s ("your application" OR "thank you for applying" OR "thanks for applying" OR "application received" '
         'OR "received your application" OR "your interest in" OR "applied to" OR "your candidacy" OR "candidatura" '
         'OR "interview" OR "hiring team" OR "talent team" OR "recruiting team" OR "talent acquisition")') % SINCE
# A thread is an application email when its own lines say so. Deliberately narrow.
APPLICATION = re.compile(
    r"your application|thank(s| you) for (applying|your (interest|application))|application (received|to|for|update|status)|"
    r"received your application|we('ve| have) received|applied (to|for)|your candidacy|candidatura|"
    r"hiring team|talent (team|acquisition)|recruiting team|recruit(er|ing|ment)|"
    r"interview|next steps|(designer|design lead|head of design|design manager|ux|ui)\b.{0,40}(role|position|opening)|"
    r"(role|position|opening) (at|with)\b|unfortunately|move forward with|not (be )?moving forward", re.I)
NOT_APPLICATION = re.compile(r"newsletter|digest|webinar|% off|sale|invoice|receipt|password|verify your|security alert|"
                             r"unsubscribe from|job alert|new jobs for you|jobs you may|recommended jobs", re.I)


def main():
    dry = "--dry" in sys.argv
    seen, _ = inbox.known()
    all_new, bodies = [], []
    for w, t, url in tabs.every("mail.google.com"):
        tab = (w, t)
        account = (re.search(r"[\w.+-]+@[\w.-]+", tabs.js(tab, "document.title")) or [""])[0]
        rows = []
        try:
            for page in range(1, 21):
                tabs.js(tab, "location.hash='#search/'+encodeURIComponent(%s)" % json.dumps(QUERY) + (f"+'/p{page}'" if page > 1 else ""))
                time.sleep(5)
                got = json.loads(tabs.js(tab, inbox.GRAB) or "[]")
                rows += [r for r in got if r.get("tid")]
                if len(got) < 50:
                    break
            rows = list({r["tid"]: r for r in rows}.values())
            line = lambda r: " ".join(str(r.get(k) or "") for k in ("from", "email", "subject", "snippet"))
            keep = [r for r in rows if APPLICATION.search(line(r)) and not NOT_APPLICATION.search(line(r))]
            new = [r for r in keep if r["tid"] not in seen]
            print(f"{account}: {len(rows)} threads use application language, {len(keep)} read like an application, {len(new)} not on file", flush=True)
            if dry:
                for r in new[:400]:
                    print(f"    {str(r.get('date'))[5:17]:12} | {str(r.get('from'))[:26]:26} | {str(r.get('subject'))[:70]}")
                continue
            for r in new:
                body = tabs.js(tab, inbox.BODY % r["tid"], timeout=60)
                if len(body) < 80:
                    continue
                r["account"] = account
                all_new.append(r)
                bodies.append({"tid": r["tid"], "body": body})
        finally:
            try:
                tabs.js(tab, "location.hash='#inbox'")
            except Exception:
                pass
    if dry or not all_new:
        return 0
    import vision
    by = {b["tid"]: b["body"] for b in bodies}
    live = json.load(open(inbox.LIVE)) if os.path.exists(inbox.LIVE) else []
    done = []
    from concurrent.futures import ThreadPoolExecutor
    def classify(r):
        try:
            c = vision.ask(inbox.PROMPT % (r["tid"], r["date"], r["from"], r["email"], r["subject"], by.get(r["tid"], "")))
            c["tid"] = r["tid"]
            return c
        except Exception as e:
            print(f"  not classified: {str(r.get('subject'))[:50]} ({str(e)[:60]})")
    with ThreadPoolExecutor(5) as ex:
        for c in ex.map(classify, all_new):
            if c:
                done.append(c)
                ev = ", ".join(e.get("type", "?") for e in c.get("events") or [])
                print(f"  {str(c.get('company'))[:24]:24} | {str(c.get('role'))[:40]:40} | {ev}", flush=True)
    ok = {c["tid"] for c in done}
    with open(inbox.RAW, "a") as f:
        f.write(json.dumps({"rows": [r for r in all_new if r["tid"] in ok]}) + "\n")
        f.write(json.dumps({"bodies": [b for b in bodies if b["tid"] in ok]}) + "\n")
    json.dump([c for c in live if c.get("tid") not in ok] + done, open(inbox.LIVE, "w"), indent=1, ensure_ascii=False)
    import sweep
    sys.argv = ["sweep.py"]
    sweep.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
