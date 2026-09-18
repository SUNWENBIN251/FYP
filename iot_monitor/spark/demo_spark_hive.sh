#!/usr/bin/env bash
# =====================================================================
#  Spark + Hive demo for the IoT environmental monitoring project
#  Run INSIDE WSL (Ubuntu):   bash demo_spark_hive.sh
#
#  Pipeline:
#    1. start HDFS + YARN
#    2. start Hive metastore + HiveServer2
#    3. upload the backend's readings.csv to HDFS
#    4. PySpark: hourly aggregates (avg/max/min temp & humidity)
#    5. Hive external table + SQL queries over the aggregates
#
#  Notes:
#   - Hive 4.2.1 needs Java 17 (Java 21 breaks its jline client).
#   - hive.execution.engine=mr is set in hive-site.xml (Tez is not installed).
#   - Everything runs in ONE invocation because WSL2 shuts the distro down
#     when a wsl.exe call returns.
# =====================================================================
set +e
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

CSV_SRC=/mnt/c/Users/1/Desktop/FYP/iot_monitor/server/data/readings.csv
ALERTS_CSV=/mnt/c/Users/1/Desktop/FYP/iot_monitor/server/data/alerts.csv
ETL_PY=/mnt/c/Users/1/Desktop/FYP/iot_monitor/server/spark/spark_etl.py

wait_port() { local h=$1 p=$2 t=$3 i=0
  while [ $i -lt $t ]; do (echo > /dev/tcp/$h/$p) 2>/dev/null && return 0; sleep 2; i=$((i+2)); done; return 1; }

echo "==================== 1) HDFS + YARN ===================="
pkill -f 'hive.metastore' 2>/dev/null || true
pkill -f 'HiveServer2' 2>/dev/null || true
rm -f $HOME/metastore_db/db.lck
start-dfs.sh >/dev/null 2>&1 || true
start-yarn.sh >/dev/null 2>&1 || true
wait_port localhost 9000 60 && echo "  HDFS NameNode :9000  OK"

echo
echo "==================== 2) HIVE SERVICES ===================="
nohup hive --service metastore > /tmp/ms.log 2>&1 &
wait_port localhost 9083 90 && echo "  Metastore :9083   OK"
nohup hive --service hiveserver2 > /tmp/hs2.log 2>&1 &
wait_port localhost 10000 120 && echo "  HiveServer2 :10000 OK"

echo
echo "==================== 3) CSV -> HDFS ===================="
cp "$CSV_SRC" $HOME/readings.csv
hdfs dfs -mkdir -p /iot/raw
hdfs dfs -put -f $HOME/readings.csv /iot/raw/readings.csv
echo "  upload: $(hdfs dfs -ls -h /iot/raw | tail -1)"
if [ -f "$ALERTS_CSV" ]; then
  tail -n +2 "$ALERTS_CSV" > $HOME/alerts.csv    # drop header row for Hive
  hdfs dfs -mkdir -p /iot/alerts
  hdfs dfs -put -f $HOME/alerts.csv /iot/alerts/alerts.csv
  echo "  alerts: $(hdfs dfs -ls -h /iot/alerts | tail -1)"
else
  # no alert history locally -> remove any stale copy left in HDFS by a previous run
  hdfs dfs -rm -r -f /iot/alerts >/dev/null 2>&1
  echo "  (no alerts.csv yet - cleared any previous HDFS copy)"
fi

echo
echo "==================== 4) SPARK HOURLY AGGREGATION ===================="
spark-submit --master local[*] "$ETL_PY" 2>/dev/null | grep -E '清洗后|agg 总行数|已写入'

echo
echo "==================== 5) HIVE SQL OVER THE AGGREGATES ===================="
BQ() { beeline -u jdbc:hive2://localhost:10000 -e "$1" 2>&1 \
        | grep -aE '^[|+]|Error' || true; }

BQ "CREATE DATABASE IF NOT EXISTS iot;"
BQ "DROP TABLE IF EXISTS iot.agg_hour;"
BQ "CREATE EXTERNAL TABLE iot.agg_hour (
  sensor_id STRING, hour STRING,
  avg_temp DOUBLE, max_temp DOUBLE, min_temp DOUBLE,
  avg_hum  DOUBLE, max_hum  DOUBLE, min_hum  DOUBLE,
  cnt BIGINT)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 'hdfs://localhost:9000/iot/agg_hour';"

echo "--- total hourly rows ---"
BQ "SELECT COUNT(*) AS total_hourly_rows FROM iot.agg_hour;"

echo "--- latest hourly averages per sensor ---"
BQ "SELECT sensor_id, hour, ROUND(avg_temp,1) AS avg_t, ROUND(max_temp,1) AS max_t, ROUND(avg_hum,1) AS avg_h, cnt
FROM iot.agg_hour ORDER BY hour DESC, sensor_id LIMIT 10;"

echo "--- hottest hours recorded ---"
BQ "SELECT hour, sensor_id, ROUND(max_temp,1) AS peak_temp FROM iot.agg_hour ORDER BY max_temp DESC LIMIT 5;"

echo
echo "--- [A] Compliance: hours that exceeded the temperature limit ---"
BQ "SELECT hour, sensor_id, ROUND(max_temp,1) AS peak_t FROM iot.agg_hour WHERE max_temp > 28 ORDER BY max_temp DESC LIMIT 10;"

echo "--- [B] Total over-limit hours per sensor (temp>28 OR humidity>60) ---"
BQ "SELECT sensor_id, COUNT(*) AS over_limit_hours FROM iot.agg_hour WHERE max_temp > 28 OR max_hum > 60 GROUP BY sensor_id;"

echo "--- [C] Daily trend (average / peak temperature and average humidity) ---"
BQ "SELECT SUBSTR(hour,1,10) AS day, sensor_id, ROUND(AVG(avg_temp),1) AS avg_t, ROUND(MAX(max_temp),1) AS peak_t, ROUND(AVG(avg_hum),1) AS avg_h FROM iot.agg_hour GROUP BY SUBSTR(hour,1,10), sensor_id ORDER BY day, sensor_id;"

echo "--- [D] Data completeness: hours with fewer than 55 readings (gaps) ---"
BQ "SELECT hour, sensor_id, cnt FROM iot.agg_hour WHERE cnt < 55 ORDER BY cnt LIMIT 10;"

echo "--- [E] Cross-sensor comparison of hourly average temperature ---"
BQ "SELECT hour, MAX(CASE WHEN sensor_id='dht22-01' THEN ROUND(avg_temp,1) END) AS s1_temp, MAX(CASE WHEN sensor_id='dht22-02' THEN ROUND(avg_temp,1) END) AS s2_temp FROM iot.agg_hour GROUP BY hour ORDER BY hour DESC LIMIT 10;"

echo
echo "==================== 6) HIVE SQL OVER ALERT HISTORY ===================="
if hdfs dfs -test -e /iot/alerts/alerts.csv; then
  BQ "DROP TABLE IF EXISTS iot.alerts;"
  BQ "CREATE EXTERNAL TABLE iot.alerts (
    ts STRING, sensor_id STRING, kind STRING, condition STRING, value DOUBLE, threshold DOUBLE)
  ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
  STORED AS TEXTFILE
  LOCATION 'hdfs://localhost:9000/iot/alerts';"

  echo "--- [F] Alert events by condition and type ---"
  BQ "SELECT condition, kind, COUNT(*) AS n FROM iot.alerts GROUP BY condition, kind ORDER BY n DESC;"

  echo "--- [G] Alert events per sensor ---"
  BQ "SELECT sensor_id, COUNT(*) AS alert_events FROM iot.alerts WHERE kind='alert' GROUP BY sensor_id;"

  echo "--- [H] Recent alert timeline ---"
  BQ "SELECT ts, sensor_id, kind, condition, value, threshold FROM iot.alerts ORDER BY ts DESC LIMIT 10;"
else
  echo "  (no alert history to analyse yet)"
fi

echo
echo "==================== DEMO COMPLETE ===================="
