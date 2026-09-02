"""Static server for the review UI that also accepts the marks back.

python -m http.server cannot take a POST, so marks lived only in the browser
and there was no way to read them. This serves the directory and writes
POST /api/marks straight to data/marks.json.

    python3 serve.py        # http://localhost:8123/review.html
"""
import http.server, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKS = ROOT / "data" / "marks.json"


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def do_POST(self):
        if self.path != "/api/marks":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode("utf-8", "replace")
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
    print("serving %s on http://localhost:8123" % ROOT, flush=True)
    # Threaded: a single-threaded server let one stuck keep-alive connection
    # from a quit Chrome hold every other request until it timed out.
    http.server.ThreadingHTTPServer(("127.0.0.1", 8123), H).serve_forever()
