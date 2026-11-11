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
import news_ai
import json as _json
from datetime import datetime, timedelta, timezone
from pathlib import Path

PENDING_F = Path(__file__).parent / "data" / "pending_news.json"
UIDS_F = Path(__file__).parent / "data" / "news_uids.json"
STATS_F = Path(__file__).parent / "data" / "news_stats.json"


def queue(kind: str, title: str, html_block: str) -> None:
    """Newsletter / feed items wait for the daily digest (digest.py) instead of a mail each."""
    try:
        items = _json.loads(PENDING_F.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        items = []
    items.append({"kind": kind, "title": title, "html": html_block,
                  "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    PENDING_F.parent.mkdir(exist_ok=True)
    PENDING_F.write_text(_json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


LOG_F = Path(__file__).parent / "data" / "news_log.json"


def log_items(items: list[dict]) -> None:
    """Last 60 matched newsletter / feed items, for the status page."""
    try:
        log = _json.loads(LOG_F.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        log = []
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log += [{**x, "at": at} for x in items]
    LOG_F.write_text(_json.dumps(log[-60:], ensure_ascii=False, indent=1), encoding="utf-8")


def add_stats(read: int, matched: int, senders: list[str]) -> None:
    try:
        st = _json.loads(STATS_F.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        st = {}
    day = datetime.now(timezone.utc).date().isoformat()
    d = st.setdefault(day, {"read": 0, "matched": 0, "senders": {}})
    d["read"] += read
    d["matched"] += matched
    for x in senders:
        name = re.sub(r"\s*<.*", "", x).strip('" ') or x
        d["senders"][name] = d["senders"].get(name, 0) + 1
    st = dict(sorted(st.items())[-30:])
    STATS_F.write_text(_json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")

# Not the bare word "business": newsletters have it in footers ("business address", "for business").
BUSINESS = ["business class", "business fare", "business cabin", "fly business", "in business",
            "business from", "ביזנס", "מחלקת עסקים", "מחלקה עסקית", "first class"]
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


PRICE = re.compile(r"(?:[$€£₪]\s?\d[\d,.]*|\d[\d,.]*\s?(?:usd|eur|ils|nis|ש\"ח|שח|₪|\$|€))", re.I)
WELCOME = re.compile(r"(welcome|thanks for (signing|subscrib)|thank you for (signing|subscrib)|ברוכים|תודה שנרשמת)", re.I)
NEAR = 200  # a business word and a price within this many characters


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"https?://\S+|\S{40,}", " ", text))


def classify(subject: str, text: str) -> dict | None:
    """Business class promo = a business-class word with a price close to it (not just
    both words somewhere in the mail: footers and welcome mails matched before, 6/11)."""
    if WELCOME.search(subject):
        return None
    body = clean(subject + " . " + text)
    low = body.lower()
    prices = [m.start() for m in PRICE.finditer(low)]
    for w in BUSINESS:
        for m in re.finditer(re.escape(w), low):
            if any(abs(p - m.start()) <= NEAR for p in prices):
                return {"biz": [w], "promo": [], "israel": any(x in low for x in ISRAEL), "at": m.start(),
                        "text": body}
    return None


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
        queue("feed", hits[0][1], rows)
        log_items([{"kind": "feed", "from": n, "subject": t, "link": l} for n, t, l in hits])


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
    # 11/11: track the last message UID per folder instead of "unread". Before, anyone
    # opening the dedicated inbox (marking mail as read) made the bot skip those mails.
    try:
        seen = _json.loads(UIDS_F.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        seen = {}
    hits, total_read = [], 0
    senders_all.clear()
    for folder in folders:
        _, sel = m.select(folder, readonly=True)
        _, v = m.response("UIDVALIDITY")
        validity = (v[0] or b"").decode() if v and v[0] else ""
        st = seen.get(folder, {})
        if st.get("validity") == validity and st.get("last"):
            _, data = m.uid("search", None, f"UID {int(st['last']) + 1}:*")
        else:  # first time: the last 7 days
            since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d-%b-%Y")
            _, data = m.uid("search", None, f"SINCE {since}")
        uids = [u for u in data[0].split() if not st.get("last") or int(u) > int(st["last"])][:MAX_PER_RUN]
        print(f"newsletters: {folder}: {len(uids)} new")
        hits += read_folder(m, uids, dry_run)
        total_read += len(uids)
        if uids and not dry_run:
            seen[folder] = {"validity": validity, "last": int(uids[-1])}
        elif not st and not dry_run:
            seen[folder] = {"validity": validity, "last": 0}
    m.logout()
    if not dry_run:
        UIDS_F.write_text(_json.dumps(seen, indent=1), encoding="utf-8")
    add_stats(total_read, len(hits), senders_all)
    finish(hits, user, dry_run)
    return 0


senders_all: list[str] = []
MAX_AI_PER_RUN = 40   # cost guard on top of the Workspace spend limit
HOL_NEWS_F = Path(__file__).parent / "data" / "holidays" / "pending_news.json"
ai_state = {"client": None, "used": 0, "ctx": None}


def _ai_ctx():
    """Upcoming holidays and destination lists for routing (loaded once per run)."""
    if ai_state["ctx"] is None:
        import config as C
        from datetime import date as _date
        try:
            import holiday_cal
            from profiles import holidays as HP
            hols, hdests = holiday_cal.upcoming(_date.today()), HP.DESTINATIONS
        except Exception as e:  # holidays profile not installed: business only
            print(f"news_ai: holidays routing off ({e})")
            hols, hdests = [], {}
        ai_state["ctx"] = (hols, hdests, C.DESTINATIONS, C.MAX_PRICE)
    return ai_state["ctx"]


def biz_reference(deal: dict) -> str:
    """What our own business history says about this route and month (latest scans)."""
    import config as C
    dest = deal.get("destination")
    if dest not in C.DESTINATIONS:
        return ""
    try:
        hist = _json.loads((Path(__file__).parent / "data" / "history.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return ""
    region = C.DESTINATIONS[dest][1]
    rk = f"TLV-{dest}-{C.REGIONS[region]['dur']}"
    month = (deal.get("travel_from") or "")[:7]
    rows = hist.get(rk, {}).get(month) or []
    if not rows:
        allm = [r for m_, rs in hist.get(rk, {}).items() for r in rs[-1:]]
        if not allm:
            return "לא נסרק אצלנו עדיין"
        return f"אצלנו (גוגל, ביזנס): הזול בחודשים שנבדקו ${min(r[2] for r in allm):,}"
    return f"אצלנו (גוגל, ביזנס) ל-{month}: הזול בבדיקה האחרונה ${rows[-1][2]:,}"


def deal_line(d: dict, extra: str = "") -> str:
    price = f"{d['price']:,.0f} {d.get('currency') or ''}".strip() if d.get("price") is not None else "בלי מחיר"
    basis = {"round_trip": "הלוך חזור", "one_way": "כיוון אחד"}.get(d.get("price_basis"), "")
    cab = {"economy": "תיירים", "premium_economy": "פרימיום", "business": "ביזנס", "first": "ראשונה"}.get(d.get("cabin"), "")
    where = " - ".join(x for x in (d.get("origin") or d.get("origin_name"), d.get("destination") or d.get("destination_name")) if x)
    when = f"טיסות {d['travel_from']} עד {d['travel_to']}" if d.get("travel_from") and d.get("travel_to") else ""
    by = f"לקנות עד {d['book_by']}" if d.get("book_by") else ""
    bits = [b for b in (where, cab, f"{price} {basis}".strip(), when, by, d.get("conditions") or "", extra) if b]
    return "• " + html.escape(" · ".join(bits))


def queue_holidays(sender: str, subject: str, ai: dict, deals: list[dict]) -> None:
    """Holiday-relevant promos wait for the holidays email (separate from the business digest)."""
    try:
        items = _json.loads(HOL_NEWS_F.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        items = []
    items.append({"from": sender, "subject": subject, "summary": ai.get("summary_he", ""),
                  "deals": deals, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    HOL_NEWS_F.parent.mkdir(parents=True, exist_ok=True)
    HOL_NEWS_F.write_text(_json.dumps(items[-100:], ensure_ascii=False, indent=1), encoding="utf-8")


def read_ai(frm: str, subj: str, text: str, msg) -> dict | None:
    """Claude reads the mail. Returns a business hit, None (not for the business digest),
    or {"fallback": True} when the API is unavailable (then the keyword filter runs)."""
    if ai_state["used"] >= MAX_AI_PER_RUN:
        return {"fallback": True}
    if ai_state["client"] is None:
        ai_state["client"] = news_ai._client()
    ai_state["used"] += 1
    ai = news_ai.extract(frm, subj, text, ai_state["client"])
    if ai is None:  # API problem: keyword filter for the rest of this run
        ai_state["used"] = MAX_AI_PER_RUN
        return {"fallback": True}
    hols, hdests, bdests, bmax = _ai_ctx()
    routed = news_ai.route(ai, hols, hdests, bdests, bmax) if ai.get("is_promo") else {"business": [], "holidays": []}
    sender = re.sub(r"\s*<.*", "", frm).strip('" ')
    log_items([{"kind": "ai", "from": sender, "subject": subj, "snip": ai.get("summary_he", "")[:300],
                "promo": ai.get("is_promo"), "business": len(routed["business"]), "holidays": len(routed["holidays"]),
                "deals": len(ai.get("deals") or [])}])
    if routed["holidays"]:
        queue_holidays(sender, subj, ai, routed["holidays"])
    msgid = (msg.get("Message-ID") or "").strip("<>")
    if ai.get("needs_action"):
        return {"from": frm, "subject": subj, "c": {"biz": [], "promo": [], "israel": False, "confirm": True},
                "snip": "", "msgid": msgid}
    if not routed["business"]:
        return None
    lines = "<br>".join(deal_line(d, biz_reference(d)) for d in routed["business"])
    return {"from": frm, "subject": subj, "msgid": msgid, "snip": ai.get("summary_he", ""), "lines": lines,
            "c": {"biz": ["ai"], "promo": [], "israel": any(d.get("origin") in ("TLV", "LCA") for d in routed["business"])}}


def read_folder(m, ids, dry_run: bool) -> list[dict]:
    hits = []
    for i in ids:
        _, raw = m.uid("fetch", i, "(BODY.PEEK[])")
        msg = email.message_from_bytes(raw[0][1])
        subj, frm = dec(msg.get("Subject")), dec(msg.get("From"))
        senders_all.append(frm)
        text = body_text(msg)
        if news_ai.enabled():
            h = read_ai(frm, subj, text, msg)
            if h is None:
                continue
            if not h.get("fallback"):
                hits.append(h)
                continue
        c = classify(subj, text)
        if not c and CONFIRM.search(subj):
            c = {"biz": [], "promo": [], "israel": False, "confirm": True}
        if c:
            src = c.get("text") or clean(text)
            hits.append({"from": frm, "subject": subj, "c": c, "snip": snippet(src, c["biz"]),
                         "msgid": (msg.get("Message-ID") or "").strip("<>")})
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
            + (f'<div dir="auto" style="margin-top:6px;font-size:13px">{h["lines"]}</div>' if h.get("lines") else "") +
            f'<div style="margin-top:8px">{notify.button("לפתוח את המייל", link, primary=True)}</div>'
            f'</td></tr></table>')
    head = (f'<div style="{notify.FONT}font-size:20px;font-weight:bold;color:{notify.INK};margin:0 4px 12px">'
            f'📬 מבצעי ביזנס בניוזלטרים ({len(hits)})</div>')
    queue("news", hits[0]["subject"], cards)
    log_items([{"kind": "news", "from": re.sub(r"\s*<.*", "", h["from"]).strip('" '), "subject": h["subject"],
                "snip": h["snip"][:300], "israel": h["c"].get("israel"), "confirm": h["c"].get("confirm", False)}
               for h in hits])


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
