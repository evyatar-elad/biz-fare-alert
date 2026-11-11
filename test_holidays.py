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
    print("HOLIDAYS_OK")


if __name__ == "__main__":
    main()
