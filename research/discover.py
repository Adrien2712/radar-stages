"""Crawl each firm's careers page (2 levels) and detect which ATS it uses."""
import csv, json, re, sys, ssl, concurrent.futures as cf
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
CTX = ssl.create_default_context()

SIGS = {
    "workday": r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)",
    "greenhouse": r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)",
    "lever": r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_-]+)",
    "smartrecruiters": r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)",
    "ashby": r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)",
    "oracle": r"([a-z0-9-]+\.fa\.[a-z0-9-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z-]+/sites/([A-Za-z0-9_-]+)",
    "taleo": r"([a-z0-9-]+)\.taleo\.net",
    "successfactors": r"(career\d*\.successfactors\.(?:com|eu)|[a-z0-9.-]*jobs2web\.com|rmk-map-\d+\.jobs2web\.com)",
    "teamtailor": r"([a-z0-9-]+)\.teamtailor\.com",
    "wttj": r"welcometothejungle\.com/(?:fr|en)/companies/([a-z0-9-]+)",
    "workable": r"apply\.workable\.com/([a-z0-9-]+)",
    "recruitee": r"([a-z0-9-]+)\.recruitee\.com",
    "icims": r"(careers-[a-z0-9-]+\.icims\.com)",
    "avature": r"([a-z0-9.-]+\.avature\.net)",
    "eightfold": r"([a-z0-9-]+)\.eightfold\.ai",
    "phenom": r"(phenompeople\.com|phenom\.com/)",
    "jobvite": r"jobs\.jobvite\.com/([a-z0-9-]+)",
    "personio": r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)",
    "pinpoint": r"([a-z0-9-]+)\.pinpointhq\.com",
    "bamboohr": r"([a-z0-9-]+)\.bamboohr\.com",
    "beesite": r"(beesite\.de)",
    "hirehive": r"([a-z0-9-]+)\.hirehive\.com",
}
NAV = re.compile(r"career|carri|job|join|rejoind|recrut|student|graduate|campus|opportunit|vacanc|talent|work-with|nous-rejoindre|offres", re.I)


def fetch(url):
    try:
        r = urlopen(Request(url, headers={"User-Agent": UA, "Accept-Language": "en,fr;q=0.8"}), timeout=20, context=CTX)
        return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")
    except Exception as e:
        return url, ""


def detect(text):
    out = {}
    for k, rx in SIGS.items():
        m = re.findall(rx, text)
        if m:
            out[k] = sorted(set(m if isinstance(m[0], str) else ["|".join(x) for x in m]))[:5]
    return out


def links(base, html):
    hrefs = re.findall(r'href=["\']([^"\'#]+)', html)
    res = []
    for h in hrefs:
        u = urljoin(base, h)
        if u.startswith("http") and NAV.search(u) and not re.search(r"\.(pdf|jpg|png|css|js)$", u):
            res.append(u)
    return list(dict.fromkeys(res))


def run(row):
    url, html = fetch(row["homepage"])
    found = detect(url + html)
    visited = 1
    if not found and html:
        for u in links(url, html)[:25]:
            u2, h2 = fetch(u)
            visited += 1
            f2 = detect(u2 + h2)
            for k, v in f2.items():
                found.setdefault(k, []).extend(x for x in v if x not in found.get(k, []))
            if found:
                break
    return {"name": row["name"], "homepage": row["homepage"], "final": url, "ok": bool(html), "found": found, "visited": visited}


if __name__ == "__main__":
    rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
    with cf.ThreadPoolExecutor(24) as ex:
        results = list(ex.map(run, rows))
    json.dump(results, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
    for r in results:
        print(("OK " if r["found"] else ("-- " if r["ok"] else "XX ")) + r["name"].ljust(40), json.dumps(r["found"])[:160])
