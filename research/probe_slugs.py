"""Guess ATS slugs from firm names and probe public job-board APIs."""
import csv, json, re, sys, unicodedata, concurrent.futures as cf
from urllib.request import Request, urlopen

UA = {"User-Agent": "Mozilla/5.0 Chrome/129", "Accept": "application/json"}


def get(url):
    try:
        r = urlopen(Request(url, headers=UA), timeout=15)
        return r.status, r.read(400_000).decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", 0), ""


def slugs(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\(.*?\)", "", n).replace("&", "and")
    words = re.findall(r"[a-z0-9]+", n)
    stop = {"and", "co", "company", "group", "partners", "capital", "management", "asset", "investment", "the", "llc", "inc"}
    core = [w for w in words if w not in stop] or words
    c = {"".join(words), "".join(core), "-".join(words), core[0], "".join(core) + "partners", "".join(core) + "capital"}
    return [s for s in c if len(s) > 2]


def probe(slug):
    hits = []
    s, b = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if s == 200 and '"jobs"' in b:
        hits.append(("greenhouse", slug, b.count('"absolute_url"')))
    s, b = get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if s == 200 and b.startswith("["):
        hits.append(("lever", slug, b.count('"hostedUrl"')))
    s, b = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if s == 200 and '"jobs"' in b:
        hits.append(("ashby", slug, b.count('"jobUrl"')))
    s, b = get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    if s == 200 and '"jobs"' in b:
        hits.append(("workable", slug, b.count('"shortcode"')))
    s, b = get(f"https://{slug}.recruitee.com/api/offers/")
    if s == 200 and '"offers"' in b:
        hits.append(("recruitee", slug, b.count('"careers_url"')))
    s, b = get(f"https://{slug}.tal.net/vx/candidate/jobboard/vacancy/1/adv/")
    if s == 200 and "jobboard" in b:
        hits.append(("oleeo", slug, b.count('class="subject"')))
    s, b = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1")
    if s == 200 and '"totalFound"' in b and '"totalFound":0' not in b:
        hits.append(("smartrecruiters", slug, re.search(r'"totalFound":(\d+)', b).group(1)))
    return hits


if __name__ == "__main__":
    names = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    jobs = {(n, s) for n in names for s in slugs(n)}
    with cf.ThreadPoolExecutor(32) as ex:
        res = dict(zip(jobs, ex.map(lambda j: probe(j[1]), jobs)))
    out = {}
    for (n, s), h in res.items():
        if h:
            out.setdefault(n, []).extend(h)
    for n in names:
        print(("OK " if n in out else "-- ") + n.ljust(40), out.get(n, ""))
    json.dump(out, open(sys.argv[2], "w"), indent=1)
