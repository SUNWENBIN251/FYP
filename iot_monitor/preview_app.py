# -*- coding: utf-8 -*-
"""
preview_app.py - 前端预览用 mock 数据服务器（零依赖，仅 Python 标准库）
只用于在浏览器里预览 dashboard，不是生产后端。
运行: python preview_app.py  ->  http://localhost:5000
"""
import json
import math
import os
import random
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "server", "static")

SENSORS = ["dht22-01", "dht22-02", "dht22-03"]
MINUTE = 60
HISTORY_MINUTES = 24 * 60  # 24 小时

thresholds = {"temp_min": 15.0, "temp_max": 30.0, "humidity_min": 20.0, "humidity_max": 70.0}
lock = threading.Lock()


def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# 每个传感器一个随机游走状态，保证曲线连续不跳变
# 演示模式: 'high' = 超温超湿(>30°C, >70%RH); 'low' = 低温低湿(<15°C, <20%RH); 'normal' = 正常范围
ALARM_MODE = "normal"

walks = {sid: {"t": random.uniform(22.5, 24.5), "h": random.uniform(42, 52)} for sid in SENSORS}


def _hour_of(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).hour


def next_value(sid, hour):
    w = walks[sid]
    t_diurnal = 3.0 * math.sin((hour - 6) / 24 * 2 * math.pi)   # 昼夜温差
    h_diurnal = 8.0 * math.sin((hour + 4) / 24 * 2 * math.pi)
    if ALARM_MODE == "high":
        t_target, h_target = 34.0, 78.0   # 超上限: temp>30, humid>70
        t_lo, t_hi, h_lo, h_hi = 32.0, 38.0, 72.0, 86.0
    elif ALARM_MODE == "low":
        t_target, h_target = 12.0, 15.0   # 低于下限: temp<15, humid<20
        t_lo, t_hi, h_lo, h_hi = 8.0, 14.0, 8.0, 18.0
    else:
        t_target, h_target = 23.0, 50.0
        t_lo, t_hi, h_lo, h_hi = 16.0, 31.0, 28.0, 71.0
    w["t"] += random.gauss(0, 0.15) + (t_target + t_diurnal - w["t"]) * 0.02
    w["h"] += random.gauss(0, 0.45) + (h_target + h_diurnal - w["h"]) * 0.02
    w["t"] = min(t_hi, max(t_lo, w["t"]))
    w["h"] = min(h_hi, max(h_lo, w["h"]))
    return round(w["t"], 1), round(w["h"], 1)


# 预生成 24 小时历史
_now_min = int(time.time() // MINUTE) * MINUTE
history = []
for i in range(HISTORY_MINUTES):
    ts = _now_min - (HISTORY_MINUTES - 1 - i) * MINUTE
    for sid in SENSORS:
        t, h = next_value(sid, _hour_of(ts))
        history.append({"ts": iso(ts), "sensor_id": sid, "temperature": t, "humidity": h})
cursor = _now_min


def advance():
    """把历史推进到当前分钟，返回新追加的点（供 /api/latest 实时推送）。"""
    global cursor
    now = int(time.time() // MINUTE) * MINUTE
    added = []
    while cursor < now:
        cursor += MINUTE
        ts = iso(cursor)
        for sid in SENSORS:
            t, h = next_value(sid, _hour_of(cursor))
            rec = {"ts": ts, "sensor_id": sid, "temperature": t, "humidity": h}
            history.append(rec)
            added.append(rec)
    if len(history) > HISTORY_MINUTES * len(SENSORS) * 2:
        del history[: len(SENSORS) * MINUTE]
    return added


def latest_per_sensor():
    seen = {}
    for rec in reversed(history):
        if rec["sensor_id"] not in seen:
            seen[rec["sensor_id"]] = rec
        if len(seen) == len(SENSORS):
            break
    return [seen[sid] for sid in SENSORS if sid in seen]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默访问日志
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self):
        path = "index.html"
        full = os.path.join(STATIC_DIR, path)
        if not os.path.exists(full):
            self._json({"error": "static file missing"}, 404)
            return
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        qs = parse_qs(parsed.query)
        with lock:
            if route == "/" or route == "/index.html":
                self._serve_static()
            elif route == "/api/latest":
                added = advance()
                self._json({
                    "server_time": iso(time.time()),
                    "thresholds": thresholds,
                    "sensors": latest_per_sensor(),
                    "trend_points": added[-len(SENSORS):] if added else [],
                })
            elif route == "/api/trend":
                hours = int(qs.get("hours", ["24"])[0])
                n = min(hours * 60, len(history) // len(SENSORS))
                pts = history[-n * len(SENSORS):] if n > 0 else []
                self._json({"points": pts})
            elif route == "/api/thresholds":
                self._json(thresholds)
            elif route == "/api/history.csv":
                start_s = (qs.get("start") or [""])[0]
                end_s = (qs.get("end") or [""])[0]

                def parse_dt(s):
                    if not s:
                        return None
                    try:
                        return datetime.strptime(s, "%Y-%m-%dT%H:%M")
                    except ValueError:
                        return None

                start_dt = parse_dt(start_s) or datetime(2000, 1, 1)
                end_dt = parse_dt(end_s) or datetime(2100, 1, 1)
                lines = ["timestamp,sensor_id,temperature_c,humidity_rh"]
                for rec in history:
                    rec_dt = datetime.strptime(rec["ts"], "%Y-%m-%dT%H:%M:%SZ")
                    if start_dt <= rec_dt <= end_dt:
                        lines.append("%s,%s,%.1f,%.1f" % (rec["ts"], rec["sensor_id"], rec["temperature"], rec["humidity"]))
                body = ("\n".join(lines) + "\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="readings.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/thresholds":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw)
            except ValueError:
                data = {}
            with lock:
                for k in ("temp_min", "temp_max", "humidity_min", "humidity_max"):
                    if k in data:
                        thresholds[k] = float(data[k])
                self._json(thresholds)
        else:
            self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("preview server running at http://localhost:%d" % port)
    server.serve_forever()
