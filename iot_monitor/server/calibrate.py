# -*- coding: utf-8 -*-
"""Sensor calibration tool.

Procedure:
  1. Put the DHT22 next to a reference thermometer / hygrometer.
  2. Let it settle for a few minutes so both instruments read the same air.
  3. Run this tool with the reference readings:

       python calibrate.py --sensor dht22-01 --ref-temp 25.4 --ref-hum 48.0

  The tool averages the sensor's most recent readings, computes the offset
  (reference - measured), and stores it. From then on the back end adds the
  offset to every incoming reading for that sensor, so stored values are the
  corrected ones.

  Omit --ref-temp or --ref-hum to calibrate only one quantity.
  List current offsets:  python calibrate.py --show
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timezone

import config
import database


def recent_mean(sensor_id, n):
    """Mean (temperature, humidity) over the sensor's last n readings."""
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT temperature, humidity FROM readings WHERE sensor_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (sensor_id, int(n)),
        ).fetchall()
    if not rows:
        return None
    t = sum(r["temperature"] for r in rows) / len(rows)
    h = sum(r["humidity"] for r in rows) / len(rows)
    return t, h


def main():
    ap = argparse.ArgumentParser(description="DHT22 calibration tool")
    ap.add_argument("--sensor", help="sensor id, e.g. dht22-01")
    ap.add_argument("--ref-temp", type=float, default=None,
                    help="reference temperature in C")
    ap.add_argument("--ref-hum", type=float, default=None,
                    help="reference relative humidity in %%RH")
    ap.add_argument("--samples", type=int, default=5,
                    help="how many recent readings to average (default 5)")
    ap.add_argument("--show", action="store_true", help="list current offsets")
    args = ap.parse_args()

    if args.show:
        rows = database.get_all_calibration()
        if not rows:
            print("No calibration offsets set (all sensors use 0/0).")
        for r in rows:
            print("  %-12s temp %+.2f C   humidity %+.2f %%RH"
                  % (r["sensor_id"], r["temp_offset"], r["hum_offset"]))
        return

    if not args.sensor:
        ap.error("--sensor is required (or use --show)")

    measured = recent_mean(args.sensor, args.samples)
    if measured is None:
        print("No readings found for sensor '%s' yet." % args.sensor)
        sys.exit(1)
    m_t, m_h = measured
    print("sensor %s: mean of last %d readings = %.2f C / %.2f %%RH"
          % (args.sensor, args.samples, m_t, m_h))

    cur_t, cur_h = database.get_calibration(args.sensor)
    # strip existing offset from the measurement before recomputing
    base_t = m_t - cur_t
    base_h = m_h - cur_h

    new_t = cur_t if args.ref_temp is None else round(args.ref_temp - base_t, 2)
    new_h = cur_h if args.ref_hum is None else round(args.ref_hum - base_h, 2)
    database.set_calibration(args.sensor, new_t, new_h)

    print("reference            = %s / %s"
          % (args.ref_temp if args.ref_temp is not None else "-",
             args.ref_hum if args.ref_hum is not None else "-"))
    print("offsets saved        = temp %+.2f C   humidity %+.2f %%RH"
          % (new_t, new_h))
    print("corrected reading    = %.2f C / %.2f %%RH" % (m_t + (new_t - cur_t),
                                                         m_h + (new_h - cur_h)))
    print("done.")


if __name__ == "__main__":
    main()
