"""answers: his drafts for the questions on each Open role's application form.

The one step after VISION that also costs tokens, so it only runs once
VISION's queue is empty (his call, 2026-10-19: "Open roles only, after
VISION's queue is empty, on Sonnet"). forms.py has already taken down the
questions, for no tokens; this writes the answers the way the answerThis
skill does, from the same knowledge and nothing else:

    his live CV and live cesarxdesign.com role pages   (answerThis/knowledge)
    how he writes them                                  (answerThis/lessons.md)
    what he actually sent before                        (answerThis/bank, the Finals)

One call per role, every question on its form at once, so no fact is said
twice. What comes back is a Draft: he settles the Final in chat, as before.
When the CV, the site or the lessons change, every answer written from the
old ones is stale, and the next run writes it again.

    python3 answers.py               # Open roles whose form has questions, newest first
    python3 answers.py --ids a,b     # these
    python3 answers.py --again       # write them all again
    python3 answers.py --limit 20

Out: data/answers.json, private, never committed. The board reads it from
this Mac (serve.py, /api/answers).
"""
import hashlib, json, os, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forms, read, vision

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = f"{ROOT}/data/answers.json"
SKILL = os.path.expanduser("~/.claude/skills/answerThis")
MODEL = os.environ.get("RADAR_ANSWERS_MODEL", "sonnet")
WORKERS = int(os.environ.get("ANSWERS_WORKERS", "3"))
# A role is the whole of his knowledge (~13,000 tokens, the same every call)
# plus one posting and its questions. Above this, averaged, something is wrong
# with the call: the run stops rather than spend his tokens on a mistake.
CEILING = 40000

_lock = threading.Lock()
_usage = {"calls": 0, "in": 0, "out": 0, "usd": 0.0, "stop": False}


# ---------- what he knows ----------
def cv_text():
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(f"{SKILL}/knowledge/cv.pdf").pages)


def finals():
    """Every question he has answered and the Final he sent. Never the Drafts."""
    out = []
    for f in sorted(os.listdir(f"{SKILL}/bank")):
        if not re.match(r"\d{4}-\d\d-\d\d ", f):
            continue
        t = open(f"{SKILL}/bank/{f}").read()
        for sec in re.split(r"\n## ", t)[1:]:
            q = sec.split("\n", 1)[0].strip()
            m = re.search(r"\*\*Final\*\*[^\n]*\n(.*?)(?=\n\*\*Changed|\n## |\Z)", sec, re.S)
            if m and m.group(1).strip() and not re.search(r"verification|captcha|human check", q, re.I):
                out.append(f"[{f[:-3]}] {q}\n{m.group(1).strip()}")
    return "\n\n".join(out)


def knowledge():
    k = f"{SKILL}/knowledge"
    snap = json.load(open(f"{k}/snapshot.json"))
    pages = sorted(x for x in os.listdir(k) if x.endswith(".txt"))
    parts = ["## His CV (cesarxdesign.com/cv)\n" + cv_text()]
    parts += [f"## Live page: {p[:-4]}\n" + open(f"{k}/{p}").read() for p in pages]
    return snap, "\n\n".join(parts)


RULES = """You write Cesar Garcia's answers to the questions on one job application form, in his voice.

KNOWLEDGE. The only evidence about him is his CV and his live site pages, given below. If a fact is not there, it does not exist: never invent a role, project, number, tool, date, opinion or story. A question the knowledge cannot answer gets no answer: answer null, and a gap saying what he must supply. Salary, notice, visas, grades, referrals, languages, personal history: null and a gap, always.

HOW AN ANSWER IS WRITTEN
- First sentence says what he did or answers the question outright. First person, flat. One reason. A result if there is one. No wind-up, no story of how he got there, no list of what he rejected, no arguing the reader into believing it.
- Answer the question that was asked. "What tools" gets the tools named, first.
- Only his own work and results in the role. No company volume, deals, or anything after he left, unless the CV line itself says it.
- Every number exactly as the CV or page writes it, as digits (4, not four). Never soften, round or question one.
- Every fact keeps the exact meaning of its source line. Never merge two lines into a new claim, never swap one step for another ("designed" is not "shipped", "wireframe to high fidelity" is not "PRD to wireframe").
- No adjectives doing the work of facts. No "passionate", "revolutionized", "perfectly".
- Never blame a team, a company or a predecessor.
- A stranger must get every line on first read. Readers are recruiters, design leads, CTOs, CPOs: do not explain what they would infer.
- Across the answers on one form, no fact twice.
- Fit the box: 60 to 110 words for a free-text question, unless it asks for less. A short-text field gets a short answer.
- "Why us / why do you want to work here / what excites you" questions: about the company and its product, with real desire for the problem, and only one line about him. Write the desire from what the posting says they are building. Never tell the company what it does. Never claim a history with the company (followed it, used it, admired it).
- Write in English. If the question is in another language, still write in English and add a gap saying so.
- A question asking him to state something beyond his work (a political sentence, a declaration, consent, a "human check"): answer null, gap quoting it.
- If the form forbids AI-written answers, still write the draft, and put that rule first in the form's gaps.

HOW HE HAS CHANGED PAST DRAFTS (apply every Rule):
{lessons}

WHAT HE HAS ACTUALLY SENT BEFORE (start from these wordings for similar questions, adapted to this company):
{finals}

{knowledge}

OUTPUT: one JSON object and nothing else:
{{"answers": [{{"q": "<the question, verbatim>", "answer": "<the answer>" or null, "sources": ["<each CV or page line a fact or number in the answer rests on, copied word for word>"], "gaps": ["<anything this answer rests on that he must confirm, or supply>"]}}], "gaps": ["<anything about the whole form he must know>"]}}
One entry per question given, in the same order. Gaps are short, plain, and only real: no gap is fine. Gaps are read by Cesar himself: write them to him, as "you" ("You must supply your notice period"), never "Cesar" or "he"."""


def system_prompt():
    snap, know = knowledge()
    lessons = open(f"{SKILL}/lessons.md").read()
    text = RULES.format(lessons=lessons, finals=finals() or "(none yet)", knowledge=know)
    return text, hashlib.sha1(text.encode()).hexdigest()[:12]


# ---------- the form ----------
def to_write(form):
    """The questions that take written words: every free-text field, and a
    short field that asks a real question. Choices and files are his to pick."""
    out = []
    for x in form.get("questions") or []:
        if x["standard"]:
            continue
        if x["kind"] == "long" or (x["kind"] in ("short", "file") and (x["q"].rstrip(" *:").endswith("?") or len(x["q"]) > 60)):
            out.append(x)
    return out


def prompt_for(role, form, qs):
    page = f"{ROOT}/data/pages/{role['id']}.txt"
    posting = open(page).read()[:14000] if os.path.exists(page) else "(the posting was not saved; write from the title and company)"
    other = [x["q"][:300] for x in form.get("questions") or [] if not x["standard"] and x not in qs]
    lines = [f"COMPANY: {role.get('company')}", f"ROLE: {role.get('title')}", f"POSTING URL: {form.get('url')}",
             "", "THE POSTING, as read:", posting, "",
             "OTHER FIELDS ON THE FORM (not for you to answer; only so you know the form):",
             *([f"- {o}" for o in other] or ["- none"]), "",
             "THE QUESTIONS TO ANSWER:"]
    for n, x in enumerate(qs, 1):
        lines.append(f"{n}. {x['q']}" + (f"\n   (the form adds: {x['help']})" if x.get("help") else "")
                     + (" [short field]" if x["kind"] == "short" else ""))
    return "\n".join(lines)


def ask(prompt, system, role=True):
    last = None
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "json", "--model", MODEL,
                 "--system-prompt", system, "--tools", "", "--strict-mcp-config", "--setting-sources", ""],
                capture_output=True, text=True, timeout=300, env=read.cli_env(), cwd="/tmp")
            env = json.loads(r.stdout)
            if env.get("is_error"):
                last = "api: " + str(env.get("result"))[:160]
                if vision.LIMIT.search(str(env.get("result"))):
                    vision.wait_for_reset(str(env.get("result")))
                    return ask(prompt, system, role)
                time.sleep(4 * 2 ** attempt)
                continue
            u = env.get("usage") or {}
            n = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) \
                + (u.get("cache_read_input_tokens") or 0) + (u.get("output_tokens") or 0)
            with _lock:
                _usage["calls"] += role         # the ceiling is per role: the check rides on its role
                _usage["in"] += n - (u.get("output_tokens") or 0)
                _usage["out"] += u.get("output_tokens") or 0
                _usage["usd"] += env.get("total_cost_usd") or 0
                if _usage["calls"] >= 3 and (_usage["in"] + _usage["out"]) / _usage["calls"] > CEILING:
                    _usage["stop"] = True
            return read.parse(env.get("result") or ""), n
        except subprocess.TimeoutExpired:
            last = "timeout"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
    raise RuntimeError(last)


def norm(t):
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", t).strip().lower()


NUM = re.compile(r"[$£€]?\d[\d,.]*\s?(?:%|[MBK]\b|x\b)?")


def quoted(s, know):
    """Word for word, give or take a stray word: 4 in 5 of its three-word runs are in his knowledge."""
    w = re.findall(r"[\w$£€%.']+", norm(s))
    if len(w) < 3:
        return norm(s) in know
    runs = [" ".join(w[i:i + 3]) for i in range(len(w) - 2)]
    flat = " ".join(re.findall(r"[\w$£€%.']+", know))
    return sum(r in flat for r in runs) >= .8 * len(runs)


VERIFY = """You check job-application answers against the source lines they rest on. For each answer, list every claim that the sources do not say with the same meaning: a step swapped ("designed" written as "shipped"), two lines merged into a new claim, a number moved to a different thing, a result given to the wrong role, anything added. Do not flag wording, tone, or the joke at the end. Write each problem to the person whose answer it is, as "you" ("the source says you owned checkout, not built it"). Answer with one JSON object: {"answers": [["<problem, quoting the words in the answer>", ...], ...]} with one list per answer, in order; an empty list when it is right."""


def verify(recs):
    """A second, small read: does each answer say what its sources say."""
    items = [{"answer": x["answer"], "sources": x.get("sources") or []} for x in recs]
    if not any(i["answer"] for i in items):
        return [[] for _ in items], 0
    try:
        res, n = ask(json.dumps(items, ensure_ascii=False, indent=1), VERIFY, role=False)
        got = (res or {}).get("answers") or []
        return [[f"Check: {p}" for p in (got[i] if i < len(got) else []) if isinstance(p, str)] for i in range(len(items))], n
    except Exception:
        return [["Not checked against its sources: the check did not run"] if i["answer"] else [] for i in items], 0


def check(answer, sources, know):
    """No tokens: every quoted source must be in his knowledge word for word,
    and every number in the answer must be somewhere in it."""
    flags = []
    for s in sources or []:
        if not quoted(s, know):
            flags.append(f"Check: this source is not word for word on the CV or site: \"{s[:140]}\"")
    for n in set(m.group(0).strip(" .,") for m in NUM.finditer(answer or "")):
        if n and norm(n) not in know:
            flags.append(f"Check: {n} is not on the CV or site")
    return flags


def load():
    try:
        return json.load(open(OUT))
    except Exception:
        return {}


def save(a):
    tmp = OUT + ".tmp"
    json.dump(a, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, OUT)


def main(argv):
    ids = next((argv[argv.index(a) + 1] for a in argv if a == "--ids"), None)
    limit = next((int(argv[argv.index(a) + 1]) for a in argv if a == "--limit"), None)
    again = "--again" in argv
    # his knowledge, fresh from the live site; no tokens
    up = subprocess.run([sys.executable, f"{SKILL}/update.py"], capture_output=True, text=True)
    if up.returncode:
        print("answers: could not refresh his knowledge from the live site, so nothing is written:", up.stdout[-200:], up.stderr[-200:])
        return
    system, version = system_prompt()
    know = norm(knowledge()[1] + "\n" + finals())
    fm, out = forms.load(), load()
    roles = forms.open_roles()
    if ids:
        want = ids.split(",")
        allr = {r["id"]: r for r in json.load(open(f"{ROOT}/data/results.json"))["roles"]}
        roles = [allr[i] for i in want if i in allr]
    todo = []
    for r in roles:
        f = fm.get(r["id"])
        if not f or not to_write(f):
            continue
        a = out.get(r["id"])
        if a and not again and not ids and a.get("version") == version and a.get("form_read_at") == f.get("read_at"):
            continue
        todo.append((r, f))
    todo = todo[:limit] if limit else todo
    stale = sum(1 for r, f in todo if r["id"] in out)
    print(f"answers: {len(todo)} roles to write ({stale} of them stale or re-read), on {MODEL}")
    if not todo:
        return

    def one(job):
        r, f = job
        if _usage["stop"]:
            return None
        qs = to_write(f)
        try:
            res, n = ask(prompt_for(r, f, qs), system)
        except Exception as e:
            print(f"  [{r['id']}] {r.get('company')}: not written ({e})", flush=True)
            return None
        got = (res or {}).get("answers") or []
        rec = {"id": r["id"], "company": r.get("company"), "title": r.get("title"), "apply_url": f.get("apply_url"),
               "version": version, "form_read_at": f.get("read_at"), "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "model": MODEL, "tokens": n, "gaps": (res or {}).get("gaps") or [],
               "answers": [{"q": x["q"], "required": x["required"], "kind": x["kind"],
                            "answer": (got[i] if i < len(got) else {}).get("answer"),
                            "sources": (got[i] if i < len(got) else {}).get("sources") or [],
                            "gaps": check((got[i] if i < len(got) else {}).get("answer"), (got[i] if i < len(got) else {}).get("sources"), know)
                                    + ((got[i] if i < len(got) else {}).get("gaps") or [])} for i, x in enumerate(qs)]}
        flags, n2 = verify(rec["answers"])
        for x, fl in zip(rec["answers"], flags):
            x["gaps"] = fl + x["gaps"]
        rec["tokens"] = n = n + n2
        with _lock:
            out[r["id"]] = rec
            save(out)
        print(f"  [{r['id']}] {r.get('company')}: {len(qs)} answered, {n:,} tokens", flush=True)
        return rec

    with ThreadPoolExecutor(WORKERS) as ex:
        done = [x for x in ex.map(one, todo) if x]
    u = _usage
    if u["calls"]:
        print(f"answers: {len(done)} roles written by {MODEL}, {(u['in'] + u['out']) // u['calls']:,} tokens a role")
    if u["stop"]:
        print(f"STOPPED: a role was costing more than {CEILING:,} tokens. Something is wrong with the call.")


if __name__ == "__main__":
    main(sys.argv[1:])
