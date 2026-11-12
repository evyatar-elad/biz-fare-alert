"""Holidays - economy email (separate from the business digest).

- Alert email: when there is a new lowest price for a holiday and destination, or a drop of
  DROP_ALERT since the previous check (data/holidays/pending.json). At most one per day,
  from ALERT_HOUR_IL Israel time.
- Weekly summary (Sunday, same hour): the cheapest per holiday and destination, the dates
  that cost the fewest vacation days, and holiday promos from newsletters.

Usage: python holiday_notify.py [--dry-run] [--force] [--weekly]
"""
from __future__ import annotations

import html
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import holiday_cal as HC
import holiday_text as T
import notify
from profiles import holidays as P

DATA = Path(__file__).parent / "data" / "holidays"
STATE_F = DATA / "mail_state.json"
PAGE_URL = "https://evyatar-elad.github.io/biz-fare-alert/holidays.html"
IL = ZoneInfo("Asia/Jerusalem")
ALERT_HOUR_IL = 9
GREEN = "#14532d"
NAMES = T.NAMES


def jload(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def e(s) -> str:
    return html.escape(str(s))


def wrap(inner: str, preheader: str) -> str:
    return f'''<!doctype html><html dir="rtl" lang="he"><body style="margin:0;padding:0;background:{notify.BG}">
<div style="display:none;max-height:0;overflow:hidden">{e(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{notify.BG}"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" dir="rtl" style="max-width:640px;text-align:right">
<tr><td>{inner}</td></tr>
<tr><td style="{notify.FONT}font-size:12px;color:{notify.MUTED};line-height:1.6;padding:4px 6px">
מחירים מ-Kiwi.com ומ-Google Flights, בדולרים, <b>תיירים</b> הלוך חזור לנוסע אחד מתל אביב.
"ימי חופש" = ראשון-חמישי שאינם חג, ערב חג או חול המועד, כולל ימי הטיסה.
<br><a href="{PAGE_URL}" style="color:{GREEN}">דף "חגים - תיירים"</a></td></tr>
</table></td></tr></table></body></html>'''


def card(inner: str) -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;'
            f'border:1px solid {notify.LINE};border-radius:12px;margin-bottom:12px;border-collapse:separate">'
            f'<tr><td style="padding:14px 16px;{notify.FONT}font-size:14px;color:{notify.INK};line-height:1.6">{inner}</td></tr></table>')


def route(o: dict) -> str:
    r = T.route(o)
    if not r:
        return ""
    bits = [r] + ([", ".join(o["airlines"])] if o.get("airlines") else []) + ["⚠️ " + x if not x.startswith("⭐") else x for x in T.tags(o)]
    return " · ".join(e(b) for b in bits)


def when(o: dict) -> str:
    dep, ret = date.fromisoformat(o["dep"]), date.fromisoformat(o["ret"])
    return f"{HC.fmt(dep)} - {HC.fmt(ret)} · {o['nights']} לילות · {o['vac']} ימי חופש"


def when_short(o: dict) -> str:
    dep, ret = date.fromisoformat(o["dep"]), date.fromisoformat(o["ret"])
    return f"{dep.day}/{dep.month}-{ret.day}/{ret.month} · {o['nights']} לילות · {o['vac']} ימי חופש"


def ours(best: dict, d: dict) -> str:
    """Our own cheapest for the holiday and destination of a newsletter deal, for comparison."""
    g = "TYO" if d.get("destination") in ("NRT", "HND", "TYO") else d.get("destination")
    o = (best.get(d.get("holiday"), {}).get(g) or {}).get("now")
    return f" · אצלנו לחג הזה: ${o['price']:,}" if o else ""


def buttons(o: dict) -> str:
    out = notify.button("לחיפוש בגוגל", T.google_link(o), primary=not o.get("url"))
    if o.get("url"):
        out = notify.button("להזמנה ב-Kiwi", o["url"], primary=True) + out
    return out


def alert_card(a: dict, sample: bool = False) -> str:
    """Three lines: what and how much (and why now), when, how. Then buttons."""
    o = a["o"]
    if sample:
        why = "דוגמה לאיך נראית התראה"
    elif a["type"] == "low":
        why = f"🏆 הכי זול מאז שהתחלנו לחפש (הקודם: ${a['prev']:,})"
    else:
        why = f"📉 ירד ב-{round(100 * (a['prev'] - o['price']) / a['prev'])}% מאתמול (היה ${a['prev']:,})"
    notes = f' · ✓ {e(", ".join(n.replace("בארץ", "בבית") for n in o["notes"]))}' if o.get("notes") else ""
    r = route(o)
    return card(f'<div style="font-size:18px;font-weight:bold">{e(NAMES.get(a["group"], a["group"]))} · '
                f'<span style="color:{GREEN}">${o["price"]:,}</span></div>'
                f'<div style="color:{notify.MUTED};font-size:13px">{e(a["hname"])} · {e(why)}</div>'
                f'<div style="margin-top:6px">📅 {e(when(o))}{notes}</div>'
                + (f'<div>✈️ {r}</div>' if r else "")
                + f'<div style="margin-top:6px">{buttons(o)}</div>')


def summary(best: dict, news: list) -> str:
    """Per holiday: the dates that cost the fewest vacation days, then one line per destination."""
    parts = []
    for h in HC.upcoming(date.today()):
        hb = best.get(h.key, {})
        rows = sorted(((g, b) for g, b in hb.items() if not g.startswith("_") and b.get("now")),
                      key=lambda x: x[1]["now"]["price"])
        top = HC.best_spread(h)["top"][0]
        lines = "".join(
            f'<tr><td style="padding:7px 0;border-top:1px solid {notify.LINE};white-space:nowrap"><b>{e(NAMES.get(g, g))}</b></td>'
            f'<td style="padding:7px 6px;border-top:1px solid {notify.LINE};white-space:nowrap"><b>${b["now"]["price"]:,}</b></td>'
            f'<td style="padding:7px 0;border-top:1px solid {notify.LINE};font-size:13px;color:{notify.MUTED}">'
            f'{e(when_short(b["now"]))}</td></tr>' for g, b in rows)
        hn = [n for n in news if any(d.get("holiday") == h.key for d in n.get("deals", []))][-3:]
        news_html = "".join(f'<div style="font-size:13px;margin-top:6px">📬 {e(n["from"])}: {e(n.get("summary", ""))}</div>' for n in hn)
        parts.append(card(
            f'<div style="font-size:18px;font-weight:bold">{e(h.name)}</div>'
            f'<div style="color:{notify.MUTED};font-size:13px">הכי חסכוני בימי חופש: {e(HC.fmt(top["dep"]))} - {e(HC.fmt(top["ret"]))} '
            f'({top["nights"]} לילות, {top["vac"]} ימי חופש)</div>'
            f'<table role="presentation" width="100%" style="{notify.FONT}font-size:14px;margin-top:8px;border-collapse:collapse">'
            f'<tr><td style="color:{notify.MUTED};font-size:12px">יעד</td><td style="color:{notify.MUTED};font-size:12px;padding:0 6px">הזול עכשיו</td>'
            f'<td style="color:{notify.MUTED};font-size:12px">תאריכים</td></tr>'
            f'{lines or "<tr><td>עוד אין מחירים</td></tr>"}</table>{news_html}'
            f'<div style="margin-top:8px">{notify.button("לכל הפרטים בדף", PAGE_URL)}</div>'))
    return "".join(parts)


def sample_alerts(best: dict) -> list[dict]:
    """For a sample email: the cheapest option of the two cheapest destinations, as if new lows."""
    out = []
    for h in HC.upcoming(date.today())[:1]:
        rows = sorted(((g, b) for g, b in best.get(h.key, {}).items() if not g.startswith("_") and b.get("now")),
                      key=lambda x: x[1]["now"]["price"])[:2]
        out += [{"type": "low", "h": h.key, "hname": h.name, "group": g, "o": b["now"],
                 "prev": b["now"]["price"]} for g, b in rows]
    return out


def main(dry_run: bool = False, force: bool = False, weekly: bool = False, sample: bool = False) -> int:
    st = jload(STATE_F, {})
    pending = jload(DATA / "pending.json", [])
    if sample:  # a one-off example: alert cards + the weekly summary, nothing marked as sent
        force = weekly = True
    best = jload(DATA / "best.json", {})
    news = jload(DATA / "pending_news.json", [])
    now_il = datetime.now(IL)
    today = now_il.date().isoformat()
    hour_ok = force or now_il.hour >= ALERT_HOUR_IL
    weekly_due = weekly or (now_il.weekday() == 6 and st.get("last_weekly") != today and hour_ok)
    new_news = [n for n in news if not n.get("mailed")]
    alerts_due = (pending or new_news) and hour_ok and (force or st.get("last_alert") != today)
    if not (alerts_due or weekly_due):
        print(f"holiday mail: nothing now ({len(pending)} alerts, {len(new_news)} news waiting)")
        return 0
    if sample:
        pending = sample_alerts(best)
    head = (f'<div style="background:{GREEN};color:#fff;border-radius:12px;padding:14px 16px;margin-bottom:12px;{notify.FONT}">'
            f'<div style="font-size:20px;font-weight:bold">🌴 חגים - תיירים</div>'
            + ('<div style="font-size:13px;margin-top:4px">מייל לדוגמה: כך ייראו התראה (כשיש מחיר הכי זול מאז שהתחלנו, או ירידה של 10%) והסיכום השבועי. '
               'המחירים אמיתיים.</div>' if sample else '') + '</div>')
    parts = [head]
    if pending:
        parts.append(f'<div style="{notify.FONT}font-size:18px;font-weight:bold;margin:6px 4px 10px">'
                     f'{"התראות" if not sample else "כך נראית התראה"} ({len(pending)})</div>')
        parts += [alert_card(a, sample) for a in sorted(pending, key=lambda a: a["o"]["price"])]
    if new_news and not weekly_due:
        parts.append(f'<div style="{notify.FONT}font-size:18px;font-weight:bold;margin:16px 4px 10px">📬 מבצעים מניוזלטרים לחגים</div>')
        for n in new_news:
            lines = "<br>".join(
                "• " + e(" · ".join(str(x) for x in (T.city(d["destination"]) if d.get("destination") else d.get("destination_name"),
                                                    f"{d['price']:,.0f} {d.get('currency') or ''}" if d.get("price") is not None else None,
                                                    f"טיסות {d['travel_from']} עד {d['travel_to']}" if d.get("travel_from") else None,
                                                    f"לקנות עד {d['book_by']}" if d.get("book_by") else None,
                                                    d.get("holiday_name")) if x)) + e(ours(best, d)) for d in n["deals"])
            parts.append(card(f'<div style="color:{notify.MUTED};font-size:12px">{e(n["from"])}</div>'
                              f'<b>{e(n["subject"])}</b><br>{e(n.get("summary", ""))}<br>{lines}'))
    if weekly_due:
        parts.append(f'<div style="{notify.FONT}font-size:18px;font-weight:bold;margin:16px 4px 10px">סיכום שבועי: הזול לכל חג ויעד</div>')
        parts.append(summary(best, news))
    if pending:
        top = min(pending, key=lambda a: a["o"]["price"])
        subject = f"🌴 {top['hname']}: {NAMES.get(top['group'], top['group'])} ${top['o']['price']:,} בתיירים" + (
            f" ועוד {len(pending) - 1}" if len(pending) > 1 else "")
    elif weekly_due:
        subject = "🌴 סיכום שבועי: חגים בתיירים"
    else:
        subject = f"🌴 {len(new_news)} מבצעים מניוזלטרים לחגים"
    if sample:
        subject = "דוגמה: " + subject
    if not notify._send(subject, wrap("".join(parts), subject), dry_run):
        return 1
    if not dry_run and not sample:
        if pending or new_news:
            st["last_alert"] = today
        if weekly_due:
            st["last_weekly"] = today
        DATA.mkdir(parents=True, exist_ok=True)
        STATE_F.write_text(json.dumps(st, indent=1), encoding="utf-8")
        (DATA / "pending.json").write_text("[]", encoding="utf-8")
        for n in news:
            n["mailed"] = True
        (DATA / "pending_news.json").write_text(json.dumps(news[-100:], ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv, "--force" in sys.argv, "--weekly" in sys.argv, "--sample" in sys.argv))
