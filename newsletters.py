"""Reads the dedicated newsletter Gmail (IMAP) and emails a digest of business class promos.

Secrets: NEWS_USER (the dedicated Gmail address), NEWS_PASS (its app password).
Unread messages are read once and then marked as read. Matches are sent to MAIL_TO /
SMTP_USER through notify._send. Without the secrets this does nothing.
"""
from __future__ import annotations

import email
import html
import imaplib
import os
import re
import sys
from email.header import decode_header, make_header
from urllib.parse import quote

import notify

BUSINESS = ["business class", "business", "ביזנס", "מחלקת עסקים", "premium", "first class", "upgrade"]
PROMO = ["sale", "offer", "deal", "promo", "discount", "save", "special fare", "special price", "from $",
         "from usd", "from €", "%", "מבצע", "הנחה", "מחיר מיוחד", "flash"]
ISRAEL = ["tel aviv", "israel", "tlv", "תל אביב", "ישראל"]
MAX_PER_RUN = 60
CONFIRM = re.compile(r"(confirm|verify|activate|validate|double opt|אישור|אשר)", re.I)
# Free deal-site feeds that load without a bot check (Secret Flying is behind Cloudflare).
FEEDS = {"Fly4free": "https://www.fly4free.com/feed/"}
FEED_WORDS = ["business", "tel aviv", "israel", "larnaca", "cyprus", "ביזנס"]


def dec(s) -> str:
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:
        return s or ""


def body_text(msg) -> str:
    parts = []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ("text/plain", "text/html") or part.get("Content-Disposition", "").startswith("attachment"):
            continue
        try:
            t = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if ct == "text/html":
            t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
            t = html.unescape(re.sub(r"<[^>]+>", " ", t))
        parts.append(t)
    return re.sub(r"\s+", " ", " ".join(parts))


def snippet(text: str, words: list[str], n: int = 220) -> str:
    low = text.lower()
    for w in words:
        i = low.find(w)
        if i >= 0:
            a = max(0, i - n // 2)
            return ("…" if a else "") + text[a:a + n].strip() + "…"
    return text[:n] + "…"


def classify(subject: str, text: str) -> dict | None:
    low = (subject + " " + text).lower()
    biz = [w for w in BUSINESS if w in low]
    promo = [w for w in PROMO if w in low]
    if not biz or not promo:
        return None
    return {"biz": biz, "promo": promo, "israel": any(w in low for w in ISRAEL)}


def check_feeds(dry_run: bool) -> None:
    """RSS of deal sites: new posts that mention business class or Israel/Cyprus."""
    import json
    import urllib.request
    from pathlib import Path
    seen_f = Path(__file__).parent / "data" / "feeds_seen.json"
    try:
        seen = set(json.loads(seen_f.read_text()))
    except (FileNotFoundError, ValueError):
        seen = set()
    first_run = not seen
    hits = []
    for name, url in FEEDS.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "biz-fare-alert (personal RSS reader)"})
            xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        except Exception as e:
            print(f"feed {name}: {e}")
            continue
        for item in re.findall(r"(?s)<item>(.*?)</item>", xml):
            link = (re.search(r"<link>(.*?)</link>", item) or [None, ""])[1].strip()
            title = html.unescape((re.search(r"(?s)<title>(.*?)</title>", item) or [None, ""])[1]).strip()
            desc = html.unescape(re.sub(r"<[^>]+>", " ", (re.search(r"(?s)<description>(.*?)</description>", item) or [None, ""])[1]))
            if not link or link in seen:
                continue
            seen.add(link)
            low = (title + " " + desc).lower()
            if not first_run and any(w in low for w in FEED_WORDS):
                hits.append((name, title, link))
    seen_f.parent.mkdir(exist_ok=True)
    seen_f.write_text(json.dumps(sorted(seen)[-500:]))
    print(f"feeds: {len(hits)} matching new posts")
    if hits:
        rows = "".join(
            f'<tr><td style="padding:8px 0;border-top:1px solid {notify.LINE};{notify.FONT}font-size:14px">'
            f'<span style="color:{notify.MUTED}">{html.escape(n)}</span><br>{notify.ltr(t)}<br>'
            f'{notify.button("לפוסט", l)}</td></tr>' for n, t, l in hits)
        body = (f'<div style="{notify.FONT}font-size:20px;font-weight:bold;margin:0 4px 12px">📰 דילים מאתרי מציאות</div>'
                f'<table role="presentation" width="100%" style="background:#fff;border:1px solid {notify.LINE};'
                f'border-radius:12px;padding:6px 14px">{rows}</table>')
        notify._send(f"📰 דילים מאתרי מציאות: {len(hits)}", notify.page(body, hits[0][1]), dry_run)


def main(dry_run: bool = False) -> int:
    check_feeds(dry_run)
    user, pw = os.environ.get("NEWS_USER"), os.environ.get("NEWS_PASS")
    if not (user and pw):
        print("newsletters: no NEWS_USER/NEWS_PASS, skipping")
        return 0
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(user, pw.replace(" ", ""))
    # INBOX includes Gmail's Promotions/Updates tabs. Spam is a separate folder; find it by
    # its \\Junk flag (its name depends on the account language).
    folders = ["INBOX"]
    _, lst = m.list()
    for row in lst or []:
        row = row.decode(errors="replace")
        if "\\Junk" in row:
            folders.append(row.rsplit(' "/" ', 1)[-1].strip())
    hits = []
    for folder in folders:
        m.select(folder)
        _, data = m.search(None, "UNSEEN")
        ids = data[0].split()[:MAX_PER_RUN]
        print(f"newsletters: {folder}: {len(ids)} unread")
        hits += read_folder(m, ids, dry_run)
    m.logout()
    finish(hits, user, dry_run)
    return 0


def read_folder(m, ids, dry_run: bool) -> list[dict]:
    hits = []
    for i in ids:
        _, raw = m.fetch(i, "(BODY.PEEK[])")
        msg = email.message_from_bytes(raw[0][1])
        subj, frm = dec(msg.get("Subject")), dec(msg.get("From"))
        text = body_text(msg)
        c = classify(subj, text)
        if not c and CONFIRM.search(subj):
            c = {"biz": [], "promo": [], "israel": False, "confirm": True}
        if c:
            hits.append({"from": frm, "subject": subj, "c": c, "snip": snippet(text, c["biz"]),
                         "msgid": (msg.get("Message-ID") or "").strip("<>")})
        if not dry_run:
            m.store(i, "+FLAGS", "\\Seen")
    return hits


def finish(hits: list[dict], user: str, dry_run: bool) -> None:
    if not hits:
        return
    hits.sort(key=lambda h: not h["c"]["israel"])
    cards = ""
    for h in hits:
        link = (f"https://mail.google.com/mail/u/?authuser={quote(user)}#search/rfc822msgid%3A{quote(h['msgid'])}"
                if h["msgid"] else "https://mail.google.com/")
        if h["c"].get("confirm"):
            h["snip"] = "מייל אישור הרשמה. צריך להיכנס לתיבה וללחוץ על הקישור שבו."
        tag = (' <span style="background:#d1fae5;color:#047857;font-size:12px;padding:2px 8px;border-radius:10px">'
               'מזכיר את ישראל</span>') if h["c"]["israel"] else ""
        cards += (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;'
            f'border:1px solid {notify.LINE};border-radius:12px;margin-bottom:12px;border-collapse:separate">'
            f'<tr><td style="padding:14px 16px;{notify.FONT}font-size:14px;color:{notify.INK}">'
            f'<div style="color:{notify.MUTED};font-size:12px">{html.escape(h["from"])}</div>'
            f'<div style="font-size:16px;font-weight:bold;margin:4px 0">{notify.ltr(h["subject"]) if h["subject"].isascii() else html.escape(h["subject"])}{tag}</div>'
            f'<div dir="auto" style="color:{notify.MUTED}">{html.escape(h["snip"])}</div>'
            f'<div style="margin-top:8px">{notify.button("לפתוח את המייל", link, primary=True)}</div>'
            f'</td></tr></table>')
    head = (f'<div style="{notify.FONT}font-size:20px;font-weight:bold;color:{notify.INK};margin:0 4px 12px">'
            f'📬 מבצעי ביזנס בניוזלטרים ({len(hits)})</div>')
    notify._send(f"📬 מבצעי ביזנס בניוזלטרים: {len(hits)}", notify.page(head + cards, hits[0]["subject"]), dry_run)


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
