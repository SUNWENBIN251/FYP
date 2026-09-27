# -*- coding: utf-8 -*-
"""Read the Spark-built Hive tables for the dashboard.

Every query runs through beeline inside WSL, which costs several seconds, so
results are cached. The Hive tables only change when a batch run finishes —
batch.py calls invalidate() at that point — so a stale answer is not possible.

The reports below are what a user who does not write SQL can still ask for.
Each one covers the whole `iot.agg_hour` table (the long-term store), which is
exactly what the hot SQLite copy is not the right place to answer.
"""
import subprocess
import threading
import time

import config
import database

CACHE_TTL_SECONDS = 900         # generous: invalidate() covers real changes
QUERY_TIMEOUT_SECONDS = 120     # a Hive query is seconds, not minutes

# `hour` is stored as "YYYY-MM-DD HH:00", so the day is characters 1-10 and the
# hour of day is characters 12-13.
#
# "risk" is not in here: its thresholds come from the dashboard's alert
# settings, so _sql_for() builds it per call.
QUERIES = {
    # Per day, per sensor: the long-run trend. The hour count rides along so the
    # table can also report how completely each day was captured.
    "trend": """
        SELECT SUBSTR(hour,1,10) AS day, sensor_id,
               ROUND(AVG(avg_temp),2) AS avg_t,
               ROUND(MAX(max_temp),1) AS peak_t,
               ROUND(MIN(min_temp),1) AS low_t,
               ROUND(AVG(avg_hum),1) AS avg_h,
               SUM(cnt) AS samples,
               COUNT(*) AS hours
        FROM iot.agg_hour
        GROUP BY SUBSTR(hour,1,10), sensor_id
        ORDER BY day, sensor_id
    """,
    # One cell per day and hour of day: enough for a 31-day grid. The min/max
    # ride along so the cell tooltip can show the hour's full range, not just
    # its average.
    "heatmap": """
        SELECT SUBSTR(hour,1,10) AS day, SUBSTR(hour,12,2) AS hh,
               ROUND(AVG(avg_temp),2) AS t,
               ROUND(MAX(max_temp),1) AS t_hi,
               ROUND(MIN(min_temp),1) AS t_lo,
               ROUND(AVG(avg_hum),1) AS h,
               ROUND(MAX(max_hum),1) AS h_hi,
               ROUND(MIN(min_hum),1) AS h_lo,
               SUM(cnt) AS samples
        FROM iot.agg_hour
        GROUP BY SUBSTR(hour,1,10), SUBSTR(hour,12,2)
        ORDER BY day DESC, hh
        LIMIT 744
    """,
    # Hours where the temperature moved suddenly — an air conditioner failing,
    # a door opening, a load appearing. Pairing each hour with the one before it
    # needs a window function; the UNIX_TIMESTAMP guard then keeps out pairs that
    # a collection gap separates, which would otherwise read as a one-hour jump
    # when they are really six hours apart.
    "spike": """
        SELECT hour, sensor_id,
               ROUND(prev_t,1) AS was_t, ROUND(t,1) AS now_t,
               ROUND(t - prev_t,2) AS delta
        FROM (
            SELECT hour, sensor_id, avg_temp AS t,
                   LAG(avg_temp) OVER (PARTITION BY sensor_id ORDER BY hour) AS prev_t,
                   LAG(hour)     OVER (PARTITION BY sensor_id ORDER BY hour) AS prev_hour
            FROM iot.agg_hour
        ) pairs
        WHERE prev_t IS NOT NULL
          AND UNIX_TIMESTAMP(hour,'yyyy-MM-dd HH:mm')
              - UNIX_TIMESTAMP(prev_hour,'yyyy-MM-dd HH:mm') = 3600
          AND ABS(t - prev_t) >= 0.5
        ORDER BY ABS(t - prev_t) DESC
        LIMIT 40
    """,
}

# Hours that were hot AND humid at once — the combination that actually stresses
# equipment (condensation, corrosion). Built on the hour's extremes, not its
# averages: a brief excursion to 32 degrees at 81 %RH is the risk, and averaging
# it with the rest of the hour washes it away.
# Substitution order: temp ceiling, humidity ceiling, temp floor, humidity floor.
RISK_SQL = """
    SELECT hour, sensor_id,
           ROUND(max_temp,1) AS t_hi,
           ROUND(max_hum,1)  AS h_hi,
           ROUND(max_temp / %s + max_hum / %s, 3) AS risk
    FROM iot.agg_hour
    WHERE max_temp > %s AND max_hum > %s
    ORDER BY risk DESC
    LIMIT 40
"""

# How far below the configured ceiling counts as "running hot / damp".
RISK_TEMP_MARGIN = 3.0
RISK_HUM_MARGIN = 10.0

_cache = {}
_lock = threading.Lock()


def invalidate():
    """Drop cached results — called when a batch run finishes."""
    with _lock:
        _cache.clear()


def _coerce(value):
    """TSV yields strings; turn the ones that are plainly numbers into numbers."""
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _parse_tsv(text):
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return []
    header = [c.strip() for c in lines[0].split("\t")]
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.split("\t")]
        if len(cells) != len(header):
            continue                     # beeline footer / stray output
        rows.append({k: _coerce(v) for k, v in zip(header, cells)})
    return rows


def _run(sql):
    """Run one query through the WSL helper. Returns (rows, error).

    The rows arrive on the helper's stdout. Writing them to a file under
    /mnt/c instead would be unreliable: WSL2's drvfs does not always see a
    directory that Windows created moments earlier.
    """
    script = getattr(config, "HIVE_QUERY_SCRIPT_MNT", "")
    if not script:
        return None, "HIVE_QUERY_SCRIPT_MNT is not configured"

    cmd = [
        "wsl.exe", "-d", getattr(config, "BATCH_WSL_DISTRO", "Ubuntu"),
        "bash", script,
        # collapse to one line so nothing has to survive a newline in argv
        "--sql", " ".join(sql.split()),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=QUERY_TIMEOUT_SECONDS,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return None, "the query timed out after %d seconds" % QUERY_TIMEOUT_SECONDS
    except FileNotFoundError:
        return None, "wsl.exe not found - is WSL installed?"

    text = proc.stdout or ""
    for line in text.split("\n"):
        if line.startswith("#ERROR"):
            return None, line[len("#ERROR"):].strip() or "the query failed"
    if not text.strip():
        tail = (proc.stderr or "").strip()[-300:]
        return None, "the query produced no output. %s" % tail
    return _parse_tsv(text), None


def _sql_for(name):
    """The SQL behind a report, or None when there is no such report.

    "risk" depends on the configured alert thresholds, so it is assembled here
    rather than being a constant.
    """
    if name == "risk":
        th = database.get_thresholds()
        t_max = float(th["temp_max"])
        h_max = float(th["humidity_max"])
        return RISK_SQL % ("%.1f" % t_max, "%.1f" % h_max,
                           "%.1f" % (t_max - RISK_TEMP_MARGIN),
                           "%.1f" % (h_max - RISK_HUM_MARGIN))
    return QUERIES.get(name)


def report(name):
    """Rows for a named report, or (None, error) if it could not run.

    Returns (rows, error, cached).
    """
    sql = _sql_for(name)
    if sql is None:
        return None, "unknown report: %s" % name, False

    with _lock:
        hit = _cache.get(name)
        if hit and (time.time() - hit["at"]) < CACHE_TTL_SECONDS:
            return hit["rows"], None, True

    rows, error = _run(sql)
    if error:
        return None, error, False        # failures are never cached

    with _lock:
        _cache[name] = {"at": time.time(), "rows": rows}
    return rows, None, False
