"""Public trackers used as extra sources:
- TrackR "Spring Week Timeline" article: every programme + expected opening date (refreshed daily)
- L3vlUp spring week tracker: programmes already open + their closing date (refreshed every 6 h)
- YourFinanceJob lists: open offers aggregated from many firms, with a direct link to the firm's posting
"""
import html as htmllib
import json
import re
from datetime import date, datetime

from .http import get_text

TRACKR_URL = "https://the-trackr.com/blog/spring-week-timeline-2027-when-uk-finance-firms-open-applications/"
L3VLUP_URL = "https://www.l3vlup.com/intel/spring-weeks"
YFJ_LISTS = {
    "spring-weeks-and-insight-days": "Spring weeks & insight days",
    "summer-internships-list": "Summer internships",
    "student-and-graduate": "Student & graduate",
    "investment-banks": "Investment banks",
    "boutique-advisory": "Boutique advisory",
    "private-equity-firms": "Private equity",
    "france": "France",
    "switzerland": "Suisse",
    "new-this-week": "New this week",
}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _txt(s):
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


# ------------------------------------------------------------------ TrackR
def trackr_programmes():
    """[{company, program, sectors, expected_open, last_open, url}] from TrackR's public timeline article."""
    page = get_text(TRACKR_URL)
    out = []
    for row in re.findall(r'<li class="tl-row">(.*?)</li>', page, re.S):
        name = _txt((re.search(r'class="tl-name">(.*?)</span>', row, re.S) or [None, ""])[1])
        prog = _txt((re.search(r'class="tl-prog">(.*?)</span>', row, re.S) or [None, ""])[1])
        expect = _txt((re.search(r'class="tl-expect">(.*?)</span>', row, re.S) or [None, ""])[1])
        day = _txt((re.search(r'class="tl-date">(.*?)</span>', row, re.S) or [None, ""])[1])
        tags = [_txt(t) for t in re.findall(r'class="tl-tag">(.*?)</span>', row, re.S)]
        link = (re.search(r'class="tl-link" href="([^"]+)"', row) or [None, ""])[1]
        m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})", day)
        y = re.search(r"\b(20\d\d)\b", expect)
        if not (name and prog and m and y):
            continue
        exp = date(int(y.group(1)), MONTHS[m.group(2).lower()], int(m.group(1)))
        out.append({"company": name, "program": prog, "sectors": tags, "expected_open": exp.isoformat(),
                    "last_open": exp.replace(year=exp.year - 1).isoformat(), "url": link, "source": "TrackR"})
    if len(out) < 20:
        raise ValueError(f"article TrackR : seulement {len(out)} programmes lus (mise en page changée ?)")
    return out


# ------------------------------------------------------------------ L3vlUp
def l3vlup_open():
    """[{company, program, closes, url}] for spring weeks L3vlUp marks as open."""
    page = get_text(L3VLUP_URL)
    pairs = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        for el in re.findall(r'"name":"([^"]+? \u2014 [^"]+?|[^"]+? — [^"]+?)","url":"([^"]+)"', block):
            name = json.loads(f'"{el[0]}"')
            firm, prog = name.split(" — ", 1)
            pairs.append((firm.strip(), prog.strip(), el[1]))
    text = _txt(re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S))
    out = []
    for firm, prog, url in pairs:
        m = re.search(re.escape(firm) + r" Open " + re.escape(prog) + r".{0,160}?closes (\d{4}-\d{2}-\d{2})", text)
        if m:
            out.append({"company": firm, "program": prog, "closes": m.group(1), "url": url, "source": "L3vlUp"})
    return out


# ------------------------------------------------------------------ YourFinanceJob (aggregator)
def yourfinancejob(src):
    """source_id: comma-separated list slugs (see YFJ_LISTS). Returns raw jobs with their own company name."""
    slugs = [x.strip() for x in (src.get("source_id") or ",".join(YFJ_LISTS)).split(",") if x.strip()]
    out, seen = [], set()
    for slug in slugs:
        page = get_text(f"https://yourfinancejob.com/lists/{slug}")
        for card in re.split(r'<div class="row\b', page)[1:]:
            title = re.search(r'<span class="t">(.*?)</span>', card, re.S)
            comp = re.search(r'<div class="co"><a[^>]*>(.*?)</a>', card, re.S)
            url = re.search(r'<a class="btn[^"]*apply" href="([^"]+)"', card)
            if not (title and comp and url) or url.group(1) in seen:
                continue
            seen.add(url.group(1))
            loc = re.search(r'<span class="loc"[^>]*>(.*?)</span>', card, re.S)
            kind = re.search(r'<span class="lvl"><span class="tag">(.*?)</span>', card, re.S)
            out.append({"key": url.group(1), "title": _txt(title.group(1)), "company": _txt(comp.group(1)),
                        "location": _txt(loc.group(1)) if loc else "", "url": htmllib.unescape(url.group(1)), "posted": None,
                        "kind": _txt(kind.group(1)) if kind else "", "via": f"YourFinanceJob · {YFJ_LISTS.get(slug, slug)}"})
    if not out:
        raise ValueError("aucune offre lue (mise en page changée ?)")
    return out
