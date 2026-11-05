"""Offline test: fake Google answers, check deal detection, dedupe and email text."""
import json, random, shutil, tempfile
from datetime import date, timedelta
from pathlib import Path
import scanner, config as C

def fake_fli(args, timeout=180):
    if args[0] == "flights":
        return {"success": True, "flights": [{"price": 1300, "outbound": {"stops": 1, "duration": 900, "legs": [
            {"arrival_airport": {"code": "GYD"}, "airline": {"name": "Azerbaijan Airlines"}},
            {"arrival_airport": {"code": "PEK"}, "airline": {"name": "Azerbaijan Airlines"}}]},
            "return": {"stops": 1, "duration": 960, "mixed_cabin": True, "legs": [
            {"arrival_airport": {"code": "GYD"}, "airline": {"name": "Azerbaijan Airlines"}},
            {"arrival_airport": {"code": "TLV"}, "airline": {"name": "Azerbaijan Airlines"}}]}}]}
    o, d, f, t = args[1], args[2], args[4], args[6]
    dur = int(args[9]); start = date.fromisoformat(f); end = date.fromisoformat(t)
    out = []; i = 0
    while start + timedelta(i) <= end:
        dep = start + timedelta(i)
        p = 4500 + random.randint(-300, 300)
        if d == "PEK" and o == "TLV" and SPIKE and 10 <= i <= 14: p = 1250   # the AZAL style promo
        out.append({"departure_date": dep.isoformat(), "return_date": (dep + timedelta(dur)).isoformat(), "price": p})
        i += 1
    return {"success": True, "dates": out}

tmp = Path(tempfile.mkdtemp())
scanner.DATA = tmp; scanner.STATE_F = tmp/"state.json"; scanner.HIST_F = tmp/"history.json"
scanner.ALERTS_F = tmp/"alerts.json"; scanner.LOG_F = tmp/"runs.jsonl"
scanner.fli = fake_fli; C.PACE_SECONDS = 0; C.KIWI_ENABLED = False
import sys
def run(extra=()):
    sys.argv = ["scanner.py", "--only", "PEK,DPS", "--dry-run", *extra]; scanner.main()

SPIKE = False; run()                                  # day 1: normal prices, builds history
st = json.loads((tmp/"state.json").read_text()); st["last"] = {}; st["last_email"] = "2099-01-01T00:00:00+00:00"
(tmp/"state.json").write_text(json.dumps(st))
SPIKE = True; print("\n===== with promo ====="); run()      # promo appears -> email
st = json.loads((tmp/"state.json").read_text()); st["last"] = {}; (tmp/"state.json").write_text(json.dumps(st))
print("\n===== same promo again (must NOT email) ====="); run()
shutil.rmtree(tmp)
