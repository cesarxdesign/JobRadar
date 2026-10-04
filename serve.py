"""Static server for the review UI that also accepts the marks back.

python -m http.server cannot take a POST, so marks lived only in the browser
and there was no way to read them. This serves the directory and writes
POST /api/marks straight to data/marks.json.

    python3 serve.py        # http://localhost:8123/review.html
"""
import http.server, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKS = ROOT / "data" / "marks.json"
# His verdicts and notes on the TestBattery page. That page is public and has
# nowhere private to save them, so it posts them here, to this Mac. Never
# committed: data/battery_calls.json is ignored.
CALLS = ROOT / "data" / "battery_calls.json"
TEST = ROOT.parent / "TestBattery"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8123


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    _jd, _jd_mtime = {}, 0

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/battery-calls":
            body = CALLS.read_bytes() if CALLS.exists() else b"{}"
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/tb" or path.startswith("/tb/"):
            # the TestBattery page, served from this Mac so it can save here
            name = path[4:] or "index.html"
            f = (TEST / name).resolve()
            if TEST.resolve() not in f.parents or not f.is_file():
                return self.send_error(404)
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if name.endswith(".json") else "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.startswith("/api/jd/"):
            return super().do_GET()
        f = ROOT / "data" / "jd.json"
        m = f.stat().st_mtime if f.exists() else 0
        if m != H._jd_mtime:                    # reloaded when the judge or pool rewrites it
            H._jd, H._jd_mtime = json.loads(f.read_text()) if f.exists() else {}, m
        text = H._jd.get(self.path[len("/api/jd/"):].split("?")[0], "")
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        # The Gmail tab posts here. It is a public https page reaching a
        # loopback http address: Chrome preflights that (Private Network
        # Access) and hangs the request unless these headers come back.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode("utf-8", "replace")
        if self.path == "/api/battery-calls":
            try:
                json.loads(body)
            except Exception:
                return self.send_error(400)
            tmp = CALLS.with_suffix(".tmp")
            tmp.write_text(body)
            tmp.replace(CALLS)
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        if self.path == "/api/inbox":
            # A page of Gmail search results, posted by a script run in the
            # Gmail tab. Appended, local only, never committed (gitignored).
            with open(ROOT / "data" / "emails_raw.jsonl", "a") as f:
                f.write(body.rstrip("\n") + "\n")
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        if self.path == "/api/export":
            import subprocess
            r = subprocess.run([sys.executable, str(ROOT / "export.py")],
                               capture_output=True, text=True, cwd=str(ROOT))
            print((r.stdout + r.stderr).strip(), flush=True)
            self.send_response(200 if r.returncode == 0 else 500)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": r.returncode == 0,
                                         "msg": (r.stdout or r.stderr).strip()}).encode())
            return
        if self.path == "/api/complete-batch":
            import subprocess
            r = subprocess.run([sys.executable, str(ROOT / "batch.py"), "--complete"],
                               capture_output=True, text=True, cwd=str(ROOT))
            print((r.stdout + r.stderr).strip(), flush=True)
            self.send_response(200 if r.returncode == 0 else 500)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": r.returncode == 0,
                                         "msg": (r.stdout or r.stderr).strip()}).encode())
            return
        if self.path != "/api/marks":
            self.send_error(404)
            return
        tmp = MARKS.with_suffix(".tmp")
        tmp.write_text(body)
        tmp.replace(MARKS)
        try:
            k = len(json.loads(body))
        except Exception:
            k = -1
        print(f"marks saved: {k} entries", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("serving %s on http://localhost:%d" % (ROOT, PORT), flush=True)
    # Threaded: a single-threaded server let one stuck keep-alive connection
    # from a quit Chrome hold every other request until it timed out.
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
