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
import holiday_text as T
from profiles import holidays as P

DATA = Path(__file__).parent / "data" / "holidays"
OUT = Path(__file__).parent / "docs" / "holidays.html"
IL = ZoneInfo("Asia/Jerusalem")
NAMES = T.NAMES
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
    r = T.route(o)
    if not r:
        return "<span class=m>מסלול: לבדוק בקישור</span>"
    tags = "".join(f" <span class={'tag' if x.startswith('⭐') else 'tag-warn'}>{e(x)}</span>" for x in T.tags(o))
    return e(r) + tags


def opt_cell(o: dict | None, extra: str = "") -> str:
    if not o:
        return "<td class=m>-</td>"
    notes = f"<br><span class=m>✓ {e(', '.join(n.replace('בארץ', 'בבית') for n in o['notes']))}</span>" if o.get("notes") else ""
    return (f"<td><b>${o['price']:,}</b> <span class=m>{dshort(o['dep'])} - {dshort(o['ret'])}, {o['nights']} לילות, "
            f"<b>{o['vac']}</b> ימי חופש</span>{extra}<br><span style='font-size:13px'>{route_txt(o)}</span>{notes}"
            f"<br>{T.links_html(o)}</td>")


def latest_price(prices: dict, o: dict) -> int | None:
    """The latest price seen for the same source, destination and dates (is the low still there?)."""
    for sk, series in prices.items():
        src, dest = sk.split("|", 1)
        if src != o.get("src"):
            continue
        rows = series.get(f"{o['dep']}|{o['nights']}")
        if rows and (dest == o.get("dest") or ("TYO" if dest in ("NRT", "HND") else dest) == ("TYO" if o.get("dest") in ("NRT", "HND") else o.get("dest"))):
            return rows[-1][1]
    return None


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


def cheapest_within(h: HC.Holiday, prices: dict, group: str, today: date, max_vac: int) -> dict | None:
    """Cheapest fresh price (14-21 nights) whose trip costs at most max_vac vacation days."""
    best = None
    for sk, series in prices.items():
        src, dest = sk.split("|", 1)
        if ("TYO" if dest in ("NRT", "HND", "TYO") else dest) != group:
            continue
        for k, rows in series.items():
            dep_s, n_s = k.split("|")
            n = int(n_s)
            seen, price = rows[-1]
            if not (P.NIGHTS_MAIN[0] <= n <= P.NIGHTS_MAIN[1]) or (today - date.fromisoformat(seen)).days > FRESH_DAYS:
                continue
            if best and price >= best["price"]:
                continue
            dep = date.fromisoformat(dep_s)
            v = HC.vacation(h, dep, dep + timedelta(days=n))["vac"]
            if v <= max_vac:
                best = {"price": price, "dep": dep_s, "ret": (dep + timedelta(days=n)).isoformat(), "nights": n,
                        "vac": v, "src": src}
    return best


CSS = """
:root{--ink:#1f2937;--muted:#6b7280;--line:#e5e7eb;--bg:#f3f4f6;--card:#fff;--navy:#14532d;--good:#047857;--bad:#b91c1c;--cellL:78%;--hl:#ecfdf5}
@media (prefers-color-scheme:dark){:root{--ink:#e5e7eb;--muted:#9ca3af;--line:#374151;--bg:#111827;--card:#1f2937;--navy:#0f3b22;--good:#34d399;--bad:#f87171;--cellL:32%;--hl:#052e1c}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif;font-size:15px}
.wrap{max-width:900px;margin:0 auto;padding:16px}
header{background:var(--navy);color:#fff;border-radius:14px;padding:14px 18px}
h1{margin:0;font-size:21px} h2{font-size:18px;margin:0 0 8px} h3{font-size:15px;margin:14px 0 6px}
.tabs{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.tabs a{color:#fff;text-decoration:none;padding:6px 14px;border-radius:9px;background:rgba(255,255,255,.15);font-weight:bold}
.tabs a.on{background:#fff;color:var(--navy)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-top:12px}
.hero div{padding:6px 0;border-top:1px solid var(--line)} .hero div:first-child{border-top:0}
.hero .k{color:var(--muted);font-size:13px;display:block}
.big{font-size:20px;font-weight:bold;color:var(--good)}
.m{color:var(--muted)} table{width:100%;border-collapse:collapse}
td,th{padding:6px 4px;border-top:1px solid var(--line);text-align:right;vertical-align:top}
th{color:var(--muted);font-weight:normal;font-size:13px}
.scroll{overflow-x:auto}
.thead,.row>summary{display:grid;grid-template-columns:1.2fr .8fr 2fr .8fr .7fr;gap:6px;align-items:center;padding:9px 4px}
.thead{color:var(--muted);font-size:12px}
.row{border-top:1px solid var(--line)} .row>summary{cursor:pointer;list-style:none} .row>summary::-webkit-details-marker{display:none}
.row>summary:hover{background:var(--hl)} .row[open]>summary{background:var(--hl)}
.row .inner{padding:4px 8px 12px}
.price{font-weight:bold} .when{font-size:13px} .vac{font-size:13px}
@media (max-width:600px){.thead{display:none}.row>summary{grid-template-columns:1fr auto;gap:2px 6px}.row .when,.row .vac{grid-column:1/3;font-size:12px;color:var(--muted)}.row>summary>span:nth-child(5){display:none}}
.tag{background:#fef3c7;color:#92400e;font-size:12px;padding:1px 7px;border-radius:9px}
.tag-warn{background:#fee2e2;color:#991b1b;font-size:12px;padding:1px 7px;border-radius:9px}
.good b{color:var(--good)} .up{color:var(--bad)} .down{color:var(--good)} .lnk{color:inherit;font-size:13px}
.mx td,.mx th{padding:3px 4px;font-size:12px;text-align:center;border:1px solid var(--line)}
.mx .rowh{text-align:right;white-space:nowrap} .cell{color:#111} .empty{background:transparent}
.ring{outline:2px solid var(--ink);outline-offset:-2px;font-weight:bold}
details.sub{margin:6px 0} details.sub>summary{cursor:pointer;font-weight:bold}
th.lab{width:150px;color:var(--muted);font-weight:normal;font-size:13px}
.adv{background:#dbeafe;color:#1e3a8a;font-size:12px;padding:1px 8px;border-radius:9px}
"""


def page_html(title: str, active: str, tabs: list, body: str, now: datetime, lr: dict) -> str:
    tab_html = "".join(f'<a href="{href}" class="{"on" if key == active else ""}">{e(label)}</a>' for key, label, href in tabs)
    return f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="600"><title>{e(title)}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header><h1>🌴 חגים בתיירים</h1>
<div style="opacity:.85;font-size:13px;margin-top:4px">הלוך חזור מתל אביב, נוסע אחד. עודכן {t(now.isoformat())}.</div>
<nav class=tabs>{tab_html}<a href="index.html">ביזנס ←</a></nav></header>
{body}
<p class=m style="font-size:12px">הריצה האחרונה: {t(lr.get('at'))}, {lr.get('calls', 0)} חיפושים.
<a href="https://github.com/evyatar-elad/biz-fare-alert/actions" style="color:inherit">ריצות</a></p>
</div></body></html>"""


def holiday_body(h: HC.Holiday, best: dict, curve: dict, news: list, today: date) -> tuple[str, dict]:
    """The page of one holiday, and a short summary for the landing page."""
    hb = best.get(h.key, {})
    prices = jload(f"prices/{h.key}.json", {})
    bs = HC.best_spread(h)
    top = bs["top"][0]
    few = top["vac"] + 2
    groups = [g for g in hb if not g.startswith("_")]
    rows, cheapest, data_days = [], None, 0
    entries = []
    for g in groups:
        b = hb[g]
        fresh = cheapest_within(h, prices, g, today, 99)
        bn = b.get("now")
        if fresh and not (bn and (bn["dep"], bn["nights"], bn["price"]) == (fresh["dep"], fresh["nights"], fresh["price"])):
            fresh["dest"] = g
            b = {**b, "now": {**fresh, "notes": HC.notes(h, date.fromisoformat(fresh["dep"]), date.fromisoformat(fresh["ret"]))}}
        if b.get("now"):
            entries.append((g, b))
    entries.sort(key=lambda x: x[1]["now"]["price"])
    best_few = None
    for g, b in entries:
        now_o = b["now"]
        cw = cheapest_within(h, prices, g, today, few)
        if cw:
            cw["dest"] = g
            cw["notes"] = HC.notes(h, date.fromisoformat(cw["dep"]), date.fromisoformat(cw["ret"]))
            if not best_few or cw["price"] < best_few[1]["price"]:
                best_few = (g, cw)
        low = b.get("low")
        low_extra = ""
        if low:
            lp = latest_price(prices, low)
            low_extra = (f" <span class=m>(נמצא {e(low['found'][8:10] + '/' + low['found'][5:7])}"
                         + ("; עדיין זמין" if lp == low["price"] else f"; עכשיו באותם תאריכים: ${lp:,}" if lp else "") + ")</span>")
        label, why = T.advice(h, curve, g, now_o["price"], (low or {}).get("price"), today)
        data_days = max(data_days, len({r[0] for r in curve.get(h.key, {}).get(g, [])}))

        def line(title, cell):
            return f"<tr><th class=lab>{title}</th>{cell}</tr>"
        det = [line("הזול עכשיו", opt_cell(now_o)),
               line(f"הזול עם עד {few} ימי חופש", opt_cell(cw)),
               line(f"קצר וזול (עצירה אחת, עד {P.FAST_HOURS.get(g, 20)} שעות לכיוון כולל המתנה)", opt_cell(b.get("fast"))),
               line("הזול בלי אירופה", opt_cell(b.get("noeu")))]
        for hub, st in sorted((b.get("stops") or {}).items(), key=lambda kv: kv[1]["price"]):
            parts = []
            if st.get("n_out"):
                parts.append(f"{st['n_out']} {'לילה' if st['n_out'] == 1 else 'לילות'} בהלוך")
            if st.get("n_back"):
                parts.append(f"{st['n_back']} {'לילה' if st['n_back'] == 1 else 'לילות'} בחזור")
            diff = st["price"] - now_o["price"]
            legs = " · ".join(f"{e(T.city(l[0]))}-{e(T.city(l[1]))} {dshort(l[2])}" for l in st["legs"])
            det.append(line(f"עצירה ב{e(T.city(hub))} (כרטיס אחד)",
                            f"<td><b>${st['price']:,}</b> <span class=m>({'+' if diff >= 0 else '-'}${abs(diff):,} מהזול עכשיו) · "
                            f"{e(', '.join(parts))} · {st['vac']} ימי חופש</span><br><span style='font-size:13px'>{legs} · "
                            f"{e(', '.join(st['airlines']))}</span><br><a href='{e(T.google_multi_link(st['legs']))}' class=lnk "
                            f"target=_blank>לחיפוש הזה בגוגל</a></td>"))
        gch = b.get("google") or {}
        for k, lab in (("any", "בגוגל לאותם תאריכים"), ("onestop", "בגוגל, עצירה אחת לכל היותר")):
            if gch.get(k):
                det.append(line(lab, opt_cell(gch[k])))
        det.append(line("הזול מאז שהתחלנו", opt_cell(low, low_extra)))
        bz = b.get("biz")
        if bz:
            det.append(line("ביזנס (הצצה)", f"<td{' class=good' if bz['price'] <= P.BIZ_PEEK_MAX else ''}><b>${bz['price']:,}</b> "
                            f"<span class=m>{dshort(bz['dep'])}, {bz['nights']} לילות</span><br>{T.links_html({**bz, 'dest': g})}</td>"))
        dep, ret = date.fromisoformat(now_o["dep"]), date.fromisoformat(now_o["ret"])
        rows.append(
            f"<details class=row><summary><b>{e(group_name(g))}</b><span class=price>${now_o['price']:,}</span>"
            f"<span class=when>{dep.day}/{dep.month} - {ret.day}/{ret.month} · {now_o['nights']} לילות</span>"
            f"<span class=vac>{now_o['vac']} ימי חופש</span><span>{trend(curve.get(h.key, {}).get(g, []))}</span></summary>"
            f"<div class=inner><div class=m style='margin-bottom:6px'><span class=adv>{e(label)}</span> {e(why)}</div>"
            f"<div class=scroll><table>{''.join(det)}</table></div>"
            f"<details class=sub><summary>לוח מחירים: תאריך יציאה × לילות</summary>{matrix(h, prices, g, today)}</details></div></details>")
    if entries:
        cheapest = entries[0]
    lead = (h.dep[0] - today).days
    hero = []
    if cheapest:
        g, b = cheapest
        o = b["now"]
        dep, ret = date.fromisoformat(o["dep"]), date.fromisoformat(o["ret"])
        hero.append(f"<div><span class=k>הזול כרגע</span><span class=big>{e(group_name(g))} ${o['price']:,}</span> "
                    f"· {e(HC.fmt(dep))} - {e(HC.fmt(ret))} · {o['nights']} לילות · {o['vac']} ימי חופש</div>")
    few_txt = ""
    if best_few:
        g, c = best_few
        dep, ret = date.fromisoformat(c["dep"]), date.fromisoformat(c["ret"])
        few_txt = (f"<br>הזול עם עד {few} ימי חופש: <b>{e(group_name(g))} ${c['price']:,}</b> · {e(HC.fmt(dep))} - {e(HC.fmt(ret))}, "
                   f"{c['vac']} ימי חופש")
    hero.append(f"<div><span class=k>הכי חסכוני בימי חופש</span>{e(HC.fmt(top['dep']))} - {e(HC.fmt(top['ret']))} · "
                f"{top['nights']} לילות · <b>{top['vac']} ימי חופש</b>{few_txt}</div>")
    if data_days < 14:
        buy = f"עוד אין המלצה: אוספים נתונים ({data_days} ימי מדידה מתוך 14). {lead} ימים עד היציאה הראשונה האפשרית."
    else:
        labels = [T.advice(h, curve, g, b["now"]["price"], (b.get("low") or {}).get("price"), today)[0] for g, b in entries]
        buy = " · ".join(f"{lab}: {labels.count(lab)} יעדים" for lab in dict.fromkeys(labels))
    hero.append(f"<div><span class=k>מתי לקנות</span>{e(buy)}</div>")

    days = "".join(f"<tr><td>{e(HC.fmt(d))}/{d.year}</td><td>{e(h.labels[d])}</td></tr>" for d in sorted(h.labels))
    spread = "".join(f"<tr><td>{e(HC.fmt(r['dep']))} - {e(HC.fmt(r['ret']))}</td><td>{r['nights']}</td><td><b>{r['vac']}</b></td>"
                     f"<td class=m>{e(', '.join(r['notes']))}</td></tr>" for r in bs["top"])
    per_n = "".join(f"<tr><td>{r['nights']}</td><td>{e(HC.fmt(r['dep']))} - {e(HC.fmt(r['ret']))}</td><td>{r['vac']}</td></tr>"
                    for r in bs["per_nights"])
    oj_rows = []
    for k, c in sorted(hb.get("_open_jaw_1t", {}).items(), key=lambda kv: kv[1]["price"]):
        a, b2 = k.split("-")
        oj_rows.append(f"<tr><td>הלוך ל{e(T.city(a))}, חזור מ{e(T.city(b2))}</td><td><b>${c['price']:,}</b> (כרטיס אחד)</td>"
                       f"<td class=m>{dshort(c['legs'][0][2])} - {dshort(c['legs'][-1][2])}, {c['vac']} ימי חופש</td>"
                       f"<td><a href='{e(T.google_multi_link(c['legs']))}' class=lnk target=_blank>בגוגל</a></td></tr>")
    for k, c in sorted(hb.get("_open_jaw", {}).items(), key=lambda kv: kv[1]["price"]):
        a, b2 = k.split("-")
        oj_rows.append(f"<tr><td>הלוך ל{e(T.city(a))}, חזור מ{e(T.city(b2))}</td><td><b>${c['price']:,}</b> (שני כרטיסים)</td>"
                       f"<td class=m>{dshort(c['dep'])} - {dshort(c['ret'])}, {c['vac']} ימי חופש</td><td></td></tr>")
    hnews = [n for n in news if any(d.get("holiday") == h.key for d in n.get("deals", []))]
    news_rows = []
    for n in reversed(hnews[-10:]):
        lines = []
        for d in n.get("deals", []):
            if d.get("holiday") != h.key:
                continue
            g = "TYO" if d.get("destination") in ("NRT", "HND", "TYO") else d.get("destination")
            o = (hb.get(g) or {}).get("now")
            price = f"{d['price']:,.0f} {d.get('currency') or ''}" if d.get("price") is not None else "בלי מחיר"
            lines.append(f"{e(T.city(d['destination']) if d.get('destination') else d.get('destination_name') or '?')}: {e(price)}"
                         + (f" · אצלנו לחג הזה: ${o['price']:,}" if o else ""))
        news_rows.append(f"<tr><td class=m>{t(n['at'])}</td><td><b>{e(n['from'])}</b>: {e(n.get('summary', ''))}"
                         f"<br><span style='font-size:13px'>{'<br>'.join(lines)}</span></td></tr>")
    body = f"""
<div class="card hero"><h2>{e(h.name)}</h2>{''.join(hero)}</div>
<div class=card><h2>לכל יעד: הזול עכשיו</h2>
<div class=m style="font-size:13px;margin-bottom:4px">לחיצה על יעד פותחת פירוט: מסלולים, עצירה בכרטיס אחד, קישורים ולוח מחירים.</div>
<div class=thead><span>יעד</span><span>מחיר</span><span>תאריכים</span><span>ימי חופש</span><span>שבוע</span></div>
{''.join(rows) or "<div class=m>עוד אין מחירים לחג הזה</div>"}</div>
<div class=card>
<details class=sub><summary>ימי החג וכל התאריכים החסכוניים</summary>
<div class=m style="font-size:13px">ימי חופש = ראשון-חמישי שאינם חג, ערב חג או חול המועד, כולל ימי הטיסה. יציאה אפשרית
{e(HC.fmt(h.dep[0]))} עד {e(HC.fmt(h.dep[1]))}.</div>
<h3>ימי החג</h3><table>{days}</table>
<h3>הכי חסכוני בימי חופש</h3><table><tr><th>תאריכים</th><th>לילות</th><th>ימי חופש</th><th></th></tr>{spread}</table>
<h3>לפי אורך הטיול</h3><table><tr><th>לילות</th><th>תאריכים</th><th>ימי חופש</th></tr>{per_n}</table></details>
<details class=sub><summary>מבצעים מניוזלטרים לחג הזה ({len(hnews)})</summary>
<table>{''.join(news_rows) or "<tr><td class=m>עוד לא נמצאו</td></tr>"}</table></details>
<details class=sub><summary>Open jaw: הלוך לעיר אחת, חזור מאחרת ({len(oj_rows)})</summary>
<div class=scroll><table>{''.join(oj_rows) or "<tr><td class=m>עוד אין</td></tr>"}</table></div></details>
<details class=sub><summary>איך זה עובד</summary>
<ul style="line-height:1.7;margin:8px 0 0;padding-right:18px">
<li>הבוט בודק כל תאריך יציאה וכל אורך טיול ({P.NIGHTS_FLEX[0]}-{P.NIGHTS_FLEX[1]} לילות; בטבלה {P.NIGHTS_MAIN[0]}-{P.NIGHTS_MAIN[1]}), בכל היעדים, ב-Kiwi ובגוגל.</li>
<li>מייל רק כשיש מחיר הכי זול מאז שהתחלנו או ירידה של {round(P.DROP_ALERT * 100)}%, ובנוסף סיכום שבועי ביום ראשון.</li>
<li>"עצירה בכרטיס אחד": לילה-שניים בעיר ביניים, כרטיס אחד של החברה (כמו באקו בכרטיס לסין). ביטול טיסה מבטל הכל יחד.</li>
<li>"מתי לקנות" מבוסס רק על המדידות שלנו: אחרי שבועיים, האם המחיר בשפל שמדדנו ולאן המגמה; מהשנה הבאה גם מה קרה בעונה הקודמת.</li>
<li>"✓ ליל הסדר בבית" ליד מחיר = התאריכים מאפשרים להיות בבית באותו ערב. רק הערה.</li>
<li>בלי טורקיה ובלי מדינות אויב, גם לא בקונקשן.</li></ul></details></div>"""
    summ = {"name": h.name, "cheapest": cheapest, "top": top}
    return body, summ


def page_name(h: HC.Holiday) -> str:
    return f"{h.kind}.html"  # pesach.html / tishrei.html: the nearest holiday of each kind


def main(out_dir: Path = OUT.parent) -> None:
    today = date.today()
    now = datetime.now(timezone.utc)
    best, curve = jload("best.json", {}), jload("curve.json", {})
    news = jload("pending_news.json", [])
    try:
        runs = [json.loads(x) for x in (DATA / "runs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    except FileNotFoundError:
        runs = []
    lr = runs[-1] if runs else {}
    hols, seen = [], set()
    for h in HC.upcoming(today):
        if h.kind not in seen:
            seen.add(h.kind)
            hols.append(h)
    tabs = [("home", "כל החגים", "holidays.html")] + [(h.kind, h.name, page_name(h)) for h in hols]
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for h in hols:
        body, summ = holiday_body(h, best, curve, news, today)
        (out_dir / page_name(h)).write_text(page_html(h.name, h.kind, tabs, body, now, lr), encoding="utf-8")
        c = summ["cheapest"]
        line = "עוד אין מחירים"
        if c:
            g, b = c
            o = b["now"]
            d0, d1 = date.fromisoformat(o["dep"]), date.fromisoformat(o["ret"])
            line = (f"<span class=big>{e(group_name(g))} ${o['price']:,}</span> · {d0.day}/{d0.month} - {d1.day}/{d1.month} · "
                    f"{o['vac']} ימי חופש")
        tp = summ["top"]
        cards.append(f"<a href='{page_name(h)}' style='color:inherit;text-decoration:none'><div class='card hero'>"
                     f"<h2>{e(h.name)} ←</h2><div><span class=k>הזול כרגע</span>{line}</div>"
                     f"<div><span class=k>הכי חסכוני בימי חופש</span>{e(HC.fmt(tp['dep']))} - {e(HC.fmt(tp['ret']))}, "
                     f"{tp['vac']} ימי חופש</div></div></a>")
    (out_dir / "holidays.html").write_text(page_html("חגים בתיירים", "home", tabs, "".join(cards), now, lr), encoding="utf-8")


if __name__ == "__main__":
    main()
