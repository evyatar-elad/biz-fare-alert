"""One-off measurement before building the holidays scanner (stage 1).

Questions:
1. Google Flights economy calendar: how many of the departure dates in each holiday window
   come back with a price, per destination? (Business was full only ~100 days ahead.)
2. Does Google see Tishrei 2027 yet (~320-340 days ahead)?
3. Do several airports in one request work (Tokyo NRT,HND)?
4. Open jaw: does `fli multi` (TLV->KIX, NRT->TLV) return prices, and how do they compare
   with the round trip?
5. Business density on the same windows (for the "peek" column).
6. Kiwi: cheapest, cheapest without a European connection, cheapest with at most 1 stop.

Prints a report and writes it to $GITHUB_STEP_SUMMARY and data/holidays/probe.md.
Usage: python holiday_probe.py [--quick]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import holiday_cal as HC
import kiwi
from profiles import holidays as P

OUT = Path(__file__).parent / "data" / "holidays" / "probe.md"
lines: list[str] = []
last_call = [0.0]


def say(s: str = "") -> None:
    print(s, flush=True)
    lines.append(s)


def fli(args: list[str], timeout: int = 180) -> dict:
    wait = P.PACE_SECONDS - (time.time() - last_call[0])
    if wait > 0:
        time.sleep(wait)
    last_call[0] = time.time()
    cmd = ["fli", *args, "--currency", "USD", "--format", "json"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"success": False, "error": (p.stdout + p.stderr)[-300:]}


def excl() -> list[str]:
    return ["--exclude-airlines", ",".join(P.EXCLUDE_AIRLINES)]


def cal(dest: str, h: HC.Holiday, nights: int, cabin: str = "ECONOMY") -> tuple[int, int, list]:
    a, b = h.dep
    d = fli(["dates", P.ORIGIN, dest, "--from", a.isoformat(), "--to", b.isoformat(),
             "--round", "-d", str(nights), "--class", cabin, *excl()])
    if not d.get("success"):
        return -1, (b - a).days + 1, [str(d.get("error"))[:120]]
    pts = [x for x in d.get("dates", []) if x.get("price")]
    return len(pts), (b - a).days + 1, sorted((round(x["price"]), x["departure_date"]) for x in pts)


def main(quick: bool = False) -> int:
    today = date.today()
    hols = HC.upcoming(today)
    say(f"# מדידה לפני בניית סורק החגים ({today})")
    for h in hols:
        say(f"- {h.name}: יציאה {h.dep[0]} עד {h.dep[1]} ({(h.dep[0] - today).days}-{(h.dep[1] - today).days} יום מהיום)")
    dests = list(P.DESTINATIONS) if not quick else ["BKK", "SGN"]

    say("\n## 1-2. גוגל, תיירים, 15 לילות: כמה תאריכי יציאה חזרו עם מחיר")
    say("| יעד | " + " | ".join(h.name for h in hols) + " |")
    say("|---|" + "---|" * len(hols))
    rt_price: dict[tuple[str, str], int] = {}
    for dest in dests:
        cells = []
        for h in hols:
            n, total, pts = cal(dest, h, 15)
            if n < 0:
                cells.append(f"שגיאה: {pts[0]}")
            elif not pts:
                cells.append(f"0/{total}")
            else:
                rt_price[(dest, h.key)] = pts[0][0]
                cells.append(f"{n}/{total}, הזול ${pts[0][0]} ({pts[0][1][5:]}), היקר ${pts[-1][0]}")
        say(f"| {dest} | " + " | ".join(cells) + " |")

    say("\n## 3. כמה שדות בבקשה אחת (NRT,HND)")
    h0 = hols[0]
    n, total, pts = cal("NRT,HND", h0, 15)
    say(f"- {h0.name}: {n}/{total}" + (f", הזול ${pts[0][0]}" if n > 0 and pts else f" {pts[:1]}"))

    say("\n## 4. Open jaw (תאריכים: הצירוף הכי חסכוני בימי חופש, 15 לילות)")
    say("שתי שיטות: (א) חיפוש רב-יעדי אחד בגוגל, (ב) שני כרטיסים לכיוון אחד (לוח מחירים לכיוון אחד, בקשה לכל כיוון).")
    for h in hols:
        best = [r for r in HC.best_spread(h)["per_nights"] if r["nights"] == 15][0]
        dep, ret = best["dep"].isoformat(), best["ret"].isoformat()
        for a, b in (("KIX", "NRT"), ("HAN", "SGN"), ("BKK", "HKT")):
            wait = P.PACE_SECONDS - (time.time() - last_call[0])
            if wait > 0:
                time.sleep(wait)
            last_call[0] = time.time()
            p = subprocess.run([sys.executable, "fli_multi.py", "ECONOMY", f"{P.ORIGIN},{a},{dep}", f"{b},{P.ORIGIN},{ret}",
                                "--exclude", ",".join(P.EXCLUDE_AIRLINES)], capture_output=True, text=True, timeout=240)
            try:
                m = json.loads(p.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                m = {"success": False, "error": (p.stdout + p.stderr)[-200:]}
            trips = m.get("trips") or []
            multi = f"${round(trips[0]['price'])} ({len(trips)} תוצאות)" if trips else f"אין ({str(m.get('error') or 'ריק')[:100]})"
            ow1 = fli(["dates", P.ORIGIN, a, "--from", dep, "--to", dep, "--class", "ECONOMY", *excl()])
            ow2 = fli(["dates", b, P.ORIGIN, "--from", ret, "--to", ret, "--class", "ECONOMY", *excl()])
            p1 = [x["price"] for x in ow1.get("dates", []) if x.get("price")]
            p2 = [x["price"] for x in ow2.get("dates", []) if x.get("price")]
            two = f"${round(min(p1) + min(p2))} (${round(min(p1))} + ${round(min(p2))})" if p1 and p2 else f"חסר ({len(p1)}, {len(p2)})"
            rt = rt_price.get((a, h.key))
            say(f"- {h.name} {dep}..{ret} TLV->{a}, {b}->TLV: רב-יעדי {multi}; שני כיוונים {two}"
                + (f"; הלוך חזור ל-{a} (הזול בחלון) ${rt}" if rt else ""))
            if quick:
                break
        if quick:
            break

    say("\n## 5. ביזנס, 15 לילות")
    for dest in (["BKK", "SGN", "DPS"] if not quick else ["BKK"]):
        for h in hols:
            n, total, pts = cal(dest, h, 15, "BUSINESS")
            say(f"- {dest} {h.name}: {n}/{total}" + (f", הזול ${pts[0][0]}" if n > 0 and pts else ""))

    say("\n## 6. Kiwi, תיירים, 12-24 לילות, כל חלון היציאה")
    say("| יעד | חג | תוצאות | הזול | הזול בלי אירופה | הזול עם עד עצירה אחת |")
    say("|---|---|---|---|---|---|")
    try:
        k = kiwi.Client()
    except kiwi.KiwiError as e:
        say(f"Kiwi לא זמין: {e}")
        k = None
    for dest in dests if k else []:
        for h in hols:
            fly_to = "TYO" if dest in ("NRT", "HND") else dest
            if dest == "HND":
                continue
            try:
                its = k.search(flyFrom=P.ORIGIN, flyTo=fly_to,
                               departureDate=kiwi.ddmmyyyy(h.dep[0].isoformat()),
                               departureDateTo=kiwi.ddmmyyyy(h.dep[1].isoformat()),
                               nights_in_dst_from=P.NIGHTS_FLEX[0], nights_in_dst_to=P.NIGHTS_FLEX[1],
                               cabinClass="M", currency="USD", adults=1,
                               exclude_airlines=",".join(P.EXCLUDE_AIRLINES),
                               exclude_stopover_airports=",".join(sorted(P.BANNED_AIRPORTS)))
            except kiwi.KiwiError as e:
                say(f"| {fly_to} | {h.name} | שגיאה {str(e)[:80]} | | | |")
                continue
            time.sleep(P.KIWI_PACE_SECONDS)

            def desc(it):
                o, r = it.get("outbound") or {}, it.get("inbound") or it.get("return") or {}
                via = "/".join(s.get("to") for s in (o.get("segments") or [])[:-1]) or "ישירה"
                return f"${round(it['price'])} {o.get('departureTime', '')[5:10]}..{r.get('departureTime', '')[5:10]} דרך {via}"

            def vias(it):
                out = []
                for side in (it.get("outbound") or {}, it.get("inbound") or it.get("return") or {}):
                    out.append([s.get("to") for s in (side.get("segments") or [])[:-1]])
                return out
            its = sorted([i for i in its if i.get("price")], key=lambda i: i["price"])
            no_eu = [i for i in its if not any(v in P.EUROPE_AIRPORTS for vs in vias(i) for v in vs)]
            one = [i for i in its if all(len(vs) <= 1 for vs in vias(i))]
            say(f"| {fly_to} | {h.name} | {len(its)} | {desc(its[0]) if its else '-'} | "
                f"{desc(no_eu[0]) if no_eu else '-'} | {desc(one[0]) if one else '-'} |")

    say("\n## השוואה: גוגל מול Kiwi (15 לילות בגוגל מול 12-24 ב-Kiwi, לא אחד לאחד)")
    say(json.dumps({f"{d}|{h}": p for (d, h), p in rt_price.items()}, ensure_ascii=False))

    text = "\n".join(lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main("--quick" in sys.argv))
