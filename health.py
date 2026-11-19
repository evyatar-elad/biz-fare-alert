"""Health check for both systems: are the runs really collecting prices?

Found 18/11: from 16/11 the holidays test failed every run, so the scan step was skipped for
3 days while the chain kept running and the page kept updating (with old prices), and nobody knew.

- problems(system): list of Hebrew problem lines (empty = healthy). Used by the pages (red warning)
  and by the workflow step below.
- python health.py biz|holidays: run at the end of each workflow run (JOB_STATUS = job.status).
  Writes data/[holidays/]health.json (read by the daily check session) and emails the user
  "תקלה" once when a problem starts (again after 24 hours if it continues), and "חזר לעבוד" when it ends.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
SYSTEMS = {
    # name, data dir, "a run that collected": key in runs.jsonl, hours without collecting = problem
    "biz": ("ביזנס", ROOT / "data", "ok", 12),
    # 30, not 6 (19/11 false alarm): each Kiwi task is due every 24 hours, so after a full sweep the
    # runs only retry Google multi-city searches, which often return nothing, for up to ~20 hours.
    "holidays": ("חגים - תיירים", ROOT / "data" / "holidays", "points", 30),
}
ANY_RUN_HOURS = 4     # no run logged at all for this long = the chain stopped (or the scan step is skipped)
FAIL_STREAK = 2       # failed workflow runs in a row = problem (one alone can be a passing network error)
REMIND_HOURS = 24


def _runs(d: Path) -> list[dict]:
    try:
        return [json.loads(x) for x in (d / "runs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    except FileNotFoundError:
        return []


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _hours(now: datetime, iso: str | None) -> float:
    return (now - datetime.fromisoformat(iso)).total_seconds() / 3600 if iso else 1e9


def problems(system: str, now: datetime | None = None, data_dir: Path | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    _, d, key, max_h = SYSTEMS[system]
    d = data_dir or d
    runs = _runs(d)
    out = []
    last_any = runs[-1]["at"] if runs else None
    last_ok = next((r["at"] for r in reversed(runs) if r.get(key)), None)
    if _hours(now, last_any) > ANY_RUN_HOURS:
        out.append(f"לא נרשמה ריצת סריקה כבר {_fmt_h(now, last_any)} (השרשרת נעצרה, או ששלב הסריקה לא רץ)")
    elif _hours(now, last_ok) > max_h:
        out.append(f"ריצות רצות אבל לא אספו מחירים כבר {_fmt_h(now, last_ok)}")
    streak = _load(d / "health.json").get("fail_streak", 0)
    if streak >= FAIL_STREAK:
        out.append(f"{streak} ריצות ברצף נכשלו ב-GitHub Actions")
    return out


def _fmt_h(now: datetime, iso: str | None) -> str:
    h = _hours(now, iso)
    if h > 1e8:
        return "מעולם"
    return f"{round(h)} שעות" if h < 48 else f"{round(h / 24)} ימים"


def warning_html(system: str) -> str:
    """A red box for the page (empty when healthy)."""
    p = problems(system)
    if not p:
        return ""
    import html
    return ("<div class=card style='border:2px solid #b91c1c;color:#b91c1c;font-weight:bold'>⚠️ תקלה: "
            + " · ".join(html.escape(x) for x in p)
            + ". המחירים בדף עלולים להיות ישנים. נשלח מייל, ובדיקה יומית אוטומטית מנסה לתקן.</div>")


def main(argv: list[str]) -> int:
    system = argv[0]
    dry = "--dry-run" in argv
    name, d, _, _ = SYSTEMS[system]
    now = datetime.now(timezone.utc)
    hp = d / "health.json"
    st = _load(hp)
    failed = os.environ.get("JOB_STATUS", "success") not in ("success", "")
    st["fail_streak"] = st.get("fail_streak", 0) + 1 if failed else 0
    hp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")  # problems() reads the streak
    p = problems(system, now)
    run_url = ""
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = f"https://github.com/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    st.update({"checked": now.isoformat(timespec="seconds"), "problems": p, "last_run_failed": failed,
               "run_url": run_url})
    import notify
    if p and (not st.get("since") or _hours(now, st.get("mailed")) > REMIND_HOURS):
        st.setdefault("since", now.isoformat(timespec="seconds"))
        body = (f"<div dir=rtl style='font-family:Arial'><h2>⚠️ תקלה במערכת {name}</h2><ul>"
                + "".join(f"<li>{x}</li>" for x in p)
                + f"</ul><p>מאז: {st['since'][:16].replace('T', ' ')} UTC.</p>"
                + (f"<p><a href='{run_url}'>הריצה האחרונה ב-GitHub</a></p>" if run_url else "")
                + "<p>בדיקה יומית אוטומטית של Claude תנסה לתקן. אפשר גם לכתוב ל-Claude בצ'אט.</p></div>")
        if notify._send(f"⚠️ תקלה בבוט ({name})", body, dry):
            st["mailed"] = now.isoformat(timespec="seconds")
    elif not p and st.get("since"):
        body = (f"<div dir=rtl style='font-family:Arial'><h2>✅ מערכת {name} חזרה לעבוד</h2>"
                f"<p>התקלה מ-{st['since'][:16].replace('T', ' ')} UTC נפתרה.</p></div>")
        if st.get("mailed"):
            notify._send(f"✅ הבוט חזר לעבוד ({name})", body, dry)
        st.pop("since", None)
        st.pop("mailed", None)
    hp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"health {system}: {'OK' if not p else p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
