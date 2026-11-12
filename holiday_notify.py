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
import notify
from profiles import holidays as P

DATA = Path(__file__).parent / "data" / "holidays"
STATE_F = DATA / "mail_state.json"
PAGE_URL = "https://evyatar-elad.github.io/biz-fare-alert/holidays.html"
IL = ZoneInfo("Asia/Jerusalem")
ALERT_HOUR_IL = 9
GREEN = "#14532d"
NAMES = {**{k: v[0] for k, v in P.DESTINATIONS.items()}, "TYO": "טוקיו"}


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
    if o.get("via_out") is None:
        return "מסלול: לבדוק באתר"
    one = lambda v: "ישירה" if not v else "דרך " + "/".join(v)
    s = one(o["via_out"]) if o["via_out"] == o["via_ret"] else f"הלוך {one(o['via_out'])}, חזור {one(o['via_ret'])}"
    bits = [s]
    if o.get("hours_out"):
        bits.append(f"{o['hours_out']:g} / {o['hours_ret']:g} שעות")
    if o.get("airlines"):
        bits.append(", ".join(o["airlines"]))
    if o.get("europe"):
        bits.append("⚠️ דרך אירופה")
    if o.get("separate"):
        bits.append("⚠️ כרטיסים נפרדים")
    return " · ".join(e(b) for b in bits)


def option_block(o: dict, title: str = "") -> str:
    dep, ret = date.fromisoformat(o["dep"]), date.fromisoformat(o["ret"])
    notes = f'<br><span style="color:{notify.MUTED}">{e(", ".join(o["notes"]))}</span>' if o.get("notes") else ""
    buttons = notify.button("Google Flights", notify.gf_link(P.ORIGIN, o["dest"], o["dep"], o["ret"], seat=1), primary=not o.get("url"))
    if o.get("url"):
        buttons = notify.button("Kiwi.com", o["url"], primary=True) + buttons
    return (f'{f"<b>{e(title)}</b><br>" if title else ""}'
            f'<span style="font-size:20px;font-weight:bold">${o["price"]:,}</span> '
            f'{e(HC.fmt(dep))} - {e(HC.fmt(ret))} · {o["nights"]} לילות · <b>{o["vac"]} ימי חופש</b>{notes}'
            f'<br><span style="font-size:13px">{route(o)}</span><br>{buttons}')


def alert_card(a: dict) -> str:
    o = a["o"]
    why = (f"🏆 הזול ביותר מאז שהתחלנו (היה ${a['prev']:,})" if a["type"] == "low"
           else f"📉 ירד מ-${a['prev']:,} ({round(100 * (a['prev'] - o['price']) / a['prev'])}%)")
    return card(f'<div style="color:{notify.MUTED};font-size:12px">{e(a["hname"])}</div>'
                f'<div style="font-size:17px;font-weight:bold">{e(NAMES.get(a["group"], a["group"]))}</div>'
                f'<div style="color:{GREEN};font-weight:bold">{e(why)}</div>{option_block(o)}')


def spread_table(h: HC.Holiday) -> str:
    rows = "".join(f'<tr><td style="padding:3px 0">{e(HC.fmt(r["dep"]))} - {e(HC.fmt(r["ret"]))}</td>'
                   f'<td>{r["nights"]} לילות</td><td><b>{r["vac"]}</b> ימי חופש</td></tr>' for r in HC.best_spread(h)["top"][:4])
    return f'<table role="presentation" style="{notify.FONT}font-size:13px">{rows}</table>'


def summary(best: dict, news: list) -> str:
    parts = []
    for h in HC.upcoming(date.today()):
        hb = best.get(h.key, {})
        rows = sorted(((g, b) for g, b in hb.items() if b.get("now")), key=lambda x: x[1]["now"]["price"])
        lines = "".join(
            f'<tr><td style="padding:6px 0;border-top:1px solid {notify.LINE}"><b>{e(NAMES.get(g, g))}</b></td>'
            f'<td style="border-top:1px solid {notify.LINE}">${b["now"]["price"]:,} · {e(HC.fmt(date.fromisoformat(b["now"]["dep"])))}'
            f' · {b["now"]["nights"]} לילות · {b["now"]["vac"]} ימי חופש'
            + (f'<br><span style="color:{notify.MUTED};font-size:12px">הזול מאז שהתחלנו: ${b["low"]["price"]:,}</span>' if b.get("low") else "")
            + (f'<br><span style="color:{notify.MUTED};font-size:12px">בלי אירופה: ${b["noeu"]["price"]:,}</span>' if b.get("noeu") and b["noeu"]["price"] != b["now"]["price"] else "")
            + '</td></tr>' for g, b in rows)
        hn = [n for n in news if any(d.get("holiday") == h.key for d in n.get("deals", []))][-5:]
        news_html = "".join(f'<br>📬 <b>{e(n["from"])}</b>: {e(n.get("summary", ""))}' for n in hn)
        parts.append(card(
            f'<div style="font-size:18px;font-weight:bold">{e(h.name)}</div>'
            f'<div style="color:{notify.MUTED};font-size:13px">יציאה {e(HC.fmt(h.dep[0]))} עד {e(HC.fmt(h.dep[1]))}</div>'
            f'<div style="margin-top:8px"><b>הכי חסכוני בימי חופש:</b>{spread_table(h)}</div>'
            f'<table role="presentation" width="100%" style="{notify.FONT}font-size:14px;margin-top:8px">'
            f'{lines or "<tr><td>עוד אין מחירים</td></tr>"}</table>{news_html}'))
    return "".join(parts)


def main(dry_run: bool = False, force: bool = False, weekly: bool = False) -> int:
    st = jload(STATE_F, {})
    pending = jload(DATA / "pending.json", [])
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
    head = (f'<div style="background:{GREEN};color:#fff;border-radius:12px;padding:14px 16px;margin-bottom:12px;{notify.FONT}">'
            f'<div style="font-size:20px;font-weight:bold">🌴 חגים - תיירים</div></div>')
    parts = [head]
    if pending:
        parts.append(f'<div style="{notify.FONT}font-size:18px;font-weight:bold;margin:6px 4px 10px">מחירים חדשים ({len(pending)})</div>')
        parts += [alert_card(a) for a in sorted(pending, key=lambda a: a["o"]["price"])]
    if new_news and not weekly_due:
        parts.append(f'<div style="{notify.FONT}font-size:18px;font-weight:bold;margin:16px 4px 10px">📬 מבצעים מניוזלטרים לחגים</div>')
        for n in new_news:
            lines = "<br>".join(
                "• " + e(" · ".join(str(x) for x in (d.get("destination") or d.get("destination_name"),
                                                    f"{d['price']:,.0f} {d.get('currency') or ''}" if d.get("price") is not None else None,
                                                    f"טיסות {d['travel_from']} עד {d['travel_to']}" if d.get("travel_from") else None,
                                                    f"לקנות עד {d['book_by']}" if d.get("book_by") else None,
                                                    d.get("holiday_name")) if x)) for d in n["deals"])
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
    if not notify._send(subject, wrap("".join(parts), subject), dry_run):
        return 1
    if not dry_run:
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
    sys.exit(main("--dry-run" in sys.argv, "--force" in sys.argv, "--weekly" in sys.argv))
