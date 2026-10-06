"""limit: run a command, and kill it if it runs past its time.

    python3 limit.py [--status FILE] SECONDS command ...

Written after 2026-10-05, when the scrape hung from 02:01 until it was killed
by hand at 10:07 and the whole night was lost. macOS has no `timeout`, so the
night run uses this. The command gets its own process group, so what it
started (caffeinate, a browser) is killed with it. One line on stderr says so,
and the exit status is 124; otherwise it is the command's own. SECONDS of 0
means no limit (the vision read waits out usage limits for hours on purpose).
With --status, the outcome is also written to FILE ("exit 0", "exit 3" or
"killed 150"), because a pipe into `tail` hides the status from the shell.
"""
import os, signal, subprocess, sys, time


def main():
    args = sys.argv[1:]
    status = None
    if args[:1] == ["--status"]:
        status, args = args[1], args[2:]
    if len(args) < 2:
        print("usage: limit.py [--status FILE] SECONDS command ...", file=sys.stderr)
        return 2
    secs, cmd = float(args[0]), args[1:]

    def note(text):
        if status:
            with open(status, "w") as f:
                f.write(text + "\n")

    try:
        p = subprocess.Popen(cmd, start_new_session=True)
    except OSError as e:
        print(f"limit: could not start {cmd[0]}: {e}", file=sys.stderr)
        note("exit 127")
        return 127
    t0 = time.time()
    while True:
        try:
            rc = p.wait(timeout=5)
            note(f"exit {rc}")
            return rc
        except subprocess.TimeoutExpired:
            if secs and time.time() - t0 > secs:
                break
    mins = round((time.time() - t0) / 60)
    print(f"limit: {' '.join(cmd[:4])[:60]} killed after {mins} min (limit {round(secs / 60)} min); the night goes on", file=sys.stderr, flush=True)
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 10)):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            break
        try:
            p.wait(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            pass
    note(f"killed {mins}")
    return 124


if __name__ == "__main__":
    sys.exit(main())
