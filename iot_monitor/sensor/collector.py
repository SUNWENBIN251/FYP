#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Raspberry Pi sensor collector.

Reads DHT22 sensors every INTERVAL seconds and POSTs readings to the Flask
backend at /api/reading. If the network/backend is unreachable, readings are
buffered to a local CSV and re-sent once connectivity recovers, to protect the
>=99% capture-rate objective.

Run modes:
  SIMULATE=1 (default)  -> generate simulated temperature/humidity (for testing
                           on a PC without hardware).
  SIMULATE=0            -> read real DHT22 sensors via adafruit-circuitpython-dht.

Environment variables:
  SERVER_URL   backend base URL, default http://localhost:5000
  INTERVAL     seconds between cycles, default 60
  SIMULATE     "1" to simulate, "0" for real sensors
  SENSOR_IDS   comma-separated sensor ids, default dht22-01,dht22-02
  GPIO_PINS    comma-separated GPIO pins matching SENSOR_IDS, default 4,17
"""
import csv
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:5000")
API_URL = SERVER_URL.rstrip("/") + "/api/reading"
INTERVAL = int(os.environ.get("INTERVAL", 60))
SIMULATE = os.environ.get("SIMULATE", "1") == "1"
SENSOR_IDS = [s.strip() for s in os.environ.get("SENSOR_IDS", "dht22-01,dht22-02").split(",") if s.strip()]
GPIO_PINS = [int(p) for p in os.environ.get("GPIO_PINS", "4,17").split(",") if p.strip()]
BUFFER_FILE = os.path.join(BASE_DIR, "offline_buffer.csv")

_dht_instances = {}


def _iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── sensor reading ─────────────────────────────────────────────
def read_sensors():
    """Return list of (sensor_id, temperature, humidity)."""
    return _simulate() if SIMULATE else _read_real()


def _simulate():
    hour = datetime.now().hour
    t_base = 23 + 2 * math.sin((hour - 6) / 24 * 2 * math.pi)
    h_base = 50 + 8 * math.sin((hour + 4) / 24 * 2 * math.pi)
    out = []
    for sid in SENSOR_IDS:
        t = t_base + random.uniform(-0.5, 0.5)
        h = h_base + random.uniform(-2.0, 2.0)
        out.append((sid, round(t, 1), round(h, 1)))
    return out


def _get_dht(pin):
    import adafruit_dht
    import board
    if pin not in _dht_instances:
        _dht_instances[pin] = adafruit_dht.DHT22(getattr(board, "D%d" % pin))
    return _dht_instances[pin]


def _read_real():
    out = []
    for sid, pin in zip(SENSOR_IDS, GPIO_PINS):
        dht = _get_dht(pin)
        try:
            t = dht.temperature
            h = dht.humidity
            if t is not None and h is not None:
                out.append((sid, round(t, 1), round(h, 1)))
        except RuntimeError:
            pass  # DHT22 occasionally returns invalid reads; skip this cycle
    return out


# ── upload + offline buffer ────────────────────────────────────
def post_reading(sensor_id, temperature, humidity):
    payload = json.dumps({
        "sensor_id": sensor_id,
        "temperature": temperature,
        "humidity": humidity,
    }).encode("utf-8")
    req = Request(API_URL, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as resp:
        return resp.status == 200


def buffer_local(sensor_id, temperature, humidity):
    with open(BUFFER_FILE, "a", newline="") as f:
        csv.writer(f).writerow([_iso_now(), sensor_id, temperature, humidity])


def flush_buffer():
    if not os.path.exists(BUFFER_FILE):
        return
    with open(BUFFER_FILE, "r", newline="") as f:
        rows = [r for r in csv.reader(f) if len(r) == 4]
    kept = []
    for ts, sid, t, h in rows:
        try:
            if post_reading(sid, float(t), float(h)):
                continue
        except Exception:
            pass
        kept.append([ts, sid, t, h])
    if kept:
        with open(BUFFER_FILE, "w", newline="") as f:
            csv.writer(f).writerows(kept)
    else:
        try:
            os.remove(BUFFER_FILE)
        except OSError:
            pass


def main():
    print("collector started | server:", API_URL, "| simulate:", SIMULATE,
          "| sensors:", SENSOR_IDS, "| interval:", INTERVAL, "s")
    while True:
        try:
            for sid, t, h in read_sensors():
                try:
                    if post_reading(sid, t, h):
                        print("%s sent %s %.1f C %.1f%%" % (_iso_now(), sid, t, h))
                        continue
                except Exception:
                    pass
                buffer_local(sid, t, h)
                print("%s %s buffered (upload failed)" % (_iso_now(), sid))
            flush_buffer()
        except Exception as e:
            print("cycle error:", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ncollector stopped")
