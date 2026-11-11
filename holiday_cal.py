"""Jewish holiday calendar, vacation-day counting and the "cheapest in vacation days" table.

Rules defined with the user (11/11/2026):
- Work days: Sunday to Thursday.
- NOT counted as vacation days: Friday, Saturday, every erev chag (incl. erev Pesach / Seder
  night, erev Rosh Hashana, erev Yom Kippur, erev Sukkot, Hoshana Raba), holiday days,
  Chol Hamoed Sukkot and Pesach, Yom Ha'atzmaut. Tzom Gedalia is a normal day.
- A flight day that is a work day counts as a vacation day.
- Trip length 14-21 nights; the holiday week can be at the start, middle or end of the trip.

Dates come from the Hebrew calendar (pyluach), so every future year works by itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from pyluach import dates as hd

from profiles import holidays as P

D1 = timedelta(days=1)
WORKDAYS = {6, 0, 1, 2, 3}  # Python weekday(): Sun=6, Mon=0 .. Thu=3
WEEKEND = {4, 5}            # Fri, Sat


def heb(y: int, m: int, d: int) -> date:
    return hd.HebrewDate(y, m, d).to_pydate()


def heb_year(hy: int) -> str:
    """5788 -> תשפ״ח"""
    return hd.HebrewDate(hy, 7, 1).hebrew_date_string().split()[-1]


def yom_haatzmaut(hy: int) -> date:
    """5 Iyar, moved like in Israel: Fri/Sat -> Thursday before, Monday -> Tuesday."""
    d = heb(hy, 2, 5)
    wd = d.weekday()
    if wd == 4:
        return d - D1
    if wd == 5:
        return d - 2 * D1
    if wd == 0:
        return d + D1
    return d


@dataclass
class Holiday:
    key: str                 # "tishrei-5788", "pesach-5787"
    kind: str                # "tishrei" | "pesach"
    name: str                # Hebrew display name
    core: tuple[date, date]  # the main holiday week (Sukkot / Pesach), first..last free day
    free: set[date]          # holiday days that are not vacation days (besides Fri/Sat)
    labels: dict[date, str]  # day -> Hebrew label, for display
    dep: tuple[date, date]   # departure window to scan
    prefs: list[tuple[str, date]] = field(default_factory=list)  # "be home for X" (label, day)

    def departures(self):
        d = self.dep[0]
        while d <= self.dep[1]:
            yield d
            d += D1


def tishrei(hy: int) -> Holiday:
    rh = heb(hy, 7, 1)
    yk = heb(hy, 7, 10)
    suk = heb(hy, 7, 15)
    labels = {rh - D1: "ערב ראש השנה", rh: "ראש השנה", rh + D1: "ראש השנה ב'",
              yk - D1: "ערב יום כיפור", yk: "יום כיפור", suk - D1: "ערב סוכות", suk: "סוכות"}
    for i in range(1, 6):
        labels[suk + i * D1] = "חול המועד סוכות"
    labels[suk + 6 * D1] = "הושענא רבה"
    labels[suk + 7 * D1] = "שמחת תורה"
    free = set(labels)
    erev_rh, erev_suk = rh - D1, suk - D1
    return Holiday(
        key=f"tishrei-{hy}", kind="tishrei", name=f"חגי תשרי {heb_year(hy)}",
        core=(erev_suk, suk + 7 * D1), free=free, labels=labels,
        dep=(erev_rh - P.TISHREI_DEP_BEFORE_EREV_RH * D1, erev_suk + P.TISHREI_DEP_AFTER_EREV_SUKKOT * D1),
        prefs=[("ראש השנה בארץ", erev_rh), ("ערב סוכות בארץ", erev_suk)],
    )


def pesach(hy: int) -> Holiday:
    erev = heb(hy, 1, 14)
    labels = {erev: "ערב פסח (ליל הסדר)", erev + D1: "פסח"}
    for i in range(2, 7):
        labels[erev + i * D1] = "חול המועד פסח"
    labels[erev + 7 * D1] = "שביעי של פסח"
    yh = yom_haatzmaut(hy)
    labels[yh] = "יום העצמאות"
    free = set(labels)
    core = (erev, erev + 7 * D1)
    core_len = (core[1] - core[0]).days
    max_n = P.NIGHTS_MAIN[1]
    return Holiday(
        key=f"pesach-{hy}", kind="pesach", name=f"פסח {heb_year(hy)}",
        core=core, free=free, labels=labels,
        dep=(core[1] - (max_n + P.PESACH_DEP_SLACK) * D1, erev + P.PESACH_DEP_AFTER_EREV * D1),
        prefs=[("ליל הסדר בארץ", erev)],
    )


def upcoming(today: date, horizon_days: int = 400) -> list[Holiday]:
    """Every Tishrei / Pesach whose departure window is not over and starts within the horizon,
    nearest first. The scanner then asks each source only for what it can see."""
    hy = hd.HebrewDate.from_pydate(today).year
    out = []
    for y in (hy - 1, hy, hy + 1, hy + 2):
        for h in (pesach(y), tishrei(y)):
            if h.dep[1] >= today and (h.dep[0] - today).days <= horizon_days:
                out.append(h)
    out.sort(key=lambda h: h.dep[0])
    return out


# ---------------------------------------------------------------- vacation days
def vacation(h: Holiday, dep: date, ret: date) -> dict:
    """Work days used (Sun-Thu that are not holiday/erev/chol hamoed), counting both flight days.
    Also: how many free Fri/Sat and holiday days the trip uses (more = better spread)."""
    work = weekend = hol = 0
    d = dep
    while d <= ret:
        if d in h.free:
            hol += 1
        elif d.weekday() in WEEKEND:
            weekend += 1
        else:
            work += 1
        d += D1
    return {"vac": work, "weekend": weekend, "hol": hol}


def notes(h: Holiday, dep: date, ret: date) -> list[str]:
    """Preferences that do not hide anything, only explain (e.g. "ליל הסדר בארץ")."""
    out = []
    for label, day in h.prefs:
        if dep > day or ret < day:
            out.append(label)
    return out


def best_spread(h: Holiday, nights: tuple[int, int] | None = None, top: int = 6) -> dict:
    """The fixed "procedure": for each trip length, the dates that use the fewest vacation days.
    Ties go to more free Fri/Sat/holiday days. Shown always, for every holiday, regardless of price."""
    lo, hi = nights or P.NIGHTS_MAIN
    rows = []
    for dep in h.departures():
        for n in range(lo, hi + 1):
            ret = dep + n * D1
            v = vacation(h, dep, ret)
            rows.append({"dep": dep, "ret": ret, "nights": n, **v, "notes": notes(h, dep, ret)})
    per_n = {}
    for r in rows:
        k = r["nights"]
        if k not in per_n or (r["vac"], -(r["weekend"] + r["hol"])) < (per_n[k]["vac"], -(per_n[k]["weekend"] + per_n[k]["hol"])):
            per_n[k] = r
    rows.sort(key=lambda r: (r["vac"], -r["nights"], -(r["weekend"] + r["hol"]), r["dep"]))
    return {"top": rows[:top], "per_nights": [per_n[k] for k in sorted(per_n)]}


def fmt(d: date) -> str:
    days = "שני שלישי רביעי חמישי שישי שבת ראשון".split()
    return f"{days[d.weekday()]} {d.day}/{d.month}"


if __name__ == "__main__":
    today = date.today()
    for h in upcoming(today):
        print(f"\n{h.name} ({h.key}): יציאה {fmt(h.dep[0])} עד {fmt(h.dep[1])}")
        for d in sorted(h.labels):
            print(f"   {fmt(d)}/{d.year}: {h.labels[d]}")
        b = best_spread(h)
        print("  הכי חסכוני בימי חופש:")
        for r in b["top"]:
            print(f"   {fmt(r['dep'])} -> {fmt(r['ret'])}: {r['nights']} לילות, {r['vac']} ימי חופש"
                  + (f" ({', '.join(r['notes'])})" if r["notes"] else ""))
        print("  לפי אורך:")
        for r in b["per_nights"]:
            print(f"   {r['nights']} לילות: {fmt(r['dep'])} -> {fmt(r['ret'])}, {r['vac']} ימי חופש")
