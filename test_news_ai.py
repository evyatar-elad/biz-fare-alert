"""Tests for the AI newsletter reader without calling the API (fake client).
Usage: python test_news_ai.py"""
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import holiday_cal
import news_ai
import config as C
from profiles import holidays as HP


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.messages = self

    def create(self, **kw):
        assert kw["model"] == "claude-haiku-5-5"
        assert kw["output_config"]["format"]["type"] == "json_schema"
        return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=3000, output_tokens=300),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def deal(**kw):
    base = {"origin": "TLV", "origin_name": "Tel Aviv", "destination": None, "destination_name": None,
            "cabin": "economy", "price": None, "currency": "USD", "price_basis": "round_trip",
            "travel_from": None, "travel_to": None, "book_by": None, "conditions": None}
    return {**base, **kw}


def main():
    tmp = Path(tempfile.mkdtemp())
    news_ai.USAGE_F = tmp / "usage.json"
    payload = {"is_promo": True, "needs_action": False, "summary_he": "מבצע", "airline": "X", "deals": [
        deal(destination="BKK", cabin="economy", price=699, travel_from="2027-04-01", travel_to="2027-05-15"),
        deal(destination="SGN", cabin="business", price=1599, travel_from="2027-01-10", travel_to="2027-03-01"),
        deal(destination="BKK", cabin="economy", price=500, travel_from="2027-01-01", travel_to="2027-02-01"),
        deal(origin="FRA", origin_name="Frankfurt", destination="BKK", cabin="business", price=900),
        deal(destination="DPS", cabin="economy", price=400, currency="EUR", price_basis="one_way",
             travel_from="2027-09-01", travel_to="2027-10-31"),
    ]}
    res = news_ai.extract("a@b", "Sale", "text", FakeClient(payload))
    assert res == payload
    u = json.loads(news_ai.USAGE_F.read_text())
    m = next(iter(u.values()))
    assert m["mails"] == 1 and m["usd"] > 0

    hols = holiday_cal.upcoming(date(2026, 11, 11))
    r = news_ai.route(res, hols, HP.DESTINATIONS, C.DESTINATIONS, C.MAX_PRICE)
    assert [d["destination"] for d in r["business"]] == ["SGN"], r["business"]       # Frankfurt promo dropped
    hk = [(d["destination"], d["holiday"]) for d in r["holidays"]]
    assert ("BKK", "pesach-5787") in hk and ("DPS", "tishrei-5788") in hk, hk
    assert not any(d["price"] == 500 for d in r["holidays"])                          # Jan-Feb: no holiday
    dps = [d for d in r["holidays"] if d["destination"] == "DPS"][0]
    assert round(dps["usd"]) == 864, dps["usd"]                                       # EUR one way -> USD round trip
    print("NEWS_AI_OK")


if __name__ == "__main__":
    main()
