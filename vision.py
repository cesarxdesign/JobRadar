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
WALL = re.compile(r"(?i)just a moment|checking your browser|verify you are human|enable javascript and cookies|access denied")

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
        _limit["cleared"] = time.time()
        print(f"RESUMED {time.strftime('%H:%M')}", flush=True)


_limit_lock, _limit = threading.Lock(), {"cleared": 0}


def ask(prompt):
    """One page, one answer. The CLI's own system prompt and tools are 30,000
    tokens a call and none of it is needed to read a page, so they are off."""
    last = None
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "json", "--model", MODEL,
                 "--system-prompt", "You read one job posting and answer with one JSON object.",
                 "--tools", "", "--strict-mcp-config", "--setting-sources", ""],
                capture_output=True, text=True, timeout=240, env=read.cli_env(), cwd="/tmp")
            env = json.loads(r.stdout)
            if env.get("is_error"):
                last = "api: " + str(env.get("result"))[:160]
                if LIMIT.search(str(env.get("result"))):
                    wait_for_reset(str(env.get("result")))
                    return ask(prompt)
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


def reader(rec, page):
    prompt = (criteria.VISION_HEAD + criteria.JUDGE_CRITERIA + criteria.JUDGE_FIELDS + criteria.VISION_OUTPUT
              + f"\n\nThe pool lists this role as: {rec.get('title')} at {rec.get('company')}."
              + f"\nPage address: {page.get('url')}\nPage title: {page.get('title')}"
              + "\n\n--- EVERY WORD VISIBLE ON THE PAGE ---\n" + (page.get("text") or "")[:MAX_CHARS])
    return ask(prompt)


def see(finder, rec):
    """Everything vision knows about one role."""
    br = finder.br
    is_board = "/" not in (rec.get("source") or "")
    first = br.page(rec["url"], shot=render.shot_path(rec["id"]))
    board, emp, found, tried = (first, None, None, []) if is_board else (None, first, None, [])
    if is_board:
        found, tried = finder.find(rec, board)
        emp = found and found["page"]
    keep = ("url", "status", "shot", "error")
    v = {"id": rec["id"], "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "criteria": criteria.VERSION,
         "model": MODEL, "pool_url": rec["url"],
         "board": board and {k: board.get(k) for k in keep},
         "employer": emp and {k: emp.get(k) for k in keep},
         "found_by": found and found["how"], "looked": tried}

    # The employer's page is the posting; the board's is a copy of it. So the
    # employer decides whether the job is open - a board calling it closed is
    # wrong about one in eight that the employer still lists.
    if found and found.get("gone"):
        return {**v, "lane": "closed", "posting_open": "no", "closed_by": "employer", "read": "employer",
                "read_url": emp.get("url"), "open_quote": found["gone"], "stage": "render",
                "reason": "the employer says it is closed"}
    if not is_board and gone(emp):
        return {**v, "lane": "closed", "posting_open": "no", "closed_by": "employer", "read": "employer",
                "read_url": emp.get("url"), "open_quote": gone(emp), "stage": "render",
                "reason": "the employer says it is closed"}
    if is_board and not found:
        dead = gone(board) or (off_the_posting(rec, board) and "the board sent the link somewhere else: " + str(board.get("url")))
        if dead:
            return {**v, "lane": "closed", "posting_open": "no", "closed_by": "board", "read": "board",
                    "read_url": board.get("url"), "open_quote": dead, "stage": "render",
                    "reason": "the board says it is closed, and the employer's posting was not found"}

    page = emp if emp and len(emp.get("text") or "") > 200 else board
    v["read"] = "employer" if emp is not None and page is emp else "board"
    v["read_url"] = page.get("url") if page else None
    text = (page or {}).get("text") or ""
    if len(text) < 200 or WALL.search(text[:600]):
        return {**v, "lane": "unsure", "posting_open": "unreadable", "stage": "render",
                "open_quote": " ".join(text.split())[:160] or (page or {}).get("error"),
                "reason": "the page could not be read in the browser"}
    a = reader(rec, page)              # ReaderDown goes up: the role stays unread, for the next run
    v.update(a)
    v["stage"] = "vision"
    if a.get("same_job") == "no":
        v["lane"] = "unsure"
        v["reason"] = "the page read is a different job · " + str(a.get("reason") or "")
    elif a.get("posting_open") == "no":
        v["lane"], v["closed_by"] = "closed", v["read"]
    elif a.get("posting_open") == "unreadable":
        v["lane"] = "unsure"
    else:
        # The reader lists what the page says; the place is worked out from the list.
        place, why = criteria.place_from_signals(a.get("place_signals"), a.get("workplace_as_posted"), a.get("place_verdict"))
        v["reader_place"], v["place_verdict"] = a.get("place_verdict"), place
        if why:
            v["reason"] = why + " · " + str(a.get("reason") or "")
        lane = criteria.lane_for(a.get("role_verdict"), place)
        v["lane"] = lane or "cut"
        if a.get("language_ok") is False:
            v["lane"] = "cut"
        # A real design role cut on place is the cut that hides a job he
        # wanted, and place is where two readings of one page disagree. So
        # that cut has to be confident, and has to survive a second reading.
        if v["lane"] == "cut" and a.get("role_verdict") != "no" and a.get("language_ok") is not False:
            if criteria.top_line_out(a.get("place_signals")):
                pass                        # the posting's own top line said so: nothing to doubt
            elif a.get("confidence") != "high":
                v["lane"], v["reason"] = "unsure", "cut on place, but not sure of it · " + str(a.get("reason") or "")
            else:
                try:
                    b = reader(rec, page)
                    v["second_place"] = criteria.place_from_signals(b.get("place_signals"), b.get("workplace_as_posted"), b.get("place_verdict"))[0]
                    if v["second_place"] != "no":
                        v["lane"] = "unsure"
                        v["reason"] = "two readings disagree on place · " + str(a.get("reason") or "")
                except Exception:
                    pass
        # Open is a promise that the employer's own page was read.
        if v["lane"] in ("open", "portugal") and v["read"] == "board":
            v["lane_if_employer"] = v["lane"]
            v["lane"] = "unsure"
            v["reason"] = "only the job board's copy could be read · " + str(a.get("reason") or "")
    return v


def save(out):
    """Whole file or nothing: results.py reads this while a run is still going."""
    tmp = OUT + ".tmp"
    json.dump(out, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, OUT)


def pick(jobs, done):
    args = sys.argv
    if "--ids" in args:
        want = set(args[args.index("--ids") + 1].split(","))
        rows = [j for j in jobs if j["id"] in want]
    elif "--lanes" in args:
        res = json.load(open(f"{ROOT}/data/results.json"))
        want = {i for v in res["lanes"].values() for i in v}
        rows = [j for j in jobs if j["id"] in want]
    else:   # --new: the freshest first, they are the ones worth applying to
        rows = [j for j in jobs if j.get("active") and judge.l1(j.get("title")) is None]
        # Where a job is most likely hiding, first: roles nothing has ever
        # judged; then roles the old judge cut on a job board's copy, which
        # it could not trust; last the ones it cut on the employer's own
        # text. Newest first within each.
        old = json.load(open(f"{ROOT}/data/verdicts.json"))["jobs"] if os.path.exists(f"{ROOT}/data/verdicts.json") else {}
        rank = lambda j: 0 if not old.get(j["id"], {}).get("judged") else 1 if "/" not in j["source"] else 2
        rows.sort(key=lambda j: j.get("posted") or j.get("first_seen") or "", reverse=True)
        rows.sort(key=rank)
        if "--fresh" in args:              # everything except what the old judge cut on the employer's own text
            rows = [j for j in rows if rank(j) < 2]
    if "--again" not in args:
        rows = [j for j in rows if j["id"] not in done]
    if "--limit" in args:
        rows = rows[:int(args[args.index("--limit") + 1])]
    return rows


def main():
    jobs = contracts.load_pool(f"{ROOT}/data/pool.json")["jobs"]
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    rows = pick(jobs, out)
    print(f"vision: {len(rows)} roles to read, model {MODEL}, {WORKERS} at a time", flush=True)
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
            out[rec["id"]] = v
            n[0] += 1
            print(f"  [{n[0]}/{len(rows)}] {v['lane']:8} {v.get('read', '-'):8} {str(v.get('found_by') or ''):7} {rec['company'][:22]:22} | "
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
    print(f"done in {time.time() - t0:.0f}s: {dict(c)}")
    if u["calls"]:
        print(f"{u['calls']} pages read by {MODEL}: {u['in']:,} tokens in, {u['out']:,} out, "
              f"{(u['in'] + u['out']) // u['calls']:,} per page, ${u['usd']:.2f} at API prices")
        with open(RUNS_LOG, "a") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "roles": len(rows), "pages_read": u["calls"],
                                "tokens_per_page": (u["in"] + u["out"]) // u["calls"], "model": MODEL,
                                "criteria": criteria.VERSION, "lanes": dict(c)}) + "\n")
    if u.get("over"):
        print(f"STOPPED: reading a page was costing more than {CEILING:,} tokens. Something is wrong with the call.")
        sys.exit(3)
    if u.get("stop"):
        sys.exit(4)


if __name__ == "__main__":
    main()
