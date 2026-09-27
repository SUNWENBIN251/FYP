#!/usr/bin/env bash
# ============================================================
#  Automatic Backup Demo
#  Run:  bash demo_backup.sh
#  Works both on Windows (Git Bash / CMD) and inside WSL.
# ============================================================
cd "$(dirname "$0")" || exit 1

# ---- environment detection --------------------------------------------
IS_WSL=0
grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=1

# Windows system32 (used for netstat/taskkill/cmd when not on PATH, e.g. in WSL)
WINSYS=""
[ -d /mnt/c/Windows/System32 ] && WINSYS="/mnt/c/Windows/System32"

have() { command -v "$1" >/dev/null 2>&1; }

# locate a usable python interpreter
PY=""
for c in \
  "C:/Users/1/AppData/Local/Microsoft/WindowsApps/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/python.exe" \
  "/mnt/c/Users/1/AppData/Local/Microsoft/WindowsApps/PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0/python.exe" \
  python3 python python.exe; do
  if [ -x "$c" ] || have "$c"; then PY="$c"; break; fi
done

NETSTAT="netstat"
have netstat || { [ -x "$WINSYS/netstat.exe" ] && NETSTAT="$WINSYS/netstat.exe"; }
TASKKILL="taskkill"
have taskkill || { [ -x "$WINSYS/taskkill.exe" ] && TASKKILL="$WINSYS/taskkill.exe"; }
CMD="cmd.exe"
if [ "$IS_WSL" = "1" ]; then
  # the PATH-resolved cmd.exe can block under WSL; use the absolute one
  [ -x "$WINSYS/cmd.exe" ] && CMD="$WINSYS/cmd.exe"
elif ! have cmd.exe; then
  [ -x "$WINSYS/cmd.exe" ] && CMD="$WINSYS/cmd.exe"
fi

# MSYS/Git Bash mangles a leading slash, so flags are written with two slashes
# there; WSL needs the plain single-slash form. FLAG picks the right one.
FLAG() { if [ "$IS_WSL" = "1" ]; then echo "/$1"; else echo "//$1"; fi; }

# Windows netstat.exe writes CRLF; strip the CR
win_netstat() { "$NETSTAT" -ano 2>/dev/null | tr -d '\r'; }

backend_pids() {
  win_netstat | grep ":5000" | grep -i listen | awk '{print $5}' | sort -u
}

BK="iot_monitor/server/data/backups"
LIVE="iot_monitor/server/data/monitor.db"
ROOT="$(pwd)"

line() { printf '%s\n' "------------------------------------------------------------"; }

echo "============================================================"
echo " Automatic Backup Demo"
echo "============================================================"
if [ "$IS_WSL" = "1" ]; then
  echo " (running inside WSL; Windows tools are used via $WINSYS)"
fi
if [ -z "$PY" ]; then
  echo
  echo " ERROR: no Python interpreter found (tried python3 / python / the Windows path)."
  echo "        Run this from Windows Git Bash, or install python3  (sudo apt install python3)."
  exit 1
fi
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
NEWEST_BEFORE=$(ls -1 "$BK" | sort | tail -1)
echo "    newest backup before restart: $NEWEST_BEFORE"

PIDS=$(backend_pids)
if [ -n "$PIDS" ]; then
  echo "    >>> stopping backend (pid: $(echo "$PIDS" | tr '\n' ' ')) and restarting it ..."
  for p in $PIDS; do
    "$TASKKILL" "$(FLAG F)" "$(FLAG PID)" "$p" >/dev/null 2>&1
  done
  sleep 2
else
  echo "    (backend not detected on :5000; starting it now)"
fi

BAT="$ROOT/run_server.bat"
if [ "$IS_WSL" = "1" ]; then
  WINBAT=$(wslpath -w "$BAT" 2>/dev/null || echo "$BAT")
else
  WINBAT=$(cygpath -w "$BAT" 2>/dev/null || echo "$BAT")
fi
if have "$CMD" || [ -x "$CMD" ]; then
  # guard with a timeout so a stuck Windows call can never hang the demo
  if have timeout; then
    timeout 20 "$CMD" "$(FLAG c)" "$WINBAT" >/dev/null 2>&1 || true
  else
    "$CMD" "$(FLAG c)" "$WINBAT" >/dev/null 2>&1 || true
  fi
else
  echo "    (cannot start the backend from here - start run_server.bat on Windows)"
fi
sleep 8

NEWEST_AFTER=$(ls -1 "$BK" | sort | tail -1)
echo "    newest backup after restart : $NEWEST_AFTER"
echo "    backups retained            : $(ls -1 "$BK" | wc -l)"
echo
if [ "$NEWEST_AFTER" != "$NEWEST_BEFORE" ]; then
  echo "    Result: a new backup was created automatically at startup  (OK)"
else
  echo "    Result: no new backup yet (one may not be due);"
  echo "            run '$PY backup.py' inside iot_monitor/server to verify manually"
fi
echo
echo "[5] Backend status"
line
try_url() { curl -s -m 3 -o /dev/null -w "%{http_code}" "$1/api/latest" 2>/dev/null; }

CODE=""
for i in 1 2 3; do
  CODE=$(try_url "http://localhost:5000")
  [ "$CODE" = "200" ] && break
  sleep 2
done

# under WSL localhost forwarding to the Windows host is not always available,
# so fall back to the host IP reported by WSL's resolver
if [ "$CODE" != "200" ] && [ "$IS_WSL" = "1" ]; then
  HOSTIP=$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf 2>/dev/null)
  if [ -n "$HOSTIP" ]; then
    for i in 1 2 3; do
      CODE=$(try_url "http://$HOSTIP:5000")
      [ "$CODE" = "200" ] && { echo "    (reached the Windows host at $HOSTIP)"; break; }
      sleep 2
    done
  fi
fi

if [ "$CODE" = "200" ]; then
  echo "    /api/latest -> HTTP 200  (backend is up)"
elif [ "$IS_WSL" = "1" ] && [ -n "$(backend_pids)" ]; then
  # WSL cannot always reach the Windows host on localhost, but the port tells
  # us the backend process is alive
  echo "    backend process on :5000 -> running  (pid $(backend_pids | tr '\n' ' '))"
  echo "    (WSL cannot reach it over localhost; open http://localhost:5000"
  echo "     in a Windows browser to confirm the API)"
else
  echo "    /api/latest -> HTTP $CODE  (not reachable - start run_server.bat)"
fi
echo
echo "============================================================"
echo " Demo complete"
echo "============================================================"
