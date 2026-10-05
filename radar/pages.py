"""Watch "Students & Graduates" pages: what they say about applications, and when it changes."""
import concurrent.futures as cf
import csv
import html as htmllib
import os
import re

from .http import get_text

KEYWORDS = re.compile(r"appl(y|ication)|deadline|opens?\b|opening|clos(e|ed|es|ing)\b|spring|summer|intern|insight|off[- ]?cycle"
                      r"|programme|candidat|stage|rolling|recruit|inscri|register|graduate programme|eligib", re.I)
NOISE = re.compile(r"cookie|navigation|menu|search box|online banking|leaving|mobile app|privacy|javascript|subscribe"
                   r"|newsletter|insights and services|featured insight|explore insights|log ?in|sign ?in|skip to"
                   r"|opens in new window|copyright|©|all rights reserved|applications mobiles|mobile applications|</?\w+>|\\r\\n", re.I)
COUNTER = re.compile(r"^[\w &,'/().-]{2,45}\s\d{1,4}$")  # "Banking & International 77": job counters change all the time

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


def page_lines(url):
    page = get_text(url)
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


def scan_pages(state, now):
    """Fetch every page, update state["pages"], return the list of changes (for notifications)."""
    pages = load_pages()
    store = state.setdefault("pages", {})

    def one(p):
        try:
            return p, page_lines(p["url"]), None
        except Exception as e:
            return p, None, f"{type(e).__name__}: {e}"[:120]

    changes = []
    with cf.ThreadPoolExecutor(12) as ex:
        for p, lines, err in ex.map(one, pages):
            s = store.setdefault(p["url"], {"history": []})
            if err or not lines:
                s["fails"] = min(s.get("fails", 0) + 1, 99)
                s["error"] = err or "page vide (contenu chargé en JavaScript ?)"
                continue
            old = s.get("lines")
            status, key = summarize(lines)
            s.update({"fails": 0, "error": None, "lines": lines, "status": status, "highlights": key})
            if old is None:  # first time we read it: nothing to compare with
                s["since"] = now
                continue
            added = [l for l in lines if l not in old]
            removed = [l for l in old if l not in lines]
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
