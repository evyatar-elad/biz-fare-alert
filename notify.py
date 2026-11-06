"""Email alerts (Gmail SMTP with an app password).

Secrets (GitHub Actions): SMTP_USER (the Gmail address), SMTP_PASS (16 char app
password), MAIL_TO (optional, defaults to SMTP_USER).

Email HTML uses tables and inline styles only (what Gmail renders reliably).
Latin text (codes, flight numbers, aircraft) is wrapped in dir="ltr" spans so it
does not scramble inside the right-to-left Hebrew text.
"""
from __future__ import annotations

import html
import os
import smtplib
from datetime import date, datetime, timezone
from email.mime.text import MIMEText
from urllib.parse import quote

import config as C

HEARTBEAT_DAYS = 7
STATUS_URL = "https://evyatar-elad.github.io/biz-fare-alert/"

# Colors
INK, MUTED, LINE, BG = "#1f2937", "#6b7280", "#e5e7eb", "#f3f4f6"
NAVY, GREEN, GREEN_BG, AMBER_BG, RED = "#0f2a4a", "#047857", "#d1fae5", "#fef3c7", "#b91c1c"
FONT = "font-family:Arial,Helvetica,sans-serif;"

WEEKDAYS = ["ב'", "ג'", "ד'", "ה'", "ו'", "ש'", "א'"]  # Monday first

# Airline booking sites (homepage; the user searches there). Unknown -> Google search.
AIRLINE_SITES = {
    "Azerbaijan Airlines": "https://www.azal.az/en",
    "Uzbekistan Airways": "https://www.uzairways.com/en",
    "El Al Israel Airlines": "https://www.elal.com",
    "El Al": "https://www.elal.com",
    "Emirates": "https://www.emirates.com",
    "Etihad Airways": "https://www.etihad.com",
    "flydubai": "https://www.flydubai.com",
    "Air India": "https://www.airindia.com",
    "Vietnam Airlines": "https://www.vietnamairlines.com",
    "Thai Airways International": "https://www.thaiairways.com",
    "Thai Airways": "https://www.thaiairways.com",
    "Singapore Airlines": "https://www.singaporeair.com",
    "Cathay Pacific": "https://www.cathaypacific.com",
    "EVA Air": "https://www.evaair.com",
    "China Airlines": "https://www.china-airlines.com",
    "Air China": "https://www.airchina.com",
    "Hainan Airlines": "https://www.hainanairlines.com",
    "Korean Air": "https://www.koreanair.com",
    "Asiana Airlines": "https://flyasiana.com",
    "Japan Airlines": "https://www.jal.co.jp/en",
    "ANA": "https://www.ana.co.jp/en",
    "Lufthansa": "https://www.lufthansa.com",
    "Swiss": "https://www.swiss.com",
    "Austrian": "https://www.austrian.com",
    "Brussels Airlines": "https://www.brusselsairlines.com",
    "Air France": "https://www.airfrance.com",
    "KLM": "https://www.klm.com",
    "British Airways": "https://www.britishairways.com",
    "Iberia": "https://www.iberia.com",
    "ITA Airways": "https://www.ita-airways.com",
    "Aegean": "https://en.aegeanair.com",
    "Aegean Airlines": "https://en.aegeanair.com",
    "LOT Polish Airlines": "https://www.lot.com",
    "Finnair": "https://www.finnair.com",
    "SAS": "https://www.flysas.com",
    "TAP Air Portugal": "https://www.flytap.com",
    "Air Seychelles": "https://www.airseychelles.com",
    "Ethiopian Airlines": "https://www.ethiopianairlines.com",
    "Royal Jordanian": "https://www.rj.com",
    "Gulf Air": "https://www.gulfair.com",
    "Oman Air": "https://www.omanair.com",
    "Arkia": "https://www.arkia.com",
    "Israir": "https://www.israir.co.il",
    "Air Astana": "https://airastana.com",
    "Malaysia Airlines": "https://www.malaysiaairlines.com",
    "Garuda Indonesia": "https://www.garuda-indonesia.com",
    "Qantas": "https://www.qantas.com",
    "Air Canada": "https://www.aircanada.com",
    "LATAM": "https://www.latamairlines.com",
}


def name(code: str) -> str:
    d = C.DESTINATIONS.get(code)
    return d[0] if d else {"TLV": "תל אביב", "LCA": "לרנקה"}.get(code, code)


def ltr(s) -> str:
    return f'<span dir="ltr" style="unicode-bidi:embed;white-space:nowrap">{html.escape(str(s))}</span>'


def nice_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{WEEKDAYS[d.weekday()]} {ltr(d.strftime('%d/%m/%Y'))}"


def gf_link(o, d, dep, ret) -> str:
    q = f"Flights from {o} to {d} on {dep} through {ret} business class one adult"
    return "https://www.google.com/travel/flights?q=" + quote(q) + "&curr=USD"


def sky_link(o, d, dep, ret) -> str:
    f = lambda s: s[2:4] + s[5:7] + s[8:10]
    return (f"https://www.skyscanner.co.il/transport/flights/{o.lower()}/{d.lower()}/{f(dep)}/{f(ret)}/"
            "?adultsv2=1&cabinclass=business&rtn=1")


def airline_link(airline: str) -> str:
    return AIRLINE_SITES.get(airline) or ("https://www.google.com/search?q=" + quote(airline + " official site"))


# ---------------------------------------------------------------- building blocks
def button(text: str, url: str, primary: bool = False) -> str:
    style = (f"background:{NAVY};color:#ffffff;border:1px solid {NAVY};" if primary
             else f"background:#ffffff;color:{NAVY};border:1px solid #c7d2fe;")
    return (f'<a href="{html.escape(url)}" style="{style}{FONT}display:inline-block;padding:9px 16px;'
            f'margin:4px 0 4px 6px;border-radius:8px;font-size:14px;font-weight:bold;text-decoration:none">'
            f'{text}</a>')


WIDEBODY = ("787", "777", "350", "330", "340", "380", "767", "747")
NARROWBODY = ("320", "321", "319", "318", "737", "220", "190", "195", "175", "170", "757")


def seat_badge(aircraft: str | None, seat: str | None) -> str:
    """Google sometimes states the seat type ("Lie flat seat"). Otherwise guess from the aircraft."""
    s = (seat or "").lower()
    a = (aircraft or "").replace(" ", "")
    if "flat" in s or "suite" in s or "bed" in s:
        text, bg, fg = "🛏️ מיטה (לפי גוגל)", GREEN_BG, GREEN
    elif any(x in a for x in WIDEBODY):
        text, bg, fg = "🛏️ כנראה מיטה", GREEN_BG, GREEN
    elif any(x in a for x in NARROWBODY):
        text, bg, fg = "💺 כנראה כיסא נשען", AMBER_BG, "#92400e"
    else:
        text, bg, fg = "מושב לא ידוע", BG, MUTED
    return (f'<span style="background:{bg};color:{fg};{FONT}font-size:12px;padding:2px 8px;'
            f'border-radius:10px;white-space:nowrap">{text}</span>')


def direction_block(label: str, seg: dict) -> str:
    hubs = [C.HIGHLIGHT_HUBS[v] for v in seg.get("via", []) if v in C.HIGHLIGHT_HUBS]
    via = "ישירה" if not seg.get("via") else "דרך " + ", ".join(name_or_code(v) for v in seg["via"])
    star = f' <span style="color:#b45309">⭐ {" ו".join(hubs)}</span>' if hubs else ""
    warn = (f'<div style="color:{RED};font-size:13px;font-weight:bold;margin-top:4px">'
            "⚠️ חלק מהדרך לא בביזנס</div>") if seg.get("mixed_cabin") else ""
    rows = ""
    for l in seg.get("legs", []):
        rows += (
            f'<tr><td style="padding:8px 0;border-top:1px solid {LINE};{FONT}font-size:14px;color:{INK}">'
            f'<div><b>{ltr(l["from"] + " → " + l["to"])}</b></div>'
            f'<div style="color:{MUTED};font-size:13px">{l.get("hours", "")} שעות'
            f' · {ltr((l["airline"] + " " + (l.get("flight") or "")).strip())}'
            f' · {ltr(l.get("aircraft") or "מטוס לא ידוע")}</div></td>'
            f'<td style="padding:8px 0;border-top:1px solid {LINE};text-align:left;vertical-align:middle">'
            f'{seat_badge(l.get("aircraft"), l.get("seat"))}</td></tr>')
    return (f'<div style="margin-top:14px;{FONT}font-size:14px;color:{INK}">'
            f'<b>{label}</b> <span style="color:{MUTED}">· {seg.get("hours")} שעות · {via}</span>{star}{warn}</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">'
            f'{rows}</table>')


def name_or_code(code: str) -> str:
    return C.HIGHLIGHT_HUBS.get(code) or (name(code) if code in C.DESTINATIONS else code)


def det_any(d: dict) -> dict:
    return d.get("details") or {}


def deal_card(d: dict) -> str:
    o, x = d["origin"], d["dest"]
    pct = round(100 * (1 - d["effective"] / d["ref"])) if d.get("ref") else None
    badge = (f'<span style="background:{GREEN_BG};color:{GREEN};font-size:13px;font-weight:bold;'
             f'padding:3px 10px;border-radius:12px">{ltr(f"-{pct}%")} מהרגיל</span>') if pct and pct > 0 else ""
    usual = (f'<div style="color:{MUTED};font-size:14px;margin-top:2px">בדרך כלל '
             f'<s>{ltr(f"${d["ref"]:,.0f}")}</s></div>'
             f'<div style="color:{MUTED};font-size:12px">{html.escape(d.get("ref_why") or "")}</div>'
             ) if d.get("ref") else ""
    lca = (f'<tr><td style="padding:4px 0;color:{MUTED};width:90px">לרנקה</td><td style="padding:4px 0">'
           f'צריך גם טיסה לקפריסין. כולל הערכה של {ltr(f"${C.POSITIONING_USD}")}: '
           f'<b>{ltr(f"${d["effective"]:,.0f}")}</b></td></tr>') if o == "LCA" else ""
    det = d.get("details") or {}
    flights = ""
    if det.get("out"):
        flights += direction_block("הלוך", det["out"])
    if det.get("ret"):
        flights += direction_block("חזור", det["ret"])
    if not flights:
        flights = (f'<div style="margin-top:14px;color:{MUTED};font-size:14px">'
                   "פרטי הטיסות לא נבדקו בריצה הזו. אפשר לראות אותם בקישורים.</div>")
    sisters = sorted(next((g for g in C.SISTER_CITIES if x in g), {x}) - {x})
    eco = d.get("economy")
    eco_row = (f'<tr><td style="padding:4px 0;color:{MUTED}">בתיירים</td><td style="padding:4px 0">'
               f'{ltr(f"${eco:,.0f}")} באותם תאריכים · הביזנס יקר פי {ltr(f"{d["price"] / eco:.1f}")}</td></tr>'
               ) if eco else ""
    src = ("Kiwi.com" + (" (חיפוש ממוקד בחברה)" if d.get("airline_focus") else "")) if d.get("src") == "kiwi" else "Google Flights"
    sep = (" <b style='color:#b45309'>· צירוף של כמה כרטיסים נפרדים (באחריותך אם טיסה מתעכבת)</b>"
           if det_any(d).get("separate_tickets") else "")
    src_row = (f'<tr><td style="padding:4px 0;color:{MUTED}">מקור</td><td style="padding:4px 0">{src}{sep}</td></tr>')
    open_jaw = (f'<tr><td style="padding:4px 0;color:{MUTED};vertical-align:top">טיפ</td><td style="padding:4px 0">'
                f'אפשר לבדוק גם הלוך ל{name(x)} וחזור מ{" או מ".join(name(c) for c in sisters)} '
                f'(בחיפוש "כמה יעדים"), לרוב באותו מחיר</td></tr>') if sisters else ""
    airlines = []
    for seg in (det.get("out"), det.get("ret")):
        for a in (seg or {}).get("airlines", []):
            if a not in airlines:
                airlines.append(a)
    if d.get("src") == "kiwi" and det.get("booking_url"):
        buttons = button("Kiwi.com (המחיר הזה)", det["booking_url"], primary=True)
        buttons += button("Google Flights", gf_link(o, x, d["dep"], d["ret"]))
    else:
        buttons = button("Google Flights", gf_link(o, x, d["dep"], d["ret"]), primary=True)
    buttons += button("Skyscanner", sky_link(o, x, d["dep"], d["ret"]))
    if d.get("airline_focus") in C.HUB_SITES:
        buttons += button(f"אתר {C.HUB_SITES[d['airline_focus']][0]}", C.HUB_SITES[d["airline_focus"]][1])
    for a in airlines[:2]:
        buttons += button(f"אתר {html.escape(a)}", airline_link(a))
    return f'''
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#ffffff;border:1px solid {LINE};border-radius:14px;margin-bottom:18px;border-collapse:separate">
 <tr><td style="background:{NAVY};border-radius:14px 14px 0 0;padding:16px 20px;{FONT}color:#ffffff">
   <div style="font-size:12px;opacity:.75;letter-spacing:.5px">מציאת ביזנס · הלוך חזור · נוסע אחד</div>
   <div style="font-size:21px;font-weight:bold;margin-top:4px">{name(o)} ⇄ {name(x)}
     <span style="font-size:14px;opacity:.7;font-weight:normal">{ltr(x)}</span></div>
 </td></tr>
 <tr><td style="padding:18px 20px 6px;{FONT}color:{INK}">
   <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
     <td style="vertical-align:top">
       <div style="font-size:34px;font-weight:bold;color:{GREEN};line-height:1.1">{ltr(f"${d['price']:,.0f}")}</div>
       {usual}
     </td>
     <td style="vertical-align:top;text-align:left">{badge}</td>
   </tr></table>
 </td></tr>
 <tr><td style="padding:6px 20px 0;{FONT}font-size:14px;color:{INK}">
   <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
     <tr><td style="padding:4px 0;color:{MUTED};width:90px">תאריכים</td>
         <td style="padding:4px 0">{nice_date(d["dep"])} עד {nice_date(d["ret"])} ({d["dur"]} ימים)</td></tr>
     <tr><td style="padding:4px 0;color:{MUTED}">גמישות</td>
         <td style="padding:4px 0">{d["similar_dates"]} תאריכי יציאה בחודש הזה במחיר דומה</td></tr>
     <tr><td style="padding:4px 0;color:{MUTED};vertical-align:top">למה</td>
         <td style="padding:4px 0">{html.escape("; ".join(d["reasons"]))}</td></tr>
     {eco_row}{src_row}{lca}{open_jaw}
   </table>
 </td></tr>
 <tr><td style="padding:0 20px">{flights}</td></tr>
 <tr><td style="padding:16px 20px 18px">{buttons}</td></tr>
</table>'''


def page(inner: str, preheader: str = "") -> str:
    return f'''<!doctype html><html dir="rtl" lang="he"><body style="margin:0;padding:0;background:{BG}">
<div style="display:none;max-height:0;overflow:hidden">{html.escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG}"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" dir="rtl" style="max-width:620px;text-align:right">
<tr><td>{inner}</td></tr>
<tr><td style="{FONT}font-size:12px;color:{MUTED};line-height:1.6;padding:4px 6px">
מחירים מ-Google Flights ומ-Kiwi.com, בדולרים, ביזנס הלוך חזור לנוסע אחד. אורך השהייה הוא רק "גשש" לזיהוי המחיר, ואפשר לשנות אותו באתר.
<br><a href="{STATUS_URL}" style="color:{NAVY}">דף הסטטוס של הבוט</a></td></tr>
</table></td></tr></table></body></html>'''


# ---------------------------------------------------------------- sending
def _send(subject: str, body_html: str, dry_run: bool) -> bool:
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    to = os.environ.get("MAIL_TO") or user
    if dry_run or not (user and pw):
        print("---- email (not sent:", "dry run" if dry_run else "no SMTP secrets", ") ----")
        print(subject)
        print(body_html[:3000])
        return dry_run  # without secrets, do not mark as sent
    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    print(f"email sent: {subject}")
    return True


def send_deals(deals: list[dict], dry_run: bool = False, prefix: str = "") -> bool:
    deals = sorted(deals, key=lambda d: d["effective"] / (d["ref"] or d["effective"]))
    top = deals[0]
    subject = (prefix + f"✈️ ביזנס {name(top['origin'])}-{name(top['dest'])} ${top['price']:,.0f}"
               + (f" (בדרך כלל ~${top['ref']:,.0f})" if top["ref"] else "")
               + (f" ועוד {len(deals) - 1}" if len(deals) > 1 else ""))
    pre = f"{top['dep']} עד {top['ret']}"
    return _send(subject, page("".join(deal_card(d) for d in deals), pre), dry_run)


def heartbeat_due(last_email: str | None) -> bool:
    if not last_email:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(last_email)).days >= HEARTBEAT_DAYS


def send_heartbeat(state: dict, hist: dict, dry_run: bool = False) -> bool:
    """Weekly 'still alive' mail with the cheapest price seen per destination (from TLV)."""
    rows = []
    for rk, months in hist.items():
        parts = rk.split("-")
        if len(parts) != 3 or parts[0] == "K":
            continue
        o, d, dur = parts
        mins = [(r[2], m) for m, rs in months.items() for r in rs[-1:]]
        if mins and o == "TLV":
            p, m = min(mins)
            rows.append((name(d), p, m))
    rows.sort(key=lambda r: r[1])
    trs = "".join(
        f'<tr><td style="padding:6px 0;border-top:1px solid {LINE}">{html.escape(n)}</td>'
        f'<td style="padding:6px 0;border-top:1px solid {LINE};text-align:left">{ltr(f"${p:,.0f}")}</td>'
        f'<td style="padding:6px 0;border-top:1px solid {LINE};text-align:left;color:{MUTED}">{ltr(m)}</td></tr>'
        for n, p, m in rows)
    blocked = (f'<p style="color:{RED}">חסימה אחרונה: עד {ltr(state["backoff_until"])}</p>'
               if state.get("backoff_until") else "")
    inner = f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="background:#ffffff;border:1px solid {LINE};border-radius:14px;border-collapse:separate">
<tr><td style="background:{NAVY};border-radius:14px 14px 0 0;padding:16px 20px;{FONT}color:#fff;font-size:20px;font-weight:bold">
סיכום שבועי: הבוט פעיל</td></tr>
<tr><td style="padding:16px 20px;{FONT}font-size:14px;color:{INK}">
<p style="margin-top:0">לא נמצאו מציאות חדשות השבוע. כך נראים המחירים הזולים ביותר שראיתי (ביזנס הלוך חזור מתל אביב):</p>{blocked}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{trs}</table>
</td></tr></table>'''
    return _send("✈️ סיכום שבועי: בוט הביזנס פעיל", page(inner, "הבוט פעיל, אין מציאות חדשות"), dry_run)


SAMPLE = {
    "route": "TLV-PEK-14", "origin": "TLV", "dest": "PEK", "dur": 14, "month": "2027-03",
    "dep": "2027-03-10", "ret": "2027-03-24", "price": 1200, "effective": 1200, "ref": 4300,
    "ref_why": "הזול שנמצא לחודש הזה ב-6 בדיקות קודמות",
    "reasons": ["[בדיקה, לא מחיר אמיתי] 72% מתחת למחיר הרגיל"], "similar_dates": 4, "economy": 980,
    "details": {"price": 1200,
        "out": {"stops": 1, "via": ["GYD"], "airlines": ["Azerbaijan Airlines"], "hours": 13.5, "mixed_cabin": False,
                "legs": [{"from": "TLV", "to": "GYD", "airline": "Azerbaijan Airlines", "flight": "J2 82", "aircraft": "Airbus A320neo", "seat": None, "hours": 3.3},
                         {"from": "GYD", "to": "PEK", "airline": "Azerbaijan Airlines", "flight": "J2 61", "aircraft": "Boeing 787-8", "seat": "Lie flat seat", "hours": 7.2}]},
        "ret": {"stops": 1, "via": ["GYD"], "airlines": ["Azerbaijan Airlines"], "hours": 14.0, "mixed_cabin": False,
                "legs": [{"from": "PEK", "to": "GYD", "airline": "Azerbaijan Airlines", "flight": "J2 62", "aircraft": "Boeing 787-8", "seat": None, "hours": 8.0},
                         {"from": "GYD", "to": "TLV", "airline": "Azerbaijan Airlines", "flight": "J2 81", "aircraft": "Airbus A320neo", "seat": None, "hours": 3.4}]}},
}


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        sys.exit(0 if send_deals([SAMPLE], prefix="[בדיקה] ") else 1)
    if "--html" in sys.argv:  # write preview files
        from pathlib import Path
        Path(sys.argv[-1]).write_text(page(deal_card(SAMPLE)), encoding="utf-8")
