"""Multi-city search through the fli library (the `fli multi` CLI has no JSON output).

Used for open jaw (TLV->KIX, NRT->TLV) and stopovers (TLV->TAS, TAS->BKK, BKK->TLV).
Google prices the whole multi-city trip on the LAST leg.
Prints one JSON line: {"success": bool, "trips": [{"price", "legs": [...]}, ...]}.

Usage: python fli_multi.py ECONOMY TLV,KIX,2027-04-16 NRT,TLV,2027-05-01 [--exclude TK,QR]
"""
from __future__ import annotations

import json
import sys


def search(cabin: str, legs: list[tuple[str, str, str]], exclude: list[str] | None = None, top_n: int = 2) -> dict:
    """top_n: how many options of each leg Google expands (each one is another request).
    The library default is 5; 2 keeps a 4-leg search to a few requests (12/11: slow runs)."""
    from fli.core import build_multi_city_segments, parse_airlines, parse_cabin_class, resolve_airport
    from fli.models import FlightSearchFilters, PassengerInfo
    from fli.search import SearchFlights

    parsed = [(resolve_airport(a), resolve_airport(b), d) for a, b, d in legs]
    segments, trip_type = build_multi_city_segments(legs=parsed)
    excl = []
    for code in exclude or []:
        try:
            excl += parse_airlines([code]) or []
        except Exception:  # airline unknown to fli
            pass
    kw = {}
    if excl:
        kw["airlines_exclude"] = excl
    filters = FlightSearchFilters(trip_type=trip_type, passenger_info=PassengerInfo(adults=1),
                                  flight_segments=segments, seat_type=parse_cabin_class(cabin), **kw)
    res = SearchFlights().search(filters, top_n=top_n, currency="USD") or []
    trips = []
    for r in res:
        segs = list(r) if isinstance(r, tuple) else [r]
        price = segs[-1].price or max((s.price or 0) for s in segs)
        if not price:
            continue
        trips.append({
            "price": price,
            "legs": [{
                "stops": s.stops, "hours": round((s.duration or 0) / 60, 1),
                "flights": [{
                    "from": getattr(l.departure_airport, "name", str(l.departure_airport)),
                    "to": getattr(l.arrival_airport, "name", str(l.arrival_airport)),
                    "airline": getattr(l.airline, "value", str(l.airline)),
                    "flight": l.flight_number,
                    "dep": l.departure_datetime.isoformat() if l.departure_datetime else None,
                    "arr": l.arrival_datetime.isoformat() if l.arrival_datetime else None,
                } for l in s.legs],
            } for s in segs],
        })
    trips.sort(key=lambda t: t["price"])
    return {"success": True, "trips": trips}


if __name__ == "__main__":
    args = sys.argv[1:]
    exclude = []
    if "--exclude" in args:
        i = args.index("--exclude")
        exclude = args[i + 1].split(",")
        del args[i:i + 2]
    try:
        out = search(args[0], [tuple(x.split(",")) for x in args[1:]], exclude)
    except Exception as e:  # noqa: BLE001
        out = {"success": False, "error": f"{type(e).__name__}: {e}"[:400]}
    print(json.dumps(out, ensure_ascii=False))
