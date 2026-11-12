"""Reads one newsletter email with Claude (Haiku 5.5) and returns structured promos.

One reader for every profile (CLAUDE.md, "תכניות להמשך"): newsletters.py reads each mail
once, this module extracts what it means, and route() decides in code which profile it
belongs to (business deals / holidays - economy). The model only extracts and explains;
relevance is decided in code, so it is consistent and testable.

Needs the ANTHROPIC_API_KEY secret (a key in a separate Workspace with a monthly spend
limit). Without it newsletters.py keeps the old keyword filter.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

MODEL = "claude-haiku-5-5"   # user's choice (11/11): cheapest, enough for extraction
MAX_CHARS = 15000            # long marketing mails are mostly footer; keep the start
USAGE_F = Path(__file__).parent / "data" / "news_ai_usage.json"
# USD per million tokens (Haiku 5.5, prompts up to 100K tokens)
PRICE_IN, PRICE_OUT = 0.10, 0.50
# Rough conversion for comparing a promo price with our USD history (not for booking).
TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "ILS": 0.27, "NIS": 0.27, "CHF": 1.12, "AED": 0.27}

SYSTEM = """You read airline and travel-deal newsletters for a traveller based in Tel Aviv, Israel.
For each email, extract every flight promotion it contains, exactly as written. Do not guess
missing values: use null. Prices: the number and currency as written, and whether it is round
trip, one way, or unknown. Dates: ISO yyyy-mm-dd; travel_from/travel_to = the period in which
the flights can be taken; book_by = the last day to buy. Cabin: economy, premium_economy,
business, first, or unknown. Origin/destination: IATA airport or city codes when you can tell
them (Tel Aviv = TLV), otherwise null, plus the place name as written.
summary_he: one or two short sentences in Hebrew explaining what the email offers and any
important condition (for example "only from Europe", "members only", "a points sale").
is_promo is false for welcome mails, account notices, surveys and newsletters without a
concrete flight offer. needs_action is true when the email asks to confirm a subscription."""

SCHEMA = {
    "type": "object",
    "properties": {
        "is_promo": {"type": "boolean"},
        "needs_action": {"type": "boolean"},
        "summary_he": {"type": "string"},
        "airline": {"type": ["string", "null"]},
        "deals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "origin": {"type": ["string", "null"]},
                    "origin_name": {"type": ["string", "null"]},
                    "destination": {"type": ["string", "null"]},
                    "destination_name": {"type": ["string", "null"]},
                    "cabin": {"type": "string", "enum": ["economy", "premium_economy", "business", "first", "unknown"]},
                    "price": {"type": ["number", "null"]},
                    "currency": {"type": ["string", "null"]},
                    "price_basis": {"type": "string", "enum": ["round_trip", "one_way", "unknown"]},
                    "travel_from": {"type": ["string", "null"]},
                    "travel_to": {"type": ["string", "null"]},
                    "book_by": {"type": ["string", "null"]},
                    "conditions": {"type": ["string", "null"]},
                },
                "required": ["origin", "origin_name", "destination", "destination_name", "cabin", "price",
                             "currency", "price_basis", "travel_from", "travel_to", "book_by", "conditions"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["is_promo", "needs_action", "summary_he", "airline", "deals"],
    "additionalProperties": False,
}


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    import anthropic
    return anthropic.Anthropic(max_retries=3, timeout=120)


def _record_usage(inp: int, out: int) -> None:
    try:
        u = json.loads(USAGE_F.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        u = {}
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    m = u.setdefault(month, {"mails": 0, "in": 0, "out": 0, "usd": 0.0})
    m["mails"] += 1
    m["in"] += inp
    m["out"] += out
    m["usd"] = round(m["in"] / 1e6 * PRICE_IN + m["out"] / 1e6 * PRICE_OUT, 4)
    USAGE_F.parent.mkdir(exist_ok=True)
    USAGE_F.write_text(json.dumps(dict(sorted(u.items())[-12:]), indent=1), encoding="utf-8")


def extract(sender: str, subject: str, text: str, client=None) -> dict | None:
    """Structured reading of one email, or None on any API problem (caller falls back)."""
    import anthropic
    client = client or _client()
    body = f"From: {sender}\nSubject: {subject}\nToday: {date.today().isoformat()}\n\n{text[:MAX_CHARS]}"
    try:
        r = client.messages.create(
            model=MODEL, max_tokens=4000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": body}],
        )
    except anthropic.APIStatusError as e:
        print(f"news_ai: API error {e.status_code}: {str(e)[:200]}")
        return None
    except anthropic.APIConnectionError as e:
        print(f"news_ai: connection error: {e}")
        return None
    _record_usage(r.usage.input_tokens, r.usage.output_tokens)
    if r.stop_reason in ("refusal", "max_tokens"):
        print(f"news_ai: stop_reason={r.stop_reason}")
        return None
    txt = next((b.text for b in r.content if b.type == "text"), "")
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- routing (code, not the model)
def usd(deal: dict) -> float | None:
    p, cur = deal.get("price"), (deal.get("currency") or "USD").upper().replace("$", "USD")
    if p is None or cur not in TO_USD:
        return None
    v = p * TO_USD[cur]
    return v * 2 if deal.get("price_basis") == "one_way" else v  # compare as round trip


def _d(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def route(res: dict, holidays: list, holiday_dests: dict, biz_dests: dict, biz_max: float) -> dict:
    """Which profile each deal belongs to. holidays = holiday_cal.Holiday list.
    Returns {"business": [...], "holidays": [...]} of deals with notes."""
    out = {"business": [], "holidays": []}
    for d in res.get("deals") or []:
        if d.get("origin") not in (None, "TLV", "LCA") and (d.get("origin_name") or "").lower() not in ("tel aviv", "תל אביב"):
            continue  # promos from other countries are not for us
        dest = d.get("destination")
        price_usd = usd(d)
        if d.get("cabin") in ("business", "first") and (dest in biz_dests or dest is None):
            if price_usd is None or price_usd <= biz_max * 1.25:
                out["business"].append({**d, "usd": price_usd})
        if d.get("cabin") in ("economy", "premium_economy", "unknown") or (d.get("cabin") == "business" and (price_usd or 9e9) <= biz_max):
            if dest is not None and dest not in holiday_dests:
                continue
            a, b = _d(d.get("travel_from")), _d(d.get("travel_to"))
            for h in holidays:
                # the promo travel period must overlap the holiday departure window
                if a and b and (b < h.dep[0] or a > h.dep[1]):
                    continue
                out["holidays"].append({**d, "usd": price_usd, "holiday": h.key, "holiday_name": h.name,
                                        "dates_known": bool(a and b)})
    return out


SAMPLE = """Flash sale! Fly from Tel Aviv to Bangkok from $649 return in Economy, and Business Class
to Ho Chi Minh City from $1,590 return. Travel 1 April - 15 May 2027. Book by 30 November 2026.
Prices per person, including taxes. Unsubscribe | Our business address: 1 Airport Rd."""

if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        if not enabled():
            print("news_ai selftest: no ANTHROPIC_API_KEY")
            sys.exit(1)
        r = extract("Sample Airline <news@example.com>", "Flash sale to Asia", SAMPLE)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        print(json.dumps(json.loads(USAGE_F.read_text()), indent=1))
        sys.exit(0 if r and r.get("deals") else 1)
