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


def main(dry_run: bool = False) -> int:
    user, pw = os.environ.get("NEWS_USER"), os.environ.get("NEWS_PASS")
    if not (user and pw):
        print("newsletters: no NEWS_USER/NEWS_PASS, skipping")
        return 0
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(user, pw.replace(" ", ""))
    m.select("INBOX")
    _, data = m.search(None, "UNSEEN")
    ids = data[0].split()[:MAX_PER_RUN]
    print(f"newsletters: {len(ids)} unread")
    hits = []
    for i in ids:
        _, raw = m.fetch(i, "(BODY.PEEK[])")
        msg = email.message_from_bytes(raw[0][1])
        subj, frm = dec(msg.get("Subject")), dec(msg.get("From"))
        text = body_text(msg)
        c = classify(subj, text)
        if c:
            hits.append({"from": frm, "subject": subj, "c": c, "snip": snippet(text, c["biz"]),
                         "msgid": (msg.get("Message-ID") or "").strip("<>")})
        if not dry_run:
            m.store(i, "+FLAGS", "\\Seen")
    m.logout()
    if not hits:
        return 0
    hits.sort(key=lambda h: not h["c"]["israel"])
    cards = ""
    for h in hits:
        link = (f"https://mail.google.com/mail/u/?authuser={quote(user)}#search/rfc822msgid%3A{quote(h['msgid'])}"
                if h["msgid"] else "https://mail.google.com/")
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
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
