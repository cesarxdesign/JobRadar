"""Radar2 — the seam between the four modules.

    pool      -> data/pool.json       every role found. no opinions.
    judge     -> data/verdicts.json   criteria cut the pool. the only opinions.
    results   -> data/results.json    what survived, split into three lanes.
    decisions -> RadarRouting.json    on the Mac. applied/discarded. never here.

A module may only write the file it owns. The judge may read the pool; it may
not write to it. results derives, it does not decide. Swap the judge and
nothing else changes shape.
"""

# ---------------------------------------------------------------- pool
# What the scrape observes. Normalised at ingest so the judge and the board
# never parse raw source text.
POOL_FIELDS = [
    "id",            # minted once, on first sight, never recomputed
    "title", "company", "url", "apply_url", "source",
    # the normalised view of a role
    "remote",        # True / False / None when the posting does not say
    "country",       # free text as posted, normalised where we can
    "location",      # the raw location string, kept for audit
    "salary",        # normalised range string, or None
    "years_xp",      # int or None
    "reports_to",    # str or None
    # provenance
    "posted", "updated", "first_seen", "first_run", "last_seen", "active",
    # evidence the judge reasons over - the pool MUST persist this or the
    # judge cannot be re-run from the pool alone
    "restrictions", "timezones", "workplace", "jdhash",
    # jd_text is bulk evidence and lives in data/jd.json, keyed by id
]

# ---------------------------------------------------------------- judge
# Two independent axes. A lane is a function of both, never of one.
#   role  - is this a role for him?          yes | no | unclear
#   place - can he take it, from Portugal?   remote | pt_onsite | no | unclear
ROLE_VERDICTS = ("yes", "no", "unclear")
PLACE_VERDICTS = ("remote", "pt_onsite", "no", "unclear")

VERDICT_FIELDS = ["role", "place", "lane", "cut", "why", "judged"]

# ---------------------------------------------------------------- lanes
# Open     both axes say yes: a role for him, that he can do remotely.
# Portugal a role for him, physically in Portugal, NOT remote.
# Unsure   neither axis says no, but at least one is not clear either.
# cut      either axis says no. Kept, never deleted, and always with a reason.
LANES = ("open", "portugal", "unsure")


def lane_for(role, place):
    """The whole lane policy, in one place, derived from two axes.

    Unsure is deliberately generous: it is not "we think probably not", it is
    "we cannot say it isn't". Only an explicit no cuts.
    """
    if role == "no" or place == "no":
        return None                      # cut
    if role == "yes" and place == "pt_onsite":
        return "portugal"
    if role == "yes" and place == "remote":
        return "open"
    return "unsure"


DEFAULT_VERDICT = {"role": "unclear", "place": "unclear", "lane": "unsure",
                   "cut": False, "why": [], "judged": False}
