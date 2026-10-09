"""Watch "Students & Graduates" pages: what they say about applications, and when it changes."""
import concurrent.futures as cf
import csv
import html as htmllib
import os
import re

from .http import get_text

KEYWORDS = re.compile(r"\bappl(y|ication|ications)\b|deadline|\bopens?\b|\bopening\b|\bclos(e|ed|es|ing)\b|\bspring\b|\bsummer\b"
                      r"|\bintern(s|ship|ships)?\b|\binsight (day|days|week|programme|program|event)s?\b|spring insight|off[- ]?cycle"
                      r"|\bprogramme\b|\bcandidat|\bstages?\b|\brolling basis\b|\brecruit|\binscri|\bregist(er|ration)\b"
                      r"|graduate programme|\beligib", re.I)
NOISE = re.compile(r"cookie|navigation|menu|search box|online banking|leaving|mobile app|privacy|javascript|subscribe"
                   r"|newsletter|insights and services|featured insight|explore insights|log ?in|sign ?in|skip to"
                   r"|opens in new window|copyright|©|all rights reserved|applications mobiles|mobile applications|</?\w+>|\\r\\n"
                   r"|\((m/f|h/f|f/m|f/h|m/w/d)\)|financial advisor to|acquisition of|announced:|conference|webinar replay|press release", re.I)
COUNTER = re.compile(r"(^[\w &,'/().-]{2,45}\s\d{1,4}$)|(\s\d{1,3}$)|(^\d{4,6}\s)")  # "Banking & International 77": job counters change all the time

OPEN = re.compile(r"(?<!when )(?<!once )(?<!until )applications? (are |is )?(now )?open\b|now open|now accepting|apply now|candidatures? (sont )?ouvertes|"
                  r"applications open:|currently accepting|we are now recruiting", re.I)
SOON = re.compile(r"(will|to) open|opening (soon|in|on)|opens (in|on)|open later|coming soon|register (your )?interest|"
                  r"keep informed|notify me|ouverture (prochaine|en)|bientôt", re.I)
CLOSED = re.compile(r"applications? (are |have )?(now )?closed|closed for (applications|20)|no longer accepting|candidatures? (sont )?fermées", re.I)
DATE = re.compile(r"\b(\d{1,2}(st|nd|rd|th)?\s+)?(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sept?(ember)?|oct(ober)?"
                  r"|nov(ember)?|dec(ember)?|janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)"
                  r"\s*(\d{1,2}(st|nd|rd|th)?,?\s*)?20\d\d\b", re.I)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_HISTORY = 8


def load_pages():
    path = os.path.join(ROOT, "pages.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("url") and not r["company"].startswith("#")]


LINK_WORDS = re.compile(r"apply|application|spring|insight|intern|summer|off[- ]?cycle|programme|program|graduate|student|"
                        r"candidat|stage|event|register|discover|early career", re.I)
ATS = re.compile(r"myworkdayjobs\.com|greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|smrtr\.io|\.tal\.net|"
                 r"oraclecloud\.com/hcmUI|teamtailor\.com|recruitee\.com|pinpointhq\.com|workable\.com|avature\.net|icims\.com|"
                 r"successfactors|jobs2web|eightfold\.ai|brassring|taleo\.net", re.I)


def page_links(url, raw):
    """Links worth watching (programme / apply pages) + links to recruiting platforms (for source discovery)."""
    from urllib.parse import urljoin
    links, ats = {}, set()
    for href, text in re.findall(r'<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', raw, re.S | re.I):
        full = urljoin(url, htmllib.unescape(href))
        label = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()
        if ATS.search(full):
            ats.add(full)
        if full.startswith("http") and 3 <= len(label) <= 120 and (LINK_WORDS.search(label) or LINK_WORDS.search(full)) \
                and not NOISE.search(label):
            links[full] = label
    return links, sorted(ats)


def page_lines(url, raw=None):
    page = raw if raw is not None else get_text(url)
    page = re.sub(r"<(script|style|noscript|svg|head|nav|footer|header)\b.*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<(br|p|/p|div|/div|li|/li|h\d|/h\d|tr|/tr|section|/section|td|/td|dt|dd)\b[^>]*>", "\n", page, flags=re.I)
    page = re.sub(r"<[^>]*>", " ", page)
    out, seen = [], set()
    for line in page.split("\n"):
        line = re.sub(r"\s+", " ", htmllib.unescape(line)).strip()
        if not (15 <= len(line) <= 400) or line.lower() in seen:
            continue
        seen.add(line.lower())
        if KEYWORDS.search(line) and not NOISE.search(line) and not COUNTER.match(line):
            out.append(line)
    return out[:120]


def summarize(lines):
    """Status + the few lines worth reading (opening/closing info, dates)."""
    status = ""
    for rx, name in ((OPEN, "ouvert"), (CLOSED, "fermé"), (SOON, "bientôt")):
        if any(rx.search(l) for l in lines):
            status = name
            break
    key = [l for l in lines if OPEN.search(l) or SOON.search(l) or CLOSED.search(l) or DATE.search(l)
           or re.search(r"deadline|rolling basis|applications?", l, re.I)]
    return status, key[:8]


def _n(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())


def scan_pages(state, now, known_titles=()):
    """Fetch every page, update state["pages"], return the list of changes (for notifications).
    Lines that are just the title of an offer the radar already tracks are ignored (no double alert)."""
    pages = load_pages()
    known = {_n(t) for t in known_titles}
    store = state.setdefault("pages", {})

    def one(p):
        try:
            raw = get_text(p["url"])
            return p, (page_lines(p["url"], raw), page_links(p["url"], raw)), None
        except Exception as e:
            return p, None, f"{type(e).__name__}: {e}"[:120]

    changes = []
    with cf.ThreadPoolExecutor(12) as ex:
        for p, got, err in ex.map(one, pages):
            lines, (links, ats) = (got if got else (None, ({}, [])))
            if lines:
                lines = [l for l in lines if not any(k and k in _n(l) for k in known if len(k) > 12)] or lines[:1]
            s = store.setdefault(p["url"], {"history": []})
            s["ats"] = ats
            if err or not lines:
                s["fails"] = min(s.get("fails", 0) + 1, 99)
                s["error"] = err or "page vide (contenu chargé en JavaScript ?)"
                continue
            old, old_links = s.get("lines"), s.get("links")
            status, key = summarize(lines)
            s.update({"fails": 0, "error": None, "lines": lines, "status": status, "highlights": key, "links": links})
            if old is None:  # first time we read it: nothing to compare with
                s["since"] = now
                continue
            added = [l for l in lines if l not in old]
            removed = [l for l in old if l not in lines]
            if old_links is not None:  # a new link to a programme / application page
                added += [f"🔗 Nouveau lien : {t}" for u, t in links.items() if u not in old_links][:4]
            if added or removed:
                event = {"at": now, "added": added[:8], "removed": removed[:8]}
                s["history"] = ([event] + s.get("history", []))[:MAX_HISTORY]
                s["last_change"] = now
                changes.append(dict(p, **event, status=status))
    known = {p["url"] for p in pages}
    for url in [u for u in store if u not in known]:
        del store[url]
    return changes


def for_dashboard(state):
    out = []
    for p in load_pages():
        s = state.get("pages", {}).get(p["url"], {})
        out.append({"company": p["company"], "label": p.get("label", ""), "url": p["url"],
                    "status": s.get("status", ""), "highlights": s.get("highlights", []),
                    "last_change": s.get("last_change"), "since": s.get("since"), "history": s.get("history", [])[:5],
                    "ok": not s.get("fails") and "lines" in s, "error": s.get("error")})
    return out
