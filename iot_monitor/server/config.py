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


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
