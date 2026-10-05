"""The Judge's criteria. THE ONLY FILE THAT HOLDS AN OPINION.

Two layers:
  the parser  cheap, title-only, runs over the whole pool. Cuts are silent and final,
      so it only cuts where the title alone is definitive.
  the judge  Claude reads the JD holding these criteria and returns the verdict.

Edit this file to change what the radar looks for. Nothing else changes.
A verdict is frozen when it is made and stamped with VERSION, so changing
criteria affects roles judged afterwards, not roles already judged.
"""

VERSION = "2026-10-05.3"

# ---------------------------------------------------------------- the parser
# Title only. Every cut is logged with the rule that fired.
PARSE_MUST_HAVE = r"\b(design|designer|ux)\b|(?:^| )ui(?: |$)|ui/ux|ux/ui"
PARSE_EXCLUDE = (r"\b(brand|marketing|graphics?|motion|research|researcher|"
              r"web ?designer|visual ?designer|"
              # 2026-10-05, his call on the Not read lane: "whatever roles can
              # be cut on title, cut". Titles that are plainly another trade.
              # "Front-End Design Engineer" is NOT here: it leans design.
              r"social media|animator|animation|draftsman|drafter|storyboard|"
              r"presentation designer|interior|fashion|packaging|"
              r"compensation design|email ?/ ?sms|"
              r"(?:security|hardware|rf|mechanical|electrical|pcb|asic|fpga|circuit|structural|civil|"
              r"physical|analog|silicon|chip|verification) (?:[a-z/&-]+ ){0,3}(?:design )?engineer)\b")
# ...unless the role is design leadership. A Head of Design or Design Director
# oversees brand, graphic and research rather than doing them, so those words
# stop being a reason to cut. "Lead" does NOT qualify - a Design Lead is still
# an IC-scope title.
# The leadership word must attach to design itself.
PARSE_LEADERSHIP = (r"\b(?:head of|director(?: of|,)?)\s+(?:[a-z]{0,12}\s+)?"
                 r"(?:design|ui|ux|product design)\b"
                 r"|\b(?:design|ui|ux|product design)\s+director\b")
# ...but "Art Director" and "Creative Director" are brand titles, not design
# leadership. Checked separately: as a lookahead inside PARSE_LEADERSHIP the regex
# engine simply retried at a later position and matched anyway.
PARSE_NOT_LEADERSHIP = r"\b(?:art|creative)\s+director\b"

PARSE_JUNIOR = (r"\b(junior|jr\.?|intern|internship|trainee|graduate|new grad|"
             r"entry[- ]level|apprentice|working student|werkstudent|placement|co[- ]?op)\b")

# ---------------------------------------------------------------- the judge
# Handed to Claude verbatim. Written as instructions to a reader, not as rules
# for a machine, because a reader is what is on the other end.
JUDGE_CRITERIA = """
BEFORE ANYTHING ELSE, LOOK AT WHAT LANGUAGE THE POSTING IS WRITTEN IN.
Read the words in the description. English or Portuguese, carry on. Any
other language - German, French, Spanish, Dutch, Italian, Polish - is a cut,
whatever the location says. It is the first field you answer, below.

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
       The TITLE has to say design, UX or UI. An engineer's title that leans
       the other way - "Frontend Engineer", "Frontend Leaning Engineer",
       "Creative Developer", "Product Engineer" - is engineering: NO, however
       much design the description talks about.
  NO   the posting is really brand, marketing, graphic design, motion, logos,
       campaigns, or user research as its own discipline.
       EXCEPT at Head of / Director of Design level, where he oversees those
       disciplines rather than doing them.
       BRAND, EXACTLY (his words, 2026-10-04):
         "Brand" in the TITLE - Brand Designer, Brand & Marketing Designer -
         leans too far: NO.
         A product, UX or UI design role whose description piles brand work
         on top (landing pages, campaigns, marketing assets as well as the
         product) is still a design role for him: YES.
         A brand or marketing role that does a little product design on the
         side is NO. Ask which one the job is mostly, not whether brand is
         mentioned.
  NO   the role is UNPAID, or it is an INTERNSHIP. Either one, whatever the
       title says and however senior it sounds ("unpaid", "volunteer",
       "no compensation", "intern", "internship"). His words: those two are
       cut reasons.
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

  THE LINE UNDER THE TITLE, AND "BASED IN", ARE THE PLACE OF THIS POSTING.
  Hiring systems print the location right under the job title - "US",
  "Germany", "France", "London" - and agencies open with "our partner is
  looking for a Senior Product Designer based in Germany". That is the first
  thing a person sees and it is where THIS posting is. The same job is often
  posted once per country; each copy is for its own country.
    It names one country or city that is not Portugal, and nothing on the
    page clearly widens it                                    -> NO.
    It names one country or city that is not Portugal, and further down
    the page says something wider - "eligible European locations",
    "authorized to work in the US, Canada, LATAM or Europe", "salary
    adjusted for Europe", "EMEA" -                            -> UNCLEAR.
    The page contradicts itself. He reads it and decides. It is NEVER
    remote/yes: wider words lower down do not erase the country at the top.
  Only when the line under the title is itself wide - Europe, EMEA,
  Worldwide, Anywhere, Remote with no country, or a list that contains
  Portugal - can the answer be yes.

  THE WHOLE RULE, IN HIS WORDS (2026-10-04). The place passes only when the
  posting names Portugal, or casts a blanket that includes Portugal by
  definition - EMEA, Europe, EU, Worldwide, Anywhere, "all countries that
  start with P". Anything else is NO. SPAIN IS NO, like Germany and France:
  there is no exception for it any more.
  A SPECIFIC REQUEST FOR CANDIDATES BASED IN A PLACE - "based in Spain",
  "must be located in the UK", "candidates in Germany" - beats the generic
  paragraph pasted at the bottom of every posting ("we hire globally", "we
  are a remote-first company", "eligible European locations"). List both
  statements. The specific one decides; the generic one never makes it yes.

  WORKING HOURS ARE NOT A PLACE. "Must overlap with US Eastern hours",
  "within CET to ET timezones", "available 9am-3pm Pacific" say when he
  works, not where he may live. He will work any hours. Never answer NO on
  hours or timezone alone - judge the place from where the posting says a
  person may live or be hired.

  THE RIGHT TO WORK IS A PLACE. "Must be authorized to work in the United
  States", "US work authorization required", "must have the right to work in
  the UK", "no visa sponsorship" beside a single country: that is NO. He has
  the right to work in Portugal and the EU, nowhere else.

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

JUDGE_FIELDS = """
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

JUDGE_OUTPUT = """
Return ONE JSON object and nothing else. No prose, no code fence.

{
  "language_of_the_posting": "the language the DESCRIPTION is written in",
  "language_ok": true | false,
  "workplace_as_posted": "remote" | "hybrid" | "onsite" | "not stated",
  "can_he_do_it_from_portugal": "yes" | "no" | "unclear",
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

Answer language_of_the_posting FIRST, from the words in the description.
language_ok is true only for English or Portuguese. When it is false, cut
MUST be true, role_verdict MUST be "no", and reason MUST be "posting is
written in <language>". Nothing else overrides that - not the location, not
the role. Stated as prose above, this rule was read and ignored: the model
named the language correctly in its fields and passed a German posting to
Open anyway. It is a field it must answer before it judges anything.

Answer workplace_as_posted and can_he_do_it_from_portugal BEFORE
place_verdict, and then let them decide it:
  can_he_do_it_from_portugal "no"      -> place_verdict MUST be "no"
  "yes" and workplace_as_posted remote -> place_verdict "remote"
  "yes" and hybrid or onsite in Portugal -> place_verdict "pt_onsite"
  "unclear"                            -> place_verdict "unclear"
A hybrid or onsite job anywhere but Portugal is "no", however good the role.
The model has answered hybrid in Vienna, Portugal no, and then written
place_verdict "remote" in the same reply. The two questions above are the
answer; place_verdict only records it.

Otherwise cut is true when role_verdict is "no" OR place_verdict is "no".
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


# ---------------------------------------------------------------- the vision pass
# What vision.py tells the reader before the criteria above. The reader is no
# longer handed fields pasted together: it is handed the page, every word a
# browser put on screen, and has to find the posting in it.
VISION_HEAD = """
You are reading ONE web page: a job posting, loaded in a real browser. Below
is every word visible on that page, top to bottom, exactly as a person would
see it - the site's menus, banners, cookie notices, ads, the posting itself,
the footer, and often a list of OTHER jobs. Read all of it.

The posting is the main content of the page. Menus and "related jobs" are not
the posting: a location or a title in a list of other jobs says nothing about
this job. But a banner or a line about THIS job - "this role is no longer
available", "applications closed", "US only", "Germany only" - is the posting
speaking, wherever on the page it sits, and it outranks any tag.

FIRST QUESTION, BEFORE ANYTHING ELSE: IS THIS POSTING STILL OPEN?
  no          the page says so in words: no longer available, closed, filled,
              archived, expired, job not found, no longer accepting
              applications.
  unreadable  the page is not a job posting at all: an error, a login wall,
              a "checking your browser" page, an empty shell, a list of jobs
              with no single posting.
  yes         otherwise. An old date is NOT closed. Never answer "no" because
              a posting looks old - only because the page says it is closed.
"""

VISION_OUTPUT = """
Return ONE JSON object and nothing else. No prose, no code fence.

{
  "same_job": "yes" | "no",
  "posted_by": "employer" | "agency",
  "hiring_for": "the company the job is actually at, when an agency names it; else null",
  "posting_open": "yes" | "no" | "unreadable",
  "open_quote": "the exact words on the page that say it is closed or unreadable, else null",
  "language_of_the_posting": "the language the DESCRIPTION is written in",
  "language_ok": true | false,
  "workplace_as_posted": "remote" | "hybrid" | "onsite" | "not stated",
  "location_under_the_title": "the location the page prints beside or under the job title, and any 'based in ...' line, copied exactly; null if there is none",
  "place_signals": [
    {"quote": "the exact words, copied from the page",
     "where": "under the title" | "opening paragraph" | "body" | "side panel" | "footer or small print",
     "says": "portugal_in" | "portugal_out" | "says_nothing"}
  ],
  "can_he_do_it_from_portugal": "yes" | "no" | "unclear",
  "place_quote": "the exact words on the page that decided the place, copied, under 30 words",
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
    "reports_to": null, "language": "...", "posted": null
  }
}

posted_by is "agency" when the posting is put up by someone other than the
company the job is at: a recruiter, a staffing or consulting firm placing
people with clients, a talent marketplace, or a site that lists roles "on
behalf of a partner company" or "for our client". "employer" otherwise.

same_job: you are told which role the pool lists. "no" only when the page
is plainly a posting for a DIFFERENT job (another title, another company) or
an advert for something else. A longer or shorter wording of the same title
is the same job.

fields.posted is the date the page itself prints for this posting, as written
("January 26", "3 weeks ago"), or null.

When posting_open is "no" or "unreadable", still fill what you can and set
the verdicts to "unclear"; the page being closed is the whole answer.

language_ok is true only for English or Portuguese. When it is false, cut MUST
be true, role_verdict MUST be "no", and reason MUST be "posting is written in
<language>".

place_signals is the heart of this. List EVERY statement on the page about
where the person must live, be based, be located, be eligible, be authorized
to work, or come to an office. Do not stop at the first one. Do not pick the
one you believe. Go through the whole page - the line under the title, the
opening paragraph, the body, the requirements, the benefits, the side panel,
the small print at the bottom - and list each one separately, even when two
of them contradict each other. ESPECIALLY when they contradict each other.

A list of locations printed together - "United States; United Kingdom;
Portugal", "London / Lisbon / Remote" - is ONE statement, not one per place:
copy the whole list as one quote and judge the list (it contains Portugal,
or it does not).

For each one, taken ON ITS OWN, say what it means for a person living in
Portugal:
  portugal_out   a single country, state or city that is not in Portugal
                 ("US", "Germany", "based in France", "London");
                 a list of countries that does not contain Portugal;
                 a region that does not contain Portugal (North America,
                 LATAM, APAC, UK, DACH, Nordics);
                 Europe / EU / EMEA / worldwide WITH PORTUGAL EXCLUDED
                 ("Europe except Portugal", "anywhere but ...Portugal",
                 "not available in Portugal") - that is NOT Europe, it is
                 Portugal out;
                 the right to work in one such country;
                 hybrid or onsite at an office outside Portugal.
  portugal_in    Portugal, Lisbon, Porto or any place in Portugal named;
                 a list of countries that contains Portugal;
                 Europe, EU, EMEA, Worldwide, Global, Anywhere, with no
                 exclusion of Portugal attached to it.
  says_nothing   "remote" with no geography; working hours and timezones;
                 where the company has offices or was founded.
Then you may give your own place_verdict - but the lane is worked out from
this list, so the list has to be complete and each item honest on its own.

Answer location_under_the_title BEFORE can_he_do_it_from_portugal. When it
names a single country or city that is not Portugal, can_he_do_it_from_portugal
is "no", or "unclear" if the page says something wider further down. It is not
"yes".

place_quote must be words that are really on the page. Answer
workplace_as_posted and can_he_do_it_from_portugal BEFORE place_verdict, and
let them decide it:
  can_he_do_it_from_portugal "no"      -> place_verdict MUST be "no"
  "yes" and workplace_as_posted remote -> place_verdict "remote"
  "yes" and hybrid or onsite in Portugal -> place_verdict "pt_onsite"
  "unclear"                            -> place_verdict "unclear"
A hybrid or onsite job anywhere but Portugal is "no", however good the role.

Otherwise cut is true when role_verdict is "no" OR place_verdict is "no".
"""


TOP = ("under the title", "opening paragraph")


def top_line_out(signals):
    """Portugal is ruled out at the top of the page, and nothing at the top lets it back in."""
    signals = [s for s in signals or [] if isinstance(s, dict)]
    at = lambda says: any(s.get("says") == says and str(s.get("where") or "").lower() in TOP
                          for s in signals or [] if isinstance(s, dict))
    return at("portugal_out") and not at("portugal_in")


def place_from_signals(signals, workplace, model_place):
    """The place verdict, worked out here and not by the reader.

    The reader kept finding one sentence it liked and stopping: a posting
    headed "Germany" went to Open on "eligible European locations" further
    down. So the reader only lists what the page says, every statement, and
    the arithmetic is done where it cannot be talked out of it:

        out, and nothing in      -> no
        out AND in               -> it depends on WHERE each one is.
            out at the top of the page (the line under the title, the opening
            paragraph) and in only further down -> no. The top line is written
            for this posting - "based in France" on one copy, "based in
            Germany" on the next. The wider words lower down are the same
            paragraph pasted onto every role, and they do not change it.
            (His call, 2026-10-03, on the Jobgether copies.)
            anything else -> unclear. The page contradicts itself where it
            matters; he looks. Never Open.
        in, and nothing out      -> remote, or pt_onsite when it is an office
        nothing either way       -> remote only if the page says remote and
                                    the reader agrees; else unclear
    And Open needs the reader to agree: if it says anything but yes, unclear.
    """
    sig = [s for s in signals or [] if isinstance(s, dict)]
    says = [s.get("says") for s in sig]
    out, inn = "portugal_out" in says, "portugal_in" in says
    if out and inn:
        if top_line_out(sig):
            return "no", "the line at the top of the page says where; the wider words lower down are boilerplate"
        return "unclear", "the page says both: Portugal in, and Portugal out"
    if out:
        return "no", None
    onsite = (workplace or "").lower() in ("hybrid", "onsite")
    if inn:
        want = "pt_onsite" if onsite else "remote"
        if model_place == want:
            return want, None
        if model_place == "pt_onsite" or (model_place == "remote" and not onsite):
            return model_place, None
        return "unclear", "the page allows Portugal, but the reader did not say yes"
    if (workplace or "").lower() == "remote" and model_place == "remote":
        return "remote", None
    return "unclear", "the page does not say where"


# Intermediaries: recruiters, staffing firms, talent marketplaces and sites
# that post jobs "on behalf of a partner company". A role from one of these
# is not the employer's own posting - the same job is often listed once per
# country - so the board keeps them in their own lane, out of Open. The
# reader also says so per posting (posted_by); this list catches the ones
# read before it was asked, and the ones whose pages never admit it.
AGENCIES = (r"jobgether|jobs ?for ?humanity|micro1|crossover|toptal|proxify|turing\b|braintrust|mercor|"
            r"hirehire|onhires|good ?maven|nameless ?ventures|wave ?talent|just ?gabs|workfully|design ?jobs ?world|"
            r"lhh|adecco|randstad|manpower|michael ?page|hays\b|robert ?(half|walters)|kelly ?services|"
            r"vivid ?resourcing|g2 ?recruitment|plexus|signify ?tech|huntingcube|emagine|humanit\b|"
            r"crossing ?hurdles|remoterocketship|arc\.dev|\barc\b|flexhire|scaleup|rightfit|discovered ?mena|"
            r"spencer ?riley|workana|andela|bairesdev|x-?team|supportninja|"
            # not agencies, but they flood the boards with the same posting over and over (his call)
            r"codekeeper")


def is_agency(company, source="", posted_by=None):
    import re
    if posted_by == "agency":
        return True
    return bool(re.search(AGENCIES, f"{company or ''} {source or ''}", re.I))


# ---------------------------------------------------------------- one page of rules
# The reader's whole brief, rewritten 2026-10-04 so that every rule is said
# once. The text above (JUDGE_CRITERIA, JUDGE_FIELDS, VISION_OUTPUT) grew by
# accretion: the place rule was stated in five blocks that did not all agree
# ("-> UNCLEAR" in one, "the specific one decides" in another), and the reader
# was asked both to list what the page says and to decide the place, twice.
# It is kept because the old judge (read.py) still imports it.
#
# The split, and the reason there is one:
#     the reader REPORTS  - is it open, what language, what kind of job, and
#                           every statement the page makes about place
#     the code DECIDES    - lane_from_reading(), below. One function.
# A rule about how statements are weighed goes in the code and nowhere else.
VISION_RULES = """
You are reading ONE web page: a job posting, loaded in a real browser. Below
is every word visible on it, top to bottom - menus, banners, cookie notices,
the posting, the footer, often a list of OTHER jobs. Read all of it.

The posting is the main content. Menus and "related jobs" are not the posting.
But a line about THIS job - "this role is no longer available", "US only" -
is the posting speaking, wherever it sits on the page.

It is for Cesar: a senior product designer who lives in Portugal, works from
home, and has the right to work in Portugal and the EU. You report what the
page says. You do not decide whether he sees the job; that is worked out from
your answers, so each answer must be true on its own.

1. IS THE POSTING OPEN?
   no          the page says so: no longer available, closed, filled, expired,
               job not found, no longer accepting applications.
   unreadable  the page is not a single job posting: an error, a login wall,
               a "checking your browser" page, an empty shell, a list of jobs.
   yes         otherwise. An old date is not closed.

2. LANGUAGE the description is written in. English and Portuguese are fine.
   Any other language: language_ok is false.

3. ROLE. Is the job itself one he does?
   yes  product design, UX, UI, design systems;
        design leadership (head, director, manager of design), including one
        that oversees brand or research;
        engineering that leans design, when the TITLE says design, UX or UI
        (Design Engineer, UI/UX Engineer, Design Technologist).
   no   engineering by title (Frontend Engineer, Creative Developer, Product
        Engineer), however much design the description mentions;
        brand, marketing, graphic, motion or campaign design, or user research
        as a job of its own. "Brand" in the title is no. A product, UX or UI
        role with brand work piled on top is yes; a brand or marketing role
        with a little product design on the side is no - ask what the job
        mostly is;
        unpaid, volunteer, or an internship, whatever the title - but only
        when the page SAYS unpaid, volunteer or no salary. "Equity-based" or
        "equity" on its own is not unpaid.
   unclear  you cannot tell what kind of job it is. Never answer no on a guess.
   With no description, judge the role from the title alone.

4. PLACE. List what the page says; do not weigh it.
   workplace_as_posted: remote, hybrid, onsite, or not stated.
     A company saying how it works counts as remote: "fully remote company",
     "remote-first", "distributed team", "we hire from 30+ countries".
     Where a company has offices or was founded does not.
     A city or country named with no mention of remote is onsite there.
     When the posting offers a choice - an office for people nearby OR remote
     for everyone else - answer remote: he would take the remote option.

   place_signals: EVERY statement about where the person must live, be based,
   be eligible, be authorised to work, or come to an office. The line under
   the title, the opening paragraph, the body, the requirements, the benefits,
   the side panel, the small print: each statement separately, and above all
   when two contradict each other. Do not stop at the first, and do not pick
   the one you believe. A list printed together ("US; UK; Portugal") is ONE
   statement. For each, copy the exact words, say where it is, what kind of
   statement it is, and what it means ON ITS OWN for someone living in
   Portugal.
   kind - how much the statement commits to:
     explicit  REALLY explicit - it says where the person may or must be for
               THIS role: "candidates based in Germany", "Remote - France",
               "Remote (USA)", "remote from Spain", "hybrid, 3 days in our
               London office", "fully onsite at our Lisbon office", "work
               remotely from any European country", "must be authorised to
               work in the US". A place with remote, hybrid or onsite
               attached is explicit. So is a list of countries or regions
               the posting says the role is OPEN TO ("open to candidates in
               the UK, Germany and Spain"): whatever is not on the list is
               out, even if the page also says "we hire globally".
     tag       bare place names in a location field and nothing more, one
               or several: "Location: France", "Berlin", "United Kingdom /
               Stockholm, Sweden". They do not say office or remote, and may
               only be where the company has offices. When the word that
               sits with "remote" is something else - "Europe / Remote"
               under "United Kingdom" and "Stockholm" - the places are tags
               and "Europe / Remote" is the explicit statement.
     generic   company-wide text that is not about this role: "we hire
               globally", "we are a remote-first company", a benefits or
               equal-opportunity paragraph pasted onto every posting.
   says:
     portugal_in   Portugal, or a place in Portugal;
                   a list of countries that contains Portugal;
                   a blanket that contains Portugal by definition: Europe, EU,
                   EMEA, Worldwide, Global, Anywhere - with no exclusion.
     portugal_out  one country, state or city that is not in Portugal ("US",
                   "Spain", "based in Germany", "London"), with or without
                   "remote" beside it;
                   a list or a region that does not contain Portugal (North
                   America, LATAM, APAC, UK, DACH, Nordics);
                   a blanket with Portugal excluded ("Europe except Portugal");
                   the right to work in a country outside the EU, or in one
                   named country that is not Portugal;
                   hybrid or onsite at an office outside Portugal, when it is
                   required of EVERYONE in the role: office days at an office
                   that is not in Portugal are explicit and out.
     portugal_maybe  the answer depends on a list or policy the page does
                   not show: "fully remote from eligible countries" with a
                   link, "remote in select countries", "depending on
                   location". Do not guess whether Portugal is on it.
     says_nothing  office days that apply only to people who live near the
                   office, when the posting also offers a remote option
                   ("London hybrid or Europe remote", "Berlin or Remote" with
                   office days for the Berlin team): the office is one option,
                   not a requirement. List the remote option on its own, by
                   the geography it gives;
                   "remote" with no geography; working hours and time zones
                   (he works any hours); where the company has offices;
                   a preference, not a requirement ("NYC preferred", "ideally
                   based in EST"); a conditional ("if you are based in France
                   you get a French contract"); pay, contract or benefit
                   details for one country.

   place_verdict: your own reading in one word, used only when the list does
   not settle it.
     remote     the job is remote and nothing on the page restricts where
     pt_onsite  hybrid or onsite at an office in Portugal
     no         it cannot be done from Portugal
     unclear    you cannot tell. With no description, always unclear.

5. FIELDS, as the page states them. null when the page does not say - most
   postings give no salary, years or reporting line, and null is correct.
   Never invent a value. List in "inferred" any field you worked out rather
   than read.

Return ONE JSON object and nothing else. No prose, no code fence.

{
  "same_job": "yes" | "no",
  "posted_by": "employer" | "agency",
  "hiring_for": "the company the job is actually at, when an agency names it; else null",
  "posting_open": "yes" | "no" | "unreadable",
  "open_quote": "the exact words that say it is closed or unreadable, else null",
  "language_of_the_posting": "...",
  "language_ok": true | false,
  "role_verdict": "yes" | "no" | "unclear",
  "workplace_as_posted": "remote" | "hybrid" | "onsite" | "not stated",
  "location_under_the_title": "the location printed beside or under the job title, and any 'based in ...' line, copied exactly; else null",
  "place_signals": [
    {"quote": "the exact words, copied from the page",
     "where": "under the title" | "opening paragraph" | "body" | "side panel" | "footer or small print",
     "kind": "tag" | "explicit" | "generic",
     "says": "portugal_in" | "portugal_out" | "portugal_maybe" | "says_nothing"}
  ],
  "place_verdict": "remote" | "pt_onsite" | "no" | "unclear",
  "place_quote": "the words on the page that matter most for place, copied, under 30 words",
  "reason": "one short sentence - what decides it",
  "confidence": "high" | "medium" | "low",
  "inferred": [],
  "fields": {
    "role": "the title as stated", "company": "the hiring company, not the agency or hiring system",
    "seniority": "junior | mid | senior | staff | principal | lead | head | director | vp | unstated",
    "remote": "remote | hybrid | onsite | unstated", "onsite_days": null,
    "countries": [], "portugal_ok": "yes | no | unclear", "salary": null,
    "years_xp": null, "reports_to": null, "language": "...", "posted": null
  }
}

same_job is "no" only when the page is plainly a posting for a DIFFERENT job
or an advert for something else; a longer or shorter wording of the title is
the same job. posted_by is "agency" when someone other than the company the
job is at put it up: a recruiter, a staffing firm, a talent marketplace, a
site listing roles "for our client". fields.posted is the date the page
prints for this posting, as written. When the posting is not open, fill what
you can and answer the verdicts "unclear".
"""


def place_from_statements(signals, workplace, model_place):
    """The place, from the statements the reader listed. His rules, in order
    (2026-10-04). A statement is a tag (a bare place name: maybe only where
    the company sits), explicit (says where the person may or must be for
    this role), or generic (company-wide text pasted on every posting).

        A role is explicitly in, or explicitly out; those two are easy.
        explicit in, no explicit out      yes     Open (Portugal lane for an office in Portugal)
        explicit out, no explicit in      no      "based in Germany", "Remote - France", a list of
                                                  countries without Portugal - whatever generic
                                                  "we hire globally" text sits beside it
        explicit out AND explicit in      unclear the page contradicts itself; never Open
        Not explicit:
        just "remote", no geography       yes     nothing ties it anywhere: Open
        a tag, and explicit in            yes     "France" on top, "work remotely from any European
                                                  country" in the body: the tag is where the
                                                  company sits (pennylane)
        a tag, and only generic text      unclear "Location: France", then "we hire globally":
                                                  muddled, he sorts it
        a tag and nothing else            no      a place named and nothing widens it
        remote from "eligible countries"  unclear the list is not on the page; he checks it
        office days required of everyone, no      "if it requires office days and it is not in
        and the office is not in Portugal         Lisbon, it is a clear cut" - unless the office
                                                  is only for people near it and the role is
                                                  remote elsewhere: then the remote option is
                                                  what is judged (London hybrid OR Europe remote)
    """
    # Only a statement about THIS role counts ("or fully remote from eligible
    # countries"). "We're a global team spanning Europe and Australasia" is
    # company talk: it held Partly - Auckland, remote in New Zealand - in Unsure.
    maybe = any(isinstance(x, dict) and x.get("says") == "portugal_maybe" and x.get("kind") != "generic" for x in signals or [])
    sig = [x for x in signals or [] if isinstance(x, dict) and x.get("says") in ("portugal_in", "portugal_out")]
    if maybe and not any(x["says"] == "portugal_in" and x.get("kind") != "generic" for x in sig):
        # "fully remote from eligible countries", and the list is behind a link:
        # he checks it himself. "This is the easy unsure" (Bending Spoons).
        return "unclear", "remote from a list of countries the page does not show"
    kind = lambda x: x.get("kind") if x.get("kind") in ("tag", "explicit", "generic") else "explicit"
    has = lambda says, k: any(x["says"] == says and kind(x) == k for x in sig)
    out = any(x["says"] == "portugal_out" and kind(x) != "generic" for x in sig)
    if has("portugal_out", "explicit"):
        if has("portugal_in", "explicit"):
            return "unclear", "the page says both, explicitly: Portugal in, and Portugal out"
        return "no", None
    if has("portugal_out", "tag"):
        if has("portugal_in", "explicit"):
            place = model_place if model_place in ("remote", "pt_onsite") \
                else "pt_onsite" if (workplace or "").lower() in ("hybrid", "onsite") else "remote"
            return place, "the place named at the top is only a tag; the posting itself says Portugal is in"
        if has("portugal_in", "generic"):
            return "unclear", "a place is named, and only company-wide text suggests anywhere wider"
        return "no", None
    if not sig and (workplace or "").lower() == "remote":
        return "remote", None            # just "remote", no country or geography to tie it to: Open
    if (workplace or "").lower() in ("hybrid", "onsite") and not any(x["says"] == "portugal_in" for x in sig):
        return "no", "office days are required, and nothing on the page puts the office in Portugal"
    return place_from_signals([x for x in sig if x["says"] == "portugal_in"], workplace, model_place) if not out else ("no", None)


def lane_from_reading(a):
    """The lane, from what the reader reported. Every rule about weighing is
    here and in place_from_statements(), and nowhere else. Returns
    (lane, place, why): why is None unless the decision needs a sentence the
    reader did not write.

        not the same job, or unreadable   unsure  (results.py files these as Not read)
        the page says it is closed        closed
        not English or Portuguese         cut
        role no, or place no              cut
        role yes, place yes               open, or portugal for an office in Portugal
        anything unclear                  unsure
    """
    if a.get("same_job") == "no":
        return "unsure", None, "the page read is a different job"
    if a.get("posting_open") == "no":
        return "closed", None, None
    if a.get("posting_open") == "unreadable":
        return "unsure", None, None
    place, why = place_from_statements(a.get("place_signals"), a.get("workplace_as_posted"), a.get("place_verdict"))
    # An agency's posting opens with its client's requirement - "our partner
    # is looking for a Senior Product Designer based in Germany" - and the
    # rest is the agency's own text, the same on every posting ("remote
    # across EMEA"). The opening line decides. Without this 6 of 11 Jobgether
    # roles sat in Unsure; he has called them cuts twice.
    if a.get("posted_by") == "agency" and place != "no" and top_line_out(
            [x for x in a.get("place_signals") or [] if isinstance(x, dict) and x.get("kind") != "generic"]):
        place, why = "no", "an agency posting: the place its opening line names is the client's requirement"
    if a.get("language_ok") is False:
        return "cut", place, None
    return lane_for(a.get("role_verdict"), place) or "cut", place, why
