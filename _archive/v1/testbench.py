#!/usr/bin/env python3
"""A bench for the judge. Its own copy of the roles, a button, no live data.

    python3 testbench.py        then open http://localhost:8777

Everything it writes goes to a sandbox directory. data/ is opened read-only,
once, to make that copy - there is no code path here that writes to it. Run it
from a normal terminal (not the Claude Code app) so the claude CLI can start.
"""
import json
import os
import shutil
import time
import threading
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIVE = ROOT / "data"
SANDBOX = Path("/private/tmp/claude-501/-Users-cgair-Claude/"
               "d907a925-4168-4fb2-8420-83f948ba9c0e/scratchpad/test42")
PORT = 8777

assert SANDBOX.resolve() != LIVE.resolve(), "sandbox must not be the live data dir"

STATE = {"running": False, "done": 0, "total": 0, "rows": [], "error": None,
         "preflight": None, "hunts": {}, "stop": False, "seen": 0.0}

# Closing the browser used to leave the run going - a separate process burning
# tokens on results nobody would see. The page polls while it is open, so a
# gap in polling means it is gone, and the run stops at the next role.
WATCHDOG_S = 20


os.environ["JOBRADAR_HUNT_CACHE"] = str(SANDBOX / "hunt_cache.json")


def sandbox_ready():
    SANDBOX.mkdir(parents=True, exist_ok=True)
    for n in ("jobs.json", "judged.json", "jds.json", "state.json", "facts.json"):
        if not (SANDBOX / n).exists():
            shutil.copy(LIVE / n, SANDBOX / n)


def open_roles():
    """The Open tab, computed exactly the way index.html computes it."""
    d = json.loads((SANDBOX / "jobs.json").read_text())
    st = json.loads((SANDBOX / "state.json").read_text())
    sj, sv = st["jobs"], st.get("verdicts") or {}
    fa = json.loads((SANDBOX / "facts.json").read_text())
    F = fa.get("jobs", fa)

    def bucket_of(j):
        v = sv.get(j["id"])
        if v:
            return "ok" if v.get("v") == "y" else "no"
        if j["bucket"] == "tiebreak" and re.match(
                r"^yes", str((F.get(j["id"]) or {}).get("portugal") or ""), re.I):
            return "eu"
        return j["bucket"]

    def is_pt(j):
        l = j.get("location") or ""
        return (bucket_of(j) == "pt"
                and re.search(r"portugal|lisbon|lisboa", l, re.I)
                and not re.search(r"remote", l, re.I))

    act = [j for j in d["jobs"] if j["active"]]
    done = [j for j in act if not sj.get(j["id"])
            and (j.get("judged") or sv.get(j["id"]))]
    return [j for j in done if not is_pt(j) and bucket_of(j) != "tiebreak"], sv


def run_judge():
    """Every role in the list, through parser v3.0, into the sandbox only."""
    import importlib
    import parser as P
    importlib.reload(P)
    try:
        STATE.update(running=True, done=0, rows=[], error=None)
        v, err = P.read({"company": "x", "title": "x"},
                        {"clean": True, "text": "Reply place=eu.", "url": None})
        STATE["preflight"] = "ok" if v else err
        if not v:
            STATE.update(running=False, error=f"the claude CLI could not be reached: {err}")
            return
        jobs, sv = open_roles()
        budget = P.new_budget()
        jds = json.loads((SANDBOX / "jds.json").read_text())["jobs"]
        judged = json.loads((SANDBOX / "judged.json").read_text())
        STATE["total"] = len(jobs)
        for j in jobs:
            if STATE["stop"]:
                STATE["error"] = "stopped"
                break
            if STATE["seen"] and time.monotonic() - STATE["seen"] > WATCHDOG_S:
                STATE["error"] = ("stopped - the page was closed, so the run "
                                  "halted rather than spend tokens unwatched")
                break
            row = {"company": j["company"], "title": j["title"],
                   "location": j.get("location") or "", "was": j["bucket"],
                   "mine": bool(sv.get(j["id"])), "source": j["source"].split("/")[0],
                   # the same link the Radar card opens, so a verdict can be
                   # checked against the page it was made from
                   "url": j.get("apply_url") or j.get("url") or ""}
            try:
                r = P.parse(j, (jds.get(j["id"], {}) or {}).get("jd") or "", budget)
                row.update(now=r["bucket"], why=r.get("why", ""),
                           work=r.get("work", ""), scope=r.get("scope", ""),
                           origin=r.get("origin", ""), via=r.get("via") or "",
                           clean=r.get("clean", False), chars=r.get("chars", 0),
                           original=r.get("original") or "")
                judged["jobs"][j["id"]] = {"bucket": r["bucket"],
                                           "why": r.get("why", ""),
                                           "pv": P.VERSION, "at": "bench"}
            except Exception as e:
                row.update(now="ERROR", why=str(e)[:200])
            STATE["rows"].append(row)
            STATE["done"] += 1
            STATE["hunts"] = dict(budget)
            (SANDBOX / "judged.json").write_text(json.dumps(judged, indent=1))
    except Exception as e:
        STATE["error"] = str(e)
    finally:
        STATE["running"] = False


PAGE = """<!doctype html><meta charset=utf-8><title>Parser v__VER__ bench</title>
<style>
 :root{color-scheme:light dark}
 body{font:14px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;margin:0;padding:24px;
      background:#fff;color:#111}
 @media(prefers-color-scheme:dark){body{background:#111;color:#eee}}
 h1{font-size:19px;margin:0 0 2px} .sub{opacity:.6;font-size:13px;margin-bottom:18px}
 .bar{display:flex;gap:12px;align-items:center;margin-bottom:18px;flex-wrap:wrap}
 button{font:600 14px inherit;padding:9px 20px;border-radius:999px;border:0;
        background:#1a7f37;color:#fff;cursor:pointer}
 button:disabled{opacity:.45;cursor:default}
 .safe{font-size:12px;opacity:.65;border-left:3px solid #1a7f37;padding-left:9px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{text-align:left;padding:6px 9px;border-bottom:1px solid rgba(128,128,128,.22);
       vertical-align:top}
 th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;opacity:.55}
 .b{font-weight:700;padding:1px 7px;border-radius:4px;font-size:12px}
 .cut{background:#b3261e;color:#fff}.tiebreak{background:#8a6d00;color:#fff}
 .eu,.ww,.pt,.ok{background:#1a7f37;color:#fff}
 .FAILED,.ERROR{background:#555;color:#fff}
 .chg{background:rgba(255,196,0,.13)} .why{opacity:.7;font-size:12px}
 .mine{font-size:11px;opacity:.6}
 code{font-size:12px;opacity:.7}
 a{color:#0b62d6} @media(prefers-color-scheme:dark){a{color:#79b8ff}}
 td a{font-size:13px}
 .orig{font-size:11px;opacity:.8}
</style>
<h1>Parser v__VER__</h1>
<div class=sub>sweep &rarr; QCC &rarr; hygiene (get the original) &rarr; read the JD for role + location. Its own copy of your roles.</div>
<div class=bar>
  <button id=go>Run parser v__VER__</button>
  <button id=stop style="background:#8a1c13;display:none">Stop</button>
  <span id=st></span>
  <span id=hunt class=why style="opacity:.7"></span>
</div>
<div class=safe>Reads and writes <code id=sb></code> only. Your live <code>data/</code> is never written to.</div>
<p id=sum></p>
<table><thead><tr><th>Role</th><th>Location</th><th>Origin</th><th>Read</th><th>Was</th><th>Now</th><th>Why</th></tr></thead>
<tbody id=rows></tbody></table>
<script>
const $=s=>document.querySelector(s);
$('#sb').textContent=SANDBOX_PATH;
async function tick(){
  const s=await (await fetch('/api/progress')).json();
  $('#go').disabled=s.running;
  $('#stop').style.display=s.running?'inline-block':'none';
  $('#st').textContent=s.running?`judging ${s.done}/${s.total}…`
    :(s.error?'✗ '+s.error:(s.done?`done — ${s.done} roles`:''));
  const h=s.hunts||{};
  $('#hunt').textContent = h.used!==undefined
    ? `hunts used ${h.used}${h.skipped?` · ${h.skipped} deferred to the next run`:''}` : '';
  const chg=s.rows.filter(r=>r.now&&r.now!==r.was);
  $('#sum').innerHTML=s.done?`<b>${s.rows.length}</b> judged · <b>${chg.length}</b> changed · `
    +`<b>${s.rows.filter(r=>r.now==='cut').length}</b> cut · `
    +`<b>${s.rows.filter(r=>r.now==='tiebreak').length}</b> to unsure`:'';
  $('#rows').innerHTML=s.rows.map(r=>{
    const moved=r.now&&r.now!==r.was;
    return `<tr class="${moved?'chg':''}">
      <td><b>${esc(r.company)}</b><br><span class=why>${esc(r.title)}</span>
        ${r.mine?'<br><span class=mine>you OK\\'d this</span>':''}</td>
      <td class=why>${esc(r.location)}</td>
      <td class=why>${r.origin==='aggregator'?'<b>aggregator</b>':(r.origin||'')}
        ${r.clean===false?'<br><span style="color:#b3261e">copy only</span>':''}</td>
      <td class=why>${r.via||''} ${r.chars?r.chars+'c':''}</td>
      <td><span class="b ${r.was}">${r.was}</span></td>
      <td>${r.now?`<span class="b ${r.now}">${r.now}</span>`:''}</td>
      <td class=why>${esc(r.why||'')}${r.scope?'<br><i>'+esc(r.scope)+'</i>':''}</td></tr>`;
  }).join('');
  if(s.running)setTimeout(tick,900);
}
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
$('#stop').onclick=async()=>{await fetch('/api/stop',{method:'POST'});};
window.addEventListener('pagehide',()=>navigator.sendBeacon('/api/stop'));
$('#go').onclick=async()=>{$('#go').disabled=true;await fetch('/api/run',{method:'POST'});tick();};
tick();
</script>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json"):
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/progress"):
            STATE["seen"] = time.monotonic()   # the page is still open
            return self._send(json.dumps(STATE))
        import parser as P
        page = (PAGE.replace("SANDBOX_PATH", json.dumps(str(SANDBOX)))
                    .replace("__VER__", P.VERSION))
        self._send(page, "text/html; charset=utf-8")

    def do_POST(self):
        if self.path.startswith("/api/stop"):
            STATE["stop"] = True
            return self._send("{}")
        if self.path.startswith("/api/run") and not STATE["running"]:
            STATE["stop"] = False
            STATE["seen"] = time.monotonic()
            threading.Thread(target=run_judge, daemon=True).start()
        self._send("{}")


if __name__ == "__main__":
    sandbox_ready()
    jobs, _ = open_roles()
    print(f"bench ready: {len(jobs)} roles in the sandbox copy")
    print(f"sandbox : {SANDBOX}")
    print(f"live    : {LIVE}  (read once to copy, never written)")
    print(f"\n  ->  http://localhost:{PORT}\n")
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
