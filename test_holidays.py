"""Tests for the holidays profile (no network): calendar, vacation days, best spread.
Usage: python test_holidays.py"""
from datetime import date, timedelta

import holiday_cal as HC


def d(y, m, dd):
    return date(y, m, dd)


def main():
    t = HC.tishrei(5788)
    assert t.labels[d(2027, 10, 1)] == "ערב ראש השנה"
    assert t.labels[d(2027, 10, 11)] == "יום כיפור"
    assert t.core == (d(2027, 10, 15), d(2027, 10, 23)), t.core
    assert t.dep == (d(2027, 9, 27), d(2027, 10, 17)), t.dep
    assert HC.missed(t, d(2027, 10, 8), d(2027, 10, 23)) == 0
    assert HC.covers(t, d(2027, 10, 1), d(2027, 10, 21))          # misses Hoshana Raba + Simchat Torah: ok
    assert not HC.covers(t, d(2027, 9, 27), d(2027, 10, 15))      # misses all of Sukkot: no
    assert d(2027, 10, 4) not in t.free  # Tzom Gedalia = normal day
    p = HC.pesach(5787)
    assert p.labels[d(2027, 4, 21)].startswith("ערב פסח")
    assert p.labels[d(2027, 5, 12)] == "יום העצמאות"
    assert p.dep == (d(2027, 4, 2), d(2027, 4, 23)), p.dep
    assert not HC.covers(p, d(2027, 4, 5), d(2027, 4, 19))        # back before the Seder: no
    assert HC.covers(p, d(2027, 4, 21), d(2027, 5, 5))            # leaving on erev Pesach, week at the start
    assert HC.covers(p, d(2027, 4, 13), d(2027, 4, 27))           # misses the 7th day only: ok
    assert HC.notes(p, d(2027, 4, 13), d(2027, 4, 27)) == ["מפספס 1 יום חג"]
    assert not HC.covers(p, d(2027, 4, 24), d(2027, 5, 10))       # misses 3 days at the start: no
    # Yom Ha'atzmaut moves: 5 Iyar 5788 is Monday 1/5/2028 -> Tuesday 2/5
    assert HC.yom_haatzmaut(5788) == d(2028, 5, 2), HC.yom_haatzmaut(5788)

    # Examples agreed with the user (11/11)
    v = HC.vacation(t, d(2027, 10, 8), d(2027, 10, 23))
    assert v["vac"] == 3, v   # Tue-Thu 12-14/10 after Yom Kippur
    v = HC.vacation(p, d(2027, 4, 16), d(2027, 5, 1))
    assert v["vac"] == 4, v   # Sun-Tue 18-20/4 + Thu 29/4
    assert HC.notes(p, d(2027, 4, 22), d(2027, 5, 6)) == ["מפספס 1 יום חג", "ליל הסדר בבית"]
    assert HC.notes(p, d(2027, 4, 16), d(2027, 5, 1)) == []

    b = HC.best_spread(t)
    assert b["top"][0]["vac"] == 3 and b["top"][0]["dep"] == d(2027, 10, 8)
    assert [r["nights"] for r in b["per_nights"]] == list(range(14, 22))
    b = HC.best_spread(p)
    assert b["top"][0]["vac"] == 4

    up = HC.upcoming(d(2026, 11, 11))
    assert [h.key for h in up][:2] == ["pesach-5787", "tishrei-5788"], [h.key for h in up]
    scanner_and_page()
    health_check()
    print("HOLIDAYS_OK")


def scanner_and_page():
    """Storage, best/low/alerts and the page, with fake points (no network)."""
    import tempfile
    from pathlib import Path
    import holiday_scanner as S
    import holiday_status as HS
    t = HC.tishrei(5788)
    D_B = date.today().isoformat()  # relative: the page hides prices older than FRESH_DAYS
    D_A = (date.today() - timedelta(days=1)).isoformat()
    pts = [{"dep": "2027-10-08", "nights": 15, "price": 900, "src": "kiwi", "dest": "BKK",
            "info": {"out": {"via": ["AUH"], "airlines": ["Etihad"], "hours": 12.0, "to": "BKK", "legs": []},
                     "ret": {"via": ["VIE"], "airlines": ["Austrian"], "hours": 16.0, "to": "TLV", "legs": []},
                     "separate": False, "url": "https://kiwi.example"}},
           {"dep": "2027-10-01", "nights": 21, "price": 850, "src": "google", "dest": "BKK", "info": None}]
    best, curve, prices, alerts = {}, {}, {}, []
    S.record(prices, pts, D_A)
    S.record(prices, pts, D_B)  # unchanged price: not stored twice
    assert prices["kiwi|BKK"]["2027-10-08|15"] == [[D_A, 900]]
    S.update_best(best, t, "BKK", pts, D_A, alerts)
    b = best[t.key]["BKK"]
    assert b["now"]["price"] == 850 and b["now"]["vac"] == 7 and b["low"]["price"] == 850
    assert b["noeu"] is None if "noeu" in b else True  # google option has no route info
    assert alerts == []                                  # first day: no alerts
    cheaper = [{**pts[1], "price": 700}]
    S.update_best(best, t, "BKK", cheaper, D_B, alerts)
    assert alerts and alerts[0]["type"] == "low" and alerts[0]["prev"] == 850, alerts
    S.update_curve(curve, t, "BKK", 700, D_B)
    assert curve[t.key]["BKK"][0][1] == (t.core[0] - date.fromisoformat(D_B)).days
    best[t.key]["BKK"]["stops"] = {"GYD": {"price": 959, "legs": [["TLV", "GYD", "2027-10-08"], ["GYD", "BKK", "2027-10-09"],
                                                                 ["BKK", "GYD", "2027-10-21"], ["GYD", "TLV", "2027-10-23"]],
                                           "airlines": ["Azerbaijan Airlines"], "hours": [3, 8, 8, 3], "via": [[], [], [], []],
                                           "hub": "GYD", "n_out": 1, "n_back": 2, "vac": 3, "nights": 15, "seen": D_B}}
    best[t.key]["_open_jaw_1t"] = {"KIX-NRT": {"price": 1200, "legs": [["TLV", "KIX", "2027-10-08"], ["NRT", "TLV", "2027-10-23"]],
                                               "airlines": ["X"], "nights": 15, "vac": 3, "seen": D_B}}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "prices").mkdir()
    import json
    (tmp / "best.json").write_text(json.dumps(best))
    (tmp / "curve.json").write_text(json.dumps(curve))
    (tmp / "prices" / f"{t.key}.json").write_text(json.dumps(prices))
    HS.DATA = tmp
    HS.main(tmp / "site")
    html_ = (tmp / "site" / "tishrei.html").read_text()
    assert "חגי תשרי" in (tmp / "site" / "holidays.html").read_text()
    assert "חגי תשרי" in html_ and "$700" in html_ and "ימי חופש" in html_
    assert "עצירה בבאקו (כרטיס אחד)" in html_ and "$959" in html_ and "(כרטיס אחד)" in html_


def health_check():
    """The 18/11 failure: runs keep going but collect nothing -> a problem; fresh collecting run -> healthy."""
    import json
    import tempfile
    from datetime import datetime, timezone
    from pathlib import Path
    import health
    d = Path(tempfile.mkdtemp())
    now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    w = lambda rows: (d / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    w([{"at": "2026-11-18T11:00:00+00:00", "points": 500}])
    assert health.problems("holidays", now, d) == []
    w([{"at": "2026-11-18T00:00:00+00:00", "points": 500}, {"at": "2026-11-18T11:00:00+00:00", "points": 0}])
    assert "לא אספו" in health.problems("holidays", now, d)[0]
    w([{"at": "2026-11-16T00:00:00+00:00", "points": 500}])
    assert "לא נרשמה" in health.problems("holidays", now, d)[0]
    w([{"at": "2026-11-18T11:00:00+00:00", "points": 500}])
    (d / "health.json").write_text(json.dumps({"fail_streak": 2}))
    assert "נכשלו" in health.problems("holidays", now, d)[0]


if __name__ == "__main__":
    main()
