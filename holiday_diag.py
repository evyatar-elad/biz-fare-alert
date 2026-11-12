"""Diagnosis 2 (12/11): stopovers of 1-2 nights on ONE ticket.

The user's Azerbaijan Airlines ticket (Sep 2026, one ticket 7712439297609): TLV-GYD 14/9,
GYD-PEK 15/9 (a night in Baku), PEK-GYD 30/9, GYD-TLV 2/10 (two nights in Baku). Kiwi's
search returned nothing for 20-48 hour layovers; does Google's multi-city search price such
itineraries as one ticket? Compare with the plain round trip for the same dates.
Writes data/holidays/diag.md and the step summary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from profiles import holidays as P

OUT = Path(__file__).parent / "data" / "holidays" / "diag.md"
lines = []
last = [0.0]


def say(s=""):
    print(s, flush=True)
    lines.append(s)


def pace():
    w = P.PACE_SECONDS - (time.time() - last[0])
    if w > 0:
        time.sleep(w)
    last[0] = time.time()


def multi(legs):
    pace()
    p = subprocess.run([sys.executable, "fli_multi.py", "ECONOMY", *[",".join(l) for l in legs],
                        "--exclude", ",".join(P.EXCLUDE_AIRLINES)], capture_output=True, text=True, timeout=300)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"success": False, "error": (p.stdout + p.stderr)[-300:]}


def rt(dest, dep, ret):
    pace()
    p = subprocess.run(["fli", "flights", "TLV", dest, dep, "--return", ret, "--class", "ECONOMY",
                        "--currency", "USD", "--format", "json", "--exclude-airlines", ",".join(P.EXCLUDE_AIRLINES)],
                       capture_output=True, text=True, timeout=200)
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None
    ps = [f["price"] for f in d.get("flights") or [] if f.get("price")]
    return round(min(ps)) if ps else None


CASES = [
    ("אזרביז'אן: לילה בבאקו הלוך, 2 לילות חזור (כמו הכרטיס לסין)", "DEL",
     [("TLV", "GYD", "2027-04-16"), ("GYD", "DEL", "2027-04-17"), ("DEL", "GYD", "2027-04-30"), ("GYD", "TLV", "2027-05-02")]),
    ("אוזבקיסטן: לילה בטשקנט הלוך, לילה בחזור", "BKK",
     [("TLV", "TAS", "2027-04-16"), ("TAS", "BKK", "2027-04-17"), ("BKK", "TAS", "2027-04-30"), ("TAS", "TLV", "2027-05-01")]),
    ("איתיחאד: 2 לילות באבו דאבי בהלוך בלבד", "BKK",
     [("TLV", "AUH", "2027-04-16"), ("AUH", "BKK", "2027-04-18"), ("BKK", "TLV", "2027-05-01")]),
    ("אמירייטס: לילה בדובאי בחזור בלבד", "HKT",
     [("TLV", "HKT", "2027-04-16"), ("HKT", "DXB", "2027-04-30"), ("DXB", "TLV", "2027-05-01")]),
    ("אזרביז'אן לסין, תשרי 2027 (רחוק: האם גוגל כבר רואה)", "PEK",
     [("TLV", "GYD", "2027-10-04"), ("GYD", "PEK", "2027-10-05"), ("PEK", "GYD", "2027-10-20"), ("GYD", "TLV", "2027-10-22")]),
]


def main():
    say("# אבחון: עצירה של לילה-שניים בכרטיס אחד (גוגל, חיפוש רב-יעדי)")
    for title, dest, legs in CASES:
        m = multi(legs)
        trips = m.get("trips") or []
        dep, ret = legs[0][2], legs[-1][2]
        base = rt(dest, dep, ret)
        say(f"\n## {title}")
        say("מסלול: " + " · ".join(f"{a}-{b} {d[5:]}" for a, b, d in legs))
        if not trips:
            say(f"- רב-יעדי: אין תוצאות ({str(m.get('error') or 'ריק')[:150]})")
        for t in trips[:3]:
            airl = sorted({f['airline'] for l in t['legs'] for f in l['flights']})
            say(f"- רב-יעדי: ${round(t['price'])} · {', '.join(airl)} · "
                + " | ".join(f"{l['flights'][0]['from']}-{l['flights'][-1]['to']} {l['hours']}ש'" for l in t['legs']))
        say(f"- הלוך חזור רגיל TLV-{dest} לאותם תאריכים: " + (f"${base}" if base else "אין"))
    text = "\n".join(lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(text)


if __name__ == "__main__":
    main()
