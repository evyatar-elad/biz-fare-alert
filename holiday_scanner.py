"""Holidays - economy scanner (second system, see CLAUDE.md "מערכת שנייה").

Each run takes the most overdue tasks and keeps, for every holiday and destination:
- every observed price per (departure date, nights), stored only when it changes, with the
  date it was observed -> the learning data ("price vs days to the holiday", over years);
- the cheapest now, the cheapest ever, the cheapest without a European connection, the
  cheapest with at most one stop per direction, and how many vacation days each one costs;
- alerts: a new lowest price for a holiday and destination, or a drop of DROP_ALERT since
  the previous check.

Sources:
- Kiwi (search-flight): one request per departure date, any stay in NIGHTS_FLEX. Sees both
  holidays already (11/11), gives the full itinerary (connections, separate tickets).
  Plus one request per holiday and destination WITHOUT European connections.
- Google Flights calendar (fli dates --round -d N): one request per nights value covers
  the whole departure window, when Google returns it (density is being measured).

Usage: python holiday_scanner.py [--minutes 45] [--dry-run] [--only BKK,HND]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import holiday_cal as HC
import kiwi
from profiles import holidays as P

DATA = Path(__file__).parent / "data" / "holidays"
STATE_F = DATA / "state.json"
BEST_F = DATA / "best.json"
CURVE_F = DATA / "curve.json"
PENDING_F = DATA / "pending.json"
LOG_F = DATA / "runs.jsonl"
D1 = timedelta(days=1)

# How often each task is due (hours)
DUE_H = {"kiwi_day": 24, "kiwi_noeu": 24, "gf_cal": 24, "gf_biz": 48, "kiwi_oj": 48}
BIZ_NIGHTS = 15  # business "peek": one Google calendar per destination and holiday
TOKYO = {"NRT", "HND"}


class Blocked(Exception):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(p: Path, obj, compact: bool = False) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    txt = (json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True) if compact
           else json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True))
    p.write_text(txt, encoding="utf-8")


def prices_file(hkey: str) -> Path:
    return DATA / "prices" / f"{hkey}.json"


# ---------------------------------------------------------------- tasks
def kiwi_dest(dest: str) -> str:
    return "TYO" if dest in TOKYO else dest


def build_tasks(today: date, only: set[str] | None) -> list[dict]:
    tasks = []
    for h in HC.upcoming(today):
        lead = (h.dep[0] - today).days
        kiwi_ok = lead <= P.KIWI_HORIZON_DAYS
        gf_ok = (h.dep[1] - today).days <= P.GOOGLE_HORIZON_DAYS
        seen_k = set()
        for dest in P.DESTINATIONS:
            if only and dest not in only:
                continue
            kd = kiwi_dest(dest)
            if kiwi_ok and kd not in seen_k:
                seen_k.add(kd)
                for dep in h.departures():
                    if dep <= today + 2 * D1:
                        continue
                    for lo, hi in P.KIWI_NIGHT_CHUNKS:
                        tasks.append({"key": f"K|{h.key}|{kd}|{dep}|{lo}-{hi}", "src": "kiwi_day", "h": h.key,
                                      "dest": kd, "dep": dep.isoformat(), "nights": (lo, hi)})
                tasks.append({"key": f"KN|{h.key}|{kd}", "src": "kiwi_noeu", "h": h.key, "dest": kd})
            if gf_ok and P.GOOGLE_ENABLED and dest in P.DESTINATIONS:
                for n in range(P.NIGHTS_MAIN[0], P.NIGHTS_MAIN[1] + 1):
                    tasks.append({"key": f"G|{h.key}|{dest}|{n}", "src": "gf_cal", "h": h.key,
                                  "dest": dest, "nights": n})
                tasks.append({"key": f"GB|{h.key}|{dest}", "src": "gf_biz", "h": h.key, "dest": dest,
                              "nights": BIZ_NIGHTS})
        if kiwi_ok:
            for a, b in P.OPEN_JAW:
                if only and a not in only and b not in only:
                    continue
                tasks.append({"key": f"OJ|{h.key}|{a}-{b}", "src": "kiwi_oj", "h": h.key, "a": a, "b": b})
    return tasks


def kiwi_oneway(k: kiwi.Client, frm: str, to: str, d0: date, d1: date) -> list[dict]:
    its = k.search(flyFrom=frm, flyTo=to, departureDate=kiwi.ddmmyyyy(d0.isoformat()),
                   departureDateTo=kiwi.ddmmyyyy(d1.isoformat()), cabinClass="M", currency="USD", adults=1,
                   max_sector_stopovers=2, exclude_airlines=",".join(P.EXCLUDE_AIRLINES),
                   exclude_stopover_airports=",".join(sorted(P.BANNED_AIRPORTS)))
    out = []
    for it in its:
        o = it.get("outbound") or {}
        if o.get("departureTime") and it.get("price"):
            out.append({"day": o["departureTime"][:10], "price": round(float(it["price"])),
                        "via": [x.get("to") for x in (o.get("segments") or [])[:-1]], "url": it.get("bookingUrl")})
    return out


def open_jaw(k: kiwi.Client, task: dict, h: HC.Holiday, best: dict, today: str) -> int:
    """Bonus next to the round trips: into A, back from B, as two one-way tickets.
    Measured 12/11: usually dearer than a round trip, so it is shown apart, never instead."""
    outs = kiwi_oneway(k, P.ORIGIN, task["a"], h.dep[0], h.dep[1])
    time.sleep(P.KIWI_PACE_SECONDS)
    rets = kiwi_oneway(k, task["b"], P.ORIGIN, h.dep[0] + P.NIGHTS_MAIN[0] * D1, h.dep[1] + P.NIGHTS_MAIN[1] * D1)
    combos = []
    for o in outs:
        for r in rets:
            n = (date.fromisoformat(r["day"]) - date.fromisoformat(o["day"])).days
            if P.NIGHTS_MAIN[0] <= n <= P.NIGHTS_MAIN[1]:
                dep = date.fromisoformat(o["day"])
                combos.append({"price": o["price"] + r["price"], "dep": o["day"], "ret": r["day"], "nights": n,
                               "parts": [o["price"], r["price"]], "via_out": o["via"], "via_ret": r["via"],
                               "urls": [o["url"], r["url"]], "vac": HC.vacation(h, dep, dep + n * D1)["vac"],
                               "notes": HC.notes(h, dep, dep + n * D1), "seen": today})
    oj = best.setdefault(h.key, {}).setdefault("_open_jaw", {})
    if combos:
        oj[f"{task['a']}-{task['b']}"] = min(combos, key=lambda c: (c["price"], c["vac"]))
    return len(combos)


def overdue(tasks: list[dict], last: dict) -> list[dict]:
    t = now()
    out = []
    for task in tasks:
        ts = last.get(task["key"])
        age = 1e9 if not ts else (t - datetime.fromisoformat(ts)).total_seconds() / 3600
        due = DUE_H[task["src"]]
        if age >= due:
            out.append((age / due, task))
    out.sort(key=lambda x: -x[0])
    return [t for _, t in out]


# ---------------------------------------------------------------- sources
def itin_info(it: dict) -> dict:
    """Compact, display-ready summary of a Kiwi itinerary."""
    tickets = {p.rsplit("_", 1)[0] for p in str(it.get("id", "")).split("|") if p}

    def side(s):
        segs = s.get("segments") or []
        return {"via": [x.get("to") for x in segs[:-1]],
                "airlines": sorted({x.get("carrierName") or x.get("carrier") or "?" for x in segs}),
                "hours": round((s.get("durationSeconds") or 0) / 3600, 1),
                "dep": s.get("departureTime"), "arr": s.get("arrivalTime"),
                "to": segs[-1].get("to") if segs else None,
                "legs": [{"from": x.get("from"), "to": x.get("to"), "flight": x.get("flightNumber"),
                          "airline": x.get("carrierName") or x.get("carrier"),
                          "dep": x.get("departureTime"), "arr": x.get("arrivalTime")} for x in segs]}
    out, back = it.get("outbound") or {}, it.get("inbound") or it.get("return") or {}
    return {"out": side(out), "ret": side(back), "separate": len(tickets) > 1, "url": it.get("bookingUrl")}


def via_europe(info: dict) -> bool:
    return any(v in P.EUROPE_AIRPORTS for s in ("out", "ret") for v in info[s]["via"])


def max_stops(info: dict) -> int:
    return max(len(info["out"]["via"]), len(info["ret"]["via"]))


def kiwi_points(k: kiwi.Client, task: dict, h: HC.Holiday, no_europe: bool = False) -> list[dict]:
    if task["src"] == "kiwi_day":
        a = b = task["dep"]
        lo, hi = task["nights"]
    else:
        a, b = h.dep[0].isoformat(), h.dep[1].isoformat()
        lo, hi = P.NIGHTS_FLEX
    excl_air = set(P.BANNED_AIRPORTS) | (set(P.EUROPE_HUBS_KIWI) if no_europe else set())
    args = dict(flyFrom=P.ORIGIN, flyTo=task["dest"],
                departureDate=kiwi.ddmmyyyy(a), departureDateTo=kiwi.ddmmyyyy(b),
                nights_in_dst_from=lo, nights_in_dst_to=hi,
                cabinClass="M", currency="USD", adults=1, max_sector_stopovers=2,
                exclude_airlines=",".join(P.EXCLUDE_AIRLINES),
                exclude_stopover_airports=",".join(sorted(excl_air)))
    pts = []
    for it in k.search(**args):
        o, r = it.get("outbound") or {}, it.get("inbound") or it.get("return") or {}
        if not (o.get("departureTime") and r.get("departureTime") and it.get("price")):
            continue
        dep, ret = date.fromisoformat(o["departureTime"][:10]), date.fromisoformat(r["departureTime"][:10])
        info = itin_info(it)
        if any(v in P.BANNED_AIRPORTS for s in ("out", "ret") for v in info[s]["via"]):
            continue
        # group by the searched destination (Kiwi may land at another airport of the city,
        # e.g. DMK for Bangkok); the real airport is kept for links
        pts.append({"dep": dep.isoformat(), "nights": (ret - dep).days, "price": round(float(it["price"])),
                    "src": "kiwi", "dest": task["dest"], "arr": info["out"]["to"], "info": info})
    return pts


def fli(args: list[str], timeout: int = 180) -> dict:
    cmd = ["fli", *args, "--currency", "USD", "--format", "json", *P.GOOGLE_EXTRA_ARGS]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"success": False, "error": (p.stdout + p.stderr)[-300:]}
    if not d.get("success"):
        msg = json.dumps(d.get("error", {}), ensure_ascii=False)
        if any(s in msg for s in ("429", "rate-limit", "captcha", "unusual traffic")):
            raise Blocked(msg)
    return d


def gf_points(task: dict, h: HC.Holiday) -> list[dict] | None:
    cabin = "BUSINESS" if task["src"] == "gf_biz" else "ECONOMY"
    d = fli(["dates", P.ORIGIN, task["dest"], "--from", h.dep[0].isoformat(), "--to", h.dep[1].isoformat(),
             "--round", "-d", str(task["nights"]), "--class", cabin,
             "--exclude-airlines", ",".join(P.EXCLUDE_AIRLINES)])
    if not d.get("success"):
        return None
    return [{"dep": x["departure_date"], "nights": task["nights"], "price": round(x["price"]), "src": "google",
             "dest": task["dest"], "info": None} for x in d.get("dates", []) if x.get("price")]


# ---------------------------------------------------------------- storage and logic
def record(prices: dict, pts: list[dict], today: str) -> None:
    """Append an observation only when the price changed (keeps years of data small)."""
    for p in pts:
        series = prices.setdefault(f"{p['src']}|{p['dest']}", {}).setdefault(f"{p['dep']}|{p['nights']}", [])
        if not series or series[-1][1] != p["price"]:
            series.append([today, p["price"]])


def dest_group(code: str) -> str:
    """Tokyo airports are one destination for the summary."""
    return "TYO" if code in TOKYO | {"TYO"} else code


def option(h: HC.Holiday, p: dict, today: str) -> dict:
    dep = date.fromisoformat(p["dep"])
    ret = dep + p["nights"] * D1
    v = HC.vacation(h, dep, ret)
    o = {"price": p["price"], "dep": p["dep"], "ret": ret.isoformat(), "nights": p["nights"], "src": p["src"],
         "dest": p.get("arr") or p["dest"], "vac": v["vac"], "notes": HC.notes(h, dep, ret), "seen": today}
    if p.get("info"):
        i = p["info"]
        o.update(via_out=i["out"]["via"], via_ret=i["ret"]["via"], hours_out=i["out"]["hours"],
                 hours_ret=i["ret"]["hours"], airlines=sorted(set(i["out"]["airlines"]) | set(i["ret"]["airlines"])),
                 separate=i["separate"], europe=via_europe(i), url=i["url"], legs_out=i["out"]["legs"],
                 legs_ret=i["ret"]["legs"])
    return o


def main_window(o: dict) -> bool:
    return P.NIGHTS_MAIN[0] <= o["nights"] <= P.NIGHTS_MAIN[1]


def update_best(best: dict, h: HC.Holiday, group: str, pts: list[dict], today: str, alerts: list) -> None:
    """Keep the summary per holiday and destination group, and raise alerts."""
    b = best.setdefault(h.key, {}).setdefault(group, {})
    opts = [option(h, p, today) for p in pts]
    if not opts:
        return
    main_opts = [o for o in opts if main_window(o)]
    if not main_opts:  # only 12-13 / 22-24 nights: kept apart, shown only when exceptional
        f = min(opts, key=lambda o: o["price"])
        if not b.get("flex") or b["flex"].get("seen") != today or f["price"] < b["flex"]["price"]:
            b["flex"] = f
        return
    cheapest = min(main_opts, key=lambda o: (o["price"], o["vac"]))
    prev_now, prev_low = b.get("now"), b.get("low")
    # "now" = cheapest among today's observations of this group (all sources merged per day)
    if b.get("now_day") == today and prev_now and prev_now["price"] <= cheapest["price"]:
        cheapest = prev_now
    else:
        if b.get("now_day") != today and prev_now:
            b["prev_day_price"] = prev_now["price"]
        b["now"], b["now_day"] = cheapest, today
    if not prev_low or cheapest["price"] < prev_low["price"]:
        b["low"] = {**cheapest, "found": today}
        if prev_low and prev_low.get("found") != today:  # no alerts while the first sweep fills in
            alerts.append({"type": "low", "h": h.key, "hname": h.name, "group": group, "o": cheapest,
                           "prev": prev_low["price"]})
    prev = b.get("prev_day_price")
    if prev and cheapest["price"] <= prev * (1 - P.DROP_ALERT) and not (prev_low and cheapest["price"] < prev_low["price"]):
        alerts.append({"type": "drop", "h": h.key, "hname": h.name, "group": group, "o": cheapest, "prev": prev})
    for name, pred in (("noeu", lambda o: o.get("europe") is False),
                       ("onestop", lambda o: o.get("via_out") is not None and max(len(o["via_out"]), len(o["via_ret"])) <= 1),
                       ("fewvac", lambda o: True)):
        cand = [o for o in main_opts if pred(o)]
        if not cand:
            continue
        key = (lambda o: (o["vac"], o["price"])) if name == "fewvac" else (lambda o: (o["price"], o["vac"]))
        c = min(cand, key=key)
        cur = b.get(name)
        if not cur or cur.get("seen") != today or key(c) < key(cur):
            b[name] = c
    b["checked"] = now().isoformat(timespec="seconds")


def update_curve(curve: dict, h: HC.Holiday, group: str, price: int, today: str) -> None:
    """Learning data: per holiday and destination, the cheapest price each day and how many
    days were left until the holiday. Kept forever (one small row per day)."""
    rows = curve.setdefault(h.key, {}).setdefault(group, [])
    days_left = (h.core[0] - date.fromisoformat(today)).days
    if rows and rows[-1][0] == today:
        rows[-1][2] = min(rows[-1][2], price)
    else:
        rows.append([today, days_left, price])


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=45)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    t0 = time.time()
    today_d = date.today()
    today = today_d.isoformat()
    only = {x.strip().upper() for x in a.only.split(",") if x.strip()} or None
    state = load(STATE_F, {"last": {}})
    best, curve = load(BEST_F, {}), load(CURVE_F, {})
    pending = load(PENDING_F, [])
    hols = {h.key: h for h in HC.upcoming(today_d)}
    if state.get("blocked_until") and now() < datetime.fromisoformat(state["blocked_until"]):
        print(f"google paused until {state['blocked_until']}")
    tasks = overdue(build_tasks(today_d, only), state["last"])
    print(f"holidays: {len(tasks)} tasks due, {len(hols)} holidays: {', '.join(h.name for h in hols.values())}")
    k = None
    stats = {"calls": 0, "points": 0, "errors": 0, "alerts": 0}
    alerts: list = []
    price_cache: dict[str, dict] = {}
    gf_last = 0.0
    for task in tasks:
        if time.time() - t0 > a.minutes * 60:
            break
        h = hols[task["h"]]
        try:
            if task["src"] == "kiwi_oj":
                if k is None:
                    k = kiwi.Client()
                n = open_jaw(k, task, hols[task["h"]], best, today)
                time.sleep(P.KIWI_PACE_SECONDS)
                state["last"][task["key"]] = now().isoformat(timespec="seconds")
                stats["calls"] += 2
                print(f"  {task['key']}: {n} צירופים")
                continue
            if task["src"].startswith("kiwi"):
                if k is None:
                    k = kiwi.Client()
                pts = kiwi_points(k, task, h, no_europe=task["src"] == "kiwi_noeu")
                time.sleep(P.KIWI_PACE_SECONDS)
            else:
                if state.get("blocked_until") and now() < datetime.fromisoformat(state["blocked_until"]):
                    continue
                wait = P.PACE_SECONDS - (time.time() - gf_last)
                if wait > 0:
                    time.sleep(wait)
                gf_last = time.time()
                pts = gf_points(task, h)
                if pts is None:
                    stats["errors"] += 1
                    continue
        except kiwi.KiwiError as e:
            print(f"  ! kiwi: {e}")
            stats["errors"] += 1
            continue
        except Blocked as e:
            print(f"  ! google blocked: {e}")
            state["blocked_until"] = (now() + timedelta(hours=P.BACKOFF_HOURS)).isoformat(timespec="seconds")
            continue
        stats["calls"] += 1
        stats["points"] += len(pts)
        state["last"][task["key"]] = now().isoformat(timespec="seconds")
        if task["src"] == "gf_biz":
            g = dest_group(task["dest"])
            b = best.setdefault(h.key, {}).setdefault(g, {})
            if pts:
                c = option(h, min(pts, key=lambda p: p["price"]), today)
                b["biz"] = {**c, "cabin": "business"}
            print(f"  {task['key']}: ביזנס {len(pts)} מחירים" + (f", הזול ${min(p['price'] for p in pts)}" if pts else ""))
            continue
        if task["h"] not in price_cache:
            price_cache[task["h"]] = load(prices_file(task["h"]), {})
        record(price_cache[task["h"]], pts, today)
        groups: dict[str, list] = {}
        for p in pts:
            groups.setdefault(dest_group(p["dest"]), []).append(p)
        for g, gp in groups.items():
            update_best(best, h, g, gp, today, alerts)
            update_curve(curve, h, g, min(p["price"] for p in gp if P.NIGHTS_MAIN[0] <= p["nights"] <= P.NIGHTS_MAIN[1]) if any(P.NIGHTS_MAIN[0] <= p["nights"] <= P.NIGHTS_MAIN[1] for p in gp) else min(p["price"] for p in gp), today)
        print(f"  {task['key']}: {len(pts)} מחירים" + (f", הזול ${min(p['price'] for p in pts)}" if pts else ""))
    # alerts: keep the best per holiday+destination
    for al in alerts:
        key = (al["h"], al["group"])
        pending = [x for x in pending if (x["h"], x["group"]) != key or x["o"]["price"] <= al["o"]["price"]]
        if not any((x["h"], x["group"]) == key for x in pending):
            pending.append({**al, "at": now().isoformat(timespec="seconds")})
    stats["alerts"] = len(alerts)
    if not a.dry_run:
        for hk, pr in price_cache.items():
            save(prices_file(hk), pr, compact=True)  # years of observations: keep the file small
        save(STATE_F, state)
        save(BEST_F, best)
        save(CURVE_F, curve)
        save(PENDING_F, pending)
        with LOG_F.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now().isoformat(timespec="seconds"), **stats}, ensure_ascii=False) + "\n")
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
