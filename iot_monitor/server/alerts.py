# -*- coding: utf-8 -*-
"""Alert module: evaluate readings against thresholds and notify via Telegram.

Threshold checking is called synchronously at the point of ingestion (so alerts
fire quickly), while the Telegram HTTP call itself runs in a background thread.
Repeated alerts for the same sensor and condition are suppressed for a cooldown
window to avoid flooding the operator.
"""
import threading
import time
from datetime import datetime, timezone

try:
    from . import config, database
except ImportError:
    import config
    import database

_last_alert = {}          # (sensor_id, condition) -> epoch seconds
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


def handle_reading(sensor_id, temperature, humidity):
    """Called at ingestion time. Fires alerts for breached conditions (with cooldown)."""
    th = database.get_thresholds()
    conditions = evaluate(sensor_id, temperature, humidity, th)
    now = time.time()
    fired = []
    for c in conditions:
        key = (sensor_id, c)
        last = _last_alert.get(key, 0)
        if now - last >= config.ALERT_SUPPRESS_SECONDS:
            _last_alert[key] = now
            fired.append(c)
    if fired:
        msg = _msg(sensor_id, temperature, humidity, fired, th)
        send_telegram(msg)
    return len(fired) > 0
