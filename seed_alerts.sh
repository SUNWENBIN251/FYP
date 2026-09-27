#!/usr/bin/env bash
# ============================================================
#  Seed alert history for demos
#  Run:  bash seed_alerts.sh [--no-restart]
#
#  Posts readings that cross the configured thresholds so the alert
#  log (alerts table + alerts.csv) has content for:
#    - the Hive demo section 6 ([F] [G] [H] queries)
#    - the dashboard "Alert History" panel
#
#  The alerts come from the real ingestion path (the backend's threshold
#  check), not written directly, so they are genuine events.
#
#  Why restart first: the backend suppresses a repeat alert for the same
#  sensor+condition for 10 minutes. Restarting clears that in-memory state
#  so the seed always produces the full set. Pass --no-restart to skip it.
#
#  Requires: Windows + Git Bash (the backend runs there). Not WSL.
# ============================================================
cd "$(dirname "$0")" || exit 1

API="http://localhost:5000"
SENSORS="dht22-01 dht22-02"
RESTART=1
[ "$1" = "--no-restart" ] && RESTART=0

# ---- must be Windows (Git Bash), not WSL --------------------------------
if grep -qi microsoft /proc/version 2>/dev/null; then
  echo " This script must run from Windows Git Bash, not WSL."
  echo " (WSL cannot reach the backend on localhost.)"
  exit 1
fi

have() { command -v "$1" >/dev/null 2>&1; }
http_code() { curl -s -m 3 -o /dev/null -w "%{http_code}" "$1" 2>/dev/null; }
alert_count() { curl -s -m 5 "$API/api/alerts?limit=500" 2>/dev/null | grep -o '"condition"' | wc -l; }

# ---- restart the backend so the alert cooldown is cleared ---------------
restart_backend() {
  local pids p
  pids=$(netstat -ano 2>/dev/null | grep ":5000" | grep -i listen | awk '{print $5}' | sort -u)
  for p in $pids; do
    taskkill //F //PID "$p" >/dev/null 2>&1
  done
  sleep 2
  if have cygpath; then
    cmd.exe //c "$(cygpath -w "$(pwd)/run_server.bat")" >/dev/null 2>&1
  else
    cmd.exe //c "$(pwd)\\run_server.bat" >/dev/null 2>&1
  fi
  local i
  for i in 1 2 3 4 5 6 7 8; do
    [ "$(http_code "$API/api/latest")" = "200" ] && return 0
    sleep 2
  done
  return 1
}

echo "============================================================"
echo " Seed alert history"
echo "============================================================"

if [ "$RESTART" = "1" ]; then
  echo " restarting the backend (clears the alert cooldown) ..."
  if restart_backend; then
    echo " backend is up."
  else
    echo " backend did not come back - start run_server.bat and retry."
    exit 1
  fi
fi

if [ "$(http_code "$API/api/latest")" != "200" ]; then
  echo " Backend not reachable at $API. Start run_server.bat first."
  exit 1
fi

# ---- read current thresholds and pick values that breach ----------------
TH=$(curl -s -m 5 "$API/api/thresholds")
get_th() { printf '%s' "$TH" | sed -n "s/.*\"$1\":[ ]*\([0-9.][0-9.]*\).*/\1/p"; }
T_MIN=$(get_th temp_min); T_MAX=$(get_th temp_max)
H_MIN=$(get_th humidity_min); H_MAX=$(get_th humidity_max)
[ -z "$T_MAX" ] && T_MAX=29
[ -z "$H_MAX" ] && H_MAX=75
[ -z "$T_MIN" ] && T_MIN=20
[ -z "$H_MIN" ] && H_MIN=20

T_HIGH=$(awk -v m="$T_MAX" 'BEGIN{printf "%.1f", m+3}')
H_HIGH=$(awk -v m="$H_MAX" 'BEGIN{printf "%.1f", m+6}')
T_OK=$(awk -v a="$T_MIN" -v b="$T_MAX" 'BEGIN{printf "%.1f", (a+b)/2}')
H_OK=$(awk -v a="$H_MIN" -v b="$H_MAX" 'BEGIN{printf "%.1f", (a+b)/2 - 10}')

post() {
  curl -s -m 5 -X POST "$API/api/reading" -H "Content-Type: application/json" \
       -d "$1" >/dev/null 2>&1
  sleep 0.6
}

echo " thresholds : temp ${T_MIN}-${T_MAX} C, humidity ${H_MIN}-${H_MAX} %RH"
echo " breaching  : temp ${T_HIGH} C, humidity ${H_HIGH} %RH"
echo

BEFORE=$(alert_count)

for S in $SENSORS; do
  echo "[$S]"
  post "{\"sensor_id\":\"$S\",\"temperature\":$T_HIGH,\"humidity\":$H_OK}"
  echo "   temp ${T_HIGH} C (over max)       -> temp_high alert"
  post "{\"sensor_id\":\"$S\",\"temperature\":$T_OK,\"humidity\":$H_OK}"
  echo "   back to normal                -> temp_high recovery"
  post "{\"sensor_id\":\"$S\",\"temperature\":$T_OK,\"humidity\":$H_HIGH}"
  echo "   humidity ${H_HIGH} %RH (over max) -> humidity_high alert"
  post "{\"sensor_id\":\"$S\",\"temperature\":$T_OK,\"humidity\":$H_OK}"
  echo "   back to normal                -> humidity_high recovery"
  echo
done

AFTER=$(alert_count)
echo "============================================================"
if [ "$AFTER" -gt "$BEFORE" ]; then
  echo " Done. Alert log grew from $BEFORE to $AFTER entries."
else
  echo " No new alerts were recorded (log still $AFTER entries)."
  echo " The backend may still be inside the cooldown window - rerun"
  echo " without --no-restart, or wait 10 minutes."
fi
echo
echo " Where to see it:"
echo "   dashboard : http://localhost:5000  ->  Alert History panel"
echo "   Hive demo : bash iot_monitor/spark/demo_spark_hive.sh  (section 6)"
echo "   file      : iot_monitor/server/data/alerts.csv"
echo "============================================================"
