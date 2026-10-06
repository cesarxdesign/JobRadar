"""tabs: read a page he has left open in his own Chrome.

Two things the night run needs can only be seen in his browser: his inbox,
which is his alone, and remote.io, which shows its listings to a person's
browser and a loading spinner to a script's. He leaves both open in Chrome
before bed and the night run reads what is on them, through Chrome's own
AppleScript door. It asks Chrome for a tab and runs a line of JavaScript in
it - which Chrome only allows once he has switched it on:

    Chrome menu bar > View > Developer > Allow JavaScript from Apple Events

Nothing is typed, clicked or signed in on his behalf. A tab that is not open
is simply not read, and the run goes on without it.

    python3 tabs.py                # which of the two tabs it can see
    python3 tabs.py remoteio       # save the listings on the remote.io tab for the pool
"""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))


class NoTab(Exception):
    pass


def osa(script, timeout=60):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise NoTab(r.stderr.strip()[:300])
    return r.stdout.rstrip("\n")


def every(part):
    """Every open tab whose address contains `part`."""
    out = osa('tell application "Google Chrome"\nset o to ""\nrepeat with w from 1 to count of windows\n'
              'repeat with t from 1 to count of tabs of window w\n'
              'set o to o & w & "\t" & t & "\t" & (URL of tab t of window w) & "\n"\nend repeat\nend repeat\nreturn o\nend tell')
    tabs = [(int(w), int(t), url) for w, t, url in (line.split("\t")[:3] for line in out.splitlines() if line.count("\t") >= 2)
            if part in url]
    if not tabs:
        raise NoTab(f"no Chrome tab open on {part}")
    return tabs


def find(part):
    """(window index, tab index) of the first open tab whose address contains `part`."""
    out = osa('tell application "Google Chrome"\nset o to ""\nrepeat with w from 1 to count of windows\n'
              'repeat with t from 1 to count of tabs of window w\n'
              'set o to o & w & "\t" & t & "\t" & (URL of tab t of window w) & "\n"\nend repeat\nend repeat\nreturn o\nend tell')
    for line in out.splitlines():
        w, t, url = (line.split("\t") + ["", "", ""])[:3]
        if part in url:
            return int(w), int(t), url
    raise NoTab(f"no Chrome tab open on {part}")


def js(tab, code, timeout=120):
    """Run JavaScript in the tab and return what it evaluates to (a string)."""
    w, t = tab[0], tab[1]
    esc = code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return osa(f'tell application "Google Chrome" to execute tab {t} of window {w} javascript "{esc}"', timeout)


REMOTEIO_JS = """JSON.stringify([...document.querySelectorAll('a[data-testid^="card-job-"]')].map(a=>({
 url:'https://remote.io'+a.getAttribute('href'), title:(a.querySelector('h3')?.innerText||'').trim(),
 company:(a.querySelector('img')?.getAttribute('alt')||'').trim(), text:a.innerText.replace(/\\s+/g,' ').trim().slice(0,240)})))"""


def remoteio():
    """The listings showing on his remote.io tabs, as he left them. A page is
    not reloaded and not paged: what a person would see on each tab is read.
    The list is newest first, 30 to a page, so page 1 holds each day's new
    postings; to cover more he opens page 2 and 3 in tabs of their own, and
    every remote.io tab that is open gets read."""
    rows, had = [], set()
    for tab in every("remote.io"):
        for r in json.loads(js(tab, REMOTEIO_JS) or "[]"):
            if r["url"] not in had:
                had.add(r["url"])
                rows.append(r)
    path = f"{ROOT}/data/remoteio_rows.json"
    old = json.load(open(path))["rows"] if os.path.exists(path) else []
    seen = {r["url"] for r in rows}
    rows += [r for r in old if r["url"] not in seen and r.get("seen", "") >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - 21 * 86400))]
    for r in rows:
        r.setdefault("seen", time.strftime("%Y-%m-%d"))
    json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows}, open(path, "w"), indent=1, ensure_ascii=False)
    return len(seen), len(rows)


if __name__ == "__main__":
    if sys.argv[1:] == ["remoteio"]:
        try:
            new, total = remoteio()
            print(f"remote.io tab: {new} listings on the page, {total} kept")
        except NoTab as e:
            print(f"remote.io tab not read: {e}")
        except subprocess.TimeoutExpired as e:
            # Chrome did not answer AppleScript in time; the night goes on without the tab
            print(f"remote.io tab: Chrome did not answer in {e.timeout:.0f} s, skipped")
    else:
        for name, part in (("inbox", "mail.google.com"), ("remote.io", "remote.io")):
            try:
                tab = find(part)
                try:
                    print(f"{name}: open · {js(tab, 'document.title')[:70]}")
                except NoTab as e:
                    print(f"{name}: open, but cannot be read · {e}")
            except NoTab as e:
                print(f"{name}: {e}")
