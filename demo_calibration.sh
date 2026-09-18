#!/usr/bin/env bash
# ============================================================
#  Sensor Calibration Demo
#  Run:  bash demo_calibration.sh
#  Note: demonstrates the full path "set offset -> applied at ingestion",
#        then removes the test data automatically
# ============================================================
cd "$(dirname "$0")" || exit 1

PY="C:/Users/1/AppData/Local/Microsoft/WindowsApps/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/python.exe"
[ -x "$PY" ] || PY="python"

API="http://localhost:5000"
SENSOR="dht22-01"
DB="iot_monitor/server/data/monitor.db"

line() { printf '%s\n' "------------------------------------------------------------"; }

# Read back what was actually stored for the sensor (proves the stored value).
show_stored() {
  PYTHONIOENCODING=utf-8 "$PY" - "$DB" "$SENSOR" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
row = c.execute(
    "SELECT temperature, humidity, ts FROM readings WHERE sensor_id=? "
    "ORDER BY id DESC LIMIT 1", (sys.argv[2],)).fetchone()
print("      stored in DB = %.1f C / %.1f %%RH   (%s)" % (row[0], row[1], row[2]))
c.close()
PY
}

echo "============================================================"
echo " Sensor Calibration Demo"
echo "============================================================"
echo

# 0) the backend must be running
code=$(curl -s -m 5 -o /dev/null -w "%{http_code}" "$API/api/latest")
if [ "$code" != "200" ]; then
  echo " Backend is not running (no response from $API)."
  echo " Start run_server.bat first, then run this demo again."
  exit 1
fi

echo "[1] Current calibration offsets"
line
curl -s -m 5 "$API/api/calibration"
echo
echo "    (empty list = not calibrated yet; all sensors use offset 0 / 0)"
echo

echo "[2] Before calibration: send a known reading of 24.5 C / 51.0 %RH"
line
curl -s -m 5 -X POST "$API/api/reading" -H "Content-Type: application/json" \
     -d "{\"sensor_id\":\"$SENSOR\",\"temperature\":24.5,\"humidity\":51.0}" >/dev/null
sleep 1
echo "    raw value sent to the system = 24.5 C / 51.0 %RH"
show_stored
echo "    -> no correction applied, stored as-is"
echo

echo "[3] Set a calibration offset (simulating a reference-instrument comparison:"
echo "    this sensor reads 0.5 C high and 2.0 %RH low)"
line
curl -s -m 5 -X POST "$API/api/calibration" -H "Content-Type: application/json" \
     -d "{\"sensor_id\":\"$SENSOR\",\"temp_offset\":0.5,\"hum_offset\":-2.0}"
echo
echo "    -> offset saved: temperature +0.5 C, humidity -2.0 %RH"
echo

echo "[4] After calibration: send the SAME raw reading of 24.5 C / 51.0 %RH"
line
curl -s -m 5 -X POST "$API/api/reading" -H "Content-Type: application/json" \
     -d "{\"sensor_id\":\"$SENSOR\",\"temperature\":24.5,\"humidity\":51.0}" >/dev/null
sleep 1
echo "    raw value sent to the system = 24.5 C / 51.0 %RH"
show_stored
echo "    -> the offset is applied automatically; the corrected value is stored"
echo

echo "[5] Comparison"
line
printf "    %-28s %-16s %s\n" "Item" "Temperature" "Humidity"
printf "    %-28s %-16s %s\n" "Raw reading from sensor" "24.5 C" "51.0 %RH"
printf "    %-28s %-16s %s\n" "Calibration offset" "+0.5 C" "-2.0 %RH"
printf "    %-28s %-16s %s\n" "Stored value (corrected)" "25.0 C" "49.0 %RH"
echo

echo "[6] Real calibration procedure (requires a more accurate reference instrument)"
line
echo "    1) Place the DHT22 next to the reference instrument and let both settle"
echo "    2) Read the reference value, e.g. 25.4 C / 48.0 %RH"
echo "    3) Run the tool (it averages recent readings, computes and saves the offset):"
echo
echo "         cd iot_monitor/server"
echo "         python calibrate.py --sensor $SENSOR --ref-temp 25.4 --ref-hum 48.0"
echo
echo "    Show current offsets:  python calibrate.py --show"
echo
echo "    NOTE: no reference instrument is available yet, so actual calibration has"
echo "          not been performed (offsets remain 0/0). The mechanism is in place;"
echo "          once a reference is available, follow the steps above - no code change."
echo

echo "[7] Clean up the demo data (reset offset + delete the test readings)"
line
curl -s -m 5 -X POST "$API/api/calibration" -H "Content-Type: application/json" \
     -d "{\"sensor_id\":\"$SENSOR\",\"temp_offset\":0,\"hum_offset\":0}" >/dev/null
PYTHONIOENCODING=utf-8 "$PY" - "$DB" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
where = ("sensor_id='dht22-01' "
         "AND temperature IN (24.5, 25.0) AND humidity IN (51.0, 49.0) "
         "AND ts >= '2026-09-13'")
n = c.execute("SELECT COUNT(*) FROM readings WHERE " + where).fetchone()[0]
c.execute("DELETE FROM readings WHERE " + where)
c.execute("DELETE FROM calibration WHERE sensor_id='dht22-01'")
c.commit()
print("    removed %d test readings; offset reset to 0/0" % n)
print("    readings total now = %d" % c.execute("SELECT COUNT(*) FROM readings").fetchone()[0])
c.close()
PY
echo
echo "============================================================"
echo " Demo complete -- mechanism: set offset -> corrected at ingestion"
echo " (default 0/0 leaves stored data unchanged)"
echo "============================================================"
