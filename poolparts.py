"""poolparts: data/pool.json <-> data/pool1.json, data/pool2.json, ...

The pool the scripts read stays on this Mac (data/pool.json, not pushed). It
holds every design-titled posting whole, and one slim line for each posting
the title cut dropped (pool.slim). Those slim lines are reference for this Mac
only: 147,000 of them, 45MB, and a scrape brings them back.

What is pushed is the rest - the postings vision reads, with every first-seen
date - cut into POOL_PARTS pieces so no file nears GitHub's 100MB wall. One
posting per line, cut between lines: gluing the pieces back gives one file.

    python3 poolparts.py split     # pool.json -> pool1.json ... (before a push)
    python3 poolparts.py join      # pool1.json ... -> pool.json (after a loss)
"""
import json, pathlib, sys

# How many pieces the pool is pushed in. Raise it when split warns.
POOL_PARTS = 1

DATA = pathlib.Path(__file__).parent / "data"
POOL = DATA / "pool.json"
WARN_MB = 80                      # per piece; GitHub's wall is 100


def part(i):
    return DATA / f"pool{i}.json"


def split():
    import contracts, pool
    doc = contracts.load_pool(POOL)
    jobs = doc.pop("jobs")
    whole = [j for j in jobs if not set(j) <= set(pool.SLIM)]
    lines = contracts.pool_text(doc, whole).encode().splitlines(keepends=True)
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
    back = json.loads(b"".join(part(i).read_bytes() for i in range(1, POOL_PARTS + 1)))
    if len(back["rows"]) != len(whole):
        raise SystemExit("the pieces do not add up to the pool; nothing should be pushed")
    print(f"{len(whole)} postings pushed whole, {len(jobs) - len(whole)} slim lines stay on this Mac")


def join():
    if POOL.exists() and "--force" not in sys.argv:
        raise SystemExit("data/pool.json is already there; --force to overwrite it")
    tmp = POOL.with_suffix(".tmp")
    tmp.write_bytes(b"".join(part(i).read_bytes() for i in range(1, POOL_PARTS + 1)))
    tmp.replace(POOL)
    print(f"wrote {POOL} ({POOL.stat().st_size // 1048576}MB) from {POOL_PARTS} pieces")


if __name__ == "__main__":
    {"split": split, "join": join}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
