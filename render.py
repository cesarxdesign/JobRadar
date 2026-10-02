"""render: a posting, loaded in a real browser, as the person applying sees it.

The judge used to read text scraped out of feeds and pasted together. That is
not the page. This drives the Chrome already installed on this Mac, headless,
over its DevTools socket: load the URL, let its scripts run, and take back
what is on screen - every word of the rendered page, where the address bar
ended up, the status the server answered with, and a screenshot.

For a posting on a job board it then does what he would do: press Apply, and
read the page that opens. That page is the employer's own, and it is the one
that says "Germany only".

No dependencies: the websocket client below is the little of the protocol
DevTools needs.

    python3 render.py <url> [<url> ...]     # print what each page shows
"""
import base64, json, os, re, socket, struct, subprocess, sys, tempfile, time, urllib.request
from urllib.parse import urlparse

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = os.path.dirname(os.path.abspath(__file__))
SHOTS = f"{ROOT}/data/shots"

# What the page is asked for once it has rendered. innerText is what is
# visible: hidden markup, scripts and styles are not in it.
PAGE_JS = r"""
(() => {
  const host = location.hostname.replace(/^www\./, '');
  const seen = new Set(), apply = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const t = (a.innerText || a.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
    const h = a.href;
    if (!/^https?:/.test(h) || seen.has(h)) continue;
    if (/\bapply\b|apply for|apply now|candidatar|bewerben|postuler/i.test(t) && t.length < 60) {
      seen.add(h); apply.push({href: h, text: t, external: new URL(h).hostname.replace(/^www\./, '') !== host});
    }
  }
  return JSON.stringify({url: location.href, title: document.title,
    text: document.body ? document.body.innerText : '', apply,
    height: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)});
})()
"""


class WS:
    """Just enough websocket for DevTools: text frames, client-masked."""

    def __init__(self, url):
        u = urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.n = 0

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("browser closed the socket")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, timeout):
        self.s.settimeout(timeout)
        data = b""
        while True:
            b1, b2 = self._read(2)
            n = b2 & 127
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            if b1 & 15 == 9:                                   # ping
                continue
            if b1 & 15 == 8:
                raise ConnectionError("closed")
            data += payload
            if b1 & 128:
                return json.loads(data.decode("utf-8", "replace"))

    def send(self, method, **params):
        self.n += 1
        raw = json.dumps({"id": self.n, "method": method, "params": params}).encode()
        mask = os.urandom(4)
        head = b"\x81" + (bytes([128 | len(raw)]) if len(raw) < 126 else
                          bytes([254]) + struct.pack(">H", len(raw)) if len(raw) < 65536 else
                          bytes([255]) + struct.pack(">Q", len(raw)))
        self.s.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(raw)))
        return self.n

    def call(self, method, timeout=30, events=None, **params):
        """Send, and wait for the answer. Events that arrive meanwhile go to `events`."""
        i, end = self.send(method, **params), time.time() + timeout
        while time.time() < end:
            m = self.recv(max(.1, end - time.time()))
            if m.get("id") == i:
                return m.get("result") or {}
            if events is not None and "method" in m:
                events.append(m)
        raise TimeoutError(method)

    def drain(self, seconds, events, until=None):
        end = time.time() + seconds
        while time.time() < end:
            try:
                m = self.recv(max(.05, end - time.time()))
            except (socket.timeout, TimeoutError):
                break
            if "method" in m:
                events.append(m)
                if until and m["method"] == until:
                    return True
        return False

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


class Browser:
    """One headless Chrome, its own throwaway profile, a tab per page."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="radar-chrome-")
        self.p = subprocess.Popen(
            [CHROME, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.dir}",
             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--mute-audio",
             "--window-size=1280,1600", "--lang=en-US",
             # headless Chrome announces itself as HeadlessChrome; boards refuse that on sight
             "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = f"{self.dir}/DevToolsActivePort"
        for _ in range(100):
            if os.path.exists(port_file) and open(port_file).read().strip():
                break
            time.sleep(.1)
        self.port = int(open(port_file).read().split()[0])

    def _http(self, path, method="GET"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        return json.loads(urllib.request.urlopen(req, timeout=15).read() or b"{}")

    def page(self, url, shot=None, settle=2.5, timeout=25):
        """Load one URL and report what rendered. Never raises for a bad page:
        a page that will not load is a fact about the posting."""
        out = {"asked": url, "url": url, "status": None, "title": "", "text": "", "apply": [], "error": None}
        try:
            tab = self._http("/json/new?about:blank", "PUT")
        except Exception as e:
            out["error"] = f"browser: {e}"
            return out
        ws = WS(tab["webSocketDebuggerUrl"])
        try:
            ev = []
            ws.call("Page.enable")
            ws.call("Network.enable")
            ws.call("Page.navigate", events=ev, url=url)
            ws.drain(timeout, ev, until="Page.loadEventFired")
            ws.drain(settle, ev)                               # scripts paint after load
            for _ in range(3):
                r = ws.call("Runtime.evaluate", events=ev, expression=PAGE_JS, returnByValue=True)
                got = json.loads(r["result"]["value"]) if r.get("result", {}).get("value") else {}
                if len(got.get("text", "")) > 400:
                    break
                ws.drain(2.5, ev)                              # a slow single-page app
            out.update({k: got.get(k, out.get(k)) for k in ("url", "title", "text", "apply")})
            # the status of the document that ended up on screen, after redirects
            docs = [e["params"]["response"] for e in ev if e["method"] == "Network.responseReceived"
                    and e["params"].get("type") == "Document"]
            if docs:
                out["status"] = docs[-1]["status"]
            if shot:
                h = min(int(got.get("height") or 1600), 7000)
                r = ws.call("Page.captureScreenshot", timeout=40, format="jpeg", quality=55,
                            captureBeyondViewport=True,
                            clip={"x": 0, "y": 0, "width": 1280, "height": h, "scale": .75})
                os.makedirs(os.path.dirname(shot), exist_ok=True)
                open(shot, "wb").write(base64.b64decode(r["data"]))
                out["shot"] = os.path.relpath(shot, ROOT)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
        finally:
            ws.close()
            try:
                self._http(f"/json/close/{tab['id']}")
            except Exception:
                pass
        return out

    def close(self):
        self.p.terminate()
        try:
            self.p.wait(5)
        except Exception:
            self.p.kill()
        subprocess.run(["rm", "-rf", self.dir])


def site(u):
    """example.com for jobs.example.com - near enough to tell a board from an employer."""
    h = (urlparse(u).hostname or "").lower()
    parts = h.split(".")
    return ".".join(parts[-3:] if len(parts) > 2 and len(parts[-2]) <= 3 and len(parts[-1]) == 2 else parts[-2:])


SOCIAL = re.compile(r"linkedin\.com/(share|sharing)|twitter\.com|x\.com/intent|facebook\.com|whatsapp|mailto:|t\.me/", re.I)


def posting(br, url, shot_id=None, is_board=False):
    """The page behind a pool row and, when that row is a board's copy, the
    employer's page behind its Apply button.

    Returns {"board": page | None, "employer": page | None}. `employer` is set
    only when the browser really ended up on another site - never guessed.
    """
    first = br.page(url, shot=f"{SHOTS}/{shot_id}.jpg" if shot_id else None)
    if not is_board:
        return {"board": None, "employer": first}
    out = {"board": first, "employer": None}
    links = [a for a in first.get("apply") or [] if not SOCIAL.search(a["href"])]
    links.sort(key=lambda a: (not a["external"], len(a["text"])))
    for a in links[:2]:
        nxt = br.page(a["href"], shot=f"{SHOTS}/{shot_id}.employer.jpg" if shot_id else None)
        if nxt.get("text") and site(nxt["url"]) != site(first["url"]):
            # Apply often opens the form, one level below the posting itself.
            up = re.sub(r"/(apply|application)/?(\?.*)?$", "", nxt["url"])
            if up != nxt["url"]:
                par = br.page(up, shot=f"{SHOTS}/{shot_id}.employer.jpg" if shot_id else None)
                if len(par.get("text") or "") > len(nxt["text"]):
                    nxt = par
            nxt["via"] = a["href"]
            out["employer"] = nxt
            break
    return out


if __name__ == "__main__":
    b = Browser()
    try:
        for u in sys.argv[1:]:
            t = time.time()
            r = posting(b, u, shot_id="probe-" + re.sub(r"\W+", "-", u)[-40:], is_board="--board" in sys.argv)
            for k in ("board", "employer"):
                p = r[k]
                if p:
                    print(f"[{k}] {p['status']} {p['url']}\n   title: {p['title'][:90]}\n   {len(p['text'])} chars, "
                          f"{len(p['apply'])} apply links, shot {p.get('shot')}, error {p['error']}")
                    print("   " + " ".join(p["text"].split())[:300])
            print(f"   {time.time() - t:.1f}s")
    finally:
        b.close()
