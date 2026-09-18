# -*- coding: utf-8 -*-
"""Database + data backup for the monitoring back end.

Creates a timestamped folder under data/backups/ containing:
  - monitor.db      (consistent snapshot taken via the SQLite backup API,
                     which is safe while the server is running in WAL mode)
  - readings.csv
  - alerts.csv
  - alerts table exported as alerts_table.csv (so the alert log survives even
    if the CSV is lost)

Keeps the most recent KEEP backups and deletes older ones.

Run manually:      python backup.py
Schedule daily:    see README (Windows Task Scheduler / cron)
"""
import os
import shutil
import sqlite3
from datetime import datetime, timezone

import config

KEEP = getattr(config, "BACKUP_KEEP", 14)   # how many timestamped backups to retain
BACKUP_ROOT = os.path.join(config.DATA_DIR, "backups")


def _snapshot_db(dest_path):
    """Consistent copy of the live SQLite database via the backup API."""
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(dest_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def _export_alerts_table(dest_path):
    """Dump the alerts table to CSV (independent of alerts.csv)."""
    import csv
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ts, sensor_id, kind, condition, value, threshold "
            "FROM alerts ORDER BY id"
        ).fetchall()
    with open(dest_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "sensor_id", "kind", "condition", "value", "threshold"])
        for r in rows:
            w.writerow([r["ts"], r["sensor_id"], r["kind"], r["condition"],
                        r["value"], r["threshold"]])
    return len(rows)


def _prune():
    if not os.path.isdir(BACKUP_ROOT):
        return []
    dirs = sorted(
        (d for d in os.listdir(BACKUP_ROOT)
         if os.path.isdir(os.path.join(BACKUP_ROOT, d))),
        reverse=True,          # newest first (names start with a timestamp)
    )
    removed = []
    for d in dirs[KEEP:]:
        shutil.rmtree(os.path.join(BACKUP_ROOT, d), ignore_errors=True)
        removed.append(d)
    return removed


def run_backup():
    config.ensure_data_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_ROOT, stamp)
    os.makedirs(dest, exist_ok=True)

    _snapshot_db(os.path.join(dest, "monitor.db"))
    for src, name in ((config.CSV_PATH, "readings.csv"),
                      (config.ALERTS_CSV_PATH, "alerts.csv")):
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dest, name))
    n_alerts = _export_alerts_table(os.path.join(dest, "alerts_table.csv"))

    removed = _prune()
    size_kb = sum(
        os.path.getsize(os.path.join(dest, f)) for f in os.listdir(dest)
    ) // 1024
    print("backup created: %s  (%d KB, %d alert rows)" % (dest, size_kb, n_alerts))
    if removed:
        print("pruned old backups: %s" % ", ".join(removed))
    return dest


if __name__ == "__main__":
    run_backup()
