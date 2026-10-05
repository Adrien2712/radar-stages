"""One fetcher per recruiting platform. Each returns a list of raw jobs:
{"key", "title", "location", "url", "posted"} — "key" is unique within the source.
"""
import hashlib
import time
import html as htmllib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin

from .http import get_json, get_text, post_json

# Used on big boards (thousands of jobs) instead of downloading everything.
SEARCH_TERMS = ["intern", "internship", "summer", "spring", "insight", "off-cycle", "stage", "placement"]
WD_FULL_SCAN_MAX = 400  # below this many postings, fetch the whole board


def _clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def _iso_from_ms(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).date().isoformat()
    except Exception:
        return None


def _date(s):
    return (s or "")[:10] or None


def _dmy(s):
    """'12 Oct 2026' -> '2026-10-12'"""
    try:
        return datetime.strptime((s or "").strip()[:11].strip(), "%d %b %Y").date().isoformat()
    except ValueError:
        return None


def workday_posted(url):
    """Exact publication date of one Workday posting (detail endpoint)."""
    m = re.match(r"https://(([^.]+)\.wd\d+\.myworkdayjobs\.com)/en-US/([^/]+)(/.+)", url)
    if not m:
        return None
    host, tenant, site, path = m.groups()
    d = get_json(f"https://{host}/wday/cxs/{tenant}/{site}{path}")
    return _date((d.get("jobPostingInfo") or {}).get("startDate"))


# ---------------------------------------------------------------- Workday
def _wd_posted(txt):
    txt = (txt or "").lower()
    today = datetime.now(timezone.utc).date()
    if "today" in txt:
        return today.isoformat()
    if "yesterday" in txt:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+? days", txt)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    return None


def workday(src):
    """source_id: tenant.wdN/SiteA|SiteB"""
    host_part, sites = src["source_id"].split("/", 1)
    tenant = host_part.split(".")[0]
    host = f"{host_part}.myworkdayjobs.com"
    jobs = {}
    for site in sites.split("|"):
        api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

        def page(term, offset):
            return post_json(api, {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term})

        def collect(term, max_items):
            offset, total = 0, None
            while True:
                d = page(term, offset)
                if total is None:
                    total = d.get("total", 0)
                posts = d.get("jobPostings", [])
                for p in posts:
                    path = p.get("externalPath")
                    if not path or path in jobs:
                        continue
                    jobs[path] = {
                        "key": path,
                        "title": p.get("title", ""),
                        "location": p.get("locationsText", ""),
                        "url": f"https://{host}/en-US/{site}{path}",
                        "posted": _wd_posted(p.get("postedOn")),
                    }
                offset += 20
                if not posts or offset >= min(total, max_items):
                    return total

        first = page("", 0)
        if first.get("total", 0) <= WD_FULL_SCAN_MAX:
            collect("", WD_FULL_SCAN_MAX)
        else:
            for term in SEARCH_TERMS:
                collect(term, 100)
    return list(jobs.values())


# ---------------------------------------------------------------- Oracle Cloud (JPMorgan, Lazard...)
def oracle(src):
    """source_id: host/siteNumber"""
    host, site = src["source_id"].split("/", 1)
    base = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber={site},limit=50,sortBy=POSTING_DATES_DESC")
    jobs = {}

    def collect(keyword, max_items):
        offset, total = 0, 0
        while offset < max_items:
            url = base + f",offset={offset}" + (f",keyword={quote(keyword)}" if keyword else "")
            item = get_json(url)["items"][0]
            total = total or item.get("TotalJobsCount", 0)
            reqs = item.get("requisitionList", [])
            for r in reqs:
                jobs[str(r["Id"])] = {
                    "key": str(r["Id"]),
                    "title": r.get("Title", ""),
                    "location": r.get("PrimaryLocation", ""),
                    "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{r['Id']}",
                    "posted": _date(r.get("PostedDate")),
                }
            offset += 50
            if len(reqs) < 50 or offset >= total:
                break
        return total

    total = collect("", 50)
    if total > 300:
        for term in SEARCH_TERMS:
            collect(term, 150)
    elif total > 50:
        collect("", 300)
    return list(jobs.values())


# ---------------------------------------------------------------- Public JSON boards
def greenhouse(src):
    out = []
    for slug in src["source_id"].split("|"):
        for j in get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")["jobs"]:
            out.append({"key": f"{slug}-{j['id']}", "title": j["title"], "location": (j.get("location") or {}).get("name", ""),
                        "url": j["absolute_url"], "posted": _date(j.get("first_published") or j.get("updated_at"))})
    return out


def lever(src):
    return [{"key": j["id"], "title": j["text"], "location": (j.get("categories") or {}).get("location", ""),
             "url": j["hostedUrl"], "posted": _iso_from_ms(j.get("createdAt"))}
            for j in get_json(f"https://api.lever.co/v0/postings/{src['source_id']}?mode=json")]


def ashby(src):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{src['source_id']}")
    return [{"key": j["id"], "title": j["title"], "location": j.get("location", ""), "url": j["jobUrl"],
             "posted": _date(j.get("publishedAt"))} for j in d["jobs"]]


def smartrecruiters(src):
    """source_id: company slug, or "Board|Firm" for agency boards (e.g. "Wiser|Evercore")."""
    slug, _, only = src["source_id"].partition("|")
    out, offset = [], 0
    while True:
        d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}")
        for j in d["content"]:
            if only and only.lower() not in json.dumps(j).lower():
                continue
            loc = j.get("location") or {}
            out.append({"key": j["id"], "title": j["name"], "location": ", ".join(x for x in [loc.get("city"), loc.get("country", "").upper()] if x),
                        "url": f"https://jobs.smartrecruiters.com/{slug}/{j['id']}", "posted": _date(j.get("releasedDate"))})
        offset += 100
        if offset >= d.get("totalFound", 0) or offset >= 1000:
            return out


def recruitee(src):
    d = get_json(f"https://{src['source_id']}.recruitee.com/api/offers/")
    return [{"key": str(j["id"]), "title": j["title"], "location": j.get("location") or j.get("city", ""),
             "url": j["careers_url"], "posted": _date(j.get("published_at"))} for j in d["offers"]]


def workable(src):
    d = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{src['source_id']}")
    return [{"key": j["shortcode"], "title": j["title"], "location": ", ".join(x for x in [j.get("city"), j.get("country")] if x),
             "url": j.get("url") or j.get("shortlink"), "posted": _date(j.get("published_on"))} for j in d["jobs"]]


def pinpoint(src):
    d = get_json(f"https://{src['source_id']}.pinpointhq.com/postings.json")
    return [{"key": str(j["id"]), "title": j["title"], "location": (j.get("location") or {}).get("name", ""),
             "url": j["url"], "posted": None} for j in d["data"]]


def rss(src):
    """source_url: any RSS feed (Teamtailor /jobs.rss, SuccessFactors /services/rss/job/...)."""
    url = src["source_url"] or f"https://{src['source_id']}.teamtailor.com/jobs.rss"
    root = ET.fromstring(get_text(url).encode())
    out = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        title = _clean(it.findtext("title"))
        loc = ""
        for child in it:
            if child.tag.endswith("location") or child.tag.endswith("city"):
                loc = _clean("".join(child.itertext())) or loc
        out.append({"key": it.findtext("guid") or link, "title": title, "location": loc, "url": link,
                    "posted": None})
    return out


# ---------------------------------------------------------------- Bespoke APIs
GS_QUERY = ("query GetCampusRoles($searchQueryInput: RoleSearchQueryInput!) { roleSearch(searchQueryInput: $searchQueryInput) "
            "{ totalCount items { roleId jobTitle locations { city country } } } }")


def goldman(src):
    out, page = [], 0
    while True:
        d = post_json("https://api-higher.gs.com/gateway/api/v1/graphql", {
            "operationName": "GetCampusRoles", "query": GS_QUERY,
            "variables": {"searchQueryInput": {"page": {"pageSize": 100, "pageNumber": page},
                                               "sort": {"sortStrategy": "POSTED_DATE", "sortOrder": "DESC"},
                                               "filters": [], "experiences": ["CAMPUS"], "searchTerm": ""}}},
            headers={"Origin": "https://higher.gs.com", "Referer": "https://higher.gs.com/"})["data"]["roleSearch"]
        for r in d["items"]:
            num = r["roleId"].split("_")[0]
            locs = ", ".join(sorted({(l.get("city") or l.get("country") or "") for l in r.get("locations") or []} - {""}))
            out.append({"key": r["roleId"], "title": r["jobTitle"], "location": locs,
                        "url": f"https://higher.gs.com/roles/{num}", "posted": None})
        page += 1
        if page * 100 >= d["totalCount"] or not d["items"]:
            return out


def eightfold(src):
    """source_id: subdomain.eightfold.ai|domain (Morgan Stanley)."""
    host, domain = src["source_id"].split("|")
    out = {}
    for term in SEARCH_TERMS:
        for start in (0, 10, 20, 30, 40):
            d = get_json(f"https://{host}/api/pcsx/search?domain={domain}&query={quote(term)}&start={start}&sort_by=timestamp")
            pos = (d.get("data") or {}).get("positions") or []
            for p in pos:
                out[str(p["id"])] = {"key": str(p["id"]), "title": p["name"], "location": "; ".join(p.get("locations") or []),
                                     "url": f"https://{host}{p.get('positionUrl') or '/careers/job/' + str(p['id'])}",
                                     "posted": _iso_from_ms((p.get("postedTs") or 0) * 1000)}
            if len(pos) < 10:
                break
    return list(out.values())


def beesite(src):
    """Deutsche Bank (and other beesite.de tenants). source_id: api host, e.g. api-deutschebank.beesite.de"""
    out = {}
    for term in SEARCH_TERMS:
        q = {"LanguageCode": "en", "SearchParameters": {"FirstItem": 1, "CountItem": 100,
             "Sort": [{"Criterion": "PublicationStartDate", "Direction": "DESC"}],
             "MatchedObjectDescriptor": ["PositionTitle", "PositionLocation.CityName", "PositionURI", "PublicationStartDate"]},
             "SearchCriteria": [{"CriterionName": "PositionFormattedDescription.Content", "CriterionValue": [term]}]}
        d = get_json(f"https://{src['source_id']}/search/?data={quote(json.dumps(q))}")
        for it in d["SearchResult"]["SearchResultItems"]:
            m = it["MatchedObjectDescriptor"]
            jid = it["MatchedObjectId"]
            out[jid] = {"key": jid, "title": m.get("PositionTitle", ""),
                        "location": ", ".join(l.get("CityName", "") for l in m.get("PositionLocation") or []),
                        "url": f"https://careers.db.com/professionals/search-roles/#/professional/job/{jid}",
                        "posted": _date(m.get("PublicationStartDate"))}
    return list(out.values())


def oleeo(src):
    """Oleeo / TalentLink boards (*.tal.net) used by Morgan Stanley, Evercore, Jefferies...
    Each site has several boards (events, students, experienced hires...): read boards 1 to 6."""
    out = {}
    for board in range(1, 7):
        base = f"https://{src['source_id']}.tal.net/vx/candidate/jobboard/vacancy/{board}/adv/"
        start = 0
        while start < 500:
            try:
                html = get_text(f"{base}?start={start}")
            except Exception:
                if board == 1 and start == 0:
                    raise
                break
            if "Quick Check Needed" in html:
                raise ValueError("vérification anti-robot Oleeo (réessai au prochain scan)")
            if "jobboard" not in html and board == 1 and start == 0:
                raise ValueError("page Oleeo inattendue")
            time.sleep(1)  # be gentle: Oleeo shows a bot check when hit too fast
            fresh = 0
            for block in re.split(r'<(?:li|tr)\b[^>]*class="[^"]*(?:opp-container|opp_\d+)', html)[1:]:  # list or table layout
                m = re.search(r'<a class="subject" href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
                if not m:
                    continue
                href, title = m.groups()
                title = _clean(title)
                slug = re.search(r"/opp/\d+-([^/]+)", href)
                if slug and len(slug.group(1)) > len(title) + 5:  # table layouts show a shortened title
                    title = slug.group(1).replace("-", " ")
                key = re.search(r"/opp/(\d+)", href)
                key = key.group(1) if key else href
                if key in out:
                    continue
                fresh += 1
                fields = {_clean(k).rstrip(":").lower(): _clean(v) for k, v in
                          re.findall(r'candidate-opp-field-label">([^<]+)</span>(.*?)</div>', block, re.S)}
                deadline = _dmy(fields.get("application deadline") or fields.get("registration deadline") or fields.get("closing date"))
                url = re.sub(r"/xf-[0-9a-f]+", "", href)  # drop the per-session token so the URL is stable
                out[key] = {"key": key, "title": title, "location": fields.get("location", ""), "url": url,
                            "posted": None, "deadline": deadline, "event": _dmy(fields.get("event date"))}
            if not fresh or 'href="?start=' + str(start + 50) not in html:
                break
            start += 50
    return list(out.values())


# ---------------------------------------------------------------- Generic HTML
_A = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)


def html_links(src):
    """source_url: page listing jobs; source_id: regex matching job-detail URLs."""
    page = get_text(src["source_url"])
    rx = re.compile(src["source_id"])
    titles = {}
    for attrs, inner in _A.findall(page):
        m = re.search(r'href=["\']([^"\']+)', attrs)
        if m and rx.search(m.group(1)):
            t = re.search(r'title=["\']([^"\']+)', attrs)
            titles.setdefault(htmllib.unescape(m.group(1)), _clean(inner) or (t and _clean(t.group(1))) or "")
    for m in rx.finditer(page):  # links hidden in onclick="location.href=..."
        titles.setdefault(htmllib.unescape(m.group(0)), "")
    out = []
    for href, title in titles.items():
        url = urljoin(src["source_url"], href)
        if not title:
            slug = re.sub(r"(_\d+)?\.aspx$|/job$|\?.*$", "", href.rstrip("/").split("/")[-1])
            title = re.sub(r"^emploi-+", "", slug).replace("-", " ").strip()
        title = re.sub(r"^\d+ - ", "", title)  # iCIMS "1234 - Title"
        out.append({"key": url.split("?")[0], "title": title, "location": "", "url": url, "posted": None})
    return out


_WATCH_WORDS = re.compile(
    r"\bintern(ship)?s?\b|stagiaire|\bstages? (de|d.|en|M&A|analyst|au sein|chez|-|–)|summer (analyst|intern|program)"
    r"|spring (week|insight|program)|insight (day|week|program)|off[- ]cycle|graduate (programme|program)"
    r"|c[ée]sure|vacation scheme|campus recruit|student programme", re.I)


def watch(src):
    """No ATS: watch the careers page and report new internship-related lines of text."""
    page = get_text(src["source_url"])
    page = re.sub(r"<(script|style|noscript|svg|head)\b.*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<(br|p|/p|div|/div|li|/li|h\d|/h\d|/a|td|/td|tr|/tr|section|/section)\b[^>]*>", "\n", page, flags=re.I)
    page = re.sub(r"<[^>]*>", " ", page)
    out = []
    for l in {_clean(x) for x in page.split("\n")}:
        if 10 <= len(l) <= 160 and _WATCH_WORDS.search(l) and "<" not in l:
            out.append({"key": hashlib.sha1(l.lower().encode()).hexdigest()[:16], "title": l, "location": "",
                        "url": src["source_url"], "posted": None, "watch": True})
    return out


FETCHERS = {
    "workday": workday, "oracle": oracle, "greenhouse": greenhouse, "lever": lever, "ashby": ashby,
    "smartrecruiters": smartrecruiters, "recruitee": recruitee, "workable": workable, "pinpoint": pinpoint,
    "rss": rss, "teamtailor": rss, "goldman": goldman, "eightfold": eightfold, "beesite": beesite,
    "oleeo": oleeo, "html": html_links, "watch": watch,
}
