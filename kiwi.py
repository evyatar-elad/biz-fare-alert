"""Second price source: Kiwi.com public MCP server (https://mcp.kiwi.com, no key).

Why: Google Flights misses airlines that do not publish through fares to Google
(found 6/11: Uzbekistan Airways TLV-TAS-BKK). Kiwi.com has them, including business,
and its search takes a date range plus a range of nights, so one request answers
"cheapest business round trip in this month, any stay of 7-21 nights".
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.request

import config as C

URL = "https://mcp.kiwi.com"


class KiwiError(Exception):
    pass


def _ctx():
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("FLI_CA_BUNDLE")
    return ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()


class Client:
    def __init__(self):
        self.sid = None
        self.n = 0
        self._call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                  "clientInfo": {"name": "biz-fare-alert", "version": "1"}})
        self._call("notifications/initialized", None, notify=True)

    def _call(self, method, params, notify=False):
        self.n += 1
        body = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = self.n
        if params is not None:
            body["params"] = params
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["mcp-session-id"] = self.sid
        req = urllib.request.Request(URL, json.dumps(body).encode(), h)
        try:
            r = urllib.request.urlopen(req, context=_ctx(), timeout=120)
        except Exception as e:  # HTTP 429 / network
            raise KiwiError(str(e)) from e
        self.sid = r.headers.get("mcp-session-id") or self.sid
        txt = r.read().decode("utf-8", "replace")
        if notify:
            return None
        for line in txt.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:])
        return json.loads(txt) if txt.strip().startswith("{") else None

    def search(self, **args) -> list[dict]:
        r = self._call("tools/call", {"name": "search-flight", "arguments": args})
        res = (r or {}).get("result") or {}
        if res.get("isError"):
            raise KiwiError(json.dumps(res)[:300])
        c = res.get("structuredContent")
        if not c and res.get("content"):
            try:
                c = json.loads(res["content"][0]["text"])
            except (json.JSONDecodeError, KeyError, IndexError):
                raise KiwiError(str(res["content"])[:300])
        if (c or {}).get("error"):
            raise KiwiError(str(c["error"])[:300])
        return (c or {}).get("itineraries") or []


def ddmmyyyy(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"


def search_month(client: Client, t: dict) -> list[dict]:
    """Cheapest business round trips leaving in [from..to], any stay in the region's nights range.
    Returns points like Google's calendar: departure_date, return_date, price (+ itinerary)."""
    lo, hi = C.KIWI_NIGHTS[t["region"]]
    args = {
        "flyFrom": t["origin"], "flyTo": t["dest"],
        "departureDate": ddmmyyyy(t["from"]), "departureDateTo": ddmmyyyy(t["to"]),
        "nights_in_dst_from": lo, "nights_in_dst_to": hi,
        "cabinClass": "C", "currency": "USD", "adults": 1,
        "max_sector_stopovers": 2,
        "exclude_stopover_airports": ",".join(sorted(C.BANNED_AIRPORTS)),
    }
    if t.get("airline"):
        args["select_airlines"] = t["airline"]
    else:
        args["exclude_airlines"] = ",".join(C.EXCLUDE_AIRLINES)
    if t["dest"] in C.NONSTOP_ONLY:
        args["max_sector_stopovers"] = 0
    pts = []
    for it in client.search(**args):
        out, back = it.get("outbound") or {}, it.get("inbound") or it.get("return") or {}
        if not out.get("departureTime") or not back.get("departureTime") or not it.get("price"):
            continue
        pts.append({"departure_date": out["departureTime"][:10], "return_date": back["departureTime"][:10],
                    "price": float(it["price"]), "itin": it})
    return pts


def details_from_itin(it: dict) -> dict:
    """Same shape as scanner.details(), built from the Kiwi itinerary (no extra request)."""
    tickets = {p.rsplit("_", 1)[0] for p in str(it.get("id", "")).split("|") if p}

    def seg_info(side):
        segs = side.get("segments") or []
        return {
            "stops": side.get("stops", max(0, len(segs) - 1)),
            "via": [s.get("to") for s in segs[:-1]],
            "airlines": sorted({s.get("carrierName") or s.get("carrier") or "?" for s in segs}),
            "hours": round((side.get("durationSeconds") or 0) / 3600, 1),
            "mixed_cabin": any((s.get("cabinClass") or "").lower() != "business" for s in segs),
            "legs": [{
                "from": s.get("from"), "to": s.get("to"),
                "airline": s.get("carrierName") or s.get("carrier") or "?",
                "flight": s.get("flightNumber"), "aircraft": None, "seat": None,
                "hours": round((s.get("durationSeconds") or 0) / 3600, 1),
            } for s in segs],
        }
    return {"price": it.get("price"), "out": seg_info(it.get("outbound") or {}),
            "ret": seg_info(it.get("inbound") or it.get("return") or {}),
            "separate_tickets": len(tickets) > 1, "booking_url": it.get("bookingUrl")}
