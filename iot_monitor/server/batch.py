# -*- coding: utf-8 -*-
"""Incremental batch processing: export a time window from SQLite, hand it to
the WSL Spark job, and record the outcome.

A "batch" is a half-open window (from, to]: its readings are aggregated into
hourly rows and written to HDFS partitioned by day. The Spark side overwrites
only the partitions it touches, so re-running any window is idempotent — that
is what makes both arbitrary re-runs and the watermark model safe.

The watermark is the `to` of the last SUCCESSFUL batch, so an ordinary run
picks up exactly where the previous one stopped. It advances only on success,
leaving a failed window to be retried.

Success is read from the JSON result file the WSL script writes, never from
its exit code: the run is long and wsl.exe can lose the status.

Run manually:  python batch.py            one incremental batch now
               python batch.py --full     rebuild every partition
"""
import csv
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

import config
import database
import hive

HISTORY_LIMIT = 8               # batch rows shown on the dashboard
SCHEDULE_CHECK_SECONDS = 60     # how often the scheduler looks for work


class BatchError(Exception):
    """A batch could not be completed; the message is recorded and shown."""


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _stale_cutoff():
    minutes = getattr(config, "BATCH_TIMEOUT_MINUTES", 20)
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── live progress ──────────────────────────────────────────────
# Kept in memory: a run lives entirely inside this process, and the dashboard
# only needs it while the run is going.
STAGES = ("export", "services", "spark", "hdfs", "hive", "done")

# A line in the WSL script's output -> the stage it announces.
# "writing ... to HDFS" is emitted just before the write, so the HDFS station
# is visible rather than flashing past at the end of the Spark job.
_STAGE_MARKERS = (
    ("---- services ----", "services"),
    ("---- Spark ETL ----", "spark"),
    ("writing hourly aggregates to HDFS", "hdfs"),
    ("written to HDFS:", "hdfs"),
    ("---- Hive partition registration ----", "hive"),
    ("BATCH COMPLETE", "done"),
)
_LOG_TAIL = 14

_progress = {"stage": None, "log": []}


def _set_stage(stage):
    _progress["stage"] = stage
    _progress["log"] = []


def _note(line):
    """Advance the stage when the script announces one, and keep a log tail."""
    text = line.rstrip()
    for marker, stage in _STAGE_MARKERS:
        if marker in text:
            _progress["stage"] = stage
            break
    if text:
        log = _progress["log"]
        log.append(text)
        if len(log) > _LOG_TAIL:
            del log[:-_LOG_TAIL]


def get_progress():
    return {"stage": _progress["stage"], "log": list(_progress["log"])}


def export_window(batch_id, start_iso, end_iso):
    """Write this window's readings to data/batch/<id>.csv for the Spark job.

    The header matches the backend's own readings.csv, so one ETL reads both.
    Returns (path, row_count).
    """
    config.ensure_data_dir()
    rows = database.get_range_for_export(start_iso, end_iso)
    path = os.path.join(config.BATCH_DIR, "%s.csv" % batch_id)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "sensor_id", "temperature_c", "humidity_rh"])
        for r in rows:
            writer.writerow([r["ts"], r["sensor_id"], r["temperature"], r["humidity"]])
    return path, len(rows)


def _resolve_window(from_iso, to_iso, full):
    """Explicit arguments win; otherwise the watermark decides where to start."""
    to_iso = to_iso or _now_iso()
    if full:
        return database.earliest_reading_ts(), to_iso
    if not from_iso:
        from_iso = database.get_batch_state().get("watermark")
        if not from_iso:
            # first ever run: cover the whole history once, then go incremental
            from_iso = database.earliest_reading_ts()
    return from_iso, to_iso


def _read_result(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def _invoke_spark(csv_path, from_iso, to_iso, result_path):
    """Run the WSL batch script, streaming its output so the dashboard can show
    which stage the run has reached.

    Success still comes from the result JSON the script writes, never from the
    exit code: the run is long and wsl.exe can lose the status.
    """
    script = getattr(config, "BATCH_SCRIPT_MNT", "")
    if not script:
        raise BatchError("BATCH_SCRIPT_MNT is not configured")

    cmd = [
        "wsl.exe", "-d", getattr(config, "BATCH_WSL_DISTRO", "Ubuntu"),
        "bash", script,
        "--csv", config.to_mnt(csv_path),
        "--result", config.to_mnt(result_path),
    ]
    if from_iso:
        cmd += ["--from", from_iso]
    if to_iso:
        cmd += ["--to", to_iso]

    timeout = getattr(config, "BATCH_TIMEOUT_MINUTES", 20) * 60
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace",   # WSL speaks UTF-8, not the console codepage
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # backend runs under pythonw
        )
    except FileNotFoundError:
        raise BatchError("wsl.exe not found - is WSL installed?")

    # Reading the pipe blocks, so the deadline cannot be checked between lines:
    # a watchdog kills the script instead, and the closer pipe ends the loop.
    timed_out = []
    watchdog = threading.Timer(timeout, lambda: (timed_out.append(True), proc.kill()))
    watchdog.daemon = True
    watchdog.start()
    try:
        for line in proc.stdout:
            _note(line)
        proc.wait()
    finally:
        watchdog.cancel()

    if timed_out:
        raise BatchError("timed out after %d minutes" % (timeout // 60))

    outcome = _read_result(result_path)
    if outcome is None:
        tail = " | ".join(_progress["log"][-3:]) or "no output"
        raise BatchError("the batch script produced no result file. %s" % tail)
    if outcome.get("status") != "success":
        raise BatchError(outcome.get("error") or "the batch script reported a failure")
    return outcome


def run_batch(from_iso=None, to_iso=None, full=False):
    """Run one batch synchronously and return a summary dict."""
    database.fail_stale_batches(_stale_cutoff())
    from_iso, to_iso = _resolve_window(from_iso, to_iso, full)

    batch_id = database.claim_batch(from_iso, to_iso)
    if batch_id is None:
        return {"status": "busy"}
    return _execute(batch_id, from_iso, to_iso)


def start_batch(from_iso=None, to_iso=None, full=False):
    """Claim a batch slot, then run it in a background thread.

    Returns the batch_id, or None when a batch is already running. The claim
    happens here rather than inside the thread so the caller finds out
    immediately whether it got the slot — a batch runs for minutes and cannot
    be awaited inside a request.
    """
    database.fail_stale_batches(_stale_cutoff())
    from_iso, to_iso = _resolve_window(from_iso, to_iso, full)

    batch_id = database.claim_batch(from_iso, to_iso)
    if batch_id is None:
        return None
    threading.Thread(target=_execute, args=(batch_id, from_iso, to_iso), daemon=True).start()
    return batch_id


def _execute(batch_id, from_iso, to_iso):
    """Do the work for an already-claimed batch, then close its row."""
    csv_path = os.path.join(config.BATCH_DIR, "%s.csv" % batch_id)
    result_path = os.path.join(config.BATCH_DIR, "%s.result.json" % batch_id)
    _set_stage("export")
    ran_spark = False
    try:
        _, rows = export_window(batch_id, from_iso, to_iso)
        if rows == 0:
            # Nothing new in the window. Still a successful batch: the
            # watermark can move to `to` and the next run looks further ahead.
            _set_stage("done")
            database.finish_batch(batch_id, True, 0, 0, "", None)
            database.advance_watermark(to_iso)
            return {"status": "success", "batch_id": batch_id, "rows_in": 0,
                    "rows_out": 0, "partitions": "", "note": "nothing new in this window"}

        ran_spark = True
        outcome = _invoke_spark(csv_path, from_iso, to_iso, result_path)
        rows_in = outcome.get("rows_in") or 0
        rows_out = outcome.get("rows_out") or 0
        partitions = ",".join(outcome.get("partitions") or [])
        database.finish_batch(batch_id, True, rows_in, rows_out, partitions, None)
        database.advance_watermark(to_iso)
        return {"status": "success", "batch_id": batch_id, "rows_in": rows_in,
                "rows_out": rows_out, "partitions": partitions}
    except BatchError as e:
        # Watermark deliberately untouched: the window stays pending.
        database.finish_batch(batch_id, False, None, None, None, str(e))
        return {"status": "failed", "batch_id": batch_id, "error": str(e)}
    except Exception as e:                       # never leave a batch stuck running
        database.finish_batch(batch_id, False, None, None, None, repr(e))
        return {"status": "failed", "batch_id": batch_id, "error": repr(e)}
    finally:
        # Spark ran, so the Hive tables may have changed: drop cached report
        # results. Skipped for the "nothing new" path, which writes nothing.
        if ran_spark:
            hive.invalidate()
        for path in (csv_path, result_path):
            try:
                os.remove(path)
            except OSError:
                pass


def get_panel_state():
    """Everything the dashboard's batch panel needs, in one call."""
    state = database.get_batch_state()
    minutes = int(state.get("schedule_minutes") or 0)
    enabled = bool(state.get("schedule_enabled")) and minutes > 0

    next_run = None
    if enabled:
        last = state.get("last_scheduled_at")
        base = _parse_iso(last) if last else datetime.now(timezone.utc)
        next_run = (base + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "watermark": state.get("watermark"),
        # where a default run would start before the first batch sets a watermark
        "earliest": database.earliest_reading_ts(),
        "schedule": {"enabled": enabled, "minutes": minutes, "next_run": next_run},
        "running": database.get_running_batch(),
        "batches": database.get_batches(HISTORY_LIMIT),
        "stages": list(STAGES),
        "progress": get_progress(),
    }


def _tick():
    """Run a scheduled batch if one is due."""
    state = database.get_batch_state()
    if not state.get("schedule_enabled"):
        return
    minutes = int(state.get("schedule_minutes") or 0)
    if minutes <= 0:
        return

    last = state.get("last_scheduled_at")
    if last and datetime.now(timezone.utc) < _parse_iso(last) + timedelta(minutes=minutes):
        return

    # Stamp before running: a batch takes minutes, and the next tick must not
    # queue a second one behind it.
    database.set_batch_state(last_scheduled_at=_now_iso())
    outcome = run_batch()
    print("scheduled batch:", outcome.get("status"), outcome.get("batch_id"))


def _loop():
    """Scheduler thread; mirrors app.py's backup loop."""
    while True:
        try:
            _tick()
        except Exception as e:
            print("batch scheduler failed:", e)
        time.sleep(SCHEDULE_CHECK_SECONDS)


def start_scheduler():
    """Start the scheduler as a daemon thread (no-op if the interval is off)."""
    threading.Thread(target=_loop, daemon=True).start()


if __name__ == "__main__":
    import sys
    print(json.dumps(run_batch(full="--full" in sys.argv), indent=2))
