"""Telegram notifications. Without TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID the
messages are printed instead (handy for local tests)."""
import html
import os
import time

from .http import post_json

MAX_LEN = 3900  # Telegram hard limit is 4096


def esc(s):
    return html.escape(s or "", quote=False)


def send(text):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("---- [Telegram désactivé, message affiché ici] ----\n" + text + "\n")
        return
    for chunk in _chunks(text):
        post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                  {"chat_id": chat, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True})
        time.sleep(0.4)


def _chunks(text):
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > MAX_LEN and cur:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n\n{block}" if cur else block
    return parts + ([cur] if cur else [])


def job_line(j, with_meta=True):
    star = "⭐ " if j["tier"] == "1" else ""
    s = f'{star}<b>{esc(j["company"])}</b> — <a href="{esc(j["url"])}">{esc(j["title"])}</a>'
    if with_meta:
        bits = [b for b in [j.get("location") or j.get("region"), j.get("cycle"), j.get("category")] if b]
        s += "\n📍 " + esc(" · ".join(bits))
        dates = []
        if j.get("posted"):
            dates.append("publiée le " + _fr(j["posted"]))
        if j.get("deadline"):
            dates.append("⏰ deadline " + _fr(j["deadline"]))
        if dates:
            s += "\n🗓 " + " · ".join(dates)
    return s


MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def _fr(iso):
    try:
        y, m, d = iso[:10].split("-")
        return f"{int(d)} {MOIS[int(m) - 1]}"
    except Exception:
        return iso
