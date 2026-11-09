"""Daily digest: ONE email a day (from DIGEST_HOUR_IL, Israel time) with everything new:
business deals found by the scanner (state["pending"]), newsletter and deal-site items
(data/pending_news.json), and newsletter reading stats. Nothing new = no email, except
the weekly "still alive" summary.

The user asked for this on 9/11 after getting too many separate emails.
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import config as C
import notify
import scanner

IL = ZoneInfo("Asia/Jerusalem")
DATA = Path(__file__).parent / "data"
NEWS_F = DATA / "pending_news.json"
STATS_F = DATA / "news_stats.json"


def section(title: str, inner: str) -> str:
    return (f'<div style="{notify.FONT}font-size:19px;font-weight:bold;color:{notify.INK};margin:22px 4px 10px">'
            f'{title}</div>{inner}')


def stats_line() -> str:
    try:
        st = json.loads(STATS_F.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return "עוד לא נקראו ניוזלטרים."
    days = sorted(st)[-7:]
    read = sum(st[d]["read"] for d in days)
    matched = sum(st[d]["matched"] for d in days)
    senders: dict[str, int] = {}
    for d in days:
        for k, v in st[d]["senders"].items():
            senders[k] = senders.get(k, 0) + v
    top = ", ".join(f"{html.escape(k)} ({v})" for k, v in sorted(senders.items(), key=lambda kv: -kv[1])[:8])
    return (f"ב-7 הימים האחרונים נקראו {read} מיילים מהניוזלטרים, ב-{matched} מהם יש ביזנס עם מחיר."
            + (f"<br>שולחים: {top}" if top else ""))


def main(dry_run: bool = False, force: bool = False) -> int:
    state = scanner.load(scanner.STATE_F, {"last": {}})
    alerts = scanner.load(scanner.ALERTS_F, {})
    hist = scanner.load(scanner.HIST_F, {})
    try:
        news = json.loads(NEWS_F.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        news = []
    now_il = datetime.now(IL)
    today = now_il.date().isoformat()
    if not force and (now_il.hour < C.DIGEST_HOUR_IL or state.get("last_digest") == today):
        print(f"digest: not now ({now_il:%H:%M} IL, last {state.get('last_digest')}); "
              f"waiting: {len(state.get('pending', []))} deals, {len(news)} news")
        return 0

    deals = state.get("pending", [])
    if not deals and not news:
        if notify.heartbeat_due(state.get("last_email")):
            if notify.send_heartbeat(state, hist, dry_run=dry_run, extra=stats_line()):
                state["last_email"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                scanner.save(scanner.STATE_F, state)
        return 0

    parts = []
    if deals:
        parts.append(section(f"✈️ מציאות ביזנס ({len(deals)})", "".join(notify.deal_card(d) for d in deals)))
    news_html = "".join(n["html"] for n in news if n["kind"] == "news")
    feed_rows = "".join(n["html"] for n in news if n["kind"] == "feed")
    if news_html:
        parts.append(section("📬 מבצעי ביזנס בניוזלטרים", news_html))
    if feed_rows:
        parts.append(section("📰 מאתרי מציאות", f'<table role="presentation" width="100%" style="background:#fff;'
                                                f'border:1px solid {notify.LINE};border-radius:12px;padding:6px 14px">'
                                                f'{feed_rows}</table>'))
    parts.append(f'<div style="{notify.FONT}font-size:13px;color:{notify.MUTED};margin:16px 6px 0">{stats_line()}</div>')

    if deals:
        top = deals[0]
        subject = (f"✈️ סיכום יומי: ביזנס {notify.name(top['origin'])}-{notify.name(top['dest'])} ${top['price']:,.0f}"
                   + (f" ועוד {len(deals) - 1}" if len(deals) > 1 else ""))
    else:
        subject = f"📬 סיכום יומי: {len(news)} פריטים מניוזלטרים ואתרי מציאות"
    if not notify._send(subject, notify.page("".join(parts), subject), dry_run):
        return 1
    if not dry_run:
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for d in deals:
            alerts[d["route"]] = {"price": d["price"], "at": at, "month": d["month"]}
        state["pending"] = []
        state["last_digest"] = today
        state["last_email"] = at
        scanner.save(scanner.STATE_F, state)
        scanner.save(scanner.ALERTS_F, alerts)
        NEWS_F.write_text("[]", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv, force="--force" in sys.argv))
