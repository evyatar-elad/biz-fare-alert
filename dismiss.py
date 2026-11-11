"""Remove a deal from the status page (and from the pending digest) by request.

Called by .github/workflows/dismiss.yml when the repo owner opens an issue titled
"dismiss: <route key>" (the "הסר" buttons on the status page open such an issue).
The route stays in alerts.json with "dismissed": true, so it is hidden and is not
alerted again unless the price drops by REALERT_DROP or more.
"""
import sys

import scanner


def main(key: str) -> int:
    key = key.strip()
    state = scanner.load(scanner.STATE_F, {"last": {}})
    alerts = scanner.load(scanner.ALERTS_F, {})
    hit = False
    if key in alerts:
        alerts[key]["dismissed"] = True
        hit = True
    before = len(state.get("pending", []))
    state["pending"] = [d for d in state.get("pending", []) if d["route"] != key]
    hit = hit or len(state["pending"]) < before
    scanner.save(scanner.ALERTS_F, alerts)
    scanner.save(scanner.STATE_F, state)
    print("removed" if hit else "not found", key)
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
