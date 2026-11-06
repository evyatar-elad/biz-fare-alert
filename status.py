"""Writes docs/index.html: a status page served by GitHub Pages.

Shows: last run, blocking, coverage, recent alerts, and per destination the
cheapest business round trip seen in the latest scans (from TLV).
"""
from __future__ import annotations

import html
import json
import statistics
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import config as C
import scanner
from notify import name

OUT = Path(__file__).parent / "docs" / "index.html"
IL = ZoneInfo("Asia/Jerusalem")


def t(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso).astimezone(IL).strftime("%d/%m %H:%M")


def main() -> None:
    state = scanner.load(scanner.STATE_F, {"last": {}})
    hist = scanner.load(scanner.HIST_F, {})
    alerts = scanner.load(scanner.ALERTS_F, {})
    runs = []
    try:
        runs = [json.loads(l) for l in scanner.LOG_F.read_text(encoding="utf-8").splitlines() if l.strip()]
    except FileNotFoundError:
        pass
    now = datetime.now(timezone.utc)

    tasks = scanner.build_tasks(None)
    last = state.get("last", {})
    fresh = sum(1 for x in tasks if x["key"] in last and
                (now - datetime.fromisoformat(last[x["key"]])).total_seconds() / 3600 < x["due_h"])
    ever = sum(1 for x in tasks if x["key"] in last)
    day_runs = [r for r in runs if (now - datetime.fromisoformat(r["at"])).total_seconds() < 86400]
    calls_24h = sum(r.get("calls", 0) for r in day_runs)
    blocks_24h = sum(1 for r in day_runs if r.get("blocked"))
    lr = runs[-1] if runs else {}
    backoff = state.get("backoff_until")
    blocked_now = backoff and now < datetime.fromisoformat(backoff)

    if blocked_now:
        health, color = f"בהמתנה אחרי חסימה של גוגל, עד {t(backoff)}", "#b45309"
    elif runs and (now - datetime.fromisoformat(lr["at"])).total_seconds() > 3 * 3600:
        health, color = "לא רץ כבר יותר מ-3 שעות. כדאי לבדוק את Actions", "#b91c1c"
    else:
        health, color = "פעיל", "#047857"

    # per destination (TLV): cheapest in the latest scan of each month, per source
    def cheapest(rk):
        months = hist.get(rk, {})
        latest = [(rs[-1][2], m, rs[-1][0]) for m, rs in months.items() if rs]
        mins = [r[2] for rs in months.values() for r in rs]  # cheapest of each scan, same basis as alerts
        if not latest:
            return None
        p, m, d = min(latest)
        same_month = [r[2] for r in months[m]]  # usual = cheapest of each scan of THAT month
        return {"p": p, "m": m, "d": d, "med": statistics.median(same_month), "n": len(months)}

    rows = []
    for code, (hname, region, prio) in C.DESTINATIONS.items():
        rows.append((hname, code, prio, cheapest(f"TLV-{code}-{C.REGIONS[region]['dur']}"),
                     cheapest(f"K-TLV-{code}")))
    rows.sort(key=lambda r: (not r[2], r[0]))

    def cells(c):
        if not c:
            return "<td colspan=3 class=m>עוד לא נסרק</td>"
        cheap = " class=good" if c["med"] and c["p"] <= c["med"] * (1 - C.DROP) else ""  # needs history
        return (f"<td{cheap}><b>${c['p']:,.0f}</b><br><span class=m>{c['m']}</span></td>"
                f"<td class=m>${c['med']:,.0f}</td><td class=m>{c['n']}</td>")

    def row(r):
        hname, code, prio, g, k = r
        star = " ⭐" if prio else ""
        return f"<tr><td>{html.escape(hname)}{star}<br><span class=c>{code}</span></td>{cells(g)}{cells(k)}</tr>"

    dormant = [k for k, v in state.get("routes", {}).items() if v.get("empty_streak", 0) >= C.DORMANT_AFTER_EMPTY]
    dormant_html = ("<div class=card><h2>יעדים רדומים</h2><div class=m>אין טיסות בכלל, נבדקים רק כל 10 ימים: "
                    + ", ".join(html.escape(name(k.split('-')[-1]) + (" (Kiwi)" if k.startswith("K-") else "")) for k in dormant)
                    + "</div></div>") if dormant else ""
    al = sorted(alerts.items(), key=lambda kv: kv[1]["at"], reverse=True)[:15]
    def route_label(k: str) -> str:
        parts = k.split("|")[0].split("-")
        src = "Google Flights"
        if parts[0] == "K":
            src, parts = "Kiwi.com", parts[1:]
            if len(parts) > 2:
                src += f" ({parts[2]})"
        o, d = parts[0], parts[1]
        return f"{html.escape(name(o))} - {html.escape(name(d))} <span class=m>· {src}</span>"

    al_rows = "".join(
        f"<tr><td>{t(v['at'])}</td><td>{route_label(k)}</td>"
        f"<td>{k.split('|')[1]}</td><td><b>${v['price']:,.0f}</b></td></tr>" for k, v in al
    ) or "<tr><td colspan=4 class=m>עוד לא נשלחו התראות</td></tr>"

    page = f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="600"><title>בוט מציאות ביזנס</title>
<style>
:root{{--ink:#1f2937;--muted:#6b7280;--line:#e5e7eb;--bg:#f3f4f6;--card:#fff;--navy:#0f2a4a;--good:#047857}}
@media (prefers-color-scheme:dark){{:root{{--ink:#e5e7eb;--muted:#9ca3af;--line:#374151;--bg:#111827;--card:#1f2937;--navy:#0b1f38;--good:#34d399}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif;font-size:15px}}
.wrap{{max-width:860px;margin:0 auto;padding:16px}}
header{{background:var(--navy);color:#fff;border-radius:14px;padding:18px 20px}}
h1{{margin:0;font-size:22px}} h2{{font-size:17px;margin:0 0 10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-top:14px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}}
.kpi b{{display:block;font-size:22px;margin-top:2px}} .m{{color:var(--muted)}} .c{{direction:ltr;text-align:right;color:var(--muted)}}
table{{width:100%;border-collapse:collapse}} td,th{{padding:7px 4px;border-top:1px solid var(--line);text-align:right}}
th{{color:var(--muted);font-weight:normal;font-size:13px;border-top:0}} .good b{{color:var(--good)}}
.scroll{{overflow-x:auto}}
</style></head><body><div class="wrap">
<header><h1>✈️ בוט מציאות ביזנס</h1>
<div style="opacity:.8;margin-top:4px">ביזנס הלוך חזור מתל אביב. מקורות: Google Flights ו-Kiwi.com, וגם ניוזלטרים של חברות תעופה ו-Fly4free. עודכן {t(now.isoformat())}</div></header>
<div class="card"><span style="color:{color};font-weight:bold">● {health}</span></div>
<div class="kpis" style="margin-top:14px">
 <div class="kpi"><span class=m>ריצה אחרונה הסתיימה</span><b>{t(lr.get('end') or lr.get('at'))}</b><span class=m>{lr.get('calls', 0)} בדיקות</span></div>
 <div class="kpi"><span class=m>בדיקות ב-24 שעות</span><b>{calls_24h:,}</b><span class=m>{blocks_24h} חסימות</span></div>
 <div class="kpi"><span class=m>כיסוי עדכני</span><b>{100 * fresh // max(1, len(tasks))}%</b><span class=m>{fresh:,} מתוך {len(tasks):,} חלונות</span></div>
 <div class="kpi"><span class=m>נסרקו אי פעם</span><b>{100 * ever // max(1, len(tasks))}%</b><span class=m>מהחלונות</span></div>
</div>
<div class="card"><h2>התראות אחרונות</h2><div class=scroll><table>
<tr><th>נשלח</th><th>מסלול</th><th>חודש</th><th>מחיר</th></tr>{al_rows}</table></div></div>
{dormant_html}
<div class="card"><h2>הזול ביותר לכל יעד (מתל אביב)</h2>
<div class=m style="font-size:13px;margin-bottom:6px">⭐ יעד מועדף. "רגיל" = לאותו חודש, הזול שנמצא בכל בדיקה בממוצע (חציון), כמו בהתראות. "חודשים" = כמה חודשי יציאה כבר נבדקו (מתוך ~10). גוגל סורק קודם את החודשים הקרובים. ירוק = 35% ומטה מהרגיל.</div>
<div class=scroll><table><tr><th></th><th colspan=3>Google Flights</th><th colspan=3>Kiwi.com</th></tr>
<tr><th>יעד</th><th>הזול</th><th>רגיל</th><th>חודשים</th><th>הזול</th><th>רגיל</th><th>חודשים</th></tr>
{''.join(row(r) for r in rows)}</table></div></div>
<p class=m style="font-size:12px">הנתונים נשמרים בסוף כל ריצה (ריצה = כ-45 דקות סריקה, אחת לשעה בערך), והדף נטען מחדש לבד כל 10 דקות. <a href="https://github.com/evyatar-elad/biz-fare-alert/actions" style="color:inherit">ריצות</a></p>
</div></body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
