# -*- coding: utf-8 -*-
"""Configuration for the environmental monitoring backend.

Keep credentials in environment variables, never commit real tokens.
"""
import os

# ---- paths ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "monitor.db")
CSV_PATH = os.path.join(DATA_DIR, "readings.csv")
ALERTS_CSV_PATH = os.path.join(DATA_DIR, "alerts.csv")

# ---- default alert thresholds ----
# Safe envelope: temperature 15-30 C, humidity 20-70 %RH (per the project brief).
DEFAULT_THRESHOLDS = {
    "temp_min": 15.0,
    "temp_max": 30.0,
    "humidity_min": 20.0,
    "humidity_max": 70.0,
}

# ---- Telegram alerts (set via environment variables, never hardcode) ----
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ---- ingestion / alerting behaviour ----
POLL_INTERVAL_SECONDS = 60          # Raspberry Pi send cadence
ALERT_SUPPRESS_SECONDS = 600        # suppress repeats for the same sensor within N seconds
CSV_FLUSH_EVERY = 1                 # append each reading to CSV immediately

# ---- automatic backup ----
BACKUP_INTERVAL_HOURS = 24          # back up the database + CSVs this often (0 = disabled)
BACKUP_KEEP = 14                    # how many timestamped backups to retain

# ---- batch processing (Spark + Hive) ----
# The backend exports each batch window to a CSV, hands it to the WSL script
# below, and reads the JSON result file the script writes back.
BATCH_DIR = os.path.join(DATA_DIR, "batch")
BATCH_SCRIPT_MNT = "/mnt/c/Users/1/Desktop/FYP/iot_monitor/spark/batch_run.sh"
# Runs a Hive query (as an argument) and writes the rows back as TSV
HIVE_QUERY_SCRIPT_MNT = "/mnt/c/Users/1/Desktop/FYP/iot_monitor/spark/hive_query.sh"
BATCH_WSL_DISTRO = "Ubuntu"
BATCH_TIMEOUT_MINUTES = 20          # a running batch older than this is treated as dead
BATCH_SCHEDULE_MINUTES = 60         # default automatic interval (0 = disabled)


def to_mnt(win_path):
    """C:\\Users\\1\\x -> /mnt/c/Users/1/x, i.e. the path as WSL sees it."""
    p = os.path.abspath(win_path).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        p = "/mnt/" + p[0].lower() + p[2:]
    return p


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(BATCH_DIR, exist_ok=True)


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(BATCH_DIR, exist_ok=True)
