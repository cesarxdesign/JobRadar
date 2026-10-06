"""names: the role names VISION keeps rejecting, for CTF to drop without a page.

    python3 names.py        # rebuild data/cut_names.json from what VISION has decided

A name goes on the list when VISION has rejected it FOR THE ROLE three times
or more and has never once kept a job of that name - not in Open, not in
Portugal, not in Unsure, and never with a role verdict other than "no".
"design engineer" is rejected in one place and a fit in the next, so it never
gets on: those are read with the description as the tiebreak (his words).
The list is rebuilt whole each time, so a name VISION keeps once is gone from it.
"""
import collections, json, os

import contracts, judge

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = f"{ROOT}/data/cut_names.json"
MIN = 3


def build():
    vis = json.load(open(f"{ROOT}/data/vision.json"))
    jobs = {j["id"]: j for j in contracts.load_pool(f"{ROOT}/data/pool.json")["jobs"]}
    no, other = collections.Counter(), collections.Counter()
    for i, v in vis.items():
        if v.get("stage") != "vision" or i not in jobs:
            continue
        n = judge.name_of(jobs[i].get("title"))
        if not n:
            continue
        if v.get("role_verdict") == "no" and v.get("lane") in ("cut", "closed"):
            no[n] += 1
        else:
            other[n] += 1
    names = {n: c for n, c in sorted(no.items(), key=lambda x: -x[1]) if c >= MIN and not other[n]}
    tmp = OUT + ".tmp"
    json.dump(names, open(tmp, "w"), indent=0, ensure_ascii=False)
    os.replace(tmp, OUT)
    print(f"CTF: {len(names)} role names learned from VISION ({sum(names.values())} rejections behind them)")
    return names


if __name__ == "__main__":
    build()
