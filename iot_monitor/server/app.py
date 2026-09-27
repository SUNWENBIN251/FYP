# -*- coding: utf-8 -*-
"""Flask backend: sensor ingestion, dashboard queries, CSV export, thresholds.

Run from server/:  python app.py
Serves the frontend from static/ and the JSON/CSV APIs under /api/*.
"""
import csv
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, Response

import config
import database
import alerts
import backup
import batch
import hive

app = Flask(__name__, static_folder="static")
_csv_lock = threading.Lock()

database.init_db()


def _backup_loop():
    """Back up the database and CSVs at startup, then every BACKUP_INTERVAL_HOURS."""
    interval = getattr(config, "BACKUP_INTERVAL_HOURS", 24) * 3600
    if interval <= 0:
        return
    while True:
        try:
            backup.run_backup()
        except Exception as e:
            print("backup failed:", e)
        time.sleep(interval)


threading.Thread(target=_backup_loop, daemon=True).start()


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_csv(sensor_id, temperature, humidity, ts):
    with _csv_lock:
        first = not os.path.exists(config.CSV_PATH)
        with open(config.CSV_PATH, "a", newline="") as f:
            writer = csv.writer(f)
            if first:
                writer.writerow(["timestamp", "sensor_id", "temperature_c", "humidity_rh"])
            writer.writerow([ts, sensor_id, temperature, humidity])


def _normalize_dt(s, is_end=False):
    """Parse a 'YYYY-MM-DDTHH:MM' value from a datetime-local input into a
    comparable ISO UTC string.

    The browser sends local wall-clock with no offset, while every stored
    timestamp is UTC, so the value has to be converted — without this, a range
    picked in the UI is off by the machine's UTC offset.
    """
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    if is_end:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/reading", methods=["POST"])
def reading():
    data = request.get_json(silent=True) or {}
    sensor_id = data.get("sensor_id")
    temperature = data.get("temperature")
    humidity = data.get("humidity")
    if not sensor_id or temperature is None or humidity is None:
        return jsonify({"error": "sensor_id, temperature and humidity are required"}), 400
    try:
        temperature = float(temperature)
        humidity = float(humidity)
    except (TypeError, ValueError):
        return jsonify({"error": "temperature and humidity must be numbers"}), 400

    # apply per-sensor calibration offsets, so the stored value is the corrected one
    t_off, h_off = database.get_calibration(sensor_id)
    temperature = round(temperature + t_off, 2)
    humidity = round(humidity + h_off, 2)

    ts = database.insert_reading(sensor_id, temperature, humidity, data.get("ts"))
    _append_csv(sensor_id, temperature, humidity, ts)
    alerted = alerts.handle_reading(sensor_id, temperature, humidity)
    return jsonify({"ok": True, "ts": ts, "alerted": alerted})


def _sensor_trend(sensor, minutes):
    """Change in temperature/humidity against the reading `minutes` earlier.

    Used by the dashboard to describe the direction of travel in words,
    not only as a line chart.
    """
    ts = sensor.get("ts")
    if not ts:
        return None
    try:
        base = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") - timedelta(minutes=minutes)
    except (ValueError, TypeError):
        return None
    prev = database.reading_at_or_before(base.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                         sensor["sensor_id"])
    if prev is None:
        return None
    return {
        "minutes": minutes,
        "dt": round(sensor["temperature"] - prev["temperature"], 2),
        "dh": round(sensor["humidity"] - prev["humidity"], 2),
    }


@app.route("/api/latest")
def latest():
    window = request.args.get("window", 60, type=int)
    sensors = database.get_latest()
    for s in sensors:
        s["trend"] = _sensor_trend(s, window)
    now = _now_iso()
    trend_points = [
        {"sensor_id": s["sensor_id"], "temperature": s["temperature"],
         "humidity": s["humidity"], "ts": now}
        for s in sensors
    ]
    return jsonify({
        "server_time": now,
        "thresholds": database.get_thresholds(),
        "sensors": sensors,
        "trend_points": trend_points,
    })


@app.route("/api/readings")
def readings():
    """Paginated history browsing: rows + total count + range summary."""
    start = _normalize_dt(request.args.get("start")) or "2000-01-01T00:00:00Z"
    end = _normalize_dt(request.args.get("end"), is_end=True) or "2100-01-01T00:00:00Z"
    sensor_id = request.args.get("sensor_id") or None
    limit = max(1, min(request.args.get("limit", 50, type=int), 500))
    offset = max(0, request.args.get("offset", 0, type=int))
    return jsonify({
        "rows": database.get_range_paged(start, end, sensor_id, limit, offset),
        "total": database.count_range(start, end, sensor_id),
        "summary": database.summary_range(start, end, sensor_id),
        "limit": limit,
        "offset": offset,
    })


@app.route("/api/daily")
def daily():
    """Per-day per-sensor aggregates for long-run browsing."""
    start = _normalize_dt(request.args.get("start")) or "2000-01-01T00:00:00Z"
    end = _normalize_dt(request.args.get("end"), is_end=True) or "2100-01-01T00:00:00Z"
    sensor_id = request.args.get("sensor_id") or None
    return jsonify({"days": database.daily_summary(start, end, sensor_id)})


@app.route("/api/trend")
def trend():
    hours = request.args.get("hours", 24, type=int)
    return jsonify({"points": database.get_trend(hours)})


@app.route("/api/calibration", methods=["GET", "POST"])
def calibration():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        sensor_id = data.get("sensor_id")
        if not sensor_id:
            return jsonify({"error": "sensor_id is required"}), 400
        t_off = float(data.get("temp_offset", 0) or 0)
        h_off = float(data.get("hum_offset", 0) or 0)
        database.set_calibration(sensor_id, t_off, h_off)
        return jsonify({"ok": True, "sensor_id": sensor_id,
                        "temp_offset": t_off, "hum_offset": h_off})
    return jsonify({"calibration": database.get_all_calibration()})


@app.route("/api/alerts")
def alerts_history():
    limit = request.args.get("limit", 50, type=int)
    return jsonify({"alerts": database.get_alerts(limit)})


@app.route("/api/history.csv")
def history_csv():
    start = _normalize_dt(request.args.get("start"))
    end = _normalize_dt(request.args.get("end"), is_end=True)
    sensor_id = request.args.get("sensor_id")
    rows = database.get_range(
        start or "2000-01-01T00:00:00Z",
        end or "2100-01-01T00:00:00Z",
        sensor_id,
    )
    lines = ["timestamp,sensor_id,temperature_c,humidity_rh"]
    for r in rows:
        lines.append("%s,%s,%.1f,%.1f" % (r["ts"], r["sensor_id"], r["temperature"], r["humidity"]))
    body = "\n".join(lines) + "\n"
    return Response(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="readings.csv"'},
    )


@app.route("/api/thresholds", methods=["GET", "POST"])
def thresholds():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        return jsonify(database.set_thresholds(data))
    return jsonify(database.get_thresholds())


@app.route("/api/batch")
def batch_status():
    """Watermark, running state and recent runs for the dashboard panel."""
    return jsonify(batch.get_panel_state())


@app.route("/api/batch/run", methods=["POST"])
def batch_start():
    """Start one batch and return immediately; the panel then polls /api/batch.

    A batch takes minutes, so it cannot be awaited inside the request. An empty
    window means "since the watermark"; `full` rebuilds every partition.
    """
    data = request.get_json(silent=True) or {}
    # from/to come from datetime-local inputs (local wall clock); from_iso/to_iso
    # are exact UTC bounds, used when processing a stored batch window
    if "from_iso" in data or "to_iso" in data:
        from_iso = data.get("from_iso") or None
        to_iso = data.get("to_iso") or None
    else:
        from_iso = _normalize_dt(data.get("from"))
        to_iso = _normalize_dt(data.get("to"))
    if from_iso and to_iso and from_iso >= to_iso:
        return jsonify({"error": "from must be earlier than to"}), 400

    batch_id = batch.start_batch(from_iso, to_iso, bool(data.get("full")))
    if batch_id is None:
        return jsonify({"error": "busy", "message": "a batch is already running"}), 409
    return jsonify({"ok": True, "batch_id": batch_id}), 202


# ── batch windows: user-defined time periods shown as cards ────
def _windows_with_stats():
    """Windows plus the numbers and last-run status their cards display."""
    thresholds = database.get_thresholds()
    runs = database.get_batches(500)
    out = []
    for w in database.get_windows():
        w["stats"] = database.summary_range(w["ts_from"], w["ts_to"]) or {}
        w["outliers"] = database.count_outliers(
            w["ts_from"], w["ts_to"], None,
            thresholds["temp_min"], thresholds["temp_max"],
            thresholds["humidity_min"], thresholds["humidity_max"])
        # windows are created and removed, never edited, so an exact match on
        # the run log's window identifies the last processing of this batch
        w["last_run"] = next(
            (r for r in runs
             if r["ts_from"] == w["ts_from"] and r["ts_to"] == w["ts_to"]), None)
        out.append(w)
    return out


@app.route("/api/batch/windows", methods=["GET", "POST"])
def batch_windows():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        from_iso = _normalize_dt(data.get("from"))
        to_iso = _normalize_dt(data.get("to"))
        if not from_iso or not to_iso:
            return jsonify({"error": "from and to are required"}), 400
        if from_iso >= to_iso:
            return jsonify({"error": "from must be earlier than to"}), 400
        name = (data.get("name") or "").strip()
        if not name:
            name = "%s → %s UTC" % (from_iso[5:16].replace("T", " "),
                                    to_iso[5:16].replace("T", " "))
        return jsonify({"ok": True, "window": database.insert_window(name, from_iso, to_iso)}), 201

    return jsonify({"windows": _windows_with_stats()})


@app.route("/api/batch/windows/<int:window_id>", methods=["DELETE"])
def batch_window_item(window_id):
    """Remove a window definition; already-processed data is left alone."""
    if not database.delete_window(window_id):
        return jsonify({"error": "no such window"}), 404
    return jsonify({"ok": True})


@app.route("/api/batch/windows/<int:window_id>/outliers")
def batch_window_outliers(window_id):
    """Readings in the window outside a temperature/humidity box.

    With no bounds in the query string the box is the alert thresholds — that
    is the panel's "show abnormal" button. Passing any of t_min/t_max/h_min/
    h_max runs a custom range query instead.
    """
    window = database.get_window(window_id)
    if window is None:
        return jsonify({"error": "no such window"}), 404

    def bound(param):
        raw = request.args.get(param)
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    t_min, t_max = bound("t_min"), bound("t_max")
    h_min, h_max = bound("h_min"), bound("h_max")
    if t_min is None and t_max is None and h_min is None and h_max is None:
        th = database.get_thresholds()
        t_min, t_max = th["temp_min"], th["temp_max"]
        h_min, h_max = th["humidity_min"], th["humidity_max"]

    sensor_id = request.args.get("sensor_id") or None
    limit = max(1, min(request.args.get("limit", 200, type=int), 1000))
    return jsonify({
        "rows": database.outliers_range(window["ts_from"], window["ts_to"], sensor_id,
                                        t_min, t_max, h_min, h_max, limit),
        "total": database.count_outliers(window["ts_from"], window["ts_to"], sensor_id,
                                         t_min, t_max, h_min, h_max),
        "bounds": {"t_min": t_min, "t_max": t_max, "h_min": h_min, "h_max": h_max},
        "limit": limit,
    })


@app.route("/api/batch/windows/<int:window_id>/readings")
def batch_window_readings(window_id):
    """Every reading inside the window, newest first and paged."""
    window = database.get_window(window_id)
    if window is None:
        return jsonify({"error": "no such window"}), 404
    sensor_id = request.args.get("sensor_id") or None
    limit = max(1, min(request.args.get("limit", 50, type=int), 500))
    offset = max(0, request.args.get("offset", 0, type=int))
    return jsonify({
        "rows": database.get_range_paged(window["ts_from"], window["ts_to"],
                                         sensor_id, limit, offset),
        "total": database.count_range(window["ts_from"], window["ts_to"], sensor_id),
        "limit": limit,
        "offset": offset,
    })


@app.route("/api/batch/windows/<int:window_id>/alerts")
def batch_window_alerts(window_id):
    """Alert and recovery events inside the window."""
    window = database.get_window(window_id)
    if window is None:
        return jsonify({"error": "no such window"}), 404
    sensor_id = request.args.get("sensor_id") or None
    limit = max(1, min(request.args.get("limit", 100, type=int), 500))
    return jsonify({"alerts": database.get_alerts_in(window["ts_from"], window["ts_to"],
                                                     sensor_id, limit)})


@app.route("/api/hive/report")
def hive_report():
    """Run one of the canned reports over the Spark-built Hive table.

    These answer questions the hot SQLite copy is not the right place for —
    whole-history trends, sensor drift, data completeness. Each costs a few
    seconds because it goes through beeline, so hive.py caches the result until
    the next batch run invalidates it.
    """
    name = request.args.get("name") or "trend"
    rows, error, cached = hive.report(name)
    if error:
        return jsonify({"error": error}), 503
    return jsonify({
        "name": name,
        "rows": rows,
        "cached": cached,
        "last_run": (database.get_batches(1) or [None])[0],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
