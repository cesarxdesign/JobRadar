# Source sweep — 2026-09-12

**56 sites vetted. 17 verified keepers.** A keeper = a working data path *and* at least three roles
posted on or after 12 August 2026 that match the criteria (product/UX design, senior+, and reachable
from Portugal: worldwide, Europe/EMEA, Portugal-remote, or Lisbon/Porto).

Nothing has been added to `data/sources.json`. This is the shortlist for you to approve.

---

## The 17

### 1. remoterocketship.com
`__NEXT_DATA__` on `/country/portugal/jobs/product-designer/` (52) and `/country/europe/...` (288).
Rows carry `created_at`, seniority flags, `locationCountries` and a direct ATS url. Page 1 only without their paid API.
1. Senior Product Designer — Bitsight — Remote Portugal — 09-09
2. Senior UI/UX Designer — Intermedia — Remote Portugal — 09-10
3. Senior Product Designer (EMEA) — WunderGraph — Remote EMEA — 08-20
4. Staff Product Designer — The Walrus — Europe remote — 08-14
5. Head of Design (AI Startup) — Social Discovery Group — Worldwide — 09-03

### 2. jobgether.com
HTML landings `/remote-jobs/portugal/product-designer` plus per-offer ld+json carrying `applicantLocationRequirements`. Two hops.
1. Senior Product Designer — Bitsight — Full Remote Portugal — 09-10
2. Senior Product Designer — CloudTalk — Full Remote Europe — 09-03
3. Senior Product Designer, Credit & Cards — Finom — Full Remote Europe — 09-01
4. Senior Product Designer — SimpleStudy — Full Remote EU — 08-21
5. Senior Product Design Engineer — DuckDuckGo — list includes Portugal — 08-19

### 3. jobs.workable.com
`GET /api/v1/jobs?query=product%20designer&workplace=remote&day_range=30` (+ `location=Portugal`,
`nextPageToken`). Unions every Workable customer. Returns created/updated, workplace, locations, description.
1. Senior Visual & UI Designer (0-to-1, stealth) EU — Pack.com — Remote Portugal — 09-04
2. Senior Product Designer — CloudTalk — Remote Europe — 09-03
3. Lead UI/UX Designer, Mobile F2P — UserWise — Remote Portugal — 09-08
4. Director, Product Design — Velsera — Europe remote — 08-25

### 4. uiuxjobsboard.com
HTML cards `/design-jobs/<remote-europe|remote-emea|remote-anywhere|portugal>?page=N`, 100/page, ld+json `datePosted` on job pages.
1. Product Designer — BetterMe — Anywhere — 09-07
2. Product Designer — Acclaim — Remote Europe — 09-07
3. Senior Product Designer — WunderGraph — Remote EMEA — 08-27
4. Senior UX Designer — iCapital — Lisbon onsite — 08-29
5. Product Design Lead — TradingSpace — Anywhere — 08-27

### 5. simplyhired.pt  *(Indeed PT's index under another brand)*
`__NEXT_DATA__` on `/search?q="product+designer"&s=d&t=30` (date sort, 30-day filter, cursor paging); job pages carry ld+json.
1. Senior Product Designer — Bitsight — Lisbon / remote — 09-09
2. Senior UI/UX Designer — IT Labs — Remote, EU member country — 09-08
3. Senior Product Designer — UpHill — Lisbon hybrid — 09-01
4. Product Designer — Leadzai — Remote Leiria — 08-30
5. Senior Product Designer (Wallets) — Tether — 100% remote worldwide — 08-21

### 6. remote.io
`GET /api/v2/jobs?category=design&limit=100&page=N` — `publishedAt`, `locationType`, `region`, `locations[]`, `applicationUrl`.
Region tag is unreliable; verify at the ATS.
1. Lead UI/UX Designer, Mobile F2P — UserWise — incl. Portugal — 09-08
2. Senior Product Designer — Medallion — Remote, no restriction — 09-03
3. Lead UX Designer EMEA (contract) — Fueled — Remote EMEA — 08-29

### 7. uxremotetalent.com
Server-rendered Webflow cards `/?c0af7a1a_page=N`, 25/page; each card carries title, scope label, contract type, company, date. Filter out the OpenTrain AI-training spam.
1. Senior Product Designer — Miaplaza — EMEA within ~2h of CET — 09-09
2. Product Designer — BetterMe — Anywhere in the World — 09-08
3. UI Product Designer — Proton — Europe Only — 08-31
4. Product Designer — Virtusan — Europe Only — 09-02
5. UI/UX Designer — Codekeeper — Anywhere — 09-09

### 8. djinni.co
Three RSS feeds: `/jobs/rss/?primary_keyword=Product%20Design` (also `UI%20UX`, `Design`).
Use the "Published" date, not the bumped `datePosted`. Filter out "Ukrainian Native" postings.
1. Product Designer — Bewort — Full Remote, Europe or Ukraine — 09-10
2. Product Designer — Wildix — Full Remote, Europe or Ukraine — 09-08
3. Product Designer — EXITEK — Full Remote, Europe or Ukraine — 09-07
4. Product Design (Middle+/Senior) — FCE Global — Worldwide — 08-20
5. Freelance Senior Product Designer (3D configurator) — 3D Source — Worldwide — 08-20

### 9. remotefirstjobs.com  *(jobscollider.com redirects here — rebrand)*
`GET /jobs/design?p=N`, 20/page, deep paging; `p=0` relevance, `p>=1` reverse-chronological. Exact `<time datetime>` per card.
**Caveat:** a missing country badge means *unknown*, not worldwide — the detail page then emits a fabricated 173-country list. Ignore that field.
1. Senior Product Designer, Mobile — Hostaway — must be within EMEA — 09-02
2. Senior Product Designer — Sweed — 100% remote, core hours CET — 09-09
3. Product Designer (Figma) — Codekeeper — Remote, unrestricted — 09-03

### 10. weloveproduct.co
`GET /api/jobs/filters/product-designer-jobs-remote-europe?page=0` — 20 rows with `published_at`, `remote_scope`, `remote_regions`, `seniority`, `url_apply`. Page 2+ and detail pages are paywalled; the free first page is enough.
1. Senior Product Designer, Credit & Cards — Finom — Remote Europe — 08-31
2. Senior Product Designer — EverAI — Europe remote — 08-27
3. Product Designer — Acclaim — Fully remote across Europe — 09-03

### 11. realworkfromanywhere.com
RSS `/remote-design-jobs/rss.xml` + ld+json on job pages (184-country list including PT). Worldwide-remote by construction.
1. Staff Product Designer — Instrumentl — Anywhere — 09-02
2. Lead Product Designer — Circle — Anywhere — 08-26
3. Lead Product Designer, Marketplace — Circle — Anywhere — 08-26
4. Senior Product Design Engineer — DuckDuckGo — Anywhere — 08-19

### 12. remote.com/jobs
Next.js flight payload on `/jobs/all?query=<term>&page=N` — `jobsData.jobs[]` with `publishedAt`, `seniority`, `hiringLocation` country lists. Remote's own ATS, not a relay.
1. Senior Product Designer, Credit & Cards — Finom — Europe only — 09-02
2. Senior Product Designer, Growth & Activation — Finom — Europe only — 08-25
3. Senior Product Designer — eMoney Advisor — Anywhere — 09-03

### 13. startup.jobs
Algolia index `Post_production` (app 4CQMTMMK73). **The search key rotates roughly every 3 hours** — harvest it from the 404 page's meta tags each run. Filters: `published_at_i`, `workplace_type_id:remote`, `_tags` Design/Senior. Job pages are Cloudflare-walled, so verify scope at the ATS.
1. Senior Product Designer (Wallets) — Tether — Worldwide — 08-21
2. Senior Product Designer, Mobile — Hostaway — EMEA incl. PT — 09-02
3. Senior Product Design Engineer — DuckDuckGo — Anywhere — 08-19

### 14. woodyjobs.com  *(overlaps remote.io heavily)*
RSS `/rss.xml` (100 latest, with category, seniority, workmode, pubDate) + job-page ld+json with the full `applicantLocationRequirements`.
1. Lead UI/UX Designer, Mobile F2P — UserWise — incl. Portugal — 09-10
2. Senior Product Designer — Palta — Remote Europe incl. PT — 08-29
3. Product Designer — Scarlet — Remote Europe incl. PT — 08-19

### 15. pt.talent.com
HTML cards + ld+json on `/jobs?k=product+designer&l=Portugal&remote=1`, 15/page. Aggregator; its dates are refresh dates, so verify at source.
1. Senior Product Designer (Wallets) — Tether — Worldwide — 09-11
2. Senior Product Designer — Ovyo — Portugal, Poland, Spain, Hungary — 09-10
3. Senior UX/Product Designer — Alpineo — Lisbon — 09-11
4. Lead UI/UX Designer, Mobile F2P — UserWise — 100% remote PT — 09-11
5. UX/UI Product Designer (temporary) — Noesis — Porto — 09-10

### 16. dynamitejobs.com
SSR skill page `/skill/remote-product-design-jobs` — 20 newest; the full list is client-side Firestore. Curated, direct employer posts.
1. Head of Design — Hospitable — Remote NA/Europe — 09-11
2. Senior Product Designer — CloudTalk — Fully remote Europe — 09-05
3. Product Designer — Resend — 100% remote, unrestricted — 08-26
4. Senior Product Designer — Paddle — Remote or hub — 09-01

### 17. net-empregos.com
HTML cards `/pesquisa-empregos.asp?categoria=22&page=N`, 18/page, ~350 design ads, dates `d-m-yyyy`. Word-OR search, so filter titles locally. Direct employer and agency ads. *(Third match is borderline on seniority.)*
1. Product Designer (Mid/Senior) SaaS — Janela Digital — Leiria — 09-10
2. UX/UI Product Designer (temporary) — Noesis — Porto — 09-09
3. Designer UX (complex systems, 5+ yrs) — Techframe — Abrantes hybrid — 08-22

---

## Why 17 and not 20

The last five batches — 30 sites — returned **zero** keepers between them. Not for lack of trying;
the market for this profile is simply narrower than the question assumed.

Veins proven empty: generic remote aggregators, recruitment agencies, ATS-wide search,
crypto/web3/AI/gaming verticals, and design-community platforms.

One structural finding: **Pallet has exited the job-board business.** Its whole deployment —
including `api.pallet.xyz` — is disabled behind an HTTP 402. That killed UX Collective's board,
Lenny's, Design Club, Design Systems and the rest in one go. A meaningful slice of the
design-specific vein that produced the early keepers no longer exists.

I can pad to 20 with sources that have one or two matches each (Jobicy, Himalayas, escapethecity,
tryremotely, the VC portfolio boards). I'd rather not: they'd cost pool time and judge tokens for
almost no new roles, and two of them have dates that can't be trusted.

## Near-misses, if you want the number anyway

| source | matches | the catch |
|---|---|---|
| jobicy.com | 1 | best location field anywhere ("Bulgaria, Cyprus, Poland, Portugal, Serbia"), but dates are reposts inflated by 2–15 months |
| himalayas.app | 0 | structured per-country restrictions and real `pubDate`; 429s after ~20 requests; nothing in the sample window |
| tryremotely.com | 1 | great plumbing, but its "Worldwide" tag was wrong in 7 of 8 ATS checks |
| escapethecity.org | 2 | richest records in the sweep, attached to a London-centric board of 19 design roles |
| web3.career | 1 | real dates, thin design inventory |
| cryptocurrencyjobs.co | 2 | fine, just small |
| VC boards (Index, Northzone, a16z) | 0–2 each | clean Getro/Consider APIs, hundreds of companies, almost no fresh design |

## Two tricks worth stealing

- **michaelpage.pt** encodes the posting month in every job URL (`/ref/jn-092026-<id>`) — freshness with
  no detail fetch. Their design shelf is empty, but the pattern is the cleanest I saw.
- Every aggregator in this sweep over-claims in the same direction: when a feed doesn't know the
  restriction, it renders **"Worldwide"** rather than "unknown". If any of these get wired in, the judge
  should treat worldwide/anywhere as *unverified* rather than as a pass, or the Portugal filter will
  wave through a stream of US-only roles.
