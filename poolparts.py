"""poolparts: data/pool.json <-> data/pool1.json, data/pool2.json, ...

GitHub refuses any single file over 100 MB and the pool is one file close to
that. The pool the scripts read stays whole on this Mac (data/pool.json, not
pushed). What is pushed is the same file cut into POOL_PARTS pieces, so the
pool and every first-seen date in it are backed up.

The pool has one posting per line, so the pieces are cut between lines and
gluing them back in order gives the same file, byte for byte.

    python3 poolparts.py split     # pool.json -> pool1.json ... (before a push)
    python3 poolparts.py join      # pool1.json ... -> pool.json (after a loss)
"""
import pathlib, sys

# How many pieces the pool is pushed in. Raise it when split warns.
POOL_PARTS = 2

DATA = pathlib.Path(__file__).parent / "data"
POOL = DATA / "pool.json"
WARN_MB = 80                      # per piece; GitHub's wall is 100


def part(i):
    return DATA / f"pool{i}.json"


def split():
    lines = POOL.read_bytes().splitlines(keepends=True)
    total = sum(map(len, lines))
    out, size, i = [[] for _ in range(POOL_PARTS)], 0, 0
    for ln in lines:
        if size >= total * (i + 1) / POOL_PARTS and i < POOL_PARTS - 1:
            i += 1
        out[i].append(ln)
        size += len(ln)
    for i, chunk in enumerate(out, 1):
        raw = b"".join(chunk)
        tmp = part(i).with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(part(i))
        mb = len(raw) / 1048576
        print(f"pool{i}.json {mb:.0f}MB")
        if mb > WARN_MB:
            print(f"WARNING - pool{i}.json is {mb:.0f}MB and GitHub refuses 100MB. "
                  f"Raise POOL_PARTS in poolparts.py.", file=sys.stderr)
    if b"".join(part(i).read_bytes() for i in range(1, POOL_PARTS + 1)) != POOL.read_bytes():
        raise SystemExit("the pieces do not add up to the pool; nothing should be pushed")


def join():
    if POOL.exists() and "--force" not in sys.argv:
        raise SystemExit("data/pool.json is already there; --force to overwrite it")
    tmp = POOL.with_suffix(".tmp")
    tmp.write_bytes(b"".join(part(i).read_bytes() for i in range(1, POOL_PARTS + 1)))
    tmp.replace(POOL)
    print(f"wrote {POOL} ({POOL.stat().st_size // 1048576}MB) from {POOL_PARTS} pieces")


if __name__ == "__main__":
    {"split": split, "join": join}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
