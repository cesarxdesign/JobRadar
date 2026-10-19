"""forms: the questions on each Open role's application form. No tokens.

The questions an employer asks ("Why you?", "Why us?", "Tell us about...")
are on the application form, not in the posting VISION read. This opens the
apply page and takes down every question on it. answers.py then writes his
drafts for the free-text ones.

    Ashby       its own form API, the same data the apply page loads
    Greenhouse  its board API with ?questions=true
    the rest    the apply page, rendered in Chrome (render.py), every field
                with its label; if the posting has no form, its Apply link

Only Open roles, active, that he has not applied to or discarded. A form is
read once; --again reads them again.

    python3 forms.py                 # Open roles with no form read yet
    python3 forms.py --ids a,b       # these
    python3 forms.py --again         # every Open role, read again
    python3 forms.py --limit 20

Out: data/forms.json, private (his applications), never committed.
"""
import json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = f"{ROOT}/data/forms.json"
RR = os.path.expanduser("~/Desktop/RadarRouting.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")

# Fields every form has. They are filled from the CV, never written.
STANDARD = re.compile(r"^\s*(first|last|full|preferred|legal)?\s*name\b|^e-?mail|phone|resume|^cv\b|cover letter$|linkedin|github"
                      r"|portfolio|website|personal site|another link|^location|where are you based|^city|^country|address"
                      r"|^pronouns|gender|race|ethnic|veteran|disabilit|nationality|^salary|^current company|^current title", re.I)


def get(url, data=None, headers=None, timeout=20):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout).read()


def strip(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h or "")).strip()


def q(label, kind, required=False, help=""):
    label = strip(label)
    return {"q": label, "kind": kind, "required": bool(required), "help": strip(help)[:600],
            "standard": bool(STANDARD.search(label))}


# ---------- Ashby ----------
ASHBY_Q = ("query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { jobPosting("
           "organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) { "
           "applicationForm { sections { title fieldEntries { ... on FormFieldEntry { field isRequired descriptionHtml } } } } } }")
ASHBY_KIND = {"LongText": "long", "String": "short", "ValueSelect": "choice", "MultiValueSelect": "choice",
              "Boolean": "choice", "File": "file", "Email": "short", "Phone": "short", "Url": "short",
              "Location": "short", "Number": "short", "Date": "short", "Score": "choice"}


def ashby(url):
    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    body = json.dumps({"operationName": "ApiJobPosting", "query": ASHBY_Q,
                       "variables": {"organizationHostedJobsPageName": m.group(1), "jobPostingId": m.group(2)}}).encode()
    d = json.loads(get("https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting", body,
                       {"content-type": "application/json"}))
    jp = (d.get("data") or {}).get("jobPosting")
    if not jp:
        return {"error": "Ashby has no such posting"}
    out = []
    for s in (jp.get("applicationForm") or {}).get("sections") or []:
        for e in s.get("fieldEntries") or []:
            f = e.get("field") or {}
            if f.get("title"):
                out.append(q(f["title"], ASHBY_KIND.get(f.get("type"), "other"), e.get("isRequired"), e.get("descriptionHtml")))
    return {"system": "ashby", "apply_url": f"https://jobs.ashbyhq.com/{m.group(1)}/{m.group(2)}/application", "questions": out}


# ---------- Greenhouse ----------
GH_KIND = {"textarea": "long", "input_text": "short", "input_file": "file",
           "multi_value_single_select": "choice", "multi_value_multi_select": "choice", "input_hidden": None}


def greenhouse(url):
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?#&]+)/jobs/(\d+)", url) \
        or re.search(r"greenhouse\.io/embed/job_app\?(?:.*&)?for=([^&]+)&token=(\d+)", url)
    if not m:
        return None
    eu = ".eu." in url
    d = json.loads(get(f"https://boards-api{'.eu' if eu else ''}.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}?questions=true"))
    out = []
    for x in d.get("questions") or []:
        kinds = [GH_KIND.get(f.get("type"), "other") for f in x.get("fields") or []]
        kind = "file" if "file" in kinds else next((k for k in kinds if k), "other")
        out.append(q(x.get("label"), kind, x.get("required"), x.get("description")))
    return {"system": "greenhouse", "apply_url": url, "questions": out}


# ---------- any other form, rendered ----------
# Every field on the page with the words that label it: its <label>, else the
# nearest block above it that holds a little text of its own.
FORM_JS = r"""
(() => {
  const seen = new Set(), out = [];
  const txt = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const fields = document.querySelectorAll('textarea, input:not([type=hidden]):not([type=submit]):not([type=button]), select, [contenteditable=true]');
  const groups = new Set();
  for (const el of fields) {
    // hidden machinery (recaptcha, an ATS's own xml field) is not a question
    const cs = getComputedStyle(el);
    if (el.type !== 'file' && el.type !== 'radio' && el.type !== 'checkbox' && (cs.display === 'none' || cs.visibility === 'hidden' || (!el.offsetParent && cs.position !== 'fixed'))) continue;
    if (/recaptcha|xml-value|^search$/i.test(el.name || el.id || '')) continue;
    let label = '';
    // a set of options is one question: its legend or its group's words, not "Yes" and "No"
    const group = (el.type === 'radio' || el.type === 'checkbox') && el.name ? el.name : null;
    if (group) {
      if (groups.has(group)) continue;
      groups.add(group);
      const fs = el.closest('fieldset, [role=radiogroup], [role=group]');
      if (fs) label = txt(fs.querySelector('legend')) || fs.getAttribute('aria-label') || '';
      if (!label && document.querySelectorAll('input[name="' + CSS.escape(group) + '"]').length > 1) {
        let b = el.parentElement;
        for (let i = 0; b && i < 6; i++, b = b.parentElement)
          if ([...b.querySelectorAll('input')].some(x => x.name !== group)) break; else label = txt(b);
      }
    }
    if (!label && el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) label = txt(l); }
    if (!label && el.closest('label')) label = txt(el.closest('label'));
    if (!label) label = el.getAttribute('aria-label') || '';
    if (!label && el.getAttribute('aria-labelledby')) label = txt(document.getElementById(el.getAttribute('aria-labelledby')));
    let box = el.parentElement;
    for (let i = 0; !label && box && i < 6; i++, box = box.parentElement) {
      const t = txt(box);
      if (t && t.length < 700 && box.querySelectorAll('textarea, input, select').length <= (el.type === 'radio' || el.type === 'checkbox' ? 12 : 1)) label = t;
    }
    if (!label) label = el.getAttribute('placeholder') || el.name || '';
    const kind = el.tagName === 'TEXTAREA' || el.isContentEditable ? 'long' : el.tagName === 'SELECT' || ['radio', 'checkbox'].includes(el.type) ? 'choice' : el.type === 'file' ? 'file' : 'short';
    const key = kind + '|' + label;
    if (!label || seen.has(key)) continue;
    seen.add(key);
    out.push({q: label.slice(0, 700), kind, required: el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label)});
  }
  const frames = [...document.querySelectorAll('iframe[src]')].map(f => f.src).filter(s => /greenhouse|ashbyhq|lever\.co|workable|recruitee|breezy|bamboohr|personio|teamtailor|smartrecruiters/.test(s));
  return JSON.stringify({fields: out, frames});
})()
"""


def apply_url(url):
    """Where the form is, for the systems that keep it on its own page."""
    u = url.split("#")[0].rstrip("/")
    if re.search(r"jobs(\.eu)?\.lever\.co/[^/]+/[0-9a-f-]{36}$", u):
        return u + "/apply"
    if re.search(r"apply\.workable\.com/[^/]+/j/[0-9A-F]+$", u):
        return u + "/apply/"
    if re.search(r"\.breezy\.hr/p/[^/]+$", u):
        return u + "/apply"
    if re.search(r"\.recruitee\.com/o/[^/]+$", u):
        return u + "/c/new"
    return url


def rendered(browser, url):
    seen, tried = set(), [apply_url(url)]
    while tried:
        u = tried.pop(0)
        if u in seen or len(seen) >= 3:
            continue
        seen.add(u)
        p = browser.page(u, settle=3, js=FORM_JS)
        got = p.get("js") or {}
        for f in got.get("frames") or []:
            r = ashby(f) or greenhouse(f) if ("ashbyhq" in f or "greenhouse" in f) else None
            if r and r.get("questions"):
                r["apply_url"] = u
                return r
            tried.append(f)
        qs = [q(x["q"], x["kind"], x.get("required")) for x in got.get("fields") or []]
        if any(x["kind"] in ("long", "file") for x in qs) or len([x for x in qs if x["standard"]]) >= 3:
            return {"system": urlparse(p.get("url") or u).hostname, "apply_url": p.get("url") or u, "questions": qs}
        # no form here: the posting's own Apply link, then look again
        tried += [a["href"] for a in p.get("apply") or [] if a["href"] not in seen][:2]
    return {"error": "no application form found", "apply_url": url}


# ---------- which roles ----------
def decided():
    try:
        rr = json.load(open(RR))
        return {d["id"] for d in rr.get("decisions") or [] if d.get("decision")}
    except Exception:
        return set()


def open_roles():
    """Open roles he has not acted on, newest first: the board's own Open tab."""
    d = json.load(open(f"{ROOT}/data/results.json"))
    gone = decided()
    rows = [r for r in d["roles"] if (r.get("verdict") or {}).get("lane") == "open" and r.get("active", True) and r["id"] not in gone]
    return sorted(rows, key=lambda r: str(r.get("updated") or r.get("posted") or r.get("first_seen") or ""), reverse=True)


def load():
    try:
        return json.load(open(OUT))
    except Exception:
        return {}


def save(forms):
    tmp = OUT + ".tmp"
    json.dump(forms, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, OUT)


def read_one(browser, r):
    url = (r.get("verdict") or {}).get("read_url") or r["url"]
    try:
        out = ashby(url) or greenhouse(url) or rendered(browser, url)
    except Exception as e:
        try:
            out = rendered(browser, url)
        except Exception as e2:
            out = {"error": f"{type(e2).__name__}: {e2}"}
    out.update({"id": r["id"], "url": url, "company": r.get("company"), "title": r.get("title"),
                "read_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return out


def main(argv):
    ids = next((a.split("=", 1)[1] if "=" in a else argv[argv.index(a) + 1] for a in argv if a.startswith("--ids")), None)
    limit = next((int(argv[argv.index(a) + 1]) for a in argv if a == "--limit"), None)
    again = "--again" in argv
    forms = load()
    roles = open_roles()
    if ids:
        want = set(ids.split(","))
        allr = {r["id"]: r for r in json.load(open(f"{ROOT}/data/results.json"))["roles"]}
        roles = [allr[i] for i in want if i in allr]
    elif not again:
        roles = [r for r in roles if r["id"] not in forms]
    roles = roles[:limit] if limit else roles
    if not roles:
        print("forms: nothing to read")
        return
    browser = render.Browser()
    try:
        with ThreadPoolExecutor(4) as ex:
            for n, f in enumerate(ex.map(lambda r: read_one(browser, r), roles), 1):
                forms[f["id"]] = f
                if n % 10 == 0:
                    save(forms)
    finally:
        browser.close()
    save(forms)
    got = [forms[r["id"]] for r in roles]
    longs = sum(1 for f in got if any(x["kind"] == "long" and not x["standard"] for x in f.get("questions") or []))
    print(f"forms: {len(got)} read, {sum(1 for f in got if f.get('questions'))} with a form, "
          f"{longs} with questions to write, {sum(1 for f in got if f.get('error'))} not found")


if __name__ == "__main__":
    main(sys.argv[1:])
