"""Turn a link to a recruiting platform into a source the radar can read, and spot the ones we don't watch yet
(e.g. Evercore London on SmartRecruiters, Lazard's second Oracle site, BlackRock's other Oleeo board)."""
import re
from urllib.parse import urlparse, parse_qs

PATTERNS = [
    ("workday", re.compile(r"https://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
     lambda m: f"{m.group(1)}.{m.group(2)}/{m.group(3)}"),
    ("greenhouse", re.compile(r"https://(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
     lambda m: m.group(1)),
    ("lever", re.compile(r"https://jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_-]+)"), lambda m: m.group(1)),
    ("ashby", re.compile(r"https://jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)"), lambda m: m.group(1)),
    ("smartrecruiters", re.compile(r"https://(?:jobs|careers)\.smartrecruiters\.com/(?:ni/)?([A-Za-z0-9_-]+)"), lambda m: m.group(1)),
    ("oleeo", re.compile(r"https://([a-z0-9-]+)\.tal\.net/"), lambda m: m.group(1)),
    ("oracle", re.compile(r"https://([a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z-]+/sites/([A-Za-z0-9_-]+)"),
     lambda m: f"{m.group(1)}/{m.group(2)}"),
    ("teamtailor", re.compile(r"https://([a-z0-9-]+)\.teamtailor\.com"), lambda m: m.group(1)),
    ("recruitee", re.compile(r"https://([a-z0-9-]+)\.recruitee\.com"), lambda m: m.group(1)),
    ("pinpoint", re.compile(r"https://([a-z0-9-]+)\.pinpointhq\.com"), lambda m: m.group(1)),
]
GENERIC = {"www", "jobs", "careers", "app", "api", "embed", "job_board", "o", "en", "fr"}


def source_of(url):
    """(source, source_id) for a link to a recruiting platform, or None."""
    for name, rx, ident in PATTERNS:
        m = rx.match(url or "")
        if m:
            sid = ident(m)
            if sid.split("/")[-1].lower() in GENERIC or sid.lower() in GENERIC:
                return None
            return name, sid
    return None


def ids_of(source, source_id):
    """Every individual board inside a source_id ("tenant.wd1/A|B" -> two Workday sites, "Wiser|Evercore" -> wiser)."""
    sid = (source_id or "").strip()
    if source == "workday" and "/" in sid:
        host, sites = sid.split("/", 1)
        return {f"{host}/{x}".lower() for x in sites.split("|")}
    if source == "smartrecruiters":
        return {sid.split("|")[0].lower()}
    if source in ("greenhouse",):
        return {x.lower() for x in sid.split("|")}
    if source == "teamtailor" and not sid:
        return set()
    return {sid.lower()}


def known_ids(rows):
    out = set()
    for r in rows:
        for i in ids_of(r.get("source"), r.get("source_id")):
            out.add((r.get("source"), i))
    return out


def candidates(urls, known):
    """New (source, source_id) found in a list of links."""
    found = {}
    for u in urls:
        s = source_of(u)
        if not s:
            continue
        src, sid = s
        if src == "smartrecruiters" and sid.lower() == "wiser":
            continue  # agency board shared by many firms: needs a per-firm filter, handled by hand
        if (src, sid.lower()) in known or (src, sid.split("/")[0].lower()) in known:
            continue
        found[(src, sid.lower())] = (src, sid)
    return list(found.values())
