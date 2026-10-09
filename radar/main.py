"""Radar Stages — scans career sites, stores postings, notifies on Telegram.

Usage:
  python3 -m radar scan            # one scan (what GitHub runs every 15 min)
  python3 -m radar test [NAME...]  # test sources without saving anything
  python3 -m radar digest          # send the morning digest now
  python3 -m radar telegram TOKEN  # find your chat id + send a test message
"""
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from . import notify
from .details import analyze, evaluate, fill_details
from .pages import for_dashboard, scan_pages
from .classify import NON_TARGET, STRONG_TARGET, classify, country
from .details import TARGET_TEAMS, is_closed
from .discover import candidates, ids_of, known_ids
from .firms import FirmMatcher, compact
from .pages import load_pages
from .trackers import l3vlup_open, trackr_programmes
from .sources import FETCHERS, workday_posted

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "state.json")
DASH_PATH = os.path.join(ROOT, "docs", "jobs.json")
MISSING_BEFORE_CLOSED = 3     # scans in a row without the posting before we call it closed
KEEP_CLOSED_DAYS = 30
MAX_INSTANT = 10              # above this, new offers are grouped in one message
SCHEMA = 3                    # bump when sources change a lot, to re-seed silently once


def load_config():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("dashboard_url") and os.environ.get("GITHUB_REPOSITORY"):
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
        cfg["dashboard_url"] = f"https://{owner.lower()}.github.io/{repo}/"
    return cfg


def load_companies():
    with open(os.path.join(ROOT, "companies.csv"), encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("name") and not r["name"].startswith("#")]


def load_programmes(state=None, companies=None):
    """Springs & programmes to expect: every programme of TrackR's public timeline (refreshed daily)
    + the extra lines of programmes.csv. Each gets the tracked firm it belongs to (for detection)."""
    rows = []
    path = os.path.join(ROOT, "programmes.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rows = [dict(r, source="manuel", sectors=[]) for r in csv.DictReader(f) if r.get("company") and not r["company"].startswith("#")]
    tr = ((state or {}).get("trackr") or {}).get("rows") or []
    if tr:
        mine = {(compact(r["company"]), norm_title(r["program"])) for r in tr}
        rows = [dict(r, country=r.get("country") or "Royaume-Uni", type=_ptype(r["program"]), keywords="")
                for r in tr] + [r for r in rows if (compact(r["company"]), norm_title(r["program"])) not in mine]
    matcher = FirmMatcher([c["name"] for c in (companies or [])])
    for r in rows:
        r["firm"] = r["company"] if any(c["name"] == r["company"] for c in companies or []) else matcher.match(r["company"])
    return rows


def _ptype(prog):
    p = prog.lower()
    if "summer" in p:
        return "Summer"
    if re.search(r"intern(ship)?\b", p) and not re.search(r"spring|insight|discover|week", p):
        return "Stage"
    return "Spring"


DEFAULT_PROG_WORDS = r"spring|insight|discover|immersion|future leaders|prep|explor|week|possibilit|academy|women|black|heritage|kickstart|open day"


def programme_status(programmes, jobs, companies, today, sources=None, l3=None):
    """Is each expected programme open (seen by the radar or by L3vlUp), coming, or late?"""
    watched = {c["name"] for c in companies if c.get("source") in FETCHERS}
    open_l3 = l3 or []
    out = []
    for p in programmes:
        rx = re.compile(p.get("keywords") or DEFAULT_PROG_WORDS, re.I)
        want = {"Spring": "Spring / Insight", "Summer": "Summer"}.get(p.get("type", "Spring"), "Stage")

        def current_cycle(t):  # "2026 ... Insight Day" belongs to last year's cycle
            years = re.findall(r"20[2-3]\d", t)
            return not years or max(years) >= "2027"

        names = {p.get("firm") or "", p["company"]} - {""}
        cnames = {compact(n) for n in names}
        hits = [j for j in jobs.values() if not j.get("closed") and (j["company"] in names or compact(j["company"]) in cnames)
                and rx.search(j["title"]) and current_cycle(j["title"]) and (j.get("cycle") == want or want == "Stage")]
        l3hit = next((x for x in open_l3 if compact(x["company"]) in cnames or compact(x["company"]) == compact(p.get("firm") or "")), None)
        exp = _d(p.get("expected_open", ""))
        seen_by = []
        if hits:
            status, seen_by = "ouverte", ["Radar"]
        elif l3hit:
            status, seen_by = "ouverte", ["L3vlUp"]
        elif not (names & watched):
            status = "non surveillée"
        elif exp and exp >= today:
            status = "à venir"
        elif any(v.get("fails") for k, v in (sources or {}).items() if k.split("#")[0] in names):
            status = "source indisponible"
        else:
            status = "en retard"
        if hits and l3hit:
            seen_by.append("L3vlUp")
        best = sorted(hits, key=lambda j: j.get("posted") or j["first_seen"])[:1]
        closes = p.get("closes") or (l3hit or {}).get("closes") or (best[0].get("deadline") if best else "") or ""
        out.append(dict(p, status=status, days=(exp - today).days if exp else None, seen_by=seen_by, closes=closes,
                        job_url=best[0]["url"] if best else (l3hit or {}).get("url", ""),
                        job_title=best[0]["title"] if best else ((l3hit or {}).get("program", "") if l3hit else ""),
                        opened=(best[0].get("posted") or (None if best[0].get("seed") else best[0]["first_seen"][:10])) if best else None))
    return out


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"initialized": False, "jobs": {}, "sources": {}, "last_digest": None}


def skey(c):
    """One firm can have several sources (e.g. Evercore US on Oleeo + Evercore London on SmartRecruiters)."""
    return f'{c["name"]}#{c["source"]}#{c.get("source_id") or c.get("source_url")}'


def source_states(state, name):
    return [v for k, v in state["sources"].items() if k.split("#")[0] == name]


def fingerprint(state):
    s = json.loads(json.dumps(state))
    for v in s["sources"].values():
        v.pop("last_ok", None)
        v.pop("raw", None)
        v.pop("suspect", None)
        v.pop("max_raw", None)
    return hashlib.sha1(json.dumps(s, sort_keys=True).encode()).hexdigest()


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_now(cfg):
    tz = ZoneInfo(cfg.get("timezone", "Europe/Paris")) if ZoneInfo else timezone.utc
    return datetime.now(tz)


# ------------------------------------------------------------------ fetching
def fetch_one(c):
    t0 = time.time()
    try:
        raw = FETCHERS[c["source"]](c)
        return c, True, raw, round(time.time() - t0, 1)
    except Exception as e:  # one broken site must never stop the others
        msg = f"{type(e).__name__}: {e}"[:160]
        return c, False, msg, round(time.time() - t0, 1)


def fetch_all(companies):
    active = [c for c in companies if c.get("source") in FETCHERS]
    with cf.ThreadPoolExecutor(20) as ex:
        return list(ex.map(fetch_one, active))


# ------------------------------------------------------------------ scan
def iso_to_dt(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def minutes_since(s):
    d = iso_to_dt(s) if s else None
    return (datetime.now(timezone.utc) - d).total_seconds() / 60 if d else 1e9


def norm_url(u):
    """Same posting, different link (tracking params...): keep host + path + the job id params only."""
    p = urlparse(u or "")
    q = {k: v for k, v in parse_qs(p.query).items() if k in ("gh_jid", "id", "jobId", "job")}
    return f"{p.netloc.lower().replace('www.', '')}{p.path.rstrip('/')}?{sorted(q.items())}"


def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def all_sources(companies, state):
    rows = [dict(c) for c in companies]
    for a in state.get("auto_sources", {}).values():
        rows.append(dict(a, auto=True))
    return rows


INTERN_KINDS = {"Off-Cycle Internship", "Summer Internship", "Working Student"}


def scan(force=None):
    t0 = time.time()
    cfg = load_config()
    companies = load_companies()
    state = load_state()
    before = fingerprint(state)
    first_run = not state["initialized"]
    now = now_iso()
    jobs = state["jobs"]
    new, discovered_links = [], []
    primary = {}
    for c in companies:  # migrate old state keyed by firm name -> per-source key
        k = skey(c)
        primary.setdefault(c["name"], k)
        if k not in state["sources"] and primary[c["name"]] == k and c["name"] in state["sources"]:
            state["sources"][k] = state["sources"].pop(c["name"])
            state["sources"][k].pop("ever_ok", None)

    reseed = state.get("schema") != SCHEMA
    state["schema"] = SCHEMA
    if reseed:  # page filters changed too: compare student pages from scratch, without alerts
        for pg in state.get("pages", {}).values():
            pg.pop("lines", None)
            pg.pop("links", None)

    # Mode: every 5 min the ★ firms only ("fast"); every ~15 min everything ("full"); every hour whole boards ("deep")
    full = force == "full" or (force != "fast" and minutes_since(state.get("last_full")) >= 14)
    deep = full and (force == "deep" or minutes_since(state.get("last_deep")) >= 55)
    mode = "deep" if deep else "full" if full else "fast"
    rows = all_sources(companies, state)
    if not full:
        rows = [r for r in rows if r.get("tier") == "1" and r["source"] != "aggregator"]
    active = []
    for r in rows:
        if deep and r["source"] in ("workday", "oracle"):
            r["deep"] = True
        if not full:
            r["fast"] = True
        s = state["sources"].get(skey(r), {})
        if s.get("cooldown_until", "") > now:  # backing off after an anti-robot check
            continue
        active.append(r)
    print(f"Scan {mode} : {len(active)} sources")

    firm_rows = {c["name"]: c for c in companies}
    matcher = FirmMatcher(list(firm_rows))
    open_jobs = [j for j in jobs.values() if not j.get("closed")]
    url_index = {norm_url(j["url"]): j["id"] for j in open_jobs}
    title_index = {(j["company"], norm_title(j["title"])): j["id"] for j in open_jobs}
    to_check = []  # (job, counts_as_missing) to confirm closed by opening the posting

    results = fetch_all(active)
    results.sort(key=lambda x: x[0]["source"] == "aggregator")  # direct sources first: they win on duplicates
    for c, ok, payload, secs in results:
        name, sk = c["name"], skey(c)
        src = state["sources"].setdefault(sk, {"fails": 0})
        if not ok:
            src["fails"] = min(src.get("fails", 0) + 1, 999)
            src["error"] = payload
            src.setdefault("fail_since", now)
            pause = 45 if "anti-robot" in payload else 10 if "429" in payload else 0
            if pause:  # the site asks us to slow down: skip it for a while instead of insisting
                src["cooldown_until"] = (datetime.now(timezone.utc) + timedelta(minutes=pause)).replace(microsecond=0).isoformat()
            print(f"  ✗ {name:40s} {payload}")
            continue
        prev = src.get("raw") or 0
        if prev >= 10 and len(payload) < prev * 0.5 and src.get("suspect", 0) < 6 and not c.get("deep"):
            src["suspect"] = src.get("suspect", 0) + 1
            print(f"  ? {name:40s} {len(payload)} offres au lieu de ~{prev}, scan ignoré")
            continue
        src.pop("suspect", None)
        src.pop("cooldown_until", None)
        src.pop("fail_since", None)
        seeding = first_run or reseed or (not src.get("ever_ok") and not c.get("auto"))
        src.update({"fails": 0, "error": None, "ever_ok": True, "last_ok": now, "raw": len(payload)})
        src["max_raw"] = max(src.get("max_raw", 0), len(payload))
        if payload:
            src.pop("zero_since", None)
        elif src["max_raw"] > 0:
            src.setdefault("zero_since", now)
        aggregator = c["source"] == "aggregator"
        seen_now = set()
        for r in payload:
            company, cat, tier, hq = name, c["category"], c["tier"], c.get("hq", "")
            title_cls = r["title"]
            if aggregator:
                firm = matcher.match(r.get("company", ""))
                base = firm_rows.get(firm, {})
                company = firm or r.get("company") or "?"
                cat, tier, hq = base.get("category", "Autre (agrégateur)"), base.get("tier", "3"), base.get("hq", "")
                if r.get("kind") in INTERN_KINDS:
                    title_cls = f"{r['title']} ({r['kind']})"
                if firm:
                    discovered_links.append((firm, r["url"], r.get("via", "YourFinanceJob")))
            level, cycle, region = classify(title_cls, cat, r.get("location", ""))
            if not level:
                continue
            jid = hashlib.sha1(f"{company}|{r['key']}".encode()).hexdigest()[:16]
            if aggregator and jid not in jobs:
                other = url_index.get(norm_url(r["url"])) or title_index.get((company, norm_title(r["title"])))
                if other and other != jid:
                    continue  # already watched through the firm's own site
            seen_now.add(jid)
            if jid in jobs:
                j = jobs[jid]
                j.update({"title": r["title"], "url": r["url"], "location": r.get("location", ""), "key": r["key"],
                          "level": level, "cycle": cycle, "region": region, "missing": 0, "skey": sk})
                if r.get("description") and "details" not in j:
                    j["details"] = analyze(clean_html(r["description"]), r["title"])
                for k in ("deadline", "event"):
                    if r.get(k):
                        j[k] = r[k]
                if r.get("posted") and not j.get("posted"):
                    j["posted"] = r["posted"]
                j.pop("closed", None)
                continue
            dup = title_index.get((company, norm_title(r["title"])))
            if r.get("posted") and r["posted"] < (date.today() - timedelta(days=3)).isoformat():
                dup = dup or "old"  # published days ago, just found now (new keyword, deep scan...): not "new"
            jobs[jid] = {
                "id": jid, "company": company, "category": cat, "tier": tier, "hq": hq,
                "title": r["title"], "location": r.get("location", ""), "url": r["url"], "posted": r.get("posted"),
                "level": level, "cycle": cycle, "region": region, "source": "aggregator" if aggregator else c["source"],
                "first_seen": now, "seed": bool(seeding or dup), "missing": 0, "skey": sk, "key": r["key"],
            }
            if aggregator:
                jobs[jid]["via"] = r.get("via", "")
            if r.get("description"):
                jobs[jid]["details"] = analyze(clean_html(r["description"]), r["title"])
            for k in ("deadline", "event"):
                if r.get(k):
                    jobs[jid][k] = r[k]
            title_index[(company, norm_title(r["title"]))] = jid
            url_index[norm_url(r["url"])] = jid
            if not (seeding or dup):
                new.append(jobs[jid])
        # Postings that disappeared: confirm by opening them (big boards outside deep scans only count if confirmed)
        partial = c["source"] in ("workday", "oracle") and not c.get("deep")
        for j in jobs.values():
            if j.get("skey", primary.get(j["company"])) == sk and j["id"] not in seen_now and not j.get("closed"):
                to_check.append((j, not partial))
        print(f"  ✓ {name:40s} {len(payload):4d} offres lues, {len(seen_now):3d} stages ({secs}s)")

    confirm_closures(to_check, now)
    fill_posted_dates(jobs, budget=300 if full else 60)
    fill_details(jobs, budget=150 if full else 40)
    upgraded = upgrade_levels(jobs, now)
    new += [j for j in upgraded if j not in new]

    page_changes, new_sources = [], []
    if full:
        page_changes = scan_pages(state, now, known_titles=[j["title"] for j in jobs.values() if not j.get("closed")])
        for url, p in state.get("pages", {}).items():
            firm = next((x["company"] for x in load_pages() if x["url"] == url), "")
            for link in p.get("ats", []):
                discovered_links.append((firm, link, f"page étudiants {firm}"))
        new_sources = discover_sources(state, companies, discovered_links, now)
        refresh_trackers(state, now)
        state["last_full"] = now
        if deep:
            state["last_deep"] = now

    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_CLOSED_DAYS)).isoformat()
    for jid in [k for k, j in jobs.items() if j.get("closed") and j["closed"] < cutoff]:
        del jobs[jid]
    known = {skey(c) for c in all_sources(companies, state)}
    for k in [k for k in state["sources"] if k not in known]:
        del state["sources"][k]

    if first_run:
        welcome(cfg, jobs)
        state["initialized"] = True
    else:
        instant(cfg, [j for j in new if j["level"] in cfg.get("instant_levels", ["A"])])
        notify_pages(cfg, page_changes)
        notify_sources(cfg, new_sources)
        health_alerts(cfg, state, companies, now)

    lt = local_now(cfg)
    if lt.hour >= cfg.get("digest_hour", 7) and state.get("last_digest") != lt.date().isoformat():
        digest(cfg, state, companies)
        state["last_digest"] = lt.date().isoformat()

    if fingerprint(state) != before or not os.path.exists(DASH_PATH):
        save(state, companies, cfg)
        print(f"État mis à jour ({len(new)} nouvelles offres) en {time.time() - t0:.0f} s.")
    else:
        print(f"Aucun changement ({time.time() - t0:.0f} s).")


def confirm_closures(items, now, budget=40):
    """Open each missing posting once: closed right away if it's gone, otherwise count the miss."""
    checks = [j for j, _ in items if not j.get("close_checked")][:budget]

    def one(j):
        return j, is_closed(j)

    verdict = {}
    with cf.ThreadPoolExecutor(10) as ex:
        for j, v in ex.map(one, checks):
            verdict[j["id"]] = v
    for j, counts in items:
        v = verdict.get(j["id"])
        if v is True:
            j["closed"] = now
            j.pop("close_checked", None)
        elif counts:
            j["missing"] = j.get("missing", 0) + 1
            if v is False:
                j["close_checked"] = True  # still online: don't reopen it every scan, wait for the 3 misses
            if j["missing"] >= MISSING_BEFORE_CLOSED:
                j["closed"] = now


def upgrade_levels(jobs, now):
    """Generic titles ("2027 Summer Analyst") become target offers when the description says M&A, LevFin, PE..."""
    out = []
    for j in jobs.values():
        team = (j.get("details") or {}).get("team")
        years = set(re.findall(r"20[2-3]\d", j["title"]))
        if j.get("closed") or j["level"] != "B" or team not in TARGET_TEAMS or NON_TARGET.search(j["title"]) \
                or (years and not years & {"2027", "2028"}):
            continue
        was = j.get("upgraded")
        j["level"], j["upgraded"] = "A", True
        if not was and not j.get("seed") and minutes_since(j.get("first_seen")) < 180:
            out.append(j)  # notified once, the first time it becomes a target offer
    return out


def discover_sources(state, companies, links, now, budget=6):
    """Platforms seen on student pages / in the aggregator that the radar doesn't read yet: test them, add the good ones."""
    rows = [c for c in companies if c.get("source") in FETCHERS] + list(state.get("auto_sources", {}).values())
    known = known_ids(rows)
    rejected = state.setdefault("rejected_sources", {})
    by_firm = {c["name"]: c for c in companies}
    added, tested = [], 0
    for firm, link, where in links:
        if not firm or firm not in by_firm:
            continue
        for src, sid in candidates([link], known):
            key = f"{src}:{sid}".lower()
            if key in state.get("auto_sources", {}) or minutes_since(rejected.get(key)) < 7 * 24 * 60 or tested >= budget:
                continue
            tested += 1
            row = {"source": src, "source_id": sid, "source_url": ""}
            try:
                got = FETCHERS[src](row)
            except Exception:
                got = []
            if not got:
                rejected[key] = now
                continue
            base = by_firm[firm]
            state.setdefault("auto_sources", {})[key] = {
                "name": firm, "category": base["category"], "tier": base["tier"], "hq": base.get("hq", ""),
                "source": src, "source_id": sid, "source_url": "", "careers_url": base.get("careers_url", ""),
                "found_on": where, "at": now, "count": len(got)}
            known |= {(src, i) for i in ids_of(src, sid)}
            added.append(state["auto_sources"][key])
            print(f"  + Nouvelle source pour {firm} : {src} {sid} ({len(got)} offres) via {where}")
    return added


def notify_sources(cfg, added):
    if not added:
        return
    lines = "\n".join(f"• <b>{notify.esc(a['name'])}</b> — {notify.esc(a['source'])} « {notify.esc(a['source_id'])} » "
                      f"({a['count']} offres), trouvée via {notify.esc(a['found_on'])}" for a in added)
    notify.send(f"🔎 <b>Nouvelle source ajoutée automatiquement</b>\n{lines}\nSes offres ciblées te seront envoyées au prochain scan.")


def health_alerts(cfg, state, companies, now):
    """Tell once when a ★ firm stops answering (or answers 0 offers) for 24 h."""
    stars = {skey(c): c["name"] for c in companies if c["tier"] == "1" and c.get("source") in FETCHERS}
    bad = []
    for k, name in stars.items():
        s = state["sources"].get(k, {})
        since = s.get("fail_since") or s.get("zero_since")
        if since and minutes_since(since) >= 24 * 60:
            if not s.get("alerted"):
                s["alerted"] = True
                bad.append(f"• <b>{notify.esc(name)}</b> — {'erreur : ' + notify.esc((s.get('error') or '')[:80]) if s.get('fail_since') else '0 offre lue depuis 24 h'}")
        else:
            s.pop("alerted", None)
    if bad:
        notify.send("⚠️ <b>Radar : source muette depuis 24 h</b>\n" + "\n".join(bad) + "\nJe la vérifie au prochain passage, ou dis-le à Claude.")


def refresh_trackers(state, now):
    """TrackR article once a day, L3vlUp every 6 hours (public pages, read rarely)."""
    errs = state.setdefault("tracker_errors", {})
    if minutes_since((state.get("trackr") or {}).get("at")) >= 24 * 60:
        try:
            state["trackr"] = {"at": now, "rows": trackr_programmes()}
            errs.pop("TrackR", None)
        except Exception as e:
            errs["TrackR"] = f"{type(e).__name__}: {e}"[:120]
    if minutes_since((state.get("l3vlup") or {}).get("at")) >= 6 * 60:
        try:
            state["l3vlup"] = {"at": now, "rows": l3vlup_open()}
            errs.pop("L3vlUp", None)
        except Exception as e:
            errs["L3vlUp"] = f"{type(e).__name__}: {e}"[:120]


def clean_html(s):
    from .details import clean
    return clean(s)


def notify_pages(cfg, changes):
    if not changes:
        return
    blocks = []
    for c in changes[:8]:
        lines = "\n".join("➕ " + notify.esc(l[:160]) for l in c["added"][:3])
        if not lines:
            lines = "➖ " + notify.esc(c["removed"][0][:160])
        badge = {"ouvert": " · 🟢 candidatures ouvertes", "bientôt": " · 🟡 bientôt", "fermé": " · 🔴 fermé"}.get(c.get("status"), "")
        blocks.append(f'📄 <b>{notify.esc(c["company"])}</b> — <a href="{notify.esc(c["url"])}">{notify.esc(c["label"])}</a>{badge}\n{lines}')
    notify.send("<b>Page étudiants modifiée</b>\n\n" + "\n\n".join(blocks) + dash_link(cfg))


def fill_posted_dates(jobs, budget=300):  # noqa: E302
    """Workday lists only say "Posted 30+ Days Ago": fetch the exact date once per posting."""
    todo = [j for j in jobs.values() if j["source"] == "workday" and not j.get("posted")
            and not j.get("posted_tried") and not j.get("closed")][:budget]
    if not todo:
        return

    def one(j):
        try:
            return j, workday_posted(j["url"])
        except Exception:
            return j, None

    with cf.ThreadPoolExecutor(12) as ex:
        for j, d in ex.map(one, todo):
            j["posted_tried"] = True
            if d:
                j["posted"] = d
    print(f"  Dates de publication récupérées pour {sum(1 for j in todo if j.get('posted'))}/{len(todo)} offres Workday.")


# ------------------------------------------------------------------ messages
def dash_link(cfg):
    return f'\n\n📊 <a href="{cfg["dashboard_url"]}">Tableau de bord</a>' if cfg.get("dashboard_url") else ""


PREFERRED_REGIONS = {"Paris / France": 2, "London / UK": 2, "New York / US": 2, "Suisse": 1, "Corée / Asie": 1}


def relevance(j):
    """Higher = more interesting. Used to order messages."""
    s = {"1": 3, "2": 1}.get(j["tier"], 0) + PREFERRED_REGIONS.get(j.get("region"), 0)
    if STRONG_TARGET.search(j["title"]):
        s += 3
    if j.get("cycle") == "Spring / Insight":
        s += 2
    return s


def sort_key(j):
    return (-relevance(j), j["company"], j["title"])


def diverse(jobs, n, per_company=2):
    out, seen = [], {}
    for j in sorted(jobs, key=sort_key):
        if seen.get(j["company"], 0) < per_company:
            out.append(j)
            seen[j["company"]] = seen.get(j["company"], 0) + 1
        if len(out) == n:
            break
    return out


def welcome(cfg, jobs):
    open_a = [j for j in jobs.values() if j["level"] == "A" and not j.get("closed")]
    n_b = sum(1 for j in jobs.values() if j["level"] == "B" and not j.get("closed"))
    msg = (f"📡 <b>Radar Stages activé !</b>\n{len(open_a)} offres ciblées sont déjà ouvertes "
           f"(+{n_b} autres stages). À partir de maintenant, tu reçois chaque nouvelle offre ciblée dès sa publication.")
    if open_a:
        msg += "\n\n<b>Déjà ouvertes (extrait) :</b>\n\n" + "\n\n".join(notify.job_line(j) for j in diverse(open_a, 25))
    notify.send(msg + dash_link(cfg))


def instant(cfg, new):
    if not new:
        return
    new = sorted(new, key=sort_key)
    if len(new) <= MAX_INSTANT:
        for j in new:
            notify.send("🔥 <b>Nouvelle offre</b>\n" + notify.job_line(j))
    else:
        body = "\n\n".join(notify.job_line(j) for j in new[:30])
        more = f"\n\n… et {len(new) - 30} autres." if len(new) > 30 else ""
        notify.send(f"🔥 <b>{len(new)} nouvelles offres ciblées</b>\n\n{body}{more}{dash_link(cfg)}")


def _d(s):
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def digest(cfg, state, companies):
    lt = local_now(cfg)
    today = lt.date()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    fresh = [j for j in state["jobs"].values() if not j.get("seed") and j["first_seen"] >= since]
    a = sorted([j for j in fresh if j["level"] == "A"], key=sort_key)
    b = sorted([j for j in fresh if j["level"] == "B"], key=sort_key)
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    msg = f"☀️ <b>Radar du {jours[today.weekday()]} {today.strftime('%d/%m')}</b>\n"
    if a or b:
        msg += f"{len(a)} nouvelle(s) offre(s) ciblée(s) et {len(b)} autre(s) stage(s) en 24 h."
    else:
        msg += "Rien de nouveau ces dernières 24 h."
    if a:
        msg += "\n\n<b>🎯 Ciblées</b>\n\n" + "\n\n".join(notify.job_line(j) for j in a[:20])
    if b:
        msg += "\n\n<b>Autres stages</b>\n" + "\n".join("• " + notify.job_line(j, False) for j in b[:10])

    soon = []
    for p in programme_status(load_programmes(state, companies), state["jobs"], companies, today, state["sources"], (state.get("l3vlup") or {}).get("rows")):
        closes = _d(p.get("closes", ""))
        label = f'<b>{notify.esc(p["company"])}</b> — {notify.esc(p["program"])}'
        link = p.get("job_url") or p.get("url")
        if link:
            label = f'<a href="{notify.esc(link)}">{label}</a>'
        if closes and 0 <= (closes - today).days <= 14:
            soon.append(((closes - today).days, f"⏰ J-{(closes - today).days} · ferme le {closes.strftime('%d/%m')} · {label}"))
        elif p["status"] in ("à venir", "non surveillée") and p["days"] is not None and 0 <= p["days"] <= 7:
            soon.append((p["days"], f"🟡 attendue vers le {_d(p['expected_open']).strftime('%d/%m')} (l'an dernier : {_d(p['last_open']).strftime('%d/%m/%Y')}) · {label}"))
    for j in state["jobs"].values():
        dl = _d(j.get("deadline") or "")
        if j["level"] == "A" and not j.get("closed") and dl and 0 <= (dl - today).days <= 7:
            soon.append(((dl - today).days, f"⏰ J-{(dl - today).days} · {notify.job_line(j, False)}"))
    if soon:
        msg += "\n\n<b>Deadlines & ouvertures attendues</b>\n" + "\n".join(s for _, s in sorted(soon)[:20])

    broken = sorted({k.split("#")[0] for k, s in state["sources"].items() if s.get("fails", 0) >= 4})
    if broken:
        msg += f"\n\n⚠️ {len(broken)} source(s) en panne : " + notify.esc(", ".join(broken[:12])) + ("…" if len(broken) > 12 else "")
    notify.send(msg + dash_link(cfg))


# ------------------------------------------------------------------ files
def save(state, companies, cfg):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(DASH_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=0, sort_keys=True)
    recent = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    jobs = [j for j in state["jobs"].values() if not j.get("closed") or j["closed"] >= recent]
    comp, by_name = [], {}
    for c in companies:
        s = state["sources"].get(skey(c), {})
        status = ("manuel" if c.get("source") not in FETCHERS else
                  "ok" if s.get("ever_ok") and not s.get("fails") else
                  "en panne" if s.get("fails") else "en attente")
        if c["name"] in by_name:  # second source of the same firm
            e = by_name[c["name"]]
            e["source"] += " + " + c["source"]
            if status == "en panne" or e["status"] == "manuel":
                e["status"], e["error"] = status, s.get("error") or e["error"]
            continue
        e = {"name": c["name"], "category": c["category"], "tier": c["tier"], "hq": c.get("hq", ""),
             "source": c.get("source", ""), "careers_url": c.get("careers_url", ""), "status": status,
             "error": s.get("error"), "country": country(c.get("hq", "")),
             "open": sum(1 for j in jobs if j["company"] == c["name"] and not j.get("closed"))}
        by_name[c["name"]] = e
        comp.append(e)
    out, groups = [], {}
    for j in sorted(jobs, key=lambda x: (x.get("source") == "aggregator", x["first_seen"])):
        g = (j["company"], norm_title(j["title"]), norm_title(j.get("location", "")))
        if g in groups and not j.get("closed"):
            continue  # same offer listed twice (two boards, aggregator...): keep the first one
        groups[g] = True
        det = j.get("details") or {}
        j = {k: v for k, v in j.items() if k not in ("missing", "posted_tried", "details_tried", "skey", "key", "close_checked")}
        j["score"] = relevance(j)
        j["country"] = country(j.get("location", ""), j["title"]) or det.get("country", "")
        if not j.get("deadline") and det.get("deadline"):
            j["deadline"] = det["deadline"]
        if det.get("team"):
            j["team"] = det["team"]
        j["elig"] = evaluate(j, cfg.get("profile", {}))
        # Publication date: the site's own date if known, else when the radar first saw it (unknown for launch-day offers).
        j["published"] = j.get("posted") or (None if j.get("seed") else j["first_seen"][:10])
        out.append(j)
    out.sort(key=lambda j: (j["published"] or "", j["score"]), reverse=True)
    today = local_now(cfg).date()
    with open(DASH_PATH, "w", encoding="utf-8") as f:
        json.dump({"updated": now_iso(), "jobs": out, "companies": comp, "perf": perf(state, companies),
                   "programmes": programme_status(load_programmes(state, companies), state["jobs"], companies, today, state["sources"], (state.get("l3vlup") or {}).get("rows")),
                   "pages": for_dashboard(state)},
                  f, ensure_ascii=False, separators=(",", ":"))


def perf(state, companies):
    """Health of the radar, shown in Infos générales."""
    rows = all_sources(companies, state)
    stars = {skey(c) for c in rows if c.get("tier") == "1"}
    silent, failing = [], []
    for c in rows:
        s = state["sources"].get(skey(c), {})
        if c.get("source") not in FETCHERS:
            continue
        if s.get("fails"):
            failing.append({"name": c["name"], "source": c["source"], "error": (s.get("error") or "")[:100], "star": skey(c) in stars})
        elif s.get("ever_ok") and not s.get("raw") and c["source"] != "watch":
            silent.append({"name": c["name"], "source": c["source"], "star": skey(c) in stars, "since": s.get("zero_since")})
    lat = []
    for j in state["jobs"].values():
        if not j.get("seed") and j.get("posted") and j.get("first_seen"):
            lat.append((date.fromisoformat(j["first_seen"][:10]) - date.fromisoformat(j["posted"][:10])).days)
    A = [j for j in state["jobs"].values() if j["level"] == "A" and not j.get("closed")]
    return {"last_full": state.get("last_full"), "last_deep": state.get("last_deep"),
            "same_day": [sum(1 for x in lat if x <= 0), len(lat)],
            "failing": failing, "silent": silent,
            "auto_sources": [{k: a[k] for k in ("name", "source", "source_id", "found_on", "at", "count")} for a in state.get("auto_sources", {}).values()],
            "details": [sum(1 for j in A if j.get("details")), len(A)],
            "trackers": {"TrackR": (state.get("trackr") or {}).get("at"), "L3vlUp": (state.get("l3vlup") or {}).get("at"),
                         "errors": state.get("tracker_errors", {})},
            "sources_total": sum(1 for c in rows if c.get("source") in FETCHERS)}


# ------------------------------------------------------------------ CLI helpers
def test(names):
    companies = [c for c in load_companies() if not names or any(n.lower() in c["name"].lower() for n in names)]
    results = fetch_all(companies)
    ok = 0
    for c, good, payload, secs in sorted(results, key=lambda r: r[0]["name"]):
        if not good:
            print(f"✗ {c['name']:38s} [{c['source']}] {payload}")
            continue
        ok += 1
        cls = [(classify(r["title"], c["category"], r.get("location", "")), r) for r in payload]
        a = [r for (lv, _, _), r in cls if lv == "A"]
        b = [r for (lv, _, _), r in cls if lv == "B"]
        print(f"✓ {c['name']:38s} [{c['source']}] {len(payload):4d} lues · {len(a)} ciblées · {len(b)} autres ({secs}s)")
        for r in a[:3]:
            print(f"      🎯 {r['title'][:90]}  ({r.get('location', '')[:30]})")
    print(f"\n{ok}/{len(results)} sources OK")


def telegram_setup(token):
    from .http import get_json
    me = get_json(f"https://api.telegram.org/bot{token}/getMe")["result"]
    print(f"Bot trouvé : @{me['username']}")
    ups = get_json(f"https://api.telegram.org/bot{token}/getUpdates")["result"]
    chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "") for u in ups if "message" in u}
    if not chats:
        print("Aucun message reçu : ouvre ton bot dans Telegram, appuie sur « Démarrer » (ou envoie-lui « salut »), puis relance cette commande.")
        return
    for cid, who in chats.items():
        print(f"\n➡️  TELEGRAM_CHAT_ID = {cid}   ({who})")
        os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"] = token, str(cid)
        notify.send("✅ Radar Stages est bien connecté à ton Telegram !")
    print("\nMessage de test envoyé. Copie ce numéro, il servira pour GitHub.")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "scan"
    if cmd == "scan":
        scan(argv[2].lstrip("-") if len(argv) > 2 else None)
    elif cmd == "test":
        test(argv[2:])
    elif cmd == "digest":
        cfg, state = load_config(), load_state()
        digest(cfg, state, load_companies())
    elif cmd == "telegram" and len(argv) > 2:
        telegram_setup(argv[2])
    else:
        print(__doc__)
