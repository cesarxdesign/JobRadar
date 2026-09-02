"""The Judge's criteria. THE ONLY FILE THAT HOLDS AN OPINION.

Two layers:
  L1  cheap, title-only, runs over the whole pool. Cuts are silent and final,
      so it only cuts where the title alone is definitive.
  L2  Claude reads the JD holding these criteria and returns the verdict.

Edit this file to change what the radar looks for. Nothing else changes.
A verdict is frozen when it is made and stamped with VERSION, so changing
criteria affects roles judged afterwards, not roles already judged.
"""

VERSION = "2026-09-02.7"

# ---------------------------------------------------------------- L1
# Title only. Every cut is logged with the rule that fired.
L1_MUST_HAVE = r"\b(design|designer|ux)\b|(?:^| )ui(?: |$)|ui/ux|ux/ui"
L1_EXCLUDE = (r"\b(brand|marketing|graphic|motion|research|researcher|"
              r"web ?designer|visual ?designer)\b")
# ...unless the role is design leadership. A Head of Design or Design Director
# oversees brand, graphic and research rather than doing them, so those words
# stop being a reason to cut. "Lead" does NOT qualify - a Design Lead is still
# an IC-scope title.
# The leadership word must attach to design itself.
L1_LEADERSHIP = (r"\b(?:head of|director(?: of|,)?)\s+(?:[a-z]{0,12}\s+)?"
                 r"(?:design|ui|ux|product design)\b"
                 r"|\b(?:design|ui|ux|product design)\s+director\b")
# ...but "Art Director" and "Creative Director" are brand titles, not design
# leadership. Checked separately: as a lookahead inside L1_LEADERSHIP the regex
# engine simply retried at a later position and matched anyway.
L1_NOT_LEADERSHIP = r"\b(?:art|creative)\s+director\b"

L1_JUNIOR = (r"\b(junior|jr\.?|intern|internship|trainee|graduate|new grad|"
             r"entry[- ]level|apprentice|working student|werkstudent|placement|co[- ]?op)\b")

# ---------------------------------------------------------------- L2
# Handed to Claude verbatim. Written as instructions to a reader, not as rules
# for a machine, because a reader is what is on the other end.
L2_CRITERIA = """
BEFORE ANYTHING ELSE, LOOK AT WHAT LANGUAGE THE POSTING IS WRITTEN IN.
Read the words on the page. If the description is written in any language
other than English or Portuguese - German, French, Spanish, Dutch, Italian,
Polish, anything - stop there. Do not judge the role. Do not judge the place.
Return cut, role_verdict "no", reason "posting is written in <language>".
A German posting is a cut even when its location says Portugal.

READ THE WHOLE PAGE FIRST. THE SIDE PANEL IS PART OF THE POSTING.
You are given the posting as it renders: the title block, then the side panel
(Location, Location Type, Employment Type, Compensation, Department), then the
description. All of it is the posting. The side panel is where the location
usually lives. Read it before you read the description, and read the
description to the end - a statement further down can widen what the panel
says.

Then answer two independent questions about Cesar, a senior product designer
who lives in Portugal and works from home.


AXIS 1 - ROLE. Is this a role for him?
  YES  anything genuinely design: product design, UX, UI, design systems,
       design leadership (head, director, manager of design).
  YES  engineering roles that lean design - Design Engineer, UI/UX Engineer,
       Design Technologist. He judges the balance himself; let them through.
  NO   the posting is really brand, marketing, graphic design, motion, logos,
       campaigns, or user research as its own discipline.
       EXCEPT at Head of / Director of Design level, where he oversees those
       disciplines rather than doing them.
  NO   pure front-end engineering, even when the description talks about UI
       and UX. That job leans on code.


AXIS 2 - PLACE. Can he do this job while living in Portugal?

  REMOTE     the posting says remote and the scope includes Portugal.
             PORTUGAL IS IN EUROPE AND IN THE EU. So every one of these
             includes Portugal and is REMOTE - the posting does not need to
             name Portugal separately:
               "Remote - Europe"   "EU remote"   "European Union"   "EMEA"
               "Remote (Europe)"   "Worldwide"   "Global"   "Anywhere"
               "International"     "Remote - EMEA"
             Also REMOTE: a country list that contains Portugal, and remote
             with NO location specified at all (nothing restricts it).
  PT_ONSITE  hybrid or onsite, stated specifically in Portugal.
  NO         everything else.

  Remote must be clearly stated - but the company saying how IT works counts.
  These ARE evidence that the job is remote:
    "we are a fully remote company"   "remote-only team"   "remote-first"
    "we hire from 30+ countries"      "distributed team"
  These are NOT evidence, because they say where a company has people, not
  where it will hire:
    "we are a global company"         "offices in Lisbon and San Francisco"
    "teams in London, Boston and New York"
    where the company was founded
  A company that states it is fully remote hires remotely. A company that
  merely has offices in several places does not.

  A city or country named, with no clear remote mention, means the job is
  onsite in that location.

  All hybrid and onsite roles are cut immediately unless they are in Portugal,
  or unless remote-from-Portugal is also clearly stated.

  Remote tied to a city - "Remote-NYC", "Paris - Full Remote" - is remote in
  that city. Do not widen it to the whole country, and do not widen it to
  Europe, unless the posting says so.

  SPAIN IS THE ONE EXCEPTION, because Spain borders Portugal.
    Remote-Spain and the company is Spanish        -> NO. They mean Spain.
    Remote-Spain and the company is based elsewhere -> UNCLEAR, never NO.
    You cannot tell where the company is based      -> UNCLEAR.
    Work it out from the posting - headquarters, offices, the entity named.
    Spain only. France, Germany and Italy stay NO.

  UNCLEAR when you genuinely cannot tell. Do not guess NO.


BE GENEROUS ABOUT THE ROLE. BE EXACT ABOUT THE PLACE.
  ROLE - when you cannot tell what kind of job it is, pass it. Better he
  rejects it in two seconds than never sees it.
  PLACE - do not be generous. Where a job can be done is stated, not inferred.
  Take the answer the posting gives, including NO. If you are about to write
  "the location says X, but the company...", stop. The location said X.


IF THERE IS NO JOB DESCRIPTION
  Judge the ROLE from the title. Set PLACE to unclear - a missing description
  is not evidence about location. Never cut on place with no description.
"""

L2_FIELDS = """
Extract these fields from the posting. They live on the role afterwards, so
they matter as much as the verdict.

  role          the job title as stated
  company       the hiring company (not the ATS, not the agency)
  seniority     junior | mid | senior | staff | principal | lead | head |
                director | vp | unstated
  remote        remote | hybrid | onsite | unstated
  onsite_days   integer if the posting says "3 days a week in the office", else null
  countries     list of countries/regions the role can be done from, as stated.
                [] if the posting does not say.
  portugal_ok   yes | no | unclear - can someone living in Portugal hold it
  salary        as stated, e.g. "EUR 70-90k". null if not stated - MOST
                postings do not state it, and null is the correct answer.
  years_xp      integer minimum if stated, else null. "Senior" is NOT a number;
                do not convert it into one.
  reports_to    the role it reports to, if stated. null otherwise.
  language      the language the posting is written in

Salary, years_xp, onsite_days and reports_to are usually absent. Returning
null is correct and expected. Never invent a value to fill a field. For
remote and portugal_ok, do give an answer where the evidence supports one -
a posting that never mentions remote work and names an office is onsite, and
you should say so, but mark it inferred.
"""

L2_OUTPUT = """
Return ONE JSON object and nothing else. No prose, no code fence.

{
  "role_verdict": "yes" | "no" | "unclear",
  "place_verdict": "remote" | "pt_onsite" | "no" | "unclear",
  "cut": true | false,
  "reason": "one short sentence - what decided it",
  "confidence": "high" | "medium" | "low",
  "inferred": ["names of fields you inferred rather than read"],
  "fields": {
    "role": "...", "company": "...", "seniority": "...",
    "remote": "...", "onsite_days": null, "countries": [],
    "portugal_ok": "...", "salary": null, "years_xp": null,
    "reports_to": null, "language": "..."
  }
}

cut is true when role_verdict is "no" OR place_verdict is "no" OR the
language is neither English nor Portuguese. Otherwise cut is false.
"""


def lane_for(role_verdict, place_verdict):
    """The lane policy, derived from the two axes. Kept here so the criteria
    and the routing they imply live in the same file."""
    if role_verdict == "no" or place_verdict == "no":
        return None                       # cut
    if role_verdict == "yes" and place_verdict == "pt_onsite":
        return "portugal"
    if role_verdict == "yes" and place_verdict == "remote":
        return "open"
    return "unsure"
