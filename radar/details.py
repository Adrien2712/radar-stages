"""Read each offer's description once, extract what matters (graduation year, dates, duration,
languages, documents, tests, visa), and decide whether the candidate is eligible."""
import concurrent.futures as cf
import html as htmllib
import json
import re
from datetime import date
from urllib.parse import quote

from .http import get_json, get_text

I = re.I
MONTHS = {"jan": 1, "janv": 1, "january": 1, "janvier": 1, "feb": 2, "february": 2, "fév": 2, "fev": 2, "février": 2,
          "fevrier": 2, "mar": 3, "march": 3, "mars": 3, "apr": 4, "april": 4, "avr": 4, "avril": 4, "may": 5, "mai": 5,
          "jun": 6, "june": 6, "juin": 6, "jul": 7, "july": 7, "juil": 7, "juillet": 7, "aug": 8, "august": 8, "août": 8,
          "aout": 8, "sep": 9, "sept": 9, "september": 9, "septembre": 9, "oct": 10, "october": 10, "octobre": 10,
          "nov": 11, "november": 11, "novembre": 11, "dec": 12, "december": 12, "déc": 12, "décembre": 12, "decembre": 12}
MONTH_RX = r"(janv(?:ier)?|jan(?:uary)?|f[ée]v(?:rier)?|feb(?:ruary)?|mars|mar(?:ch)?|avr(?:il)?|apr(?:il)?|mai|may|juin|june?|juil(?:let)?|july?|ao[uû]t|aug(?:ust)?|sept?(?:ember|embre)?|oct(?:ober|obre)?|nov(?:ember|embre)?|d[ée]c(?:ember|embre)?)"
QUARTERS = {"q1": 1, "q2": 4, "q3": 7, "q4": 10, "s1": 1, "s2": 7, "h1": 1, "h2": 7}
LANGS = {"german": "allemand", "allemand": "allemand", "italian": "italien", "italien": "italien", "spanish": "espagnol",
         "espagnol": "espagnol", "dutch": "néerlandais", "néerlandais": "néerlandais", "mandarin": "mandarin",
         "chinese": "chinois", "japanese": "japonais", "korean": "coréen", "arabic": "arabe", "portuguese": "portugais",
         "swedish": "suédois", "polish": "polonais", "norwegian": "norvégien", "danish": "danois", "finnish": "finnois",
         "russian": "russe", "turkish": "turc", "hebrew": "hébreu", "cantonese": "cantonais", "french": "français",
         "français": "français", "english": "anglais", "anglais": "anglais"}
TESTS = [("HireVue", r"hirevue"), ("Pymetrics", r"pymetrics"), ("SHL", r"\bshl\b"), ("Cappfinity", r"cappfinity"),
         ("Sova", r"\bsova\b"), ("Aon", r"\baon\b"), ("Arctic Shores", r"arctic shores"), ("Codility", r"codility"),
         ("Tests en ligne", r"online (test|assessment)|numerical reasoning|verbal reasoning|psychometric|tests? (en ligne|de raisonnement)"),
         ("Entretien vidéo", r"video interview|recorded interview|entretien vid[ée]o"),
         ("Case study", r"case study|étude de cas"), ("Superday", r"superday|assessment cent(er|re)")]
VISA_COUNTRIES = {"Royaume-Uni", "États-Unis", "Canada", "Singapour", "Hong Kong", "Japon", "Australie", "Inde", "Chine",
                  "Corée du Sud", "Émirats arabes unis", "Arabie saoudite", "Qatar", "Brésil", "Mexique", "Philippines",
                  "Taïwan", "Kazakhstan"}


def clean(html):
    t = htmllib.unescape(htmllib.unescape(html or ""))
    t = re.sub(r"<(br|p|/p|li|/li|div|/div|h\d|/h\d)\b[^>]*>", "\n", t, flags=I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t\xa0]+", " ", t).strip()


# ----------------------------------------------------------------- fetching descriptions
def fetch_description(j):
    """Return (description text, extra fields) for one job, using the cheapest endpoint of its platform."""
    src, url, key = j.get("source"), j.get("url", ""), str(j.get("key", ""))
    if src == "workday":
        m = re.match(r"https://(([^.]+)\.wd\d+\.myworkdayjobs\.com)/en-US/([^/]+)(/.+)", url)
        if m:
            host, tenant, site, path = m.groups()
            info = get_json(f"https://{host}/wday/cxs/{tenant}/{site}{path}").get("jobPostingInfo") or {}
            return clean(info.get("jobDescription")), {"posted": (info.get("startDate") or "")[:10] or None}
    if src == "greenhouse" and "-" in key:
        slug, jid = key.rsplit("-", 1)
        return clean(get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}").get("content")), {}
    if src == "lever":
        m = re.search(r"jobs\.(?:eu\.)?lever\.co/([^/]+)/([0-9a-f-]+)", url)
        if m:
            d = get_json(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}")
            parts = [d.get("descriptionPlain", ""), d.get("additionalPlain", "")] + [clean(x.get("content")) for x in d.get("lists", [])]
            return "\n".join(parts), {}
    if src == "smartrecruiters":
        m = re.search(r"smartrecruiters\.com/([^/]+)/(\d+)", url)
        if m:
            d = get_json(f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}")
            secs = (d.get("jobAd") or {}).get("sections") or {}
            return "\n".join(clean(v.get("text")) for v in secs.values() if isinstance(v, dict)), {}
    if src == "oracle":
        m = re.match(r"https://([^/]+)/hcmUI/CandidateExperience/[a-z]+/sites/([^/]+)/job/(\d+)", url)
        if m:
            host, site, jid = m.groups()
            d = get_json(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                         f"?expand=all&onlyData=true&finder=ById;Id=%22{jid}%22,siteNumber={site}")["items"][0]
            return "\n".join(clean(d.get(k)) for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr",
                                                       "ExternalQualificationsStr", "ShortDescriptionStr")), {}
    if src == "goldman":
        return "", {}  # descriptions already come with the list (see sources.goldman)
    # Generic: the job page itself (Oleeo, Teamtailor, Recruitee, Pinpoint, iCIMS, Talentsoft...)
    page = get_text(url)
    page = re.sub(r"<(script|style|noscript|svg|head|nav|footer|header)\b.*?</\1>", " ", page, flags=re.S | I)
    text = clean(page)
    return (text if len(text) > 400 else ""), {}


# ----------------------------------------------------------------- extraction
def _mon(word):
    w = re.sub(r"[^a-zéûô]", "", word.lower())
    return MONTHS.get(w[:9]) or MONTHS.get(w[:4]) or MONTHS.get(w[:3])


def _month_year(text):
    """All (year, month) mentioned like 'January 2027', 'janv. 2027', 'Q1 2027', 'Jan-June 2027'."""
    out = []
    for m in re.finditer(MONTH_RX + r"\.?\s*(?:-|–|to|à|au|until)\s*" + MONTH_RX + r"\.?\s*(20\d\d)", text, I):
        a = _mon(m.group(1))
        if a:
            out.append((int(m.group(3)), a))
    for m in re.finditer(MONTH_RX + r"\.?\s*(?:\d{1,2}(?:st|nd|rd|th)?,?\s*)?(20\d\d)", text, I):
        mon = MONTHS.get(re.sub(r"[^a-zéûô]", "", m.group(1).lower())[:9]) or MONTHS.get(m.group(1).lower()[:3])
        if mon:
            out.append((int(m.group(2)), mon))
    for m in re.finditer(r"\b(q[1-4]|s[12]|h[12])[\s-]*(20\d\d|\d\d)\b", text, I):
        y = int(m.group(2)) if len(m.group(2)) == 4 else 2000 + int(m.group(2))
        out.append((y, QUARTERS[m.group(1).lower()]))
    return out


def analyze(text, title=""):
    """Compact facts used for the summary and the eligibility check."""
    t = f"{title}\n{text}"
    low = t.lower()
    d = {}

    # Graduation years required ("graduating in 2028", "class of 2029", "between December 2027 and July 2028")
    grad = set()
    for m in re.finditer(r"(graduat\w*|class of|dipl[ôo]m\w*|fin d.[ée]tudes|expected to complete)[^.\n]{0,90}", t, I):
        span = m.group(0)
        years = [int(y) for y in re.findall(r"20(2[5-9]|3[0-2])", span)]
        years = [2000 + y for y in years]
        if len(years) >= 2 and re.search(r"between|from|to|and|-|–|et|entre", span, I):
            grad.update(range(min(years), max(years) + 1))
        else:
            grad.update(years)
    if grad:
        d["grad_years"] = sorted(grad)

    # Year of study
    years_of_study = []
    for label, rx in (("1re année", r"first[- ]year|1st[- ]year|premi[eè]re ann[ée]e"),
                      ("année pénultième", r"penultimate|pre-?final"),
                      ("dernière année", r"final[- ]year|last year of (your )?stud|derni[eè]re ann[ée]e"),
                      ("césure / gap year", r"gap year|c[ée]sure|year out|leave of absence|ann[ée]e de rupture")):
        if re.search(rx, low):
            years_of_study.append(label)
    if years_of_study:
        d["study"] = years_of_study
    if re.search(r"convention de stage|internship agreement", low):
        d["convention"] = True

    # Dates: start and duration
    starts = []
    for m in re.finditer(r"(start\w*|begin\w*|commenc\w*|d[ée]but\w*|from|à partir d[eu']|dès|date de d[ée]marrage)[^.\n]{0,40}", t, I):
        starts += _month_year(m.group(0))
    starts += _month_year(title)
    if not starts:  # "2027 4-Month Off-Cycle Internship (February, Munich)"
        ys, ms = set(re.findall(r"\b(20\d\d)\b", title)), re.findall(MONTH_RX, title, I)
        if len(ys) == 1 and ms and _mon(ms[0]):
            starts.append((int(ys.pop()), _mon(ms[0])))
    if starts:
        y, mth = min(starts)
        d["start"] = f"{y}-{mth:02d}"
    if re.search(r"starting (now|asap|immediately)|d[èe]s que possible|asap", low):
        d["start_asap"] = True
    dur = re.search(r"(\d{1,2})(?:\s*(?:to|à|-|–)\s*(\d{1,2}))?[\s-]*(month|mois|week|semaine)s?", low)
    if dur:
        n = int(dur.group(2) or dur.group(1))
        unit = "mois" if dur.group(3) in ("month", "mois") else "sem."
        if (unit == "mois" and n <= 24) or (unit == "sem." and n <= 52):
            d["duration"] = f"{dur.group(1)}{'–' + dur.group(2) if dur.group(2) else ''} {unit}"

    # Languages required (only when the text says it's required / fluent)
    req = set()
    bonus = re.compile(r"plus\b|advantage|bonus|desirable|preferred|nice to have|appr[ée]ci|atout|souhait|helpful|beneficial|optional")
    for m in re.finditer(r"(fluen\w*|native|proficien\w*|business[- ]level|courant|ma[iî]trise|bilingu\w*|excellent|strong)[^.\n]{0,40}", low):
        for k, v in LANGS.items():
            lm = re.search(r"\b" + k + r"\b", m.group(0))
            if lm and not bonus.search(low[m.start() + lm.end(): m.start() + lm.end() + 35]):
                req.add(v)
    for k, v in LANGS.items():
        if re.search(r"\b" + k + r"\b[^.\n]{0,25}(required|mandatory|essential|is a must|obligatoire|exig)", low):
            req.add(v)
    req -= {"anglais", "français"}
    if req:
        d["languages"] = sorted(req)

    # Documents & tests
    docs = []
    if re.search(r"\bcv\b|r[ée]sum[ée]", low):
        docs.append("CV")
    if re.search(r"cover letter|lettre de motivation|motivation letter|covering letter", low):
        docs.append("Lettre de motivation")
    if re.search(r"transcript|relev[ée]s? de notes|academic record|grades", low):
        docs.append("Relevés de notes")
    if re.search(r"motivation(al)? questions?|application questions|questions de motivation|short answer", low):
        docs.append("Questions")
    if docs:
        d["documents"] = docs
    tests = [name for name, rx in TESTS if re.search(rx, low)]
    if tests:
        d["tests"] = tests[:4]

    # Work authorisation
    if re.search(r"(not|unable to|cannot|won.t|will not|do not|does not)\s+(be able to\s+)?(provide|offer|sponsor)\w*\s+(visa|sponsorship|work)|no (visa )?sponsorship"
                 r"|without (the need for )?(visa )?sponsorship|must (already )?(have|hold) (the )?(right|authori[sz]ation) to work", low):
        d["no_sponsorship"] = True
    elif re.search(r"right to work|work authori[sz]ation|eligible to work|work permit|permis de travail", low):
        d["work_auth_mentioned"] = True

    # Rolling basis
    if re.search(r"rolling basis|au fil de l.eau|first come", low):
        d["rolling"] = True
    return d


# ----------------------------------------------------------------- eligibility
def evaluate(job, profile):
    """Return {"status": "eligible" | "check" | "no", "reasons": [...], "flags": [...]}"""
    d = job.get("details") or analyze("", job.get("title", ""))
    reasons, flags, verdicts = [], [], []
    grad = profile.get("graduation_year", 2029)
    is_spring = job.get("cycle") == "Spring / Insight"

    if d.get("grad_years"):
        if grad in d["grad_years"]:
            reasons.append(f"Diplôme {grad} accepté")
            verdicts.append("ok")
        else:
            ys = d["grad_years"]
            reasons.append(f"Réservé aux diplômés {ys[0]}" + (f"–{ys[-1]}" if len(ys) > 1 else ""))
            verdicts.append("no")

    if not is_spring:
        avail_from, avail_to = profile.get("available_from", "2027-06"), profile.get("available_to", "2028-08")
        if d.get("start_asap"):
            reasons.append("Démarrage immédiat (avant ta césure)")
            verdicts.append("no")
        elif d.get("start"):
            if d["start"] < avail_from:
                reasons.append(f"Commence en {_fmt_month(d['start'])}, avant ta césure")
                verdicts.append("no")
            elif d["start"] > avail_to:
                reasons.append(f"Commence en {_fmt_month(d['start'])}, après ta césure")
                verdicts.append("no")
            else:
                reasons.append(f"Début {_fmt_month(d['start'])} : pendant ta césure")
                verdicts.append("ok")

    if d.get("languages"):
        spoken = {k for k, v in profile.get("languages", {}).items() if v in ("native", "fluent")}
        missing = [l for l in d["languages"] if l not in spoken]
        if missing:
            reasons.append(f"{', '.join(missing).capitalize()} exigé")
            verdicts.append("no" if "intermediate" not in [profile.get("languages", {}).get(m) for m in missing] else "check")

    if not d.get("grad_years"):  # usual targets when the offer doesn't say
        y = re.search(r"\b(202[6-9])\b", job.get("title", ""))
        if y and job.get("cycle") == "Summer" and int(y.group(1)) + 1 != grad:
            reasons.append(f"Les summers {y.group(1)} visent en général les diplômés {int(y.group(1)) + 1}")
            verdicts.append("check")
        elif y and job.get("cycle") == "Summer":
            reasons.append(f"Les summers {y.group(1)} visent en général les diplômés {grad}")
            verdicts.append("ok")
        elif y and is_spring and int(y.group(1)) + 2 == grad:
            reasons.append(f"Les springs {y.group(1)} visent en général les diplômés {grad}")
            verdicts.append("ok")

    if "1re année" in d.get("study", []) and not d.get("grad_years") and not is_spring:
        reasons.append("Vise les étudiants de 1re année")
        verdicts.append("check")

    country = job.get("country", "")
    if country in VISA_COUNTRIES:
        flags.append("Visa à prévoir")
        if d.get("no_sponsorship"):
            reasons.append("Pas de sponsoring de visa indiqué")
            verdicts.append("check")

    if "no" in verdicts:
        status = "no"
    elif "check" in verdicts or "ok" not in verdicts:
        status = "check"
    else:
        status = "eligible"
    if status == "check" and not reasons:
        reasons.append("Pas assez d'informations dans l'offre")
    return {"status": status, "reasons": reasons, "flags": flags}


def _fmt_month(ym):
    y, m = ym.split("-")
    return ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."][int(m) - 1] + " " + y


def fill_details(jobs, budget=150):
    """Fetch descriptions for target offers that don't have details yet (once per offer)."""
    todo = [j for j in jobs.values() if j["level"] == "A" and not j.get("closed")
            and "details" not in j and not j.get("details_tried")]
    todo.sort(key=lambda j: j.get("first_seen", ""), reverse=True)  # newest first
    todo = todo[:budget]
    if not todo:
        return 0

    def one(j):
        try:
            return j, fetch_description(j)
        except Exception:
            return j, ("", {})

    done = 0
    with cf.ThreadPoolExecutor(10) as ex:
        for j, (text, extra) in ex.map(one, todo):
            j["details_tried"] = True
            if extra.get("posted") and not j.get("posted"):
                j["posted"] = extra["posted"]
            if text:
                j["details"] = analyze(text, j["title"])
                done += 1
    print(f"  Descriptions lues : {done}/{len(todo)} offres ciblées.")
    return done
