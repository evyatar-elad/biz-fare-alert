"""Writes docs/holidays.html: the "holidays - economy" page (GitHub Pages, next to the business page).

Per holiday: the holiday days, the dates that cost the fewest vacation days (always shown),
the cheapest economy round trip per destination (now / ever / without Europe / at most one
stop), the trend, newsletter promos for the holiday, and a color matrix per destination
(departure date x nights).
"""
from __future__ import annotations

import html
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import holiday_cal as HC
from profiles import holidays as P

DATA = Path(__file__).parent / "data" / "holidays"
OUT = Path(__file__).parent / "docs" / "holidays.html"
IL = ZoneInfo("Asia/Jerusalem")
NAMES = {**{k: v[0] for k, v in P.DESTINATIONS.items()}, "TYO": "טוקיו"}
FRESH_DAYS = 3  # matrix cells older than this are not shown


def jload(name, default):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def e(s) -> str:
    return html.escape(str(s))


def t(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso).astimezone(IL).strftime("%d/%m %H:%M")


def dshort(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{HC.fmt(d)}"


def group_name(g: str) -> str:
    return NAMES.get(g, g)


def route_txt(o: dict) -> str:
    if o.get("via_out") is None:
        return "<span class=m>(גוגל: מסלול לא ידוע)</span>"
    def one(v):
        return "ישירה" if not v else "דרך " + "/".join(v)
    s = one(o["via_out"]) if o["via_out"] == o["via_ret"] else f"הלוך {one(o['via_out'])}, חזור {one(o['via_ret'])}"
    tags = []
    if o.get("europe"):
        tags.append("<span class=tag-warn>דרך אירופה</span>")
    stops = [v for v in (o.get("via_out") or []) + (o.get("via_ret") or []) if v in P.STOPOVER_HUBS]
    if stops:
        tags.append("<span class=tag>⭐ " + e(P.STOPOVER_HUBS[stops[0]]) + "</span>")
    if o.get("separate"):
        tags.append("<span class=tag-warn>כרטיסים נפרדים</span>")
    hours = f" · {o['hours_out']:g}/{o['hours_ret']:g} שעות" if o.get("hours_out") else ""
    return e(s) + hours + (" " + " ".join(tags) if tags else "")


def opt_cell(o: dict | None, extra: str = "") -> str:
    if not o:
        return "<td class=m>-</td>"
    notes = f"<br><span class=m>{e(', '.join(o['notes']))}</span>" if o.get("notes") else ""
    link = f" <a href='{e(o['url'])}' class=lnk>להזמנה</a>" if o.get("url") else ""
    return (f"<td><b>${o['price']:,}</b> <span class=m>{dshort(o['dep'])} - {dshort(o['ret'])}, {o['nights']} לילות, "
            f"<b>{o['vac']}</b> ימי חופש</span>{extra}<br><span style='font-size:13px'>{route_txt(o)}</span>{notes}{link}</td>")


def trend(curve_rows: list) -> str:
    if len(curve_rows) < 2:
        return "<span class=m>עוד אין</span>"
    last = curve_rows[-1][2]
    week = [r for r in curve_rows if (date.fromisoformat(curve_rows[-1][0]) - date.fromisoformat(r[0])).days >= 7]
    ref = week[-1][2] if week else curve_rows[0][2]
    d = last - ref
    if d == 0:
        return "<span class=m>ללא שינוי</span>"
    pct = round(100 * d / ref)
    return f"<span class={'up' if d > 0 else 'down'}>{'▲' if d > 0 else '▼'} {abs(pct)}%</span>"


def matrix(h: HC.Holiday, prices: dict, group: str, today: date) -> str:
    """Departure date (rows) x nights (columns), cheapest fresh price over all sources; color by price."""
    cells: dict[tuple[str, int], int] = {}
    for sk, series in prices.items():
        src, dest = sk.split("|", 1)
        if ("TYO" if dest in ("NRT", "HND", "TYO") else dest) != group:
            continue
        for k, rows in series.items():
            dep, n = k.split("|")
            seen, price = rows[-1]
            if (today - date.fromisoformat(seen)).days > FRESH_DAYS:
                continue
            key = (dep, int(n))
            cells[key] = min(price, cells.get(key, 10 ** 9))
    if not cells:
        return "<div class=m>עוד אין מחירים טריים</div>"
    lo, hi = min(cells.values()), max(cells.values())
    best = {(r["dep"].isoformat(), r["nights"]) for r in HC.best_spread(h)["top"]}

    def color(p):
        x = (p - lo) / max(1, hi - lo)
        # green (cheap) -> yellow -> red (expensive)
        hue = int(130 - 130 * x)
        return f"hsl({hue},70%,var(--cellL))"
    nights = list(range(P.NIGHTS_FLEX[0], P.NIGHTS_FLEX[1] + 1))
    head = "<tr><th>יציאה \\ לילות</th>" + "".join(f"<th>{n}</th>" for n in nights) + "</tr>"
    rows = []
    for dep in h.departures():
        di = dep.isoformat()
        tds = []
        for n in nights:
            p = cells.get((di, n))
            if p is None:
                tds.append("<td class=empty></td>")
                continue
            v = HC.vacation(h, dep, dep + timedelta(days=n))["vac"]
            ring = " ring" if (di, n) in best else ""
            tds.append(f"<td class='cell{ring}' style='background:{color(p)}' title='{e(HC.fmt(dep))} + {n} לילות: "
                       f"${p:,}, {v} ימי חופש'>{p}</td>")
        lab = h.labels.get(dep, "")
        rows.append(f"<tr><th class=rowh>{e(HC.fmt(dep))}<span class=m> {e(lab)}</span></th>{''.join(tds)}</tr>")
    return (f"<div class=scroll><table class=mx>{head}{''.join(rows)}</table></div>"
            f"<div class=m style='font-size:12px'>ירוק = זול, אדום = יקר (בתוך היעד הזה). מסגרת = מהתאריכים הכי חסכוניים בימי חופש. "
            f"מחירים מ-{FRESH_DAYS} הימים האחרונים, הזול מבין Kiwi וגוגל.</div>")


def main(out: Path = OUT) -> None:
    today = date.today()
    now = datetime.now(timezone.utc)
    best, curve = jload("best.json", {}), jload("curve.json", {})
    news = jload("pending_news.json", [])
    runs = []
    try:
        runs = [json.loads(x) for x in (DATA / "runs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    except FileNotFoundError:
        pass
    lr = runs[-1] if runs else {}
    sections = []
    for h in HC.upcoming(today):
        hb = best.get(h.key, {})
        prices = jload(f"prices/{h.key}.json", {})
        days = "".join(f"<tr><td>{e(HC.fmt(d))}/{d.year}</td><td>{e(h.labels[d])}</td></tr>" for d in sorted(h.labels))
        bs = HC.best_spread(h)
        spread = "".join(
            f"<tr><td>{e(HC.fmt(r['dep']))} - {e(HC.fmt(r['ret']))}</td><td>{r['nights']}</td><td><b>{r['vac']}</b></td>"
            f"<td class=m>{e(', '.join(r['notes']))}</td></tr>" for r in bs["top"])
        per_n = "".join(f"<tr><td>{r['nights']}</td><td>{e(HC.fmt(r['dep']))} - {e(HC.fmt(r['ret']))}</td><td>{r['vac']}</td></tr>"
                        for r in bs["per_nights"])
        groups = sorted(hb, key=lambda g: (hb[g].get("now") or {}).get("price", 10 ** 9))
        drows = []
        for g in groups:
            b = hb[g]
            low = b.get("low")
            low_txt = (f"<td><b>${low['price']:,}</b><br><span class=m>נמצא {e(low['found'][8:10] + '/' + low['found'][5:7])}</span></td>"
                       if low else "<td>-</td>")
            bz = b.get("biz")
            biz_txt = ("<td class=m>-</td>" if not bz else
                       f"<td{' class=good' if bz['price'] <= P.BIZ_PEEK_MAX else ''}><b>${bz['price']:,}</b>"
                       f"<br><span class=m>{dshort(bz['dep'])}, {bz['nights']} לילות</span></td>")
            drows.append(f"<tr><th>{e(group_name(g))}</th>{opt_cell(b.get('now'))}{low_txt}"
                         f"<td>{trend(curve.get(h.key, {}).get(g, []))}</td>{opt_cell(b.get('noeu'))}{opt_cell(b.get('onestop'))}{biz_txt}</tr>")
        lead = (h.dep[0] - today).days
        mats = "".join(f"<details class=sub><summary>{e(group_name(g))}</summary>{matrix(h, prices, g, today)}</details>"
                       for g in groups)
        hnews = [n for n in news if any(d.get("holiday") == h.key for d in n.get("deals", []))]
        news_rows = "".join(
            f"<tr><td class=m>{t(n['at'])}</td><td>{e(n['from'])}</td><td>{e(n['subject'])}<br>"
            f"<span class=m style='font-size:13px'>{e(n.get('summary', ''))}</span></td></tr>" for n in reversed(hnews[-10:]))
        sections.append(f"""
<div class="card hol"><h2>{e(h.name)}</h2>
<div class=m>יציאה אפשרית {e(HC.fmt(h.dep[0]))}/{h.dep[0].year} עד {e(HC.fmt(h.dep[1]))} ({lead} יום מהיום). אורך {P.NIGHTS_MAIN[0]}-{P.NIGHTS_MAIN[1]} לילות
(נבדק גם {P.NIGHTS_FLEX[0]}-{P.NIGHTS_FLEX[1]} למחיר חריג).</div>
<div class=two>
<div><h3>ימי החג</h3><table>{days}</table></div>
<div><h3>הכי חסכוני בימי חופש</h3><div class=m style="font-size:13px">ימי חופש רגילים = ראשון-חמישי שאינם חג, ערב חג או חול המועד (כולל ימי הטיסה). קבוע, בלי קשר למחיר.</div>
<table><tr><th>תאריכים</th><th>לילות</th><th>ימי חופש</th><th></th></tr>{spread}</table>
<details class=sub><summary>לפי אורך הטיול</summary><table><tr><th>לילות</th><th>תאריכים</th><th>ימי חופש</th></tr>{per_n}</table></details></div>
</div>
<h3>הזול לכל יעד (תיירים, הלוך חזור, נוסע אחד)</h3>
<div class=scroll><table class=dest><tr><th>יעד</th><th>הזול עכשיו</th><th>הזול מאז שהתחלנו</th><th>מגמה בשבוע</th><th>הזול בלי אירופה</th><th>הזול עם עצירה אחת לכל היותר</th><th>ביזנס (הצצה)</th></tr>
{''.join(drows) or "<tr><td colspan=7 class=m>עוד אין מחירים לחג הזה</td></tr>"}</table></div>
<h3>לוח מחירים לכל יעד</h3>{mats or "<div class=m>עוד אין</div>"}
<h3>מבצעים מהניוזלטרים לחג הזה</h3>
<div class=scroll><table>{news_rows or "<tr><td class=m>עוד לא נמצאו</td></tr>"}</table></div>
</div>""")

    page = f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="600"><title>חגים - תיירים</title>
<style>
:root{{--ink:#1f2937;--muted:#6b7280;--line:#e5e7eb;--bg:#f3f4f6;--card:#fff;--navy:#14532d;--good:#047857;--bad:#b91c1c;--cellL:78%}}
@media (prefers-color-scheme:dark){{:root{{--ink:#e5e7eb;--muted:#9ca3af;--line:#374151;--bg:#111827;--card:#1f2937;--navy:#0f3b22;--good:#34d399;--bad:#f87171;--cellL:32%}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif;font-size:15px}}
.wrap{{max-width:1000px;margin:0 auto;padding:16px}}
header{{background:var(--navy);color:#fff;border-radius:14px;padding:18px 20px}}
h1{{margin:0;font-size:22px}} h2{{font-size:19px;margin:0 0 6px}} h3{{font-size:15px;margin:16px 0 6px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-top:14px}}
.m{{color:var(--muted)}} table{{width:100%;border-collapse:collapse}}
td,th{{padding:6px 4px;border-top:1px solid var(--line);text-align:right;vertical-align:top}}
th{{color:var(--muted);font-weight:normal;font-size:13px}} .dest th{{color:var(--ink);font-weight:bold}}
.scroll{{overflow-x:auto}} .two{{display:grid;grid-template-columns:1fr 1.4fr;gap:18px}}
@media (max-width:700px){{.two{{grid-template-columns:1fr}}}}
.tag{{background:#fef3c7;color:#92400e;font-size:12px;padding:1px 7px;border-radius:9px}}
.tag-warn{{background:#fee2e2;color:#991b1b;font-size:12px;padding:1px 7px;border-radius:9px}}
.good b{{color:var(--good)}} .up{{color:var(--bad)}} .down{{color:var(--good)}} .lnk{{color:inherit;font-size:13px}}
.mx td,.mx th{{padding:3px 4px;font-size:12px;text-align:center;border:1px solid var(--line)}}
.mx .rowh{{text-align:right;white-space:nowrap}} .cell{{color:#111}} .empty{{background:transparent}}
.ring{{outline:2px solid var(--ink);outline-offset:-2px;font-weight:bold}}
details.sub{{margin:6px 0}} details.sub summary{{cursor:pointer;color:var(--ink)}}
</style></head><body><div class="wrap">
<header><h1>🌴 חגים - תיירים</h1>
<div style="opacity:.85;margin-top:4px">טיסות <b>בתיירים</b> הלוך חזור מתל אביב לחגי תשרי ולפסח, לנוסע אחד. מקורות: Kiwi.com ו-Google Flights, וגם ניוזלטרים (נקראים עם AI).
עודכן {t(now.isoformat())}. <a href="index.html" style="color:#fff">לבוט הביזנס ←</a></div></header>
<div class="card"><span id=health style="font-weight:bold;color:var(--good)">● הריצה האחרונה: {t(lr.get('at'))}, {lr.get('calls', 0)} חיפושים, {lr.get('points', 0)} מחירים</span></div>
<script>(function(){{var age=(Date.now()-{int(now.timestamp() * 1000)})/36e5; if(age>26){{var h=document.getElementById('health');
h.style.color='var(--bad)'; h.textContent='● הדף לא עודכן כבר '+Math.round(age)+' שעות. כדאי לבדוק את Actions';}}}})();</script>
<details class="card"><summary style="cursor:pointer;font-weight:bold">איך זה עובד? (לחץ להסבר)</summary>
<ul style="line-height:1.7;margin:10px 0 0;padding-right:18px">
<li>לכל חג הבוט בודק כל תאריך יציאה אפשרי וכל אורך טיול ({P.NIGHTS_FLEX[0]}-{P.NIGHTS_FLEX[1]} לילות), לכל היעדים.</li>
<li>לא רק מציאות: תמיד מוצג <b>הזול ביותר</b> שנמצא. מייל נשלח רק כשיש שיא זול חדש או ירידה של {round(P.DROP_ALERT * 100)}% ומעלה, ובנוסף סיכום שבועי.</li>
<li>לכל אפשרות מחושב כמה <b>ימי חופש רגילים</b> היא עולה (ראשון-חמישי שאינם חג, ערב חג או חול המועד).</li>
<li>המחיר קובע. דרך אירופה, כרטיסים נפרדים ועצירות מסומנים כדי שתוכל להחליט. בלי טורקיה ובלי מדינות אויב, גם לא בקונקשן.</li>
<li>"ביזנס (הצצה)": הזול בביזנס ל-15 לילות בחלון החג (Google Flights). ירוק = עד ${P.BIZ_PEEK_MAX:,}.</li>
<li>כל מחיר נשמר עם התאריך שבו נמדד, כדי ללמוד עם השנים מתי הכי כדאי להזמין.</li>
</ul></details>
{''.join(sections)}
<p class=m style="font-size:12px"><a href="https://github.com/evyatar-elad/biz-fare-alert/actions" style="color:inherit">ריצות</a></p>
</div></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
