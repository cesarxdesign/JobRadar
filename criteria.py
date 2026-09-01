"""The Judge's criteria. THE ONLY FILE THAT HOLDS AN OPINION.

Every rule is a small named function over one pool record, answering on ONE
axis, and abstaining whenever it has nothing to say:

    "yes"     positive evidence on this axis
    "no"      EXPLICIT negative evidence. this is what cuts.
    "unclear" it looked, and genuinely cannot tell
    None      abstain - not this rule's business

Resolution (see judge.py): an explicit `no` from any rule wins, because a cut
must always rest on evidence. Otherwise a `yes` carries. Silence is `unclear`,
never `no` - "we cannot say it isn't" is not the same as "it isn't".

Criteria are DEFINED NEXT. The registries below are intentionally empty: an
empty judge cuts nothing and calls everything unclear, so every scraped role
lands in Unsure and nothing is silently thrown away before the rules exist.
"""

ROLE_RULES = []
PLACE_RULES = []


def role_rule(name):
    def deco(fn):
        ROLE_RULES.append((name, fn))
        return fn
    return deco


def place_rule(name):
    def deco(fn):
        PLACE_RULES.append((name, fn))
        return fn
    return deco


# ---------------------------------------------------------------------------
# Role criteria - "is this a role for him?"
# e.g. @role_rule("has design")  ->  "no" when the title has no design in it
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Place criteria - "can he take it, from Portugal?"
# e.g. @place_rule("remote europe")  ->  "remote" evidence, or "no" for a
#      stated scope that excludes Portugal
# ---------------------------------------------------------------------------
