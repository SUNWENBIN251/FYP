#!/usr/bin/env bash
# =====================================================================
#  Start HDFS + YARN + Hive (metastore & HiveServer2) only.
#  Use this when you want to type SQL by hand in beeline, instead of
#  running the full demo pipeline.
#
#  IMPORTANT — run this INSIDE a WSL terminal that stays open:
#      wsl -d Ubuntu
#      bash /mnt/c/Users/1/Desktop/FYP/iot_monitor/spark/start_hive_services.sh
#      beeline -u jdbc:hive2://localhost:10000
#
#  If you launch it as `wsl -d Ubuntu bash ...` (one-off), the services
#  are killed the moment the command returns — WSL2 shuts the distro down.
# =====================================================================
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export HADOOP_HOME=$HOME/hadoop-3.4.1
export HIVE_HOME=$HOME/apache-hive-4.2.1-bin
export SPARK_HOME=$HOME/spark-4.0.4-bin-hadoop3
export HADOOP_CONF_DIR=$HADOOP_HOME/etc/hadoop
export PATH=$JAVA_HOME/bin:$HADOOP_HOME/bin:$HADOOP_HOME/sbin:$SPARK_HOME/bin:$HIVE_HOME/bin:$PATH
export HDFS_NAMENODE_USER=$USER HDFS_DATANODE_USER=$USER
export HDFS_SECONDARYNAMENODE_USER=$USER
export YARN_RESOURCEMANAGER_USER=$USER YARN_NODEMANAGER_USER=$USER
export TERM=dumb

wait_port() { local h=$1 p=$2 t=$3 i=0
  while [ $i -lt $t ]; do (echo > /dev/tcp/$h/$p) 2>/dev/null && return 0; sleep 2; i=$((i+2)); done; return 1; }

echo "==================== STARTING SERVICES ===================="
pkill -f 'hive.metastore' 2>/dev/null || true
pkill -f 'HiveServer2' 2>/dev/null || true
rm -f $HOME/metastore_db/db.lck
start-dfs.sh >/dev/null 2>&1 || true
start-yarn.sh >/dev/null 2>&1 || true
wait_port localhost 9000 60 && echo "  HDFS NameNode :9000   OK"

nohup hive --service metastore > /tmp/ms.log 2>&1 &
wait_port localhost 9083 90 && echo "  Hive Metastore :9083  OK"
nohup hive --service hiveserver2 > /tmp/hs2.log 2>&1 &
wait_port localhost 10000 120 && echo "  HiveServer2 :10000    OK"

echo
echo "==================== READY ===================="
echo "Connect with:"
echo "  beeline -u jdbc:hive2://localhost:10000"
echo
echo "Handy queries:"
echo "  SHOW TABLES IN iot;"
echo "  SELECT sensor_id, COUNT(*) AS over_limit_hours FROM iot.agg_hour"
echo "    WHERE max_temp > 28 OR max_hum > 60 GROUP BY sensor_id;"
echo "  SELECT SUBSTR(hour,1,10) AS day, ROUND(AVG(avg_temp),1) FROM iot.agg_hour"
echo "    GROUP BY SUBSTR(hour,1,10) ORDER BY day;"
echo "  !quit   (to exit beeline)"
echo
echo "NOTE: keep this WSL terminal open; closing it stops the services."
