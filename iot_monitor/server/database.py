# -*- coding: utf-8 -*-
"""SQLite data layer for the monitoring backend.

Uses WAL mode with short-lived connections so Flask can read and write
concurrently. Timestamps are stored as ISO-8601 UTC strings; being a fixed
format, lexicographic order equals chronological order, so the ts index works
for range queries.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

try:
    from . import config
except ImportError:  # allow running as a plain script from server/
    import config

ALLOWED_THRESHOLDS = ("temp_min", "temp_max", "humidity_min", "humidity_max")


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db():
    config.ensure_data_dir()
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS readings (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   sensor_id TEXT NOT NULL,
                   temperature REAL NOT NULL,
                   humidity REAL NOT NULL,
                   ts TEXT NOT NULL
               );"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_sensor_ts ON readings(sensor_id, ts);")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS thresholds (
                   id INTEGER PRIMARY KEY CHECK (id = 1),
                   temp_min REAL, temp_max REAL,
                   humidity_min REAL, humidity_max REAL
               );"""
        )
        cur = conn.execute("SELECT id FROM thresholds WHERE id = 1")
        if cur.fetchone() is None:
            t = config.DEFAULT_THRESHOLDS
            conn.execute(
                "INSERT INTO thresholds (id, temp_min, temp_max, humidity_min, humidity_max) "
                "VALUES (1, ?, ?, ?, ?)",
                (t["temp_min"], t["temp_max"], t["humidity_min"], t["humidity_max"]),
            )


def insert_reading(sensor_id, temperature, humidity, ts=None):
    ts = ts or _now_iso()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO readings (sensor_id, temperature, humidity, ts) VALUES (?, ?, ?, ?)",
            (sensor_id, float(temperature), float(humidity), ts),
        )
    return ts


def get_latest():
    """Latest reading per sensor (one row per sensor, by newest insert)."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT r.sensor_id, r.temperature, r.humidity, r.ts
               FROM readings r
               WHERE r.id IN (SELECT MAX(id) FROM readings GROUP BY sensor_id)
               ORDER BY r.sensor_id;"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_readings_since(ts_min):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sensor_id, temperature, humidity, ts FROM readings "
            "WHERE ts >= ? ORDER BY ts",
            (ts_min,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_trend(hours=24):
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return get_readings_since(start)


def get_range(start_iso, end_iso, sensor_id=None):
    query = (
        "SELECT sensor_id, temperature, humidity, ts FROM readings "
        "WHERE ts BETWEEN ? AND ?"
    )
    params = [start_iso, end_iso]
    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)
    query += " ORDER BY ts"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_thresholds():
    with _connect() as conn:
        row = conn.execute(
            "SELECT temp_min, temp_max, humidity_min, humidity_max FROM thresholds WHERE id = 1"
        ).fetchone()
    return dict(row) if row else dict(config.DEFAULT_THRESHOLDS)


def set_thresholds(updates):
    current = get_thresholds()
    for k in ALLOWED_THRESHOLDS:
        if k in updates and updates[k] is not None:
            current[k] = float(updates[k])
    with _connect() as conn:
        conn.execute(
            "UPDATE thresholds SET temp_min=?, temp_max=?, humidity_min=?, humidity_max=? WHERE id = 1",
            (current["temp_min"], current["temp_max"], current["humidity_min"], current["humidity_max"]),
        )
    return current
