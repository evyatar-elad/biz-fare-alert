"""Offline test: fake Google answers, check deal detection, dedupe and email text."""
import json, random, shutil, tempfile
from datetime import date, timedelta
from pathlib import Path
import scanner, digest, config as C

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
def fake_multi(cabin, legs):   # one-ticket stopover: DPS via Baku under the Asia cap, others dearer
    hub = legs[0][1]
    price = 1500 if (legs[1][1] == "DPS" and hub == "GYD") else 5200
    return [{"price": price, "legs": [{"hours": 4, "flights": [{"from": a, "to": b, "airline": "Azerbaijan Airlines"}]}
                                      for a, b, _ in legs]}]
scanner.multi = fake_multi
import sys
import notify
_orig_send = notify._send
notify._send = lambda subj, body, dry: (print("---- SENT ----", subj), True)[1]
digest.DATA = tmp; digest.NEWS_F = tmp/"news.json"; digest.STATS_F = tmp/"stats.json"
def run(extra=()):
    sys.argv = ["scanner.py", "--only", "PEK,DPS", "--dry-run", *extra]; scanner.main()
    digest.main(dry_run=False, force=True)   # "sends" (no SMTP secrets = printed) and clears pending

SPIKE = False; run()                                  # day 1: normal prices, builds history
st1 = json.loads((tmp/"state.json").read_text())
assert st1["stops"]["DPS"]["GYD"]["price"] == 1500, st1.get("stops")   # stopover found and kept
assert any(k.startswith("STOP-TLV-DPS-GYD") for k in json.loads((tmp/"alerts.json").read_text())), "stopover deal not sent"
h = json.loads((tmp/"history.json").read_text())   # pretend day 1 was two past days
for rk in h:
    for m in h[rk]:
        row = h[rk][m][0]; h[rk][m] = [["2000-01-01"] + row[1:], ["2000-01-02"] + row[1:]]
(tmp/"history.json").write_text(json.dumps(h))
st = json.loads((tmp/"state.json").read_text()); st["last"] = {}; st["last_email"] = "2099-01-01T00:00:00+00:00"
(tmp/"state.json").write_text(json.dumps(st))
SPIKE = True; print("\n===== with promo ====="); run()      # promo appears -> email
st = json.loads((tmp/"state.json").read_text()); st["last"] = {}; (tmp/"state.json").write_text(json.dumps(st))
print("\n===== same promo again (must NOT email) ====="); run()
shutil.rmtree(tmp)

# status page must build with the real data files (11/11: a crash froze it for a day)
import status
status.OUT = tmp / "index.html"   # never overwrite the real docs/index.html (11/11: it did, with empty test data)
status.main()
print("STATUS_PAGE_OK")
