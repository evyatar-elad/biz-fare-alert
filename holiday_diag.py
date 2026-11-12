"""Diagnosis after the first probe (12/11): from GitHub, Google returned an EMPTY economy
calendar for most destinations (BKK 0/21), while the same request from another machine
returned 21/21. Find out what changes the answer: airline exclusion, country/language,
repetition, or the flight search (shopping) instead of the calendar.
Writes data/holidays/diag.md and the step summary."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from profiles import holidays as P

OUT = Path(__file__).parent / "data" / "holidays" / "diag.md"
lines = []
last = [0.0]


def say(s=""):
    print(s, flush=True)
    lines.append(s)


def fli(args):
    w = P.PACE_SECONDS - (time.time() - last[0])
    if w > 0:
        time.sleep(w)
    last[0] = time.time()
    p = subprocess.run(["fli", *args, "--format", "json"], capture_output=True, text=True, timeout=200)
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"success": False, "error": (p.stdout + p.stderr)[-200:]}


EX = ["--exclude-airlines", ",".join(P.EXCLUDE_AIRLINES)]
PES = ["--from", "2027-04-05", "--to", "2027-04-25", "--round", "-d", "15", "--currency", "USD"]


def cal(label, dest, extra, cabin="ECONOMY", win=PES):
    d = fli(["dates", "TLV", dest, *win, "--class", cabin, *extra])
    pts = sorted(round(x["price"]) for x in d.get("dates", []) if x.get("price"))
    say(f"| {label} | {dest} | {d.get('success')} | {len(pts)} | {pts[0] if pts else '-'} | {str(d.get('error') or '')[:80]} |")


def main():
    say("# אבחון לוח מחירים מ-GitHub")
    say("| ניסוי | יעד | הצליח | תאריכים עם מחיר | הזול | שגיאה |")
    say("|---|---|---|---|---|---|")
    cal("רגיל", "BKK", [])
    cal("עם החרגת חברות", "BKK", EX)
    cal("country IL", "BKK", ["--country", "IL"])
    cal("country IL + he", "BKK", ["--country", "IL", "--language", "he"])
    cal("ביקורת (היה מלא)", "HAN", EX)
    cal("רגיל שוב", "BKK", [])
    cal("country IL", "SGN", ["--country", "IL"])
    cal("country IL", "DPS", ["--country", "IL"])
    cal("country IL", "NRT", ["--country", "IL"])
    cal("רגיל, 14 לילות", "BKK", [], win=["--from", "2027-04-05", "--to", "2027-04-25", "--round", "-d", "14", "--currency", "USD"])
    far = ["--from", "2027-07-01", "--to", "2027-07-31", "--round", "-d", "14", "--currency", "USD"]
    cal("ביזנס יולי 27, רגיל", "SGN", EX, "BUSINESS", far)
    cal("ביזנס יולי 27, country IL", "SGN", EX + ["--country", "IL"], "BUSINESS", far)
    say("\n## חיפוש טיסות (לא לוח) לתאריך אחד")
    for extra, lab in (([], "רגיל"), (["--country", "IL"], "country IL")):
        d = fli(["flights", "TLV", "BKK", "2027-04-16", "--return", "2027-05-01", "--class", "ECONOMY",
                 "--currency", "USD", *EX, *extra])
        fl = d.get("flights") or []
        ps = sorted(round(f["price"]) for f in fl if f.get("price"))
        say(f"- {lab}: success={d.get('success')}, {len(fl)} טיסות, הזול {ps[:3]} {str(d.get('error') or '')[:100]}")
    text = "\n".join(lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(text)


if __name__ == "__main__":
    main()
