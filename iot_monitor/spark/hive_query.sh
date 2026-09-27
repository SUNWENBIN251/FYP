#!/usr/bin/env bash
# =====================================================================
#  Run ONE Hive query and print its rows to stdout as TSV.
#
#  Called by server/hive.py:
#
#    wsl.exe -d Ubuntu bash hive_query.sh --sql "<sql>"
#
#  The query arrives as an argument, so the caller must pass it as a
#  single argv entry (Python's subprocess does that natively — no shell
#  is involved on the Windows side). It is quoted here before reaching
#  beeline, so it is never re-parsed.
#
#  Rows go to stdout rather than to a file under /mnt/c: writing a file
#  into a directory that Windows created moments earlier can fail, because
#  WSL2's drvfs does not always pick up a fresh directory immediately.
#  beeline's INFO logging goes to stderr and stays out of the way.
#
#  On failure a single line starting with "#ERROR " is printed instead.
#  (beeline's -f script mode does not execute under Hive 4.2.1, so -e is
#  used.)
# =====================================================================

export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export HADOOP_HOME=$HOME/hadoop-3.4.1
export HIVE_HOME=$HOME/apache-hive-4.2.1-bin
export HADOOP_CONF_DIR=$HADOOP_HOME/etc/hadoop
export PATH=$JAVA_HOME/bin:$HADOOP_HOME/bin:$HIVE_HOME/bin:$PATH
export TERM=dumb

SQL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --sql) SQL="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$SQL" ] || { echo "#ERROR --sql is required"; exit 2; }

port_up() { (echo > /dev/tcp/127.0.0.1/"$1") 2>/dev/null ; }

# Fail fast rather than waiting on a connection that will never open: a
# dashboard query must not block for the minutes a cold start would take.
if ! port_up 10000; then
  echo "#ERROR Hive is not running. Start start_wsl_keeper.bat, or press Process on a batch first."
  exit 1
fi

beeline -u jdbc:hive2://localhost:10000 --outputformat=tsv2 \
        -e "$SQL" 2>/tmp/hive_query.err
rc=$?

if [ $rc -ne 0 ] || grep -qi 'error' /tmp/hive_query.err 2>/dev/null; then
  msg=$(grep -i -m1 'error' /tmp/hive_query.err 2>/dev/null | tr -d '\r')
  [ -n "$msg" ] || msg="beeline exited with code $rc"
  echo "#ERROR $msg"
  exit 1
fi

exit 0
