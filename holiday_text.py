"""Shared text for the holidays page and email: city names, routes, links, booking advice."""
from __future__ import annotations

import html
from datetime import date

import holiday_cal as HC
import notify
from profiles import holidays as P

NAMES = {**P.AIRPORT_NAMES, **{k: v[0] for k, v in P.DESTINATIONS.items()}, "TYO": "טוקיו"}


def e(s) -> str:
    return html.escape(str(s))


def city(code: str | None) -> str:
    return NAMES.get(code or "", code or "?")


def route(o: dict) -> str:
    """'ישירה' / 'דרך אתונה וסינגפור' / 'הלוך דרך ..., חזור דרך ...' with hours (plain text)."""
    if o.get("via_out") is None:
        return ""

    def one(v):
        return "ישירה" if not v else "דרך " + " ו".join(city(x) for x in v)
    s = one(o["via_out"]) if o["via_out"] == o["via_ret"] else f"הלוך {one(o['via_out'])}, חזור {one(o['via_ret'])}"
    if o.get("hours_out"):
        s += f" · {o['hours_out']:g} / {o['hours_ret']:g} שעות"
    return s


def tags(o: dict) -> list[str]:
    t = []
    if o.get("europe"):
        t.append("דרך אירופה")
    stops = [v for v in (o.get("via_out") or []) + (o.get("via_ret") or []) if v in P.STOPOVER_HUBS]
    if stops:
        t.append("⭐ " + P.STOPOVER_HUBS[stops[0]])
    if o.get("separate"):
        t.append("כרטיסים נפרדים")
    return t


def google_link(o: dict) -> str:
    dest = o.get("dest") or ""
    if dest == "TYO":
        dest = "NRT"
    return notify.gf_link(P.ORIGIN, dest, o["dep"], o["ret"], seat=1)  # seat 1 = economy


def links_html(o: dict, cls: str = "lnk") -> str:
    """Google Flights for these exact dates, plus Kiwi's link to this exact itinerary when the
    price came from Kiwi."""
    out = f"<a href='{e(google_link(o))}' class={cls} target=_blank>לחיפוש בגוגל לתאריכים האלה</a>"
    if o.get("url"):
        out += f" · <a href='{e(o['url'])}' class={cls} target=_blank>להזמנה ב-Kiwi (המסלול הזה)</a>"
    return out


# ---------------------------------------------------------------- when to buy
def _days(rows) -> int:
    return len({r[0] for r in rows})


def advice(h: HC.Holiday, curve: dict, group: str, now_price: int | None, low_price: int | None,
           today: date) -> tuple[str, str]:
    """(short label, explanation). Based only on our own measurements, and says so.
    - first two weeks: collecting;
    - then: where the price is relative to the lowest we measured, and the 14-day trend;
    - once an earlier season of the same holiday exists: what happened from this point then."""
    rows = curve.get(h.key, {}).get(group, [])
    left = (h.core[0] - today).days
    n = _days(rows)
    past = _past_season(h, curve, group, left)
    if not rows or now_price is None:
        return "אין נתונים", "עוד לא נמצאו מחירים."
    if n < 14:
        txt = (f"אוסף נתונים ({n} ימי מדידה מתוך 14). עד אז אין המלצה מבוססת. "
               f"{left} ימים עד החג.")
        return "אוסף נתונים", txt + (" " + past if past else "")
    recent = [r for r in rows if (today - date.fromisoformat(r[0])).days <= 14]
    first, last = recent[0][2], recent[-1][2]
    change = round(100 * (last - first) / first) if first else 0
    over = round(100 * (now_price - low_price) / low_price) if low_price else 0
    if over <= 3 and change >= 3:
        label, why = "סביר לקנות", f"המחיר בשפל שמדדנו, והמגמה ב-14 יום עולה ({change:+d}%)."
    elif over <= 3:
        label, why = "בשפל", f"המחיר בשפל שמדדנו. ב-14 יום: {change:+d}%."
    elif change <= -3:
        label, why = "יורד, אפשר לחכות", f"{over}% מעל השפל שמדדנו, אבל ב-14 יום הוא יורד ({change:+d}%)."
    else:
        label, why = "לעקוב", f"{over}% מעל השפל שמדדנו. ב-14 יום: {change:+d}%."
    return label, f"{why} {left} ימים עד החג." + (" " + past if past else "")


def _past_season(h: HC.Holiday, curve: dict, group: str, left: int) -> str:
    """Same holiday in an earlier year: from this many days before the holiday, did the price
    still drop, or only go up? (Empty until we have an earlier season.)"""
    for key, groups in sorted(curve.items(), reverse=True):
        if key == h.key or not key.startswith(h.kind + "-"):
            continue
        rows = groups.get(group) or []
        at = [r for r in rows if r[1] <= left]
        if not rows or not at or at[0][1] < left - 7:
            continue
        p0 = at[0][2]
        later_min = min(r[2] for r in at)
        if later_min < p0 * 0.97:
            return f"בעונה הקודמת ({key}) המחיר ירד מהשלב הזה עוד {round(100 * (p0 - later_min) / p0)}%."
        return f"בעונה הקודמת ({key}) המחיר מהשלב הזה רק עלה או נשאר."
    return ""
