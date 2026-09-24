#!/usr/bin/env python3
"""Author + render a genuinely tuned CV per role, locally, to ~/Desktop/TCV/.
Each role's experience is ranked by relevance to THAT JD and sized XL/L/M/S,
so the most-relevant roles lead and expand and the rest compress. Content is
faithful to the master CV (every number/role traceable, no invention, no em
dashes). No Claude call: the tuner's own renderer makes the PDF."""
import sys, os, json, re, shutil
from pathlib import Path

TCV = "/Users/cgair/Claude/jobradar/tcv"
sys.path.insert(0, TCV); os.chdir(TCV)
import server  # noqa: E402

ROLES = json.load(open("/tmp/roles40.json"))
DEST = Path.home() / "Desktop" / "TCV"

# ---- per-role bullet variants (faithful to master_cv), + JD-match tags ------
V = {
 "confirmo": {"tags":["payment","checkout","merchant","crypto","stablecoin","subscription","conversion","funnel","commerce","transaction","design system","brand","b2b","saas","fintech"],
  "XL":"First designer at a crypto payments processor moving $750M a year. Owned the full product surface, buyer and merchant, plus brand and website, built the design system from scratch, and worked with the CPO to bring design to the front of product development. Audited a checkout stuck at 9% success, ran workshops and analysed usage to find the drop-off, then redesigned the flow: success reached 43% in key markets and 27% overall, adding $135M a year in converted payments without a single backend change. Launched Confirmo Subscriptions with Circle and Solana, the first recurring crypto payments product of its kind.",
  "L":"First designer at a crypto payments processor moving $750M a year. Owned the full buyer and merchant surface plus brand, built the design system from scratch, and moved design to the front of product with the CPO. Redesigned a checkout stuck at 9% success to 43% in key markets and 27% overall, adding $135M a year in converted payments with zero backend changes. Launched Confirmo Subscriptions with Circle and Solana, the first recurring crypto payments product of its kind.",
  "M":"First designer at a crypto payments processor moving $750M a year. Owned the full buyer and merchant surface and built the design system from scratch. Took checkout from 9% success to 27% overall and 43% in key markets, adding $135M a year in converted payments with zero backend changes.",
  "S":"First designer at a $750M-a-year crypto payments processor; took checkout from 9% to 27% success, adding $135M a year with zero backend changes."},
 "trustwallet": {"tags":["wallet","crypto","web3","self-custody","onboarding","blockchain","fiat","token","defi","mobile","consumer"],
  "XL":"Lead designer on Trust Wallet's Banking and Fiat squad, the bridge between traditional money and crypto, shipping to 200M+ users. Onboarding sat outside the squad and I argued it belonged to us, then took it on: rebuilt both the new-wallet and import flows through user research and iterative prototyping, and overhauled the fiat-to-crypto funding flow, cutting through serious technical complexity to deliver something users could actually understand and trust. Built on Binance's design framework, cross-functional with product, engineering and data throughout.",
  "L":"Lead designer on the Banking and Fiat squad, the bridge between traditional money and crypto, 200M+ users. Rebuilt the new-wallet and import flows and overhauled fiat-to-crypto funding, turning serious technical complexity into something users could trust. Built on Binance's design framework, cross-functional with product, engineering and data.",
  "M":"Lead designer on the Banking and Fiat squad at 200M+ user scale. Rebuilt new-wallet and import onboarding and overhauled the fiat-to-crypto funding flow, on Binance's design framework.",
  "S":"Lead designer, Banking and Fiat squad; rebuilt wallet onboarding and fiat funding at 200M+ user scale."},
 "blkbox": {"tags":["ai","machine learning","advertising","adtech","creative","marketing","generative","saas","enterprise"],
  "XL":"Lead designer at an AI creative-testing and production platform for advertisers. Ran a full UX audit and user interviews, and worked with the CTO to scope what engineering could actually ship. Contributed to a Super Bowl campaign producing AI ads across multiple markets, with the NFL as direct client.",
  "L":"Lead designer at an AI creative-testing platform for advertisers. Ran a full UX audit and user interviews, working with the CTO to scope what engineering could ship, including a Super Bowl campaign producing AI ads across markets with the NFL as direct client.",
  "M":"Lead designer at an AI creative-testing platform, including a Super Bowl campaign producing AI ads across markets with the NFL as direct client.",
  "S":"Lead designer at an AI creative-testing platform for advertisers; NFL as direct client on a Super Bowl AI campaign."},
 "mara": {"tags":["wallet","crypto","fiat","kyc","onboarding","emerging","africa","scale","leadership","product owner","fintech","head","lead","team","consumer","mobile"],
  "XL":"Led product design for a crypto and fiat digital wallet for African markets, with Coinbase as lead investor. Delivered a full end-to-end redesign of information architecture, user flows and UI in under a month, shipping to 24M users. Rebuilt onboarding from a 27-screen gauntlet down to eight, ending at three actions, and moved KYC to the point of need: completion went from 12% to 88%, adding 20M users and saving $6.9M a year. Then took on engineering and customer support alongside design, running three cross-functional teams across a live, high-scale product, and presented roadmap and growth strategy directly to investors.",
  "L":"Crypto and fiat wallet for African markets, Coinbase as lead investor. Ran three cross-functional teams across design, engineering and support, presenting strategy directly to investors. Full end-to-end redesign in under a month, shipping to 24M users. Rebuilt onboarding, moving KYC to the point of need: completion rose from 12% to 88%, adding 20M users and saving $6.9M a year.",
  "M":"Head of Design and Product Owner for a Coinbase-backed crypto and fiat wallet. Rebuilt onboarding, taking completion from 12% to 88%, adding 20M users and saving $6.9M a year. Ran three cross-functional teams across design, engineering and support.",
  "S":"Head of Design at a Coinbase-backed wallet; onboarding completion 12% to 88%, adding 20M users and saving $6.9M a year."},
 "cable": {"tags":["compliance","aml","financial crime","regtech","b2b","saas","banking","enterprise","fintech","risk","security","audit","dashboard","admin","platform"],
  "XL":"First designer at the only financial crime and AML compliance startup with a live product, a notoriously hard space to launch in. The product had been built request by request into an unfocused suite. Through structured research and systematic design I restructured the architecture around Paper Trail, the record of accounts, reviewers and decisions that was the real product, and shipped 10 features sequenced by engineering capacity rather than client demand. Turned reactive, client-driven builds into a coherent, UX-led B2B compliance suite that landed the product's first real sale; it went on to 50+ banks and fintechs, and was acquired by Synctera.",
  "L":"First designer at the only financial crime and AML compliance startup with a live product. Turned it from reactive, client-driven builds into a coherent, UX-led B2B compliance suite, restructured around Paper Trail, its real anchor, and shipped 10 features. Landed the product's first real sale; it went on to 50+ banks and fintechs, and was acquired by Synctera.",
  "M":"First designer at a financial crime and AML compliance startup. Restructured the product around its real anchor and shipped 10 features, turning free pilots into the product's first real sale.",
  "S":"Founding designer at a B2B AML compliance startup; turned free pilots into the product's first paid sale."},
 "penfold": {"tags":["pension","savings","consumer","fintech","mobile","design system","onboarding","b2c","retirement","0-1","founding"],
  "XL":"First hire, joining the co-founders and one developer to build the UK's best digital pension. Turned the proof of concept into a live app onboarding real customers in seven days, in time to matter for the funding round, then built a modular design system feeding mobile and desktop from a single component library, halving engineering work. I refocused the product on existing pension holders rather than first-time savers, driving 6x signups and £4M in first-year AUM. The foundation held: Penfold is now an award-winning app managing over £1B.",
  "L":"First hire, alongside the co-founders and one developer. Took the proof of concept to a live app onboarding real customers in seven days, in time for the funding round, then built a modular design system that halved engineering work. Refocused the product on existing pension holders, driving 6x signups and £4M first-year AUM.",
  "M":"First hire at a UK digital pension provider. Shipped a live app in seven days for the funding round, built the design system, and refocused the product on existing pension holders: 6x signups and £4M first-year AUM.",
  "S":"Founding designer at a UK digital pension; live app in seven days, 6x signups and £4M first-year AUM."},
 "starcount": {"tags":["data","analytics","intelligence","visualization","visualisation","dashboard","b2b","saas","enterprise","leadership","hiring","team","head","lead","research","map"],
  "XL":"Hired as the company's first product designer, grew the function into a five-person department on the strength of my own product work, with four designers reporting to me. Delivered a £1M first-year revenue target in 91 days across a suite that included two product lines launched from scratch and one revived. Its centrepiece: a groundbreaking audience-intelligence tool built with Twitter and Royal Mail, the first deal of its kind, covering 1.7M UK postcodes and 27M households, with discovery driven across data, engineering, sales and direct client interviews.",
  "L":"First product designer; grew the function to five on the strength of my own product work, with four designers reporting to me. Hit a £1M first-year revenue target in 91 days across two product lines launched from scratch and one revived, centred on an audience-intelligence tool built with Twitter and Royal Mail, the first data deal of its kind.",
  "M":"First product designer; grew design from one to five on the strength of my own product work, with four reporting to me. Hit a £1M first-year revenue target in 91 days, centred on an audience-intelligence tool built on Twitter and Royal Mail data.",
  "S":"First product designer; built and led a five-person design team, and hit a £1M first-year target in 91 days."},
 "done": {"tags":["consumer","mobile","ios","app","fitness","health","ai","engineering","0-1","founding","design to code"],
  "L":"Consumer fitness app, three versions in eight years. Led product strategy and UX/UI. Launched March 2020 to a 5.0 App Store rating within two months, just before global lockdown. Now building it solo, with AI covering the engineering that once took two people, for a 2026 relaunch.",
  "M":"Consumer fitness app. Led product strategy and UX/UI across three versions to a 5.0 App Store rating. Now rebuilding it solo, with AI covering the engineering that once took two people.",
  "S":"Consumer fitness app; product strategy and UX/UI across three versions, now rebuilt solo with AI."},
}

META = {  # title, company, qualifier, dates, DONE-flag
 "confirmo":("Product Design Lead","Confirmo","","Sep 2025 - Jul 2026"),
 "done":("Co-Founder","DONE","Self-employed","Mar 2018 - Mar 2020, May 2024 - Present"),
 "trustwallet":("Lead Product Designer","Trust Wallet","","Apr 2025 - Sep 2025"),
 "blkbox":("Lead Product Designer","BLKBOX.ai","","Mar 2024 - Mar 2025"),
 "mara":("Head of Design, Product Owner","Mara","","Nov 2022 - Feb 2024"),
 "cable":("Founding Designer","Cable","","Jul 2020 - Oct 2022"),
 "penfold":("Founding Designer","Penfold","","Jun 2019 - May 2020"),
 "starcount":("Head of Product Design","Starcount","","Dec 2015 - May 2019"),
}
CHRON = ["confirmo","done","trustwallet","blkbox","mara","cable","penfold","starcount"]  # reverse-chron, DONE 2nd
RECENCY = {k:i for i,k in enumerate(["confirmo","trustwallet","blkbox","mara","cable","penfold","starcount","done"])}
EARLIER = {"title":"Earlier","company":"","qualifier":"","dates":"2006 - 2015",
 "bullets":["Designer, Leo Burnett (Apple, Samsung, Mercedes, Vodafone; rebranded Lisbon's commuter rail); Software Engineer, Pfizer (CRM migration with Accenture across the UK and India)."]}
EDUCATION = [{"institution":"FLAG Design Academy","detail":"","dates":"2012 - 2013"},
             {"institution":"Instituto Superior Técnico","detail":"Computer Science","dates":"2003 - 2006"}]

SUMMARIES = {
 "ic":"Hands-on product designer at lead and staff scope, 10+ years leading design, 7 in fintech. Engineer by training: I design and ship with AI daily, concept through to code. First design hire at four companies, turning complex, messy journeys into products that are simple to use. Shipped to 200M+ users, and took a checkout stuck at 9% success to 27% overall with zero backend changes.",
 "lead":"Design leader, 10+ years leading design and 7 in fintech. First design hire at four companies, growing design from one person to a function, and has run design, engineering and support simultaneously across three cross-functional teams on a live product at 24M-user scale. Shipped to 200M+ users, and presented roadmap and growth strategy directly to investors.",
 "engineer":"Product designer and engineer by training: Computer Science degree, six years a professional software engineer, and I design and ship with AI daily, concept through to code. 10+ years leading design, 7 in fintech, working through technical constraints rather than around them. Shipped to 200M+ users, and took a checkout stuck at 9% success to 27% overall with zero backend changes.",
 "research":"Product designer with a deep discovery and research practice, 10+ years leading design, 7 in fintech. I run user interviews, usability testing and funnel analysis, then turn complex, messy journeys into products that are simple to use. Rebuilt an onboarding from 27 screens to eight, taking completion from 12% to 88%, and shipped to 200M+ users.",
 "growth":"Product designer focused on funnels and conversion, 10+ years leading design, 7 in fintech. I find where users drop off and fix it against live traffic: took a checkout from 9% to 27% success, adding $135M a year with zero backend changes, and an onboarding from 12% to 88% completion. Engineer by training, I design and ship with AI daily, shipped to 200M+ users.",
 "systems":"Product designer who builds design systems from scratch, 10+ years leading design, 7 in fintech. First design hire at four companies, standing up component libraries and design tokens that halved engineering work and set the craft bar. Engineer by training, I design and ship with AI daily, concept through to code, and shipped to 200M+ users.",
}
DESIGN=["Product design","UX design","UI design","Design systems","Component libraries","Design tokens","User flows","Interaction design","Prototyping","Information architecture","Usability testing","0-1 product design"]
DOMAINS=["B2B SaaS","Enterprise","Consumer","Payments","Crypto","Digital wallets","Fintech","Data intelligence","AI products"]
TOOLS=["Figma","Claude Code","AI-assisted prototyping","Design-to-code","Front-end implementation","Analytics"]
LEADERSHIP=["Design leadership","Team building","Hiring","Mentoring","Cross-functional leadership","Stakeholder management","Roadmapping"]
METHODS=["User research","User interviews","Usability testing","Funnel analysis","A/B testing on live traffic","Journey mapping","Heuristic audit","Workshops"]


def reorder(pool, jd):
    j=jd.lower(); hit=[x for x in pool if x.lower() in j]; miss=[x for x in pool if x.lower() not in j]
    return (hit+miss)[:9]

def classify(title, jd):
    t=title.lower()
    if "head of" in t or ("founding" in t and "head" in t): return "lead"
    if "engineer" in t: return "engineer"
    if "research" in t: return "research"
    if "growth" in t or "conversion" in t: return "growth"
    if "design system" in t: return "systems"
    if ("principal" in t or "staff" in t) and ("manager" in t or "head" in t): return "lead"
    return "ic"

def headline(title):
    t=title.lower()
    if "head of" in t: return "Head of Design · Product Design Lead"
    if "principal" in t: return "Principal Product Designer · Product Design Lead"
    if "staff" in t and "engineer" in t: return "Staff Product Designer · Design Engineer"
    if "design engineer" in t or ("design" in t and "engineer" in t): return "Design Engineer · Senior Product Designer"
    if "staff" in t: return "Staff Product Designer · Product Design Lead"
    if "lead" in t: return "Lead Product Designer · Product Design Lead"
    if "founding" in t: return "Founding Designer · Product Design Lead"
    if "senior" in t: return "Senior Product Designer · Product Design Lead"
    return "Product Designer · Product Design Lead"

def experience_for(jd, cls):
    j=jd.lower()
    # score each scorable role by tag hits in the JD; recency breaks ties
    score={}
    for k in META:
        s=sum(1 for tag in V[k]["tags"] if tag in j)
        if cls=="lead" and k in ("mara","starcount"): s+=3   # lead roles expand leadership proof
        if cls=="engineer" and k in ("confirmo","done"): s+=1
        score[k]=s*10 + (8-RECENCY[k])  # recency as minor tiebreak
    order=sorted(META, key=lambda k:-score[k])
    # assign size tiers by rank; DONE never larger than M (it is a side venture)
    tier={}
    tiers=["XL","L","M","M","S","S","S","S"]
    for rank,k in enumerate(order):
        t=tiers[rank]
        if k=="done" and t in ("XL","L"): t="M"
        tier[k]=t
    exp=[]
    for k in CHRON:  # render in reverse-chronological order, DONE 2nd
        ti,co,q,da=META[k]
        exp.append({"title":ti,"company":co,"qualifier":q,"dates":da,"bullets":[V[k][tier[k]]]})
    exp.append(EARLIER)
    return exp

def build(role):
    cls=classify(role["title"],role["jd"])
    skills=[{"label":"Design","items":reorder(DESIGN,role["jd"])},
            {"label":"Domains","items":reorder(DOMAINS,role["jd"])},
            {"label":"Tools","items":reorder(TOOLS,role["jd"])}]
    if cls=="lead": skills.append({"label":"Leadership","items":reorder(LEADERSHIP,role["jd"])})
    elif cls in ("research","growth") or re.search(r"research|interview|usability|test|workshop",role["jd"],re.I):
        skills.append({"label":"Methods","items":reorder(METHODS,role["jd"])})
    return {"headline":headline(role["title"]),"summary":[SUMMARIES[cls]],
            "skills":skills,"experience":experience_for(role["jd"],cls),"education":EDUCATION}

def main():
    ok=fail=0
    for n,role in enumerate(ROLES,1):
        slug=role["slug"]
        try:
            doc=build(role)
            path,pages,fit,fitted=server.build_pdf(doc,slug,1)
            dest=DEST/slug; dest.mkdir(parents=True,exist_ok=True)
            target=dest/"Cesar Garcia CV.pdf"
            if os.path.abspath(path)!=os.path.abspath(target): shutil.copy2(path,target)
            lead=sorted(META,key=lambda k:-(sum(1 for t in V[k]['tags'] if t in role['jd'].lower())*10+(8-RECENCY[k])))[0]
            ok+=1; print(f"[{n}/{len(ROLES)}] OK {slug} (fit={fit:.2f}, leads:{lead})",flush=True)
        except Exception as e:
            fail+=1; print(f"[{n}/{len(ROLES)}] FAIL {slug}: {e}",flush=True)
    print(f"DONE: {ok} made, {fail} failed, of {len(ROLES)}",flush=True)

if __name__=="__main__":
    main()
