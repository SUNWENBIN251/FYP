#!/usr/bin/env bash
# =====================================================================
#  Run ONE incremental batch: windowed CSV -> Spark hourly aggregates
#  -> HDFS (partitioned by day) -> Hive partition registration.
#
#  Invoked by the Flask backend (see server/batch.py) as a single
#  wsl.exe call, e.g.:
#
#    wsl.exe -d Ubuntu bash batch_run.sh \
#        --csv    /mnt/c/.../data/batch/7.csv \
#        --from   2026-09-18T00:00:00Z \
#        --to     2026-09-19T00:00:00Z \
#        --result /mnt/c/.../data/batch/7.result.json
#
#  The --result JSON is the ONLY trustworthy success signal: this script
#  is long-running and its exit code can be lost across the wsl.exe
#  boundary, so the backend reads the file instead. A trap guarantees the
#  file is written on every exit path, including failures.
#
#  Can also be run by hand from WSL with --csv/--from/--to/--result.
#
#  Notes:
#   - Hive 4.2.1 needs Java 17 (Java 21 breaks its jline client).
#   - hive.execution.engine=mr is set in hive-site.xml (Tez not installed).
#   - Services are probed first: if the keep-alive process is holding WSL
#     open they are already up and this runs fast; otherwise they are
#     started here so a batch still works after a cold boot.
# =====================================================================

export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export HADOOP_HOME=$HOME/hadoop-3.4.1
export HIVE_HOME=$HOME/apache-hive-4.2.1-bin
export SPARK_HOME=$HOME/spark-4.0.4-bin-hadoop3
export HADOOP_CONF_DIR=$HADOOP_HOME/etc/hadoop
export PATH=$JAVA_HOME/bin:$HADOOP_HOME/bin:$HADOOP_HOME/sbin:$SPARK_HOME/bin:$HIVE_HOME/bin:$PATH
export PYTHONPATH="$SPARK_HOME/python:$SPARK_HOME/python/lib/py4j-0.10.9.9-src.zip"
export HDFS_NAMENODE_USER=$USER HDFS_DATANODE_USER=$USER
export HDFS_SECONDARYNAMENODE_USER=$USER
export YARN_RESOURCEMANAGER_USER=$USER YARN_NODEMANAGER_USER=$USER
export TERM=dumb

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ETL_PY="$(cd "$SCRIPT_DIR/../server/spark" && pwd)/spark_etl.py"
AGG_HDFS=hdfs://localhost:9000/iot/agg_hour

CSV="" ; TS_FROM="" ; TS_TO="" ; RESULT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --csv)    CSV="$2" ; shift 2 ;;
    --from)   TS_FROM="$2" ; shift 2 ;;
    --to)     TS_TO="$2" ; shift 2 ;;
    --result) RESULT="$2" ; shift 2 ;;
    *) echo "unknown argument: $1" ; exit 2 ;;
  esac
done
[ -n "$CSV" ] || { echo "--csv is required" ; exit 2 ; }
[ -n "$RESULT" ] || RESULT="${CSV%.csv}.result.json"

STATUS="failed"
ROWS_IN=""
ROWS_OUT=""
PARTS_JSON="[]"
ERR="script exited before completing"

# ---- result file: written on every exit path ---------------------------
esc() { printf '%s' "$1" | tr -d '"\\' | tr '\n\r\t' '   ' | cut -c1-300 ; }

finish() {
  [ -n "$RESULT" ] || return 0
  mkdir -p "$(dirname "$RESULT")" 2>/dev/null
  printf '{"status":"%s","rows_in":%s,"rows_out":%s,"partitions":%s,"from":"%s","to":"%s","error":"%s"}\n' \
    "$STATUS" "${ROWS_IN:-0}" "${ROWS_OUT:-0}" "${PARTS_JSON:-[]}" \
    "$(esc "$TS_FROM")" "$(esc "$TS_TO")" "$(esc "$ERR")" > "$RESULT"
}
trap finish EXIT

fail() { STATUS="failed" ; ERR="$1" ; echo "  FAILED: $1" ; exit 1 ; }

port_up() { (echo > /dev/tcp/127.0.0.1/"$1") 2>/dev/null ; }

wait_port() { local p=$1 t=$2 i=0
  while [ "$i" -lt "$t" ]; do port_up "$p" && return 0 ; sleep 2 ; i=$((i+2)) ; done
  return 1 ; }

echo "==================== BATCH RUN ===================="
echo "  window : ${TS_FROM:-(beginning)}  ->  ${TS_TO:-(now)}"
echo "  csv    : $CSV"
echo "  result : $RESULT"
echo

# ---- 1) services -------------------------------------------------------
echo "---- services ----"
if port_up 9000 && port_up 9083 && port_up 10000; then
  echo "  HDFS :9000, Metastore :9083, HiveServer2 :10000 already up (keep-alive)"
else
  echo "  starting services (cold start - this is the slow path)"
  if ! port_up 9000; then
    start-dfs.sh >/dev/null 2>&1
    wait_port 9000 60 || fail "HDFS NameNode did not come up on :9000"
  fi
  if ! port_up 9083; then
    rm -f "$HOME"/metastore_db/db.lck
    nohup hive --service metastore > /tmp/ms.log 2>&1 &
    wait_port 9083 90 || fail "Hive metastore did not come up on :9083"
  fi
  if ! port_up 10000; then
    nohup hive --service hiveserver2 > /tmp/hs2.log 2>&1 &
    wait_port 10000 120 || fail "HiveServer2 did not come up on :10000"
  fi
  echo "  services ready"
fi

# ---- 2) one-time migration off the old non-partitioned layout ----------
# The aggregate directory used to hold part-* files at its root. A
# partitioned table ignores those, so remove them once to avoid a
# confusing mixture of layouts.
if hdfs dfs -ls /iot/agg_hour/ 2>/dev/null | grep -qE '/part-'; then
  echo "  migrating: removing legacy non-partitioned output"
  hdfs dfs -rm -r -f /iot/agg_hour >/dev/null 2>&1
fi

# ---- 3) Spark windowed aggregation -------------------------------------
# The raw CSV is not copied into HDFS here: SQLite is the system of record
# and the batch CSV is a throwaway slice, so duplicating it would only add
# storage and a failure mode. It IS copied out of /mnt/c into the Linux
# home first — Spark reads the native filesystem far more reliably than 9p.
echo
echo "---- Spark ETL ----"
cp "$CSV" "$HOME/batch_in.csv" || fail "could not read the batch CSV at $CSV"
SPARK_LOG=/tmp/batch_spark.log
# tee keeps the full job log (for the error tail) while grep streams the marker
# lines live, so Spark and the HDFS write show up on the dashboard as they
# happen instead of all arriving at the end.
CSV_IN="file://$HOME/batch_in.csv" AGG_OUT="$AGG_HDFS/" \
  TS_FROM="$TS_FROM" TS_TO="$TS_TO" \
  spark-submit --master 'local[*]' "$ETL_PY" 2>&1 \
  | tee "$SPARK_LOG" \
  | grep --line-buffered -E 'rows after cleaning|agg total rows|writing hourly aggregates|written to HDFS' \
  || true

RESULT_JSON=$(grep -m1 '^BATCH_RESULT ' "$SPARK_LOG" | sed 's/^BATCH_RESULT //')
if [ -z "$RESULT_JSON" ]; then
  fail "Spark produced no result line: $(tail -3 "$SPARK_LOG" | tr '\n' ' ')"
fi

PARSED=$(printf '%s' "$RESULT_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('%s|%s' % (d.get('rows_in') or 0, d.get('rows_out') or 0))
" 2>/dev/null) || fail "could not parse the Spark result line"

ROWS_IN=${PARSED%%|*}
ROWS_OUT=${PARSED#*|}

# Lift the partition array straight out of the ETL's JSON so the result file
# carries a real array for the backend to consume (it joins the elements).
PARTS_JSON=$(printf '%s' "$RESULT_JSON" | sed -n 's/.*"partitions": *\(\[[^]]*\]\).*/\1/p')
[ -n "$PARTS_JSON" ] || PARTS_JSON="[]"

# Left-open/right-closed window means an empty batch is legitimate: the
# previous run already covered this period. Nothing to write, but the run
# itself succeeded.
echo "  rows_in=$ROWS_IN rows_out=$ROWS_OUT partitions=$PARTS_JSON"

# ---- 4) Hive: (re)register the table and its partitions ----------------
# Dropping first keeps the schema in step with the ETL across upgrades; the
# table is EXTERNAL so this removes metadata only, never the data in HDFS.
echo
echo "---- Hive partition registration ----"
BQ() { beeline -u jdbc:hive2://localhost:10000 -e "$1" 2>&1 \
        | grep -aE '^[|+]|Error' || true ; }

BQ "CREATE DATABASE IF NOT EXISTS iot;" >/dev/null
BQ "DROP TABLE IF EXISTS iot.agg_hour;" >/dev/null
BQ "CREATE EXTERNAL TABLE iot.agg_hour (
  sensor_id STRING, hour STRING,
  avg_temp DOUBLE, max_temp DOUBLE, min_temp DOUBLE,
  avg_hum  DOUBLE, max_hum  DOUBLE, min_hum  DOUBLE,
  cnt BIGINT)
PARTITIONED BY (dt STRING)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION '$AGG_HDFS';" >/dev/null

MSCK_OUT=$(BQ "MSCK REPAIR TABLE iot.agg_hour;")
printf '%s\n' "$MSCK_OUT" | grep -i 'Error' && fail "MSCK REPAIR TABLE failed"

echo "--- hourly rows now in iot.agg_hour ---"
BQ "SELECT COUNT(*) AS hourly_rows FROM iot.agg_hour;"

# ---- done --------------------------------------------------------------
STATUS="success"
ERR=""
echo
echo "==================== BATCH COMPLETE ===================="
