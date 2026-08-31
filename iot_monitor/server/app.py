# -*- coding: utf-8 -*-
"""Flask backend: sensor ingestion, dashboard queries, CSV export, thresholds.

Run from server/:  python app.py
Serves the frontend from static/ and the JSON/CSV APIs under /api/*.
"""
import csv
import os
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, request, Response

import config
import database

app = Flask(__name__, static_folder="static")
_csv_lock = threading.Lock()

database.init_db()


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
    """Parse 'YYYY-MM-DDTHH:MM' and return a comparable ISO UTC string."""
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    if is_end:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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

    ts = database.insert_reading(sensor_id, temperature, humidity, data.get("ts"))
    _append_csv(sensor_id, temperature, humidity, ts)
    return jsonify({"ok": True, "ts": ts})


@app.route("/api/latest")
def latest():
    sensors = database.get_latest()
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


@app.route("/api/trend")
def trend():
    hours = request.args.get("hours", 24, type=int)
    return jsonify({"points": database.get_trend(hours)})


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
