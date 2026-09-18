# -*- coding: utf-8 -*-
"""Demo data feeder.

Posts a smooth, plausible trend to the backend so the dashboard can be
demonstrated without the Raspberry Pi. It is NOT part of the production
data path -- the real data comes from collector.py on the Pi.

What it does:
  1. Backfills the last 90 minutes at 1-minute intervals, with a clear
     trend (temperature rising 24 -> 27 C, humidity falling 62 -> 48 %RH),
     so the trend badges and the Trend Summary have something to describe.
  2. Then keeps posting a new reading every few seconds, continuing the
     trend, so the live dashboard visibly updates.

Usage:
    python simulate_feed.py                 # backfill + live (default)
    python simulate_feed.py --live-only     # skip the backfill
    python simulate_feed.py --interval 3    # live posting every 3 s
    python simulate_feed.py --once          # post one reading then exit
Stop with Ctrl+C.
"""
import argparse
import json
import math
import random
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

API = "http://localhost:5000/api/reading"
SENSORS = ("dht22-01", "dht22-02")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def pattern(frac, offset):
    """Smooth values for a given progress through the demo (0 -> 1)."""
    t = 24.0 + 3.0 * frac + offset + random.uniform(-0.15, 0.15)
    h = 62.0 - 14.0 * frac + offset * 2 + random.uniform(-0.6, 0.6)
    return round(t, 1), round(h, 1)


def post(sensor_id, temperature, humidity, ts=None):
    body = {"sensor_id": sensor_id, "temperature": temperature, "humidity": humidity}
    if ts:
        body["ts"] = ts
    req = Request(API, data=json.dumps(body).encode("utf-8"),
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as resp:
        return resp.status == 200


def main():
    ap = argparse.ArgumentParser(description="Demo data feeder")
    ap.add_argument("--live-only", action="store_true", help="skip the backfill")
    ap.add_argument("--once", action="store_true", help="post one reading and exit")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="seconds between live readings (default 5)")
    ap.add_argument("--backfill-min", type=int, default=90,
                    help="minutes of history to backfill (default 90)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)

    if args.once:
        t, h = pattern(1.0, 0)
        for sid in SENSORS:
            print(sid, post(sid, t, h) and "sent" or "failed")
        return

    if not args.live_only:
        n = args.backfill_min
        print("Backfilling the last %d minutes ..." % n)
        for i in range(n, -1, -1):
            frac = (n - i) / float(n)
            ts = iso(now - timedelta(minutes=i))
            for k, sid in enumerate(SENSORS):
                t, h = pattern(frac, k * 0.25)
                try:
                    post(sid, t, h, ts)
                except Exception as e:
                    print("  backfill error:", e)
        print("  backfilled %d readings per sensor" % (n + 1))

    print("Live posting every %.0fs (Ctrl+C to stop) ..." % args.interval)
    step = 0
    try:
        while True:
            # continue rising slowly, with a gentle wave so change is visible
            frac = min(1.0, 1.0 + step * 0.002)
            wobble = 0.4 * math.sin(step / 12.0)
            for k, sid in enumerate(SENSORS):
                t, h = pattern(frac, k * 0.25 + wobble)
                try:
                    post(sid, t, h)
                    print("  sent %s %.1f C %.1f %%RH" % (sid, t, h))
                except Exception as e:
                    print("  send error:", e)
            step += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nfeeder stopped")


if __name__ == "__main__":
    main()
