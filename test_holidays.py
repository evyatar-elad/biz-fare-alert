"""Tests for the holidays profile (no network): calendar, vacation days, best spread.
Usage: python test_holidays.py"""
from datetime import date

import holiday_cal as HC


def d(y, m, dd):
    return date(y, m, dd)


def main():
    t = HC.tishrei(5788)
    assert t.labels[d(2027, 10, 1)] == "ערב ראש השנה"
    assert t.labels[d(2027, 10, 11)] == "יום כיפור"
    assert t.core == (d(2027, 10, 15), d(2027, 10, 23)), t.core
    assert t.dep == (d(2027, 9, 24), d(2027, 10, 18)), t.dep
    assert d(2027, 10, 4) not in t.free  # Tzom Gedalia = normal day
    p = HC.pesach(5787)
    assert p.labels[d(2027, 4, 21)].startswith("ערב פסח")
    assert p.labels[d(2027, 5, 12)] == "יום העצמאות"
    assert p.dep == (d(2027, 4, 5), d(2027, 4, 25)), p.dep
    # Yom Ha'atzmaut moves: 5 Iyar 5788 is Monday 1/5/2028 -> Tuesday 2/5
    assert HC.yom_haatzmaut(5788) == d(2028, 5, 2), HC.yom_haatzmaut(5788)

    # Examples agreed with the user (11/11)
    v = HC.vacation(t, d(2027, 10, 8), d(2027, 10, 23))
    assert v["vac"] == 3, v   # Tue-Thu 12-14/10 after Yom Kippur
    v = HC.vacation(p, d(2027, 4, 16), d(2027, 5, 1))
    assert v["vac"] == 4, v   # Sun-Tue 18-20/4 + Thu 29/4
    assert HC.notes(p, d(2027, 4, 22), d(2027, 5, 6)) == ["ליל הסדר בארץ"]
    assert HC.notes(p, d(2027, 4, 16), d(2027, 5, 1)) == []

    b = HC.best_spread(t)
    assert b["top"][0]["vac"] == 3 and b["top"][0]["dep"] == d(2027, 10, 8)
    assert [r["nights"] for r in b["per_nights"]] == list(range(14, 22))
    b = HC.best_spread(p)
    assert b["top"][0]["vac"] == 4

    up = HC.upcoming(d(2026, 11, 11))
    assert [h.key for h in up][:2] == ["pesach-5787", "tishrei-5788"], [h.key for h in up]
    scanner_and_page()
    print("HOLIDAYS_OK")


def scanner_and_page():
    """Storage, best/low/alerts and the page, with fake points (no network)."""
    import tempfile
    from pathlib import Path
    import holiday_scanner as S
    import holiday_status as HS
    t = HC.tishrei(5788)
    pts = [{"dep": "2027-10-08", "nights": 15, "price": 900, "src": "kiwi", "dest": "BKK",
            "info": {"out": {"via": ["AUH"], "airlines": ["Etihad"], "hours": 12.0, "to": "BKK", "legs": []},
                     "ret": {"via": ["VIE"], "airlines": ["Austrian"], "hours": 16.0, "to": "TLV", "legs": []},
                     "separate": False, "url": "https://kiwi.example"}},
           {"dep": "2027-10-01", "nights": 21, "price": 850, "src": "google", "dest": "BKK", "info": None}]
    best, curve, prices, alerts = {}, {}, {}, []
    S.record(prices, pts, "2026-11-12")
    S.record(prices, pts, "2026-11-13")  # unchanged price: not stored twice
    assert prices["kiwi|BKK"]["2027-10-08|15"] == [["2026-11-12", 900]]
    S.update_best(best, t, "BKK", pts, "2026-11-12", alerts)
    b = best[t.key]["BKK"]
    assert b["now"]["price"] == 850 and b["now"]["vac"] == 7 and b["low"]["price"] == 850
    assert b["noeu"] is None if "noeu" in b else True  # google option has no route info
    assert alerts == []                                  # first day: no alerts
    cheaper = [{**pts[1], "price": 700}]
    S.update_best(best, t, "BKK", cheaper, "2026-11-13", alerts)
    assert alerts and alerts[0]["type"] == "low" and alerts[0]["prev"] == 850, alerts
    S.update_curve(curve, t, "BKK", 700, "2026-11-13")
    assert curve[t.key]["BKK"][0][1] == (t.core[0] - date(2026, 11, 13)).days
    tmp = Path(tempfile.mkdtemp())
    (tmp / "prices").mkdir()
    import json
    (tmp / "best.json").write_text(json.dumps(best))
    (tmp / "curve.json").write_text(json.dumps(curve))
    (tmp / "prices" / f"{t.key}.json").write_text(json.dumps(prices))
    HS.DATA = tmp
    out = tmp / "holidays.html"
    HS.main(out)
    html_ = out.read_text()
    assert "חגי תשרי" in html_ and "$700" in html_ and "ימי חופש" in html_


if __name__ == "__main__":
    main()
