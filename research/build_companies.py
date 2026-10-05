"""Merge firms_seed.csv + verified sources into ../companies.csv"""
import csv, json, os
H = os.path.dirname(os.path.abspath(__file__))
S = {  # name: (source, source_id, source_url)
 "J.P. Morgan": ("oracle", "jpmc.fa.oraclecloud.com/CX_1001", ""),
 "Goldman Sachs": ("goldman", "", ""),
 "Morgan Stanley": ("eightfold", "morganstanley.eightfold.ai|morganstanley.com", ""),
 "Bank of America": ("workday", "ghr.wd1/lateral-emea|Lateral-US", ""),
 "Citi": ("workday", "citi.wd5/2", ""),
 "Barclays": ("workday", "barclays.wd3/External_Career_Site_Barclays", ""),
 "Deutsche Bank": ("beesite", "api-deutschebank.beesite.de", ""),
 "HSBC": ("html", r"/external/(?:JobDetail|PipelineDetail)/[^\"']+/\d+", "https://mycareer.hsbc.com/en_GB/external/SearchJobs/?keyword=intern"),
 "Wells Fargo": ("oleeo", "wellsfargo", ""),
 "Crédit Agricole CIB": ("html", r"/offre-de-emploi/emploi-[a-z0-9-]+_\d+\.aspx", "https://jobs.ca-cib.com/offre-de-emploi/liste-offres.aspx?mode=list"),
 "Nomura": ("oleeo", "nomura", ""),
 "Mizuho": ("workday", "mizuho.wd1/mizuhoamericas", ""),
 "MUFG": ("workday", "mufgub.wd3/MUFG-Careers", ""),
 "RBC Capital Markets": ("workday", "rbc.wd3/RBCEARLYTALENT1", ""),
 "BMO Capital Markets": ("workday", "bmo.wd3/Campus", ""),
 "TD Securities": ("workday", "td.wd3/TD_Bank_Careers", ""),
 "Scotiabank": ("rss", "", "https://jobs.scotiabank.com/services/rss/job/?locale=en_US&keywords=intern"),
 "Jefferies": ("oleeo", "jefferies", ""),
 "Santander CIB": ("workday", "santander.wd3/SantanderCareers", ""),
 "BBVA CIB": ("workday", "bbva.wd3/BBVA", ""),
 "ING": ("workday", "ing.wd3/ICSGBLCOR|ICSFRADIR", ""),
 "Standard Chartered": ("rss", "", "https://jobs.standardchartered.com/services/rss/job/?locale=en_GB&keywords=intern"),
 "Lazard": ("oracle", "icbpjb.fa.ocs.oraclecloud.com/LazardProfessionalCareers", ""),
 "Rothschild & Co": ("workday", "rothschildandco.wd3/Rothschildandco_Interns|Rothschildandco_Lateral", ""),
 "Evercore": ("oleeo", "evercore", ""),
 "PJT Partners": ("workday", "pjtpartners.wd1/Careers", ""),
 "Moelis & Company": ("workday", "moelis.wd1/University-Hires|Experienced-Hires", ""),
 "Guggenheim Partners": ("workday", "guggenheim.wd1/Guggenheim_Careers_Campus|Guggenheim_Undergraduate_Programs|Guggenheim_Careers", ""),
 "Houlihan Lokey": ("workday", "hl.wd1/Campus|Corporate", ""),
 "LionTree": ("greenhouse", "liontree", ""),
 "Solomon Partners": ("greenhouse", "solomonpartnersprofessionals", ""),
 "Ducera Partners": ("greenhouse", "ducerapartners|ducerapartnerscampus", ""),
 "Raine Group": ("lever", "raine", ""),
 "William Blair": ("html", r"/careers/JobDetail/[^\"']+/\d+", "https://williamblair.avature.net/careers/SearchJobs/?keyword=intern"),
 "Lincoln International": ("greenhouse", "lincolninternational", ""),
 "Harris Williams": ("workday", "pnc.wd5/HarrisWilliams", ""),
 "Piper Sandler": ("workday", "pipersandler.wd501/Piper_Sandler_Careers", ""),
 "Stifel": ("html", r"/jobs/\d+/[^/\"']+/job", "https://careers-stifel.icims.com/jobs/search?ss=1&searchKeyword=intern&in_iframe=1"),
 "Raymond James": ("workday", "raymondjames.wd1/RaymondJamesEarlyCareers", ""),
 "Truist Securities": ("workday", "truist.wd1/Careers|LDP", ""),
 "KeyBanc Capital Markets": ("workday", "keybank.wd5/External_Career_Site", ""),
 "Alantra": ("workday", "alantra.wd3/Alantra", ""),
 "Clipperton": ("workable", "clipperton", ""),
 "Canaccord Genuity": ("workday", "cgf.wd10/CG", ""),
 "Evelyn Partners": ("smartrecruiters", "EvelynPartners", ""),
 "Kepler Cheuvreux": ("teamtailor", "keplercheuvreux", ""),
 "Forvis Mazars": ("greenhouse", "forvismazars", ""),
 "Grant Thornton": ("recruitee", "grantthornton", ""),
 "PwC": ("workday", "pwc.wd3/Global_Campus_Careers", ""),
 "Alvarez & Marsal": ("workday", "alvarezandmarsal.wd1/alvarezandmarsal", ""),
 "Blackstone": ("workday", "blackstone.wd1/Blackstone_Campus_Careers|Blackstone_Careers", ""),
 "Carlyle": ("workday", "carlyle.wd1/Carlyle", ""),
 "Apollo": ("workday", "athene.wd5/Apollo_Careers", ""),
 "TPG": ("greenhouse", "tpgcareers", ""),
 "Bain Capital": ("workday", "baincapital.wd1/External_Public", ""),
 "Advent International": ("workday", "adventinternational.wd12/AdventCareers", ""),
 "EQT": ("greenhouse", "eqtpartners", ""),
 "Cinven": ("pinpoint", "cinven", ""),
 "Apax Partners": ("lever", "apax", ""),
 "General Atlantic": ("greenhouse", "generalatlantic", ""),
 "Vista Equity Partners": ("html", r"/jobs/\d+/[^/\"']+/job", "https://careers-vistaequitypartners.icims.com/jobs/search?ss=1&in_iframe=1"),
 "Brookfield": ("workday", "brookfield.wd5/brookfield", ""),
 "Ardian": ("workday", "ardian.wd103/ArdianCareers", ""),
 "3i": ("workday", "3i.wd103/Intern_Career|Direct_Hire", ""),
 "ICG": ("workday", "icg.wd3/external_careers", ""),
 "IK Partners": ("recruitee", "ikpartners", ""),
 "Triton Partners": ("workday", "tritonpartners.wd3/External", ""),
 "Vitruvian Partners": ("workday", "vitruvian.wd108/vitruviancareers", ""),
 "PAI Partners": ("recruitee", "paipartners", ""),
 "Antin Infrastructure Partners": ("teamtailor", "antininfrastructurepartners-1655458195", ""),
 "Blue Owl": ("workday", "blueowl.wd1/blueowl", ""),
 "HPS Investment Partners": ("greenhouse", "hpsinvestmentpartners", ""),
 "Sixth Street": ("workday", "sixthstreet.wd1/sixthstreetcareers", ""),
 "Oaktree Capital": ("workday", "oaktree.wd1/Oaktree", ""),
 "Ares Management": ("workday", "aresmgmt.wd1/External", ""),
 "Barings": ("workday", "barings.wd1/Early_Talent|Barings", ""),
 "Pemberton Asset Management": ("ashby", "Pemberton", ""),
 "Antares Capital": ("workday", "antares.wd5/antares", ""),
 "Muzinich & Co": ("workday", "muzinich.wd5/muzinichcareers", ""),
 "Fortress Investment Group": ("workday", "fortress.wd503/Careers", ""),
 "Cerberus Capital": ("workday", "cerberus.wd1/CerberusCareers", ""),
 "Davidson Kempner": ("greenhouse", "1456754456yhgbhfg", ""),
 "Capza": ("smartrecruiters", "capza", ""),
 "CPP Investments": ("workday", "cppib.wd10/cppinvestments", ""),
 "Ontario Teachers' (OTPP)": ("workday", "otppb.wd3/OntarioTeachers_Careers", ""),
 "CDPQ": ("workday", "cdpq.wd10/CDPQ|CDPQ-recrutement-universitaire", ""),
 "PSP Investments": ("workday", "investpsp.wd3/psp_careers", ""),
 "QIA": ("oracle", "fa-esgr-saasfaprod1.fa.ocs.oraclecloud.com/CX_1", ""),
 "Lombard Odier": ("workday", "lombardodier.wd3/Lombard_Odier_Careers", ""),
 "Gunvor": ("workday", "gunvor.wd3/Gunvor_Careers", ""),
 "Trafigura": ("workday", "trafigura.wd3/TrafiguraCareerSite", ""),
 "Vitol": ("smartrecruiters", "Vitol", ""),
 "Kering": ("workday", "kering.wd3/Kering", ""),
 "AXA": ("html", r"/jobs/\d+/[^/\"']+/job", "https://careers-en-axa.icims.com/jobs/search?ss=1&searchKeyword=intern&in_iframe=1"),
 "L Catterton": ("workday", "lcatterton.wd501/External_Career_Site", ""),
 "Neuberger Berman": ("workday", "nb.wd1/NBCareers", ""),
 "Hamilton Lane": ("workday", "hamiltonlane.wd108/Search", ""),
 "StepStone Group": ("greenhouse", "stepstone", ""),
 "Coller Capital": ("teamtailor", "collercapital-1660725598", ""),
 "HarbourVest": ("workday", "harbourvest.wd5/HVP", ""),
 "Adams Street Partners": ("greenhouse", "adamsstreetpartners", ""),
 "BlackRock": ("workday", "blackrock.wd1/BlackRock_Professional", ""),
 "Siparex": ("watch", "", "https://www.welcometothejungle.com/fr/companies/siparex/jobs"),
}
DROP = {"Greenhill (Mizuho)", "Cowen (TD)", "Lazard Frères Banque", "Five Arrows (Rothschild)", "Ardian Buyout",
        "Ardian Private Debt", "Bain Capital Credit", "Apollo Credit", "Angelo Gordon (TPG)", "Eurazeo PME",
        "Eurazeo Private Debt", "Goldman Sachs Asset Management", "Morgan Stanley Investment Management",
        "Blackstone Real Estate", "Macquarie Asset Management", "BDO", "Sagard", "Siparex"}
EXTRA = [{"name": "BlackRock", "homepage": "https://careers.blackrock.com", "category": "Investisseur institutionnel", "tier": "2", "hq": "New York"}]

seed = list(csv.DictReader(open(os.path.join(H, "firms_seed.csv"), encoding="utf-8"))) + EXTRA
disc = {r["name"]: r for f in ("discovered.json", "discovered2.json") for r in json.load(open(os.path.join(H, f)))}
rows = []
for r in seed:
    if r["name"] in DROP:
        continue
    src, sid, surl = S.get(r["name"], ("", "", ""))
    d = disc.get(r["name"], {})
    careers = r["homepage"]
    if not src:
        # careers page reachable as static HTML -> watch it, else manual
        if d.get("ok") and d.get("final", "").rstrip("/").count("/") >= 3:
            src, surl = "watch", d["final"]
        else:
            src = "manuel"
    rows.append({"name": r["name"], "category": r["category"], "tier": r["tier"], "hq": r["hq"],
                 "source": src, "source_id": sid, "source_url": surl, "careers_url": careers})
rows.sort(key=lambda x: (x["tier"], x["category"], x["name"]))
with open(os.path.join(H, "..", "companies.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
from collections import Counter
print(len(rows), Counter(r["source"] for r in rows))
