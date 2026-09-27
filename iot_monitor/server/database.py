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
            """CREATE TABLE IF NOT EXISTS alerts (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   sensor_id TEXT NOT NULL,
                   condition TEXT NOT NULL,
                   value REAL,
                   threshold REAL,
                   kind TEXT NOT NULL,
                   ts TEXT NOT NULL
               );"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS calibration (
                   sensor_id TEXT PRIMARY KEY,
                   temp_offset REAL NOT NULL DEFAULT 0,
                   hum_offset  REAL NOT NULL DEFAULT 0
               );"""
        )
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
        conn.execute(
            """CREATE TABLE IF NOT EXISTS batches (
                   batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                   status TEXT NOT NULL,
                   ts_from TEXT, ts_to TEXT,
                   rows_in INTEGER, rows_out INTEGER,
                   partitions TEXT,
                   started_at TEXT NOT NULL,
                   finished_at TEXT,
                   duration_s REAL,
                   error TEXT
               );"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_batches_started ON batches(started_at);")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS batch_state (
                   id INTEGER PRIMARY KEY CHECK (id = 1),
                   watermark TEXT
               );"""
        )
        cur = conn.execute("SELECT id FROM batch_state WHERE id = 1")
        if cur.fetchone() is None:
            conn.execute("INSERT INTO batch_state (id) VALUES (1)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS batch_windows (
                   window_id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL,
                   ts_from TEXT NOT NULL,
                   ts_to TEXT NOT NULL,
                   created_at TEXT NOT NULL
               );"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_windows_from ON batch_windows(ts_from);")


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


def insert_alert(sensor_id, condition, value, threshold, kind, ts=None):
    """Record one alert or recovery event. kind is 'alert' or 'recovery'."""
    ts = ts or _now_iso()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO alerts (sensor_id, condition, value, threshold, kind, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sensor_id, condition, value, threshold, kind, ts),
        )
    return ts


def get_alerts(limit=50):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sensor_id, condition, value, threshold, kind, ts "
            "FROM alerts ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_calibration(sensor_id):
    """Return (temp_offset, hum_offset) for a sensor; (0, 0) if unset."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT temp_offset, hum_offset FROM calibration WHERE sensor_id = ?",
            (sensor_id,),
        ).fetchone()
    if row is None:
        return 0.0, 0.0
    return float(row["temp_offset"]), float(row["hum_offset"])


def get_all_calibration():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sensor_id, temp_offset, hum_offset FROM calibration ORDER BY sensor_id"
        ).fetchall()
    return [dict(r) for r in rows]


def set_calibration(sensor_id, temp_offset, hum_offset):
    """Upsert the calibration offsets for one sensor (applied at ingestion)."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO calibration (sensor_id, temp_offset, hum_offset) VALUES (?, ?, ?) "
            "ON CONFLICT(sensor_id) DO UPDATE SET temp_offset = excluded.temp_offset, "
            "hum_offset = excluded.hum_offset",
            (sensor_id, float(temp_offset), float(hum_offset)),
        )
    return get_calibration(sensor_id)


# ── history browsing ───────────────────────────────────────────
def count_range(start_iso, end_iso, sensor_id=None):
    query = "SELECT COUNT(*) AS n FROM readings WHERE ts BETWEEN ? AND ?"
    params = [start_iso, end_iso]
    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)
    with _connect() as conn:
        return conn.execute(query, params).fetchone()["n"]


def get_range_paged(start_iso, end_iso, sensor_id=None, limit=50, offset=0):
    """Newest-first page of readings within a range."""
    query = ("SELECT sensor_id, temperature, humidity, ts FROM readings "
             "WHERE ts BETWEEN ? AND ?")
    params = [start_iso, end_iso]
    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)
    query += " ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?"
    params += [int(limit), int(offset)]
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def summary_range(start_iso, end_iso, sensor_id=None):
    """Count and min/avg/max for temperature and humidity over a range."""
    query = ("SELECT COUNT(*) AS n, "
             "MIN(temperature) AS t_min, AVG(temperature) AS t_avg, MAX(temperature) AS t_max, "
             "MIN(humidity) AS h_min, AVG(humidity) AS h_avg, MAX(humidity) AS h_max "
             "FROM readings WHERE ts BETWEEN ? AND ?")
    params = [start_iso, end_iso]
    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)
    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
    return dict(row) if row else {}


def daily_summary(start_iso, end_iso, sensor_id=None):
    """Per-day per-sensor aggregates (min/avg/max) over a range."""
    query = ("SELECT SUBSTR(ts,1,10) AS day, sensor_id, COUNT(*) AS n, "
             "MIN(temperature) AS t_min, AVG(temperature) AS t_avg, MAX(temperature) AS t_max, "
             "MIN(humidity) AS h_min, AVG(humidity) AS h_avg, MAX(humidity) AS h_max "
             "FROM readings WHERE ts BETWEEN ? AND ?")
    params = [start_iso, end_iso]
    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)
    query += " GROUP BY SUBSTR(ts,1,10), sensor_id ORDER BY day DESC, sensor_id"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def reading_at_or_before(ts_iso, sensor_id):
    """Most recent reading at or before ts_iso (baseline for trend deltas)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT temperature, humidity, ts FROM readings "
            "WHERE sensor_id = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (sensor_id, ts_iso),
        ).fetchone()
    return dict(row) if row else None


# ── batch processing ───────────────────────────────────────────
def claim_batch(ts_from, ts_to):
    """Reserve the batch slot, or return None when a batch is already running.

    The single INSERT..SELECT..WHERE NOT EXISTS statement makes the
    check-and-insert atomic under SQLite's write serialisation, so two callers
    racing (two browser tabs, or a tab and the API) cannot both claim the slot.
    """
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO batches (status, ts_from, ts_to, started_at) "
            "SELECT 'running', ?, ?, ? "
            "WHERE NOT EXISTS (SELECT 1 FROM batches WHERE status = 'running')",
            (ts_from, ts_to, _now_iso()),
        )
        if cur.rowcount != 1:
            return None
        return cur.lastrowid


def finish_batch(batch_id, ok, rows_in=None, rows_out=None, partitions=None, error=None):
    """Close a batch row and stamp its duration."""
    finished = _now_iso()
    with _connect() as conn:
        row = conn.execute(
            "SELECT started_at FROM batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        duration = None
        if row and row["started_at"]:
            try:
                started = datetime.strptime(row["started_at"], "%Y-%m-%dT%H:%M:%SZ")
                ended = datetime.strptime(finished, "%Y-%m-%dT%H:%M:%SZ")
                duration = round((ended - started).total_seconds(), 2)
            except (ValueError, TypeError):
                duration = None
        conn.execute(
            "UPDATE batches SET status = ?, rows_in = ?, rows_out = ?, partitions = ?, "
            "finished_at = ?, duration_s = ?, error = ? WHERE batch_id = ?",
            ("success" if ok else "failed", rows_in, rows_out, partitions,
             finished, duration, error, batch_id),
        )
    return finished


def fail_stale_batches(cutoff_iso):
    """Fail batches still marked running since before cutoff.

    A killed WSL call or a backend crash would otherwise hold the slot forever,
    blocking every later batch. Returns how many rows were cleaned up.
    """
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE batches SET status = 'failed', error = 'timed out', finished_at = ? "
            "WHERE status = 'running' AND started_at < ?",
            (_now_iso(), cutoff_iso),
        )
        return cur.rowcount


def get_batches(limit=10):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT batch_id, status, ts_from, ts_to, rows_in, rows_out, partitions, "
            "started_at, finished_at, duration_s, error "
            "FROM batches ORDER BY batch_id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_running_batch():
    with _connect() as conn:
        row = conn.execute(
            "SELECT batch_id, ts_from, ts_to, started_at FROM batches "
            "WHERE status = 'running' ORDER BY batch_id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_batch_state():
    with _connect() as conn:
        row = conn.execute("SELECT watermark FROM batch_state WHERE id = 1").fetchone()
    return dict(row) if row else {}


def advance_watermark(ts_to):
    """Move the watermark forward, never backward. Only call after a success."""
    if not ts_to:
        return get_batch_state()
    with _connect() as conn:
        conn.execute(
            "UPDATE batch_state SET watermark = ? "
            "WHERE id = 1 AND (watermark IS NULL OR watermark < ?)",
            (ts_to, ts_to),
        )
    return get_batch_state()


def earliest_reading_ts():
    with _connect() as conn:
        row = conn.execute("SELECT MIN(ts) AS ts FROM readings").fetchone()
    return row["ts"] if row and row["ts"] else None


def get_range_for_export(start_iso, end_iso):
    """Readings in a batch window: strictly after start_iso, up to end_iso.

    Left-open so a reading on a batch boundary is never counted by two
    consecutive batches.
    """
    query = "SELECT sensor_id, temperature, humidity, ts FROM readings WHERE ts <= ?"
    params = [end_iso]
    if start_iso:
        query += " AND ts > ?"
        params.append(start_iso)
    query += " ORDER BY ts"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ── user-defined batch windows ─────────────────────────────────
# A window is a named time period the dashboard shows as one batch. It is a
# view onto the readings — deleting one never removes processed data.
def insert_window(name, ts_from, ts_to):
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO batch_windows (name, ts_from, ts_to, created_at) VALUES (?, ?, ?, ?)",
            (name, ts_from, ts_to, _now_iso()),
        )
        window_id = cur.lastrowid
    return get_window(window_id)


def get_window(window_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT window_id, name, ts_from, ts_to, created_at "
            "FROM batch_windows WHERE window_id = ?",
            (int(window_id),),
        ).fetchone()
    return dict(row) if row else None


def get_windows():
    """Every window, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT window_id, name, ts_from, ts_to, created_at "
            "FROM batch_windows ORDER BY window_id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_window(window_id):
    """Drop a window definition, leaving any processed data untouched."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM batch_windows WHERE window_id = ?", (int(window_id),)
        )
        return cur.rowcount


# ── readings outside a temperature/humidity box ────────────────
def _outlier_conds(t_min, t_max, h_min, h_max):
    """The 'outside this box' conditions and the values they bind.

    Each bound is optional; omitting one simply drops that side of the box.
    """
    conds, params = [], []
    for column, lo, hi in (("temperature", t_min, t_max), ("humidity", h_min, h_max)):
        if lo is not None:
            conds.append("%s < ?" % column)
            params.append(float(lo))
        if hi is not None:
            conds.append("%s > ?" % column)
            params.append(float(hi))
    return conds, params


def _outlier_where(start_iso, end_iso, sensor_id, t_min, t_max, h_min, h_max):
    """Shared WHERE for the two outlier queries; None when no bounds were given."""
    conds, extra = _outlier_conds(t_min, t_max, h_min, h_max)
    if not conds:
        return None, []
    query = ("WHERE ts BETWEEN ? AND ? "
             "AND temperature BETWEEN 0 AND 50 AND humidity BETWEEN 0 AND 100")
    params = [start_iso, end_iso]
    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)
    query += " AND (" + " OR ".join(conds) + ")"
    params += extra
    return query, params


def count_outliers(start_iso, end_iso, sensor_id=None,
                   t_min=None, t_max=None, h_min=None, h_max=None):
    """How many readings fall outside the given box.

    With no bounds supplied nothing is outside it, so the answer is 0.
    """
    where, params = _outlier_where(start_iso, end_iso, sensor_id, t_min, t_max, h_min, h_max)
    if where is None:
        return 0
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM readings " + where, params
        ).fetchone()["n"]


def outliers_range(start_iso, end_iso, sensor_id=None,
                   t_min=None, t_max=None, h_min=None, h_max=None, limit=200):
    """Readings outside the given box, newest first."""
    where, params = _outlier_where(start_iso, end_iso, sensor_id, t_min, t_max, h_min, h_max)
    if where is None:
        return []
    query = ("SELECT sensor_id, temperature, humidity, ts FROM readings " +
             where + " ORDER BY ts DESC LIMIT ?")
    params.append(int(limit))
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_alerts_in(start_iso, end_iso, sensor_id=None, limit=200):
    """Alert and recovery events inside a time range, newest first."""
    query = ("SELECT sensor_id, condition, value, threshold, kind, ts "
             "FROM alerts WHERE ts BETWEEN ? AND ?")
    params = [start_iso, end_iso]
    if sensor_id:
        query += " AND sensor_id = ?"
        params.append(sensor_id)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]
