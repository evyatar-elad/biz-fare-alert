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
    elif lr and not lr.get("calls"):
        health, color = "פעיל. כרגע הכל עדכני, אין מה לחפש (הריצה האחרונה לא מצאה חיפוש שהגיע זמנו)", "#047857"
    else:
        health, color = "פעיל", "#047857"

    # per destination (TLV): cheapest in the latest scan of each month, per source
    kiwi_best = state.get("kiwi_best", {})

    def cheapest(rk):
        months = hist.get(rk, {})
        latest = [(rs[-1][2], m, rs[-1][0]) for m, rs in months.items() if rs]
        if not latest:
            return None
        p, m, d = min(latest)
        past = [r[2] for r in months[m][:-1]]  # earlier scans of THAT month (same basis as alerts)
        kb = kiwi_best.get(rk, {}).get(m) if rk.startswith("K-") else None
        return {"p": p, "m": m, "d": d, "med": statistics.median(past) if len(past) >= 2 else None, "kb": kb}

    rows = []
    for code, (hname, region, prio) in C.DESTINATIONS.items():
        rows.append((hname, code, prio, cheapest(f"TLV-{code}-{C.REGIONS[region]['dur']}"),
                     cheapest(f"K-TLV-{code}")))
    rows.sort(key=lambda r: (not r[2], r[0]))

    def via_txt(kb):
        if not kb:
            return ""
        v = "ישירה" if not kb["via"] else "דרך " + ", ".join(name(x) for x in kb["via"])
        sep = " · כרטיסים נפרדים" if kb.get("sep") else ""
        return f"<br><span class=m>{html.escape(v)}{sep}</span>"

    def cells(c):
        if not c:
            return "<td colspan=2 class=m>עוד לא נסרק</td>"
        cheap = " class=good" if c["med"] and c["p"] <= c["med"] * (1 - C.DROP) else ""
        usual = f"${c['med']:,.0f}" if c["med"] else "<span class=m>עוד אין</span>"
        return (f"<td{cheap}><b>${c['p']:,.0f}</b><br><span class=m>{c['m']}</span>{via_txt(c.get('kb'))}</td>"
                f"<td class=m>{usual}</td>")

    def row(r):
        hname, code, prio, g, k = r
        star = " ⭐" if prio else ""
        return f"<tr><td>{html.escape(hname)}{star}<br><span class=c>{code}</span></td>{cells(g)}{cells(k)}</tr>"

    dormant = [k for k, v in state.get("routes", {}).items() if v.get("empty_streak", 0) >= C.DORMANT_AFTER_EMPTY]
    dormant_html = ("<div class=card><h2>יעדים רדומים</h2><div class=m>אין טיסות בכלל, נבדקים רק כל 10 ימים: "
                    + ", ".join(html.escape(name(k.split('-')[-1]) + (" (Kiwi)" if k.startswith("K-") else "")) for k in dormant)
                    + "</div></div>") if dormant else ""
    this_month = now.astimezone(IL).strftime("%Y-%m")
    al = sorted(((k, v) for k, v in alerts.items()
                 if "|" not in k  # old per-month format = the false alerts of 6-9/11
                 and (now - datetime.fromisoformat(v["at"])).days <= C.REALERT_DAYS
                 and (v.get("month") or "9999") >= this_month),
                key=lambda kv: kv[1]["at"], reverse=True)[:15]
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
        f"<td>{v.get('month') or (k.split('|')[1] if '|' in k else '')}</td><td><b>${v['price']:,.0f}</b></td></tr>"
        for k, v in al
    ) or "<tr><td colspan=4 class=m>עוד לא נשלחו התראות</td></tr>"

    import json as _j
    def jload(name, default):
        try:
            return _j.loads((scanner.DATA / name).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return default
    nstats = jload("news_stats.json", {})
    nlog = jload("news_log.json", [])
    nwait = jload("pending_news.json", [])
    days = sorted(nstats)[-7:]
    n_read = sum(nstats[d]["read"] for d in days)
    n_match = sum(nstats[d]["matched"] for d in days)
    senders = {}
    for d in days:
        for k, v in nstats[d]["senders"].items():
            senders[k] = senders.get(k, 0) + v
    sender_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>"
                          for k, v in sorted(senders.items(), key=lambda kv: -kv[1])[:15]) \
        or "<tr><td colspan=2 class=m>עוד אין נתונים (נאספים מ-9/11)</td></tr>"
    log_rows = "".join(
        f"<tr><td class=m>{t(x['at'])}</td><td>{html.escape(x.get('from',''))}</td>"
        f"<td>{html.escape(x.get('subject',''))}"
        + (f"<br><span class=m style='font-size:13px'>{html.escape(x['snip'][:160])}</span>" if x.get('snip') else "")
        + (f" <a href='{html.escape(x['link'])}' style='color:inherit'>לפוסט</a>" if x.get('link') else "")
        + "</td></tr>" for x in reversed(nlog[-12:])) \
        or "<tr><td colspan=3 class=m>עוד לא נמצא שום מבצע ביזנס עם מחיר בניוזלטרים</td></tr>"
    waiting = state.get("pending", [])
    wait_txt = (", ".join(f"{html.escape(name(d['dest']))} ${d['price']:,.0f} ({d['month']})" for d in waiting)
                if waiting else "אין")
    wait_rows = "".join(
        f"<tr><td>{html.escape(name(d['origin']))} - {html.escape(name(d['dest']))}</td><td>{d['month']}</td>"
        f"<td><b>${d['price']:,.0f}</b></td><td class=m>{html.escape('; '.join(d.get('reasons', [])))}</td></tr>"
        for d in waiting)

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
<div class="card"><span id=health style="color:{color};font-weight:bold">● {health}</span></div>
<script>
// The page is regenerated after every run. If it is old, the bot (or this page) stopped: say so.
(function(){{var age=(Date.now()-{int(now.timestamp()*1000)})/36e5; if(age>2.5){{var h=document.getElementById('health');
h.style.color='#b91c1c'; h.textContent='● הדף לא עודכן כבר '+Math.round(age)+' שעות. כנראה הבוט נעצר או שיש תקלה בדף. כדאי לבדוק את Actions';}}}})();
</script>
<details class="card"><summary style="cursor:pointer;font-weight:bold">איך הבוט עובד? (לחץ להסבר)</summary>
<ul style="line-height:1.7;margin:10px 0 0;padding-right:18px">
<li>כל שעה הבוט רץ כ-45 דקות ובודק מחירי ביזנס הלוך חזור מתל אביב לכ-70 יעדים, עד כ-10 חודשים קדימה, בשני מקורות: Google Flights ו-Kiwi.com.</li>
<li>לכל יעד ולכל חודש הוא שומר את <b>המחיר הזול ביותר</b> שמצא בכל בדיקה. "המחיר הרגיל" הוא האמצע של המחירים האלה מבדיקות קודמות.</li>
<li><b>מציאה</b> = מחיר עד $2,000, וגם: נמוך ב-35% לפחות מהרגיל לאותו חודש, או מתחת לסף קבוע לאזור (אירופה וקרובות $650, אסיה $1,700).</li>
<li>מציאות, וגם מבצעי ביזנס מהניוזלטרים ומאתרי מציאות, נאספים ונשלחים ב<b>מייל אחד ביום</b> מ-09:00, רק אם יש משהו.</li>
<li>הבוט לא עוקף חסימות. אם גוגל מבקש להאט, הוא עוצר ל-4 שעות וממשיך לבד.</li>
</ul></details>
<div class="kpis" style="margin-top:14px">
 <div class="kpi"><span class=m>הריצה האחרונה הסתיימה</span><b>{t(lr.get('end') or lr.get('at'))}</b><span class=m>{lr.get('calls', 0)} חיפושים בה</span></div>
 <div class="kpi"><span class=m>חיפושים ב-24 שעות</span><b>{calls_24h:,}</b><span class=m>{"בלי חסימות" if not blocks_24h else f"{blocks_24h} פעמים גוגל ביקש להאט"}</span></div>
 <div class="kpi"><span class=m>הנתונים עדכניים</span><b>{100 * fresh // max(1, len(tasks))}%</b><span class=m>מכל החיפושים המתוכננים נבדקו בזמן</span></div>
 <div class="kpi"><span class=m>ממתין למייל היומי (09:00)</span><b>{len(waiting)} מציאות</b><span class=m>{len(nwait)} פריטים מניוזלטרים · <a href="#waiting" style="color:inherit">פירוט</a></span></div>
</div>
<div class="card" id=waiting><h2>ממתינות למייל היומי הבא</h2>
<div class=scroll><table><tr><th>מסלול</th><th>חודש</th><th>מחיר</th><th>למה</th></tr>{wait_rows or "<tr><td colspan=4 class=m>אין כרגע</td></tr>"}</table></div></div>
<div class="card"><h2>מציאות שנשלחו במייל (14 הימים האחרונים)</h2>
<div class=m style="font-size:13px;margin-bottom:6px">כל מסלול נשלח פעם אחת, ושוב רק אם המחיר ירד ב-7% נוספים או שעברו 14 יום. שורה נעלמת לבד אחרי 14 יום או כשהחודש עבר. רוצה להסיר משהו קודם? תגיד לי בצ'אט.</div>
<div class=scroll><table>
<tr><th>נשלח</th><th>מסלול</th><th>חודש</th><th>מחיר</th></tr>{al_rows}</table></div></div>
<div class="card"><h2>ניוזלטרים ואתרי מציאות</h2>
<div class=m style="font-size:13px;margin-bottom:8px">הבוט קורא בכל ריצה את התיבה הייעודית ואת אתר Fly4free. נשלח במייל היומי רק מה שמזכיר ביזנס עם מחיר (בקרוב: קריאה חכמה עם AI).</div>
<div class="kpis"><div class="kpi"><span class=m>נקראו ב-7 ימים</span><b>{n_read}</b><span class=m>מיילים</span></div>
<div class="kpi"><span class=m>עם ביזנס ומחיר</span><b>{n_match}</b><span class=m>נכנסו למייל היומי</span></div></div>
<div class=scroll style="margin-top:10px"><table><tr><th>מי שולח (7 ימים)</th><th>מיילים</th></tr>{sender_rows}</table></div>
<h2 style="margin-top:14px">מה נמצא לאחרונה</h2>
<div class=scroll><table><tr><th>מתי</th><th>מאת</th><th>מה</th></tr>{log_rows}</table></div></div>
{dormant_html}
<div class="card"><h2>המחירים לכל יעד (ביזנס הלוך חזור מתל אביב)</h2>
<div class=m style="font-size:13px;margin-bottom:6px">לכל יעד: החודש עם המחיר הזול ביותר שנמצא. ⭐ יעד מועדף (נבדק בתדירות גבוהה יותר). "רגיל לחודש" = הזול שנמצא באותו חודש בבדיקות קודמות (חציון), כמו בהתראות; "עוד אין" = פחות משתי בדיקות קודמות. ירוק = 35% ומטה מהרגיל, כלומר מציאה. מסלול (ישירה / דרך) ידוע רק ב-Kiwi; ב-Google הוא מופיע במייל של מציאה.</div>
<div class=scroll><table><tr><th></th><th colspan=2>Google Flights</th><th colspan=2>Kiwi.com</th></tr>
<tr><th>יעד</th><th>הזול</th><th>רגיל לחודש</th><th>הזול</th><th>רגיל לחודש</th></tr>
{''.join(row(r) for r in rows)}</table></div></div>
<p class=m style="font-size:12px">הנתונים נשמרים בסוף כל ריצה (ריצה = כ-45 דקות סריקה, אחת לשעה בערך), והדף נטען מחדש לבד כל 10 דקות. <a href="https://github.com/evyatar-elad/biz-fare-alert/actions" style="color:inherit">ריצות</a></p>
</div></body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
