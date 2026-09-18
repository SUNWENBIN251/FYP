# -*- coding: utf-8 -*-
"""Alert module: evaluate readings against thresholds and notify via Telegram.

Threshold checking is called synchronously at the point of ingestion (so alerts
fire quickly), while the Telegram HTTP call itself runs in a background thread.
Repeated alerts for the same sensor and condition are suppressed for a cooldown
window to avoid flooding the operator.
"""
import os
import threading
import time
from datetime import datetime, timezone

try:
    from . import config, database
except ImportError:
    import config
    import database

_last_alert = {}          # (sensor_id, condition) -> epoch seconds
_sensor_active = {}       # sensor_id -> set of conditions currently breached
_send_lock = threading.Lock()


def _iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def evaluate(sensor_id, temperature, humidity, thresholds=None):
    """Return list of violated conditions like 'temp_high', 'humidity_low'."""
    th = thresholds or database.get_thresholds()
    out = []
    if temperature > th["temp_max"]:
        out.append("temp_high")
    elif temperature < th["temp_min"]:
        out.append("temp_low")
    if humidity > th["humidity_max"]:
        out.append("humidity_high")
    elif humidity < th["humidity_min"]:
        out.append("humidity_low")
    return out


def _msg(sensor_id, temperature, humidity, conditions, th):
    labels = {
        "temp_high": "temperature %.1f C exceeds max %.1f C",
        "temp_low": "temperature %.1f C is below min %.1f C",
        "humidity_high": "humidity %.1f%% exceeds max %.1f%%",
        "humidity_low": "humidity %.1f%% is below min %.1f%%",
    }
    lines = ["[ALERT] %s" % sensor_id, "time: %s" % _iso_now()]
    for c in conditions:
        if c == "temp_high":
            lines.append(labels[c] % (temperature, th["temp_max"]))
        elif c == "temp_low":
            lines.append(labels[c] % (temperature, th["temp_min"]))
        elif c == "humidity_high":
            lines.append(labels[c] % (humidity, th["humidity_max"]))
        elif c == "humidity_low":
            lines.append(labels[c] % (humidity, th["humidity_min"]))
    return "\n".join(lines)


def _recovered_msg(sensor_id, temperature, humidity, conditions, th):
    labels = {
        "temp_high": "temperature back to %.1f C (limit %.1f C)",
        "temp_low": "temperature back to %.1f C (limit %.1f C)",
        "humidity_high": "humidity back to %.1f%% (limit %.1f%%)",
        "humidity_low": "humidity back to %.1f%% (limit %.1f%%)",
    }
    lines = ["[RECOVERED] %s" % sensor_id, "time: %s" % _iso_now()]
    for c in conditions:
        if c in ("temp_high", "temp_low"):
            limit = th["temp_max"] if c == "temp_high" else th["temp_min"]
            lines.append(labels[c] % (temperature, limit))
        else:
            limit = th["humidity_max"] if c == "humidity_high" else th["humidity_min"]
            lines.append(labels[c] % (humidity, limit))
    return "\n".join(lines)


def send_telegram(text):
    """Send a message via the Telegram Bot API (background thread)."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    t = threading.Thread(target=_send_worker, args=(text,), daemon=True)
    t.start()
    return True


def _send_worker(text, retries=3):
    import json as _json
    from urllib.request import Request, urlopen

    url = "https://api.telegram.org/bot%s/sendMessage" % config.TELEGRAM_BOT_TOKEN
    payload = _json.dumps({"chat_id": config.TELEGRAM_CHAT_ID, "text": text}).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            with _send_lock:
                resp = urlopen(req, timeout=10)
            if resp.status == 200:
                return True
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
    return False


def _cond_value_threshold(c, temperature, humidity, th):
    """Return (reading_value, threshold) for a condition code."""
    if c == "temp_high":
        return temperature, th["temp_max"]
    if c == "temp_low":
        return temperature, th["temp_min"]
    if c == "humidity_high":
        return humidity, th["humidity_max"]
    if c == "humidity_low":
        return humidity, th["humidity_min"]
    return None, None


def _record(sensor_id, conditions, temperature, humidity, th, kind):
    """Persist alert/recovery events to the database and to alerts.csv."""
    import csv as _csv
    ts = _iso_now()
    for c in conditions:
        val, lim = _cond_value_threshold(c, temperature, humidity, th)
        try:
            database.insert_alert(sensor_id, c, val, lim, kind, ts)
        except Exception:
            pass
        try:
            first = not os.path.exists(config.ALERTS_CSV_PATH)
            with open(config.ALERTS_CSV_PATH, "a", newline="") as f:
                w = _csv.writer(f)
                if first:
                    w.writerow(["timestamp", "sensor_id", "kind", "condition", "value", "threshold"])
                w.writerow([ts, sensor_id, kind, c, val, lim])
        except Exception:
            pass


def handle_reading(sensor_id, temperature, humidity):
    """Called at ingestion time. Fires alerts for new breaches (with cooldown)
    and a recovery notice when a breached condition returns to normal."""
    th = database.get_thresholds()
    conditions = set(evaluate(sensor_id, temperature, humidity, th))
    active = _sensor_active.setdefault(sensor_id, set())

    now = time.time()
    fired = []
    for c in conditions - active:
        key = (sensor_id, c)
        last = _last_alert.get(key, 0)
        if now - last >= config.ALERT_SUPPRESS_SECONDS:
            _last_alert[key] = now
            fired.append(c)
    if fired:
        send_telegram(_msg(sensor_id, temperature, humidity, fired, th))
        _record(sensor_id, fired, temperature, humidity, th, "alert")

    recovered = active - conditions
    if recovered:
        send_telegram(_recovered_msg(sensor_id, temperature, humidity, list(recovered), th))
        _record(sensor_id, list(recovered), temperature, humidity, th, "recovery")

    active.clear()
    active.update(conditions)
    return len(fired) > 0
