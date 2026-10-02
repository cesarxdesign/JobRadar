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
    python3 vision.py --limit 50         # at most this many
    python3 vision.py --again            # re-read even if already read
"""
import json, os, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contracts, criteria, judge, read, render

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = f"{ROOT}/data/vision.json"
MODEL = os.environ.get("RADAR_VISION_MODEL", "sonnet")
WORKERS = 4
MAX_CHARS = 30000          # a long posting is ~10k; this is the page, menus and all

# A page that is certainly gone needs no reader. Only what cannot be argued
# with: the server said gone, or the page is nothing but the sentence.
GONE = re.compile(r"(?i)job not found|no longer available|no longer accepting|position (has been|is) (filled|closed)|"
                  r"this job (is|has) (closed|expired)|job (has )?expired|posting (has )?(expired|closed)|"
                  r"was archived|page not found|404")
UIUX_GONE = "This role is no longer available!"
WALL = re.compile(r"(?i)just a moment|checking your browser|verify you are human|enable javascript and cookies|access denied")

_lock = threading.Lock()
_usage = {"calls": 0, "in": 0, "out": 0, "usd": 0.0}


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
                time.sleep(4 * 2 ** attempt)
                continue
            u = env.get("usage") or {}
            with _lock:
                _usage["calls"] += 1
                _usage["in"] += (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) \
                    + (u.get("cache_read_input_tokens") or 0)
                _usage["out"] += u.get("output_tokens") or 0
                _usage["usd"] += env.get("total_cost_usd") or 0
            return read.parse(env.get("result") or "")
        except subprocess.TimeoutExpired:
            last = "timeout"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
    raise RuntimeError(last)


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


def see(br, rec):
    """Everything vision knows about one role."""
    is_board = "/" not in (rec.get("source") or "")
    pages = render.posting(br, rec["url"], shot_id=rec["id"], is_board=is_board)
    board, emp = pages["board"], pages["employer"]
    v = {"id": rec["id"], "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "criteria": criteria.VERSION,
         "model": MODEL, "pool_url": rec["url"],
         "board": board and {k: board.get(k) for k in ("url", "status", "shot", "error")},
         "employer": emp and {k: emp.get(k) for k in ("url", "status", "shot", "error", "via")}}
    # The employer's page is the posting. The board's is a copy of it.
    page = emp if emp and len(emp.get("text") or "") > 200 else board
    v["read"] = "employer" if page is emp and emp else "board"
    v["read_url"] = page.get("url") if page else None

    dead = gone(emp) or gone(board)
    if dead:
        return {**v, "lane": "closed", "posting_open": "no", "open_quote": dead, "reason": "the page says it is closed",
                "stage": "render"}
    text = (page or {}).get("text") or ""
    if len(text) < 200 or WALL.search(text[:600]):
        return {**v, "lane": "unsure", "posting_open": "unreadable", "stage": "render",
                "open_quote": " ".join(text.split())[:160] or (page or {}).get("error"),
                "reason": "the page could not be read in the browser"}

    prompt = (criteria.VISION_HEAD + criteria.JUDGE_CRITERIA + criteria.JUDGE_FIELDS + criteria.VISION_OUTPUT
              + f"\n\nThe pool lists this role as: {rec.get('title')} at {rec.get('company')}."
              + f"\nPage address: {page.get('url')}\nPage title: {page.get('title')}"
              + "\n\n--- EVERY WORD VISIBLE ON THE PAGE ---\n" + text[:MAX_CHARS])
    try:
        a = ask(prompt)
    except Exception as e:
        return {**v, "lane": "unsure", "stage": "error", "reason": f"the reader failed: {e}"}
    v.update(a)
    v["stage"] = "vision"
    if a.get("posting_open") == "no":
        v["lane"] = "closed"
    elif a.get("posting_open") == "unreadable":
        v["lane"] = "unsure"
    else:
        lane = criteria.lane_for(a.get("role_verdict"), a.get("place_verdict"))
        v["lane"] = lane or "cut"
        if a.get("language_ok") is False:
            v["lane"] = "cut"
        # Open is a promise that the employer's own page was read.
        if v["lane"] in ("open", "portugal") and v["read"] == "board":
            v["lane_if_employer"] = v["lane"]
            v["lane"] = "unsure"
            v["reason"] = "only the job board's copy could be read · " + str(a.get("reason") or "")
    return v


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
        rows.sort(key=lambda j: j.get("posted") or j.get("first_seen") or "", reverse=True)
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

    def one(rec):
        try:
            v = see(br, rec)
        except Exception as e:
            v = {"id": rec["id"], "lane": "unsure", "stage": "error", "reason": f"{type(e).__name__}: {e}"}
        with _lock:
            out[rec["id"]] = v
            n[0] += 1
            print(f"  [{n[0]}/{len(rows)}] {v['lane']:8} {v.get('read', '-'):8} {rec['company'][:22]:22} | "
                  f"{rec['title'][:38]:38} | {str(v.get('place_quote') or v.get('open_quote') or v.get('reason'))[:70]}", flush=True)
            if n[0] % 10 == 0:
                json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)

    try:
        with ThreadPoolExecutor(WORKERS) as ex:
            list(ex.map(one, rows))
    finally:
        br.close()
        json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
    import collections
    c = collections.Counter(out[r["id"]]["lane"] for r in rows)
    u = _usage
    print(f"done in {time.time() - t0:.0f}s: {dict(c)}")
    if u["calls"]:
        print(f"{u['calls']} pages read by {MODEL}: {u['in']:,} tokens in, {u['out']:,} out, "
              f"{(u['in'] + u['out']) // u['calls']:,} per page, ${u['usd']:.2f} at API prices")


if __name__ == "__main__":
    main()
