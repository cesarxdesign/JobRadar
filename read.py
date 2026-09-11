"""read: the L2 pass. Claude reads a posting holding the judge's criteria.

One call per role returns BOTH the verdict and the extracted fields, because
the fields are the evidence for the verdict - asking twice would pay twice for
the same reading.

Verdicts are cached on a hash of what was read. The same posting is never read
twice, and a verdict cannot drift between runs for a posting that has not
changed. A company editing its JD changes the hash, which is exactly when a
fresh read is wanted.
"""
import threading
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import criteria

# Sources that republish somebody else's posting. Their description is a
# summary - designjobsworld's runs about 270 characters - so a role from one
# of these MUST be resolved to the original before L2 reads it. A company
# board is already the original and needs no resolving.
AGGREGATORS = {"designjobsworld", "himalayas", "jobicy", "remoteok", "remotive",
               "arbeitnow", "landingjobs", "weworkremotely", "workingnomads",
               # from the LinkedIn sweep, 2026-09-11
               "superjobs", "euremotejobs", "jobspresso", "justremote", "wellfound",
               "builtin", "dribbble", "nodesk", "wttj", "yc", "eures", "salt"}
THIN = 1200


# This job is reading English and applying stated rules - there is very little
# reasoning in it. The cheapest model is the right default; the expensive one
# was costing ~10x for no measured gain. --fallback-model also turns an
# overload into one successful call instead of three wasted full-price ones.
MODEL = os.environ.get("RADAR_MODEL", "haiku")
FALLBACK = os.environ.get("RADAR_FALLBACK", "sonnet")

ROOT = Path(__file__).resolve().parent
CACHE_FILE = ROOT / "data" / "reads.json"


def cli_env():
    """A one-shot `claude -p` is not a nested session, but these vars make the
    CLI think it is and refuse to start with a misleading "Not logged in"."""
    env = dict(os.environ)
    for k in ("CLAUDECODE", "CLAUDECODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT",
              "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)
    return env


# The rec fields that render in the side panel, in page order. This is the ONE
# list: posting_text renders it, batch.py saves it into fixtures, regress.py
# feeds it back. A fixture that carries only "location" re-judges a different
# page than the batch saw - that is how batch2/batchA lost Location Type.
PANEL = (
    ("location", "Location"),
    ("workplace", "Location Type"),
    ("employment_type", "Employment Type"),
    ("department", "Department"),
    ("salary", "Compensation"),
    ("restrictions", "Location Restrictions"),
)


def posting_text(rec, jd):
    """The posting as a person sees it: header, side panel, then the body.

    Not labelled metadata. Cesar's instruction, and he is right: the judge
    should read whatever renders as words on screen - the title block, the
    sidebar with location and employment type, and the description - as one
    document. Feeding it "BOARD REMOTE FLAG: True" invited it to argue with
    the words on the page.
    """
    lines = [rec.get("title") or "", rec.get("company") or "", ""]
    for field, label in PANEL:
        val = rec.get(field)
        if isinstance(val, list):
            val = ", ".join(val)
        if val:
            lines.append(f"{label}\n{val}\n")
    lines.append("")
    lines.append(jd[:14000] if jd else
                 "(this posting's description could not be read)")
    return "\n".join(x for x in lines if x is not None)


def prompt_for(rec, jd):
    return (criteria.L2_CRITERIA + "\n" + criteria.L2_FIELDS + "\n"
            + criteria.L2_OUTPUT
            + "\n\n--- THE POSTING, AS IT RENDERS ON THE PAGE ---\n"
            + posting_text(rec, jd))


def key_for(rec, jd):
    """Cache key: everything the judge is shown, plus what judged it.

    The location and workplace MUST be in here. They were not, so every time a
    location was corrected the cache kept serving the verdict computed from
    the wrong one - the reason text still quoted a location that no longer
    existed.
    """
    h = hashlib.sha1()
    h.update((rec.get("title") or "").encode())
    h.update((rec.get("company") or "").encode())
    h.update((rec.get("location") or "").encode())
    h.update((str(rec.get("workplace")) or "").encode())
    h.update((str(rec.get("restrictions")) or "").encode())
    h.update((jd or "")[:14000].encode())
    h.update(criteria.VERSION.encode())
    h.update(MODEL.encode())          # a different model is a different verdict
    return h.hexdigest()[:16]


def parse(text):
    """Pull the JSON object out of whatever came back."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON object in reply")
    return json.loads(text[i:j + 1])


class Overloaded(Exception):
    """The API is failing, not this posting. Retrying harder makes it worse."""


_consecutive = [0]          # module-level, so a run can notice a bad patch
GIVE_UP_AFTER = 8           # consecutive API failures -> stop the whole run


def ask(prompt, tries=2):
    """One posting, judged.

    Two failure kinds, treated differently:
      - unparseable reply: the model wandered. Retrying is cheap and usually
        works, so retry once, immediately.
      - API error: the service is refusing. Retrying immediately is the worst
        possible response - it was 86% of one run's spend. Back off, try once
        more, and if the failures are piling up across the run, stop.
    """
    last = None
    for attempt in range(tries):
        try:
            r = subprocess.run(["claude", "-p", prompt, "--output-format", "json",
                                "--model", MODEL, "--fallback-model", FALLBACK],
                               capture_output=True, text=True, timeout=240,
                               env=cli_env())
        except subprocess.TimeoutExpired:
            last = "timeout"
            time.sleep(4 * (attempt + 1))
            continue
        out = r.stdout
        api_error = False
        try:
            env = json.loads(out)
            if env.get("is_error"):
                api_error = True
                last = "api error: " + str(env.get("result"))[:160]
            else:
                out = env.get("result") or out
        except Exception:
            pass
        if api_error:
            _consecutive[0] += 1
            if _consecutive[0] >= GIVE_UP_AFTER:
                raise Overloaded(f"{_consecutive[0]} API failures in a row - stopping")
            time.sleep(3 * (2 ** attempt))          # 3s, then 6s
            continue
        try:
            v = parse(out)
            _consecutive[0] = 0                     # a good reply clears the run
            return v
        except Exception as e:
            last = f"unparseable: {e}"
    raise RuntimeError(last or "failed")


def text_kind(rec, jd):
    """What the judge was shown: the original posting, an aggregator's
    summary, or nothing but the title block and panel."""
    if not (jd or "").strip():
        return "none"
    src = (rec.get("source") or "").split("/")[0]
    if src in AGGREGATORS and len(jd) < THIN:
        return "summary"
    return "original"


def read_one(rec, jd, cache, allow_thin=False):
    """One verdict for one posting, from the cache or from the model."""
    # Judges whatever text there is. The judge resolves originals first; when
    # that fails the aggregator's summary is still the posting as far as we
    # can see it, and with no text at all the criteria say how to judge from
    # the title and panel. Cesar, 2026-09-02: "we parse and judge like the
    # others." The cache key is the text, so an original arriving later is a
    # new read. text_kind() says what was judged.
    k = key_for(rec, jd)
    if k in cache:
        return cache[k], True
    v = ask(prompt_for(rec, jd))
    lane = criteria.lane_for(v.get("role_verdict"), v.get("place_verdict"))
    v["lane"] = lane or "unsure"
    v["cut"] = lane is None or bool(v.get("cut"))
    v["criteria_version"] = criteria.VERSION
    with _cache_lock:
        cache[k] = v
    return v, False


# Readers run in threads. Every write to the cache and every snapshot of it
# goes through this lock - a save that serialised the dict while another
# thread inserted killed a judge run at read 250.
_cache_lock = threading.Lock()


def load_cache():
    return json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}


def save_cache(cache):
    with _cache_lock:
        snap = dict(cache)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, indent=1, ensure_ascii=False))
    tmp.replace(CACHE_FILE)
