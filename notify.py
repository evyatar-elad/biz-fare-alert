"""Email alerts (Gmail SMTP with an app password).

Secrets (GitHub Actions): SMTP_USER (the Gmail address), SMTP_PASS (16 char app
password), MAIL_TO (optional, defaults to SMTP_USER).
"""
from __future__ import annotations

import html
import os
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from urllib.parse import quote

import config as C

HEARTBEAT_DAYS = 7


def name(code: str) -> str:
    d = C.DESTINATIONS.get(code)
    return d[0] if d else {"TLV": "תל אביב", "LCA": "לרנקה"}.get(code, code)


def gf_link(o, d, dep, ret) -> str:
    q = f"Flights from {o} to {d} on {dep} through {ret} business class one adult"
    return "https://www.google.com/travel/flights?q=" + quote(q) + "&curr=USD"


def sky_link(o, d, dep, ret) -> str:
    f = lambda s: s[2:4] + s[5:7] + s[8:10]
    return (f"https://www.skyscanner.co.il/transport/flights/{o.lower()}/{d.lower()}/{f(dep)}/{f(ret)}/"
            "?adultsv2=1&cabinclass=business&rtn=1")


def _send(subject: str, body_html: str, dry_run: bool) -> bool:
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    to = os.environ.get("MAIL_TO") or user
    if dry_run or not (user and pw):
        print("---- email (not sent:", "dry run" if dry_run else "no SMTP secrets", ") ----")
        print(subject)
        print(body_html)
        return dry_run  # without secrets, do not mark as sent
    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    print(f"email sent: {subject}")
    return True


def _wrap(inner: str) -> str:
    return (f'<div dir="rtl" style="font-family:Arial,sans-serif;font-size:15px;line-height:1.5">{inner}'
            '<p style="color:#888;font-size:12px">biz-fare-alert. המחירים מ-Google Flights, לנוסע אחד, הלוך חזור, '
            'בדולרים. אורך השהייה הוא רק "בדיקה", אפשר לשחק איתו באתר.</p></div>')


WIDEBODY = ("787", "777", "350", "330", "340", "380", "767", "747")
NARROWBODY = ("320", "321", "319", "318", "737", "220", "190", "195", "175", "170", "757")


def seat_guess(aircraft: str | None, seat: str | None) -> str:
    """Google sometimes says the seat type itself (e.g. "Lie flat seat"). Otherwise guess by aircraft."""
    s = (seat or "").lower()
    if "flat" in s or "suite" in s or "bed" in s:
        return f"🛏️ {html.escape(seat)}"
    a = (aircraft or "").replace(" ", "")
    if any(x in a for x in WIDEBODY):
        return "🛏️ כנראה מיטה (מטוס רחב גוף)"
    if any(x in a for x in NARROWBODY):
        return "💺 כנראה כיסא נשען (מטוס צר גוף)"
    return "לא ידוע"


def _fmt_details(det: dict | None) -> str:
    if not det:
        return "<li>פרטי טיסה: לא נבדקו (תבדוק בקישור)</li>"
    out = []
    for label, seg in (("הלוך", det.get("out")), ("חזור", det.get("ret"))):
        if not seg:
            continue
        via = ", ".join(seg["via"]) or "ישירה"
        hubs = [C.HIGHLIGHT_HUBS[v] for v in seg["via"] if v in C.HIGHLIGHT_HUBS]
        tag = f" ⭐ דרך {' ו'.join(hubs)}" if hubs else ""
        warn = ' <b style="color:#c00">(חלק מהדרך לא בביזנס!)</b>' if seg.get("mixed_cabin") else ""
        legs = "".join(
            f"<li>{l['from']}-{l['to']}: {html.escape(l['airline'])} {html.escape(str(l.get('flight') or ''))}, "
            f"{html.escape(l.get('aircraft') or 'מטוס לא ידוע')}, {l['hours']} ש'. {seat_guess(l.get('aircraft'), l.get('seat'))}</li>"
            for l in seg.get("legs", []))
        out.append(f"<li>{label}: {html.escape(', '.join(seg['airlines']))}, דרך {html.escape(via)}, "
                   f"{seg['hours']} שעות{tag}{warn}<ul>{legs}</ul></li>")
    return "".join(out)


def send_deals(deals: list[dict], dry_run: bool = False, prefix: str = "") -> bool:
    deals = sorted(deals, key=lambda d: d["effective"] / (d["ref"] or d["effective"]))
    top = deals[0]
    subject = (prefix + f"✈️ ביזנס {name(top['origin'])}-{name(top['dest'])} ${top['price']:,.0f}"
               + (f" (בדרך כלל ~${top['ref']:,.0f})" if top["ref"] else "")
               + (f" ועוד {len(deals) - 1}" if len(deals) > 1 else ""))
    parts = []
    for d in deals:
        o, x = d["origin"], d["dest"]
        pos = (f"<li>יציאה מלרנקה: צריך גם טיסה לשם. כולל הערכה של ${C.POSITIONING_USD} "
               f"זה ${d['effective']:,.0f}</li>") if o == "LCA" else ""
        parts.append(
            f"<h3 style='margin-bottom:4px'>{name(o)} - {name(x)} ({x}): ${d['price']:,.0f}</h3><ul>"
            f"<li>תאריכים: {d['dep']} עד {d['ret']} ({d['dur']} ימים). "
            f"{d['similar_dates']} תאריכי יציאה בחודש הזה במחיר דומה</li>"
            f"<li>למה: {html.escape('; '.join(d['reasons']))}</li>{pos}{_fmt_details(d.get('details'))}"
            f"<li><a href='{gf_link(o, x, d['dep'], d['ret'])}'>Google Flights</a> | "
            f"<a href='{sky_link(o, x, d['dep'], d['ret'])}'>Skyscanner</a></li></ul>")
    return _send(subject, _wrap("".join(parts)), dry_run)


def heartbeat_due(last_email: str | None) -> bool:
    if not last_email:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(last_email)).days >= HEARTBEAT_DAYS


def send_heartbeat(state: dict, hist: dict, dry_run: bool = False) -> bool:
    """Weekly 'still alive' mail with the cheapest price seen per destination."""
    rows = []
    for rk, months in hist.items():
        o, d, dur = rk.split("-")
        mins = [(r[2], m) for m, rs in months.items() for r in rs[-1:]]
        if mins:
            p, m = min(mins)
            rows.append((name(d), o, p, m))
    rows.sort(key=lambda r: (r[0], r[1]))
    table = "".join(f"<tr><td>{html.escape(n)}</td><td>{o}</td><td>${p:,.0f}</td><td>{m}</td></tr>" for n, o, p, m in rows)
    blocked = f"<p>חסימה אחרונה: עד {state['backoff_until']}</p>" if state.get("backoff_until") else ""
    body = (f"<p>הבוט עובד. לא נמצאו מציאות חדשות השבוע. נבדקו {len(state.get('last', {}))} חלונות חיפוש.</p>{blocked}"
            "<table border='1' cellpadding='4' style='border-collapse:collapse'>"
            "<tr><th>יעד</th><th>מוצא</th><th>הזול שנראה</th><th>חודש</th></tr>" + table + "</table>")
    return _send("✈️ סיכום שבועי: בוט הביזנס פעיל", _wrap(body), dry_run)


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        sample = {
            "route": "TLV-PEK-14", "origin": "TLV", "dest": "PEK", "dur": 14, "month": "2027-03",
            "dep": "2027-03-10", "ret": "2027-03-24", "price": 1200, "effective": 1200, "ref": 4300,
            "reasons": ["[בדיקה, לא מחיר אמיתי] 72% מתחת למחיר הרגיל"], "similar_dates": 4,
            "details": {"price": 1200,
                "out": {"stops": 1, "via": ["GYD"], "airlines": ["Azerbaijan Airlines"], "hours": 13.5, "mixed_cabin": False,
                        "legs": [{"from": "TLV", "to": "GYD", "airline": "Azerbaijan Airlines", "flight": "J2 82", "aircraft": "Airbus A320neo", "seat": None, "hours": 3.3},
                                 {"from": "GYD", "to": "PEK", "airline": "Azerbaijan Airlines", "flight": "J2 61", "aircraft": "Boeing 787-8", "seat": "Lie flat seat", "hours": 7.2}]},
                "ret": {"stops": 1, "via": ["GYD"], "airlines": ["Azerbaijan Airlines"], "hours": 14.0, "mixed_cabin": False,
                        "legs": [{"from": "PEK", "to": "GYD", "airline": "Azerbaijan Airlines", "flight": "J2 62", "aircraft": "Boeing 787-8", "seat": None, "hours": 8.0},
                                 {"from": "GYD", "to": "TLV", "airline": "Azerbaijan Airlines", "flight": "J2 81", "aircraft": "Airbus A320neo", "seat": None, "hours": 3.4}]}},
        }
        ok = send_deals([sample], prefix="[בדיקה] ")
        sys.exit(0 if ok else 1)
