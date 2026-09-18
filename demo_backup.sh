#!/usr/bin/env bash
# ============================================================
#  Automatic Backup Demo
#  Run:  bash demo_backup.sh
#  Note: runs entirely on the Windows side; WSL is not needed
# ============================================================
cd "$(dirname "$0")" || exit 1

PY="C:/Users/1/AppData/Local/Microsoft/WindowsApps/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/python.exe"
[ -x "$PY" ] || PY="python"

BK="iot_monitor/server/data/backups"
LIVE="iot_monitor/server/data/monitor.db"
ROOT="$(pwd)"

line() { printf '%s\n' "------------------------------------------------------------"; }

echo "============================================================"
echo " Automatic Backup Demo"
echo "============================================================"
echo
echo "[1] Backup directory -- one timestamped folder per backup"
line
ls -1 "$BK" | sed 's/^/    /'
echo
echo "[2] Contents of the most recent backup"
line
LATEST=$(ls -1 "$BK" | sort | tail -1)
echo "    Folder: $LATEST"
ls -1 "$BK/$LATEST" | sed 's/^/      /'
echo
echo "[3] Verify the backup is valid -- compare it with the live database"
line
PYTHONIOENCODING=utf-8 "$PY" - "$BK/$LATEST/monitor.db" "$LIVE" <<'PY'
import sqlite3, sys
live = sqlite3.connect(sys.argv[2])
bk = sqlite3.connect(sys.argv[1])
ln = live.execute("select count(*) from readings").fetchone()[0]
bn = bk.execute("select count(*) from readings").fetchone()[0]
lt = [r[0] for r in live.execute(
    "select name from sqlite_master where type='table' order by name")]
bt = [r[0] for r in bk.execute(
    "select name from sqlite_master where type='table' order by name")]
print("    live DB   readings rows = %d" % ln)
print("    backup DB readings rows = %d" % bn)
print("    data identical   : %s" % ("YES" if ln == bn else "NO"))
print("    schema identical : %s" % ("YES" if lt == bt else "NO"))
print("    tables in backup : %s" % ", ".join(bt))
live.close(); bk.close()
PY
echo
echo "[4] Prove it is automatic -- restart the backend, take no backup action"
line
BEFORE=$(ls -1 "$BK" | wc -l)
echo "    backups before restart: $BEFORE"
PID=$(netstat -ano | grep ":5000" | grep LISTENING | awk '{print $5}' | head -1)
if [ -n "$PID" ]; then
  echo "    >>> stopping backend (pid=$PID) and restarting it ..."
  taskkill //F //PID "$PID" >/dev/null 2>&1
  sleep 1
else
  echo "    (backend was not running; starting it now)"
fi
cmd.exe //c "$(cygpath -w "$ROOT/run_server.bat" 2>/dev/null || echo "$ROOT/run_server.bat")" >/dev/null 2>&1
sleep 8
AFTER=$(ls -1 "$BK" | wc -l)
echo "    backups after restart : $AFTER"
echo "    newest backup         : $(ls -1 "$BK" | sort | tail -1)"
echo
if [ "$AFTER" -gt "$BEFORE" ]; then
  echo "    Result: $((AFTER - BEFORE)) new backup created automatically at startup"
else
  echo "    Result: count unchanged (a backup may not be due yet);"
  echo "            run 'python backup.py' inside server/ to verify manually"
fi
echo
echo "[5] Backend status"
line
curl -s -m 5 -o /dev/null -w "    /api/latest -> HTTP %{http_code}\n" http://localhost:5000/api/latest
echo
echo "============================================================"
echo " Demo complete"
echo "============================================================"
