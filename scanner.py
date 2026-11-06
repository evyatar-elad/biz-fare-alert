"""Business class deal scanner.

Each run picks the most overdue (origin, destination, 61-day window) tasks,
asks Google Flights (via the `fli` CLI) for the round trip business price of
every departure date in the window, compares them to the route's usual price,
and emails new deals. State lives in data/*.json and is committed by the workflow.

Usage: python scanner.py [--minutes 20] [--dry-run] [--only SGN,DPS]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config as C
import kiwi
import notify

DATA = Path(__file__).parent / "data"
STATE_F = DATA / "state.json"
HIST_F = DATA / "history.json"
ALERTS_F = DATA / "alerts.json"
LOG_F = DATA / "runs.jsonl"


class Blocked(Exception):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------- tasks
def build_tasks(only: set[str] | None) -> list[dict]:
    """Near months: 61-day calendar windows. Far months (and LCA): one anchor date per
    FAR_STEP_DAYS slot, shifted by one day each day so all dates get covered over time."""
    today = date.today()
    first = today + timedelta(days=C.START_OFFSET_DAYS)
    dense_end = today + timedelta(days=C.DENSE_DAYS)
    end_all = today + timedelta(days=C.HORIZON_DAYS)
    shift = today.toordinal() % C.FAR_STEP_DAYS
    tasks = []
    for origin in C.ORIGINS:
        for code, (name, region, prio) in C.DESTINATIONS.items():
            if only and code not in only:
                continue
            if origin == "LCA" and ((C.LCA_ONLY_PRIORITY and not prio) or code in C.HUBS):
                continue
            kind = "LCA" if origin == "LCA" else ("priority" if prio else "normal")
            base = {"origin": origin, "dest": code, "dur": C.REGIONS[region]["dur"],
                    "region": region, "prio": prio}
            far_start = first
            if origin != "LCA":  # Google has no cached LCA calendar, so LCA is anchors only
                start, w = first, 0
                while start <= dense_end:
                    end = min(start + timedelta(days=C.WINDOW_DAYS - 1), dense_end)
                    tasks.append({**base, "key": f"{origin}-{code}-d{w}",
                                  "from": start.isoformat(), "to": end.isoformat(),
                                  "due_h": C.DUE_HOURS[kind]})
                    start, w = end + timedelta(days=1), w + 1
                far_start = dense_end + timedelta(days=1)
            k = 0
            while True:
                anchor = far_start + timedelta(days=k * C.FAR_STEP_DAYS + shift)
                if anchor > end_all:
                    break
                tasks.append({**base, "key": f"{origin}-{code}-far{k}",
                              "from": anchor.isoformat(), "to": anchor.isoformat(),
                              "due_h": C.DUE_HOURS[kind] * C.FAR_DUE_FACTOR})
                k += 1
    # Kiwi.com: monthly windows from TLV (all destinations), plus airline focus searches
    if C.KIWI_ENABLED:
        jobs = [(code, None) for code in C.DESTINATIONS] + \
               [(code, al) for al, codes in C.KIWI_AIRLINE_FOCUS.items() for code in codes]
        for code, al in jobs:
            if only and code not in only:
                continue
            name_, region, prio = C.DESTINATIONS.get(code, ("", "asia", False))
            start, i = first, 0
            while start <= end_all:
                end = min(start + timedelta(days=C.KIWI_WINDOW_DAYS - 1), end_all)
                tasks.append({"src": "kiwi", "origin": "TLV", "dest": code, "airline": al,
                              "dur": C.REGIONS[region]["dur"], "region": region, "prio": prio,
                              "key": f"K-{al or 'ALL'}-{code}-m{i}", "from": start.isoformat(),
                              "to": end.isoformat(),
                              "due_h": C.KIWI_DUE_HOURS["priority" if prio else "normal"]})
                start, i = end + timedelta(days=1), i + 1

    # hub legs: TAS -> east, that hub airline only (TLV -> TAS is a normal destination)
    for hub, h in C.HUBS.items():
        for code in h["dests"]:
            if only and code not in only and hub not in only:
                continue
            region = C.DESTINATIONS.get(code, ("", "asia", False))[1]
            base = {"origin": hub, "dest": code, "dur": C.REGIONS[region]["dur"], "region": region, "prio": False}
            start, w = first, 0
            while start <= dense_end:
                end = min(start + timedelta(days=C.WINDOW_DAYS - 1), dense_end)
                tasks.append({**base, "key": f"{hub}-{code}-d{w}", "from": start.isoformat(),
                              "to": end.isoformat(), "due_h": C.DUE_HOURS["normal"]})
                start, w = end + timedelta(days=1), w + 1
            k = 0
            while True:
                anchor = dense_end + timedelta(days=1 + k * C.FAR_STEP_DAYS + shift)
                if anchor > end_all:
                    break
                tasks.append({**base, "key": f"{hub}-{code}-far{k}", "from": anchor.isoformat(),
                              "to": anchor.isoformat(), "due_h": C.DUE_HOURS["normal"] * C.FAR_DUE_FACTOR})
                k += 1
    return tasks


def overdue(tasks: list[dict], last: dict) -> list[dict]:
    t_now = now_utc()
    out = []
    for t in tasks:
        ts = last.get(t["key"])
        age_h = 1e9 if not ts else (t_now - datetime.fromisoformat(ts)).total_seconds() / 3600
        if age_h >= t["due_h"]:
            out.append((age_h / t["due_h"], t))
    out.sort(key=lambda x: -x[0])
    return [t for _, t in out]


# ---------------------------------------------------------------- google flights via fli
def fli(args: list[str], timeout: int = 180) -> dict:
    cmd = ["fli", *args, "--currency", "USD", "--format", "json"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": {"type": "timeout", "message": "timeout"}}
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"success": False, "error": {"type": "bad_output", "message": (p.stdout + p.stderr)[-400:]}}
    if not d.get("success"):
        msg = json.dumps(d.get("error", {}), ensure_ascii=False)
        if any(s in msg for s in ("429", "rate-limit", "blocked", "captcha", "unusual traffic", "sorry")):
            raise Blocked(msg)
    return d


def stops_arg(dest: str) -> list[str]:
    return ["--stops", "0"] if dest in C.NONSTOP_ONLY else []


def airline_args(origin: str, dest: str) -> list[str]:
    """Legs to/from a hub: only the hub airline. Everything else: all airlines minus excluded."""
    hub = origin if origin in C.HUBS else dest if dest in C.HUBS else None
    if hub:
        return ["--airlines", C.HUBS[hub]["airline"]]
    return ["--exclude-airlines", ",".join(C.EXCLUDE_AIRLINES)]


def calendar(t: dict) -> list[dict] | None:
    d = fli(["dates", t["origin"], t["dest"], "--from", t["from"], "--to", t["to"],
             "--round", "-d", str(t["dur"]), "--class", "BUSINESS",
             *airline_args(t["origin"], t["dest"]), *stops_arg(t["dest"])])
    if not d.get("success"):
        print(f"  ! {t['key']}: {d.get('error')}")
        return None
    return [x for x in d.get("dates", []) if x.get("price")]


def economy_gf(origin: str, dest: str, dep: str, ret: str) -> float | None:
    dur = (date.fromisoformat(ret) - date.fromisoformat(dep)).days
    d = fli(["dates", origin, dest, "--from", dep, "--to", dep, "--round", "-d", str(dur),
             "--class", "ECONOMY", *airline_args(origin, dest), *stops_arg(dest)])
    ps = [x["price"] for x in d.get("dates", []) if x.get("price") and x.get("departure_date") == dep]
    return min(ps) if ps else None


def details(origin: str, dest: str, dep: str, ret: str) -> dict | None:
    d = fli(["flights", origin, dest, dep, "--return", ret, "--class", "BUSINESS", "--sort", "CHEAPEST",
             *airline_args(origin, dest), *stops_arg(dest)])
    flights = d.get("flights") or d.get("results") or []
    if not d.get("success") or not flights:
        return None
    f = min(flights, key=lambda x: x.get("price") or 1e12)

    def code(a):
        return a.get("code") if isinstance(a, dict) else str(a or "?")

    def leg_info(seg):
        if not seg:
            return None
        legs = seg.get("legs", [])
        return {
            "stops": seg.get("stops"),
            "via": [code(l.get("arrival_airport")) for l in legs[:-1]],
            "airlines": sorted({(l.get("airline") or {}).get("name", "?") for l in legs}),
            "hours": round((seg.get("duration") or 0) / 60, 1),
            "mixed_cabin": bool(seg.get("mixed_cabin")),
            "legs": [{
                "from": code(l.get("departure_airport")), "to": code(l.get("arrival_airport")),
                "airline": (l.get("airline") or {}).get("name", "?"),
                "flight": l.get("flight_number"), "aircraft": l.get("aircraft"),
                "seat": l.get("legroom"),
                "hours": round((l.get("duration") or 0) / 60, 1),
            } for l in legs],
        }
    return {"price": f.get("price"), "out": leg_info(f.get("outbound")), "ret": leg_info(f.get("return"))}


# ---------------------------------------------------------------- deal logic
def dorm_key(t: dict) -> str:
    if t.get("src") == "kiwi":
        return f"K-{t.get('airline') or 'ALL'}-{t['dest']}"
    return f"{t['origin']}-{t['dest']}"


def route_key(t: dict) -> str:
    if t.get("src") == "kiwi":
        return f"K-{t['origin']}-{t['dest']}" + (f"-{t['airline']}" if t.get("airline") else "")
    return f"{t['origin']}-{t['dest']}-{t['dur']}" + (f"-{t['via']}" if t.get("via") else "")


# ---------------------------------------------------------------- hub combinations
def remember_cal(state: dict, t: dict, pts: list[dict], today: str) -> None:
    """Keep per-date prices of hub legs (TLV->hub, hub->X) to combine them."""
    if not (t["origin"] in C.HUBS or t["dest"] in C.HUBS):
        return
    cal = state.setdefault("cal", {}).setdefault(f"{t['origin']}-{t['dest']}", {})
    for p in pts:
        cal[p["departure_date"]] = [p["price"], p["return_date"], today]
    for d in [d for d in cal if d < today]:
        del cal[d]


def hub_points(state: dict, hub: str, dest: str, today: str) -> list[dict]:
    """TLV->hub + hub->dest on the same day (Uzbekistan Airways connects the same evening)."""
    cals = state.get("cal", {})
    a, b = cals.get(f"TLV-{hub}", {}), cals.get(f"{hub}-{dest}", {})
    fresh = lambda row: (date.fromisoformat(today) - date.fromisoformat(row[2])).days <= C.HUB_MAX_AGE_DAYS
    pts = []
    for d, rb in b.items():
        ra = a.get(d)
        if ra and fresh(ra) and fresh(rb):
            pts.append({"departure_date": d, "return_date": rb[1], "price": ra[0] + rb[0], "parts": [ra[0], rb[0]]})
    return pts


def update_history(hist: dict, rk: str, points: list[dict], today: str) -> None:
    """Keep, per route and departure month, the median and min of each scan (last 30 scans)."""
    by_month: dict[str, list[float]] = {}
    for p in points:
        by_month.setdefault(p["departure_date"][:7], []).append(p["price"])
    r = hist.setdefault(rk, {})
    for m, ps in by_month.items():
        rows = [x for x in r.get(m, []) if x[0] != today]
        rows.append([today, round(statistics.median(ps)), round(min(ps)), len(ps)])
        r[m] = rows[-30:]


def reference(hist: dict, rk: str, month: str, today: str, current: list[float]) -> tuple[float | None, str]:
    """Usual CHEAPEST price for this route and month, from past scans only.

    We compare the cheapest date of a month with the cheapest of past scans (history
    column 2). Comparing with a median of all dates flagged normal prices as deals
    (6/11: Goa every month ~$2,390 vs a median inflated by December). No past scans =
    no relative rule (only the fixed regional cap)."""
    r = hist.get(rk, {})
    past_month = [x[2] for x in r.get(month, []) if x[0] != today]
    if len(past_month) >= 2:
        return statistics.median(past_month), "הזול הרגיל בחודש הזה"
    past_all = [x[2] for rows in r.values() for x in rows if x[0] != today]
    if len(past_all) >= 6:
        return statistics.median(past_all), "הזול הרגיל במסלול"
    return None, "אין עדיין מספיק היסטוריה"

def find_deals(t: dict, points: list[dict], hist: dict, today: str) -> list[dict]:
    rk = route_key(t)
    region = C.REGIONS[t["region"]]
    extra = C.POSITIONING_USD if t["origin"] == "LCA" else 0
    tlv_rk = f"TLV-{t['dest']}-{t['dur']}"
    by_month: dict[str, list[dict]] = {}
    for p in points:
        by_month.setdefault(p["departure_date"][:7], []).append(p)
    deals = []
    for month, ps in by_month.items():
        best = min(ps, key=lambda p: p["price"])
        price = best["price"] + extra
        if t.get("src") == "kiwi":
            # Kiwi only against Kiwi: it builds cheaper separate-ticket trips than Google
            # shows, so Google's usual price made normal Kiwi prices look like deals (6/11).
            ref, why = reference(hist, rk, month, today, [])
        elif t["origin"] == "LCA" or t.get("via"):
            ref, why = reference(hist, tlv_rk, month, "", [])  # TLV usual price, incl. today
            if t.get("via"):
                why = "מחיר רגיל בטיסה מתל אביב, " + why
        else:
            ref, why = reference(hist, rk, month, today, [p["price"] for p in points])
        reasons = []
        if ref and price <= ref * (1 - C.DROP):
            reasons.append(f"{round(100 * (1 - price / ref))}% מתחת למחיר הרגיל (${ref:,.0f}, {why})")
        if price <= region["cap"]:
            reasons.append(f"מתחת לסף הקבוע לאזור (${region['cap']:,})")
        if reasons:
            same = sum(1 for p in ps if p["price"] <= best["price"] * 1.03)
            deals.append({
                "route": rk, "origin": t["origin"], "dest": t["dest"], "dur": t["dur"],
                "month": month, "dep": best["departure_date"], "ret": best["return_date"],
                "price": best["price"], "effective": price, "ref": ref, "reasons": reasons,
                "similar_dates": same, "via": t.get("via"), "parts": best.get("parts"),
                "src": t.get("src", "gf"), "airline_focus": t.get("airline"),
                "details": kiwi.details_from_itin(best["itin"]) if best.get("itin") else None,
            })
    return deals


def is_new(deal: dict, alerts: dict) -> bool:
    k = f"{deal['route']}|{deal['month']}"
    a = alerts.get(k)
    if not a:
        return True
    age = (now_utc() - datetime.fromisoformat(a["at"])).days
    return deal["price"] <= a["price"] * (1 - C.REALERT_DROP) or age >= C.REALERT_DAYS


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--dry-run", action="store_true", help="print emails instead of sending")
    ap.add_argument("--only", default="", help="comma separated destination codes")
    ap.add_argument("--max-calls", type=int, default=0)
    a = ap.parse_args()

    state = load(STATE_F, {"last": {}, "backoff_until": None, "last_email": None})
    hist = load(HIST_F, {})
    alerts = load(ALERTS_F, {})
    today = date.today().isoformat()
    started = time.monotonic()
    run = {"at": now_utc().isoformat(timespec="seconds"), "calls": 0, "ok": 0, "empty": 0, "deals": 0, "blocked": False}

    if state.get("backoff_until") and now_utc() < datetime.fromisoformat(state["backoff_until"]):
        print(f"בהמתנה אחרי חסימה עד {state['backoff_until']}, לא מחפשים.")
        return 0

    only = {x.strip().upper() for x in a.only.split(",") if x.strip()} or None
    tasks = build_tasks(only)
    for t in tasks:  # routes with no flights at all: check rarely (a new route will wake them up)
        if state.get("routes", {}).get(dorm_key(t), {}).get("empty_streak", 0) >= (
                C.DORMANT_AFTER_EMPTY_KIWI if t.get("src") == "kiwi" else C.DORMANT_AFTER_EMPTY):
            t["due_h"] = C.DORMANT_DUE_HOURS
    if not only:  # forget windows that no longer exist (past dates, changed settings)
        keys = {t["key"] for t in tasks}
        state["last"] = {k: v for k, v in state["last"].items() if k in keys}
    todo = overdue(tasks, state["last"])
    print(f"{len(todo)} משימות ממתינות")
    new_deals: list[dict] = []
    detail_budget = C.MAX_DETAIL_LOOKUPS
    kc, kiwi_off = None, False
    econ_budget = C.MAX_ECONOMY_LOOKUPS

    try:
        for t in todo:
            if time.monotonic() - started > a.minutes * 60 or (a.max_calls and run["calls"] >= a.max_calls):
                break
            is_kiwi = t.get("src") == "kiwi"
            if is_kiwi and (kiwi_off or not C.KIWI_ENABLED):
                continue
            if run["calls"]:
                time.sleep(C.KIWI_PACE_SECONDS if is_kiwi else C.PACE_SECONDS)
            run["calls"] += 1
            if is_kiwi:
                try:
                    kc = kc or kiwi.Client()
                    pts = kiwi.search_month(kc, t)
                    run["kiwi"] = run.get("kiwi", 0) + 1
                except kiwi.KiwiError as e:
                    print(f"  ! Kiwi: {e}. מדלגים על Kiwi בריצה הזו.")
                    kiwi_off = True
                    continue
            else:
                pts = calendar(t)
            state["last"][t["key"]] = now_utc().isoformat(timespec="seconds")
            if pts is None:
                continue
            ds = state.setdefault("routes", {}).setdefault(dorm_key(t), {"empty_streak": 0})
            if not pts:
                run["empty"] += 1
                ds["empty_streak"] += 1
                print(f"  {t['key']}: אין תוצאות")
                continue
            if ds.get("empty_streak", 0) >= C.DORMANT_AFTER_EMPTY:
                print(f"  {t['origin']}-{t['dest']}: חזרו תוצאות, היעד פעיל שוב")
            ds["empty_streak"] = 0
            ds["last_found"] = today
            run["ok"] += 1
            deals = find_deals(t, pts, hist, today)
            update_history(hist, route_key(t), pts, today)
            hub = None
            if not is_kiwi:
                remember_cal(state, t, pts, today)
                hub = t["origin"] if t["origin"] in C.HUBS else t["dest"] if t["dest"] in C.HUBS else None
            if hub:
                targets = [t["dest"]] if t["origin"] == hub else C.HUBS[hub]["dests"]
                for x in targets:
                    vp = hub_points(state, hub, x, today)
                    if not vp:
                        continue
                    region = C.DESTINATIONS.get(x, ("", "asia", False))[1]
                    vt = {"origin": "TLV", "dest": x, "dur": C.REGIONS[region]["dur"], "region": region, "via": hub}
                    vdeals = find_deals(vt, vp, hist, today)
                    update_history(hist, route_key(vt), vp, today)
                    print(f"    דרך {hub} ל-{x}: {len(vp)} תאריכים משולבים, הזול ${min(p['price'] for p in vp):,.0f}, מציאות: {len(vdeals)}")
                    deals += vdeals
            lo = min(p["price"] for p in pts)
            print(f"  {t['key']} {t['from']}..{t['to']}: {len(pts)} תאריכים, הזול ${lo:,.0f}, מציאות: {len(deals)}")
            for dl in deals:
                if not is_new(dl, alerts):
                    continue
                if detail_budget > 0 and not dl.get("via") and not dl.get("details"):
                    detail_budget -= 1
                    time.sleep(C.PACE_SECONDS)
                    run["calls"] += 1
                    dl["details"] = details(dl["origin"], dl["dest"], dl["dep"], dl["ret"])
                if dl.get("details"):
                    vias = set()
                    for seg in ((dl["details"] or {}).get("out"), (dl["details"] or {}).get("ret")):
                        vias |= set((seg or {}).get("via", []))
                    if vias & C.BANNED_AIRPORTS:
                        print(f"    מדלג: עובר דרך {sorted(vias & C.BANNED_AIRPORTS)}")
                        continue
                if econ_budget > 0:
                    econ_budget -= 1
                    try:
                        if dl.get("src") == "kiwi":
                            time.sleep(C.KIWI_PACE_SECONDS)
                            kc = kc or kiwi.Client()
                            eco = kiwi.economy_price(kc, dl["origin"], dl["dest"], dl["dep"], dl["ret"])
                        else:
                            time.sleep(C.PACE_SECONDS)
                            eco = economy_gf(dl["origin"], dl["dest"], dl["dep"], dl["ret"])
                        run["calls"] += 1
                    except kiwi.KiwiError:
                        eco = None
                    dl["economy"] = eco
                    if eco and dl["price"] <= eco * C.BIZ_TO_ECO_RATIO:
                        dl["reasons"].append(f"ביזנס רק פי {dl['price'] / eco:.1f} ממחיר התיירים")
                new_deals.append(dl)
    except Blocked as e:
        run["blocked"] = True
        until = now_utc() + timedelta(hours=C.BACKOFF_HOURS)
        state["backoff_until"] = until.isoformat(timespec="seconds")
        print(f"נחסם / הוגבל ({e}). עוצרים עד {state['backoff_until']}.")

    run["deals"] = len(new_deals)
    if new_deals:
        sent = notify.send_deals(new_deals, dry_run=a.dry_run)
        if sent:
            for dl in new_deals:
                alerts[f"{dl['route']}|{dl['month']}"] = {"price": dl["price"], "at": now_utc().isoformat(timespec="seconds")}
            state["last_email"] = now_utc().isoformat(timespec="seconds")
    elif notify.heartbeat_due(state.get("last_email")):
        if notify.send_heartbeat(state, hist, dry_run=a.dry_run):
            state["last_email"] = now_utc().isoformat(timespec="seconds")

    save(STATE_F, state)
    save(HIST_F, hist)
    save(ALERTS_F, alerts)
    run["end"] = now_utc().isoformat(timespec="seconds")
    with LOG_F.open("a", encoding="utf-8") as f:
        f.write(json.dumps(run, ensure_ascii=False) + "\n")
    print(json.dumps(run, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
