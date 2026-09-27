#!/usr/bin/env bash
# =====================================================================
#  Keep the WSL2 distro open, with HDFS and Hive running inside it.
#
#  Why this exists: WSL2 shuts the distro down as soon as the last
#  wsl.exe call returns, which kills every daemon in it. Without a
#  process holding the distro open, each batch run would have to start
#  HDFS and Hive from cold (~1-4 minutes, HiveServer2 is the slow one).
#  With this running, a batch is just "Spark job + partition
#  registration" — about 30-60 seconds.
#
#  Started at logon via start_wsl_keeper.bat. If it is not running, the
#  batch script notices the ports are down and starts the services
#  itself, so a batch still works — it is just slower.
#
#  YARN is deliberately NOT started here: the batch path uses Spark's
#  local[*] master and Hive's mr engine, neither of which needs it.
#  demo_spark_hive.sh starts YARN itself when it needs it.
#
#  Log: tail -f the window started by start_wsl_keeper.bat
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

port_up() { (echo > /dev/tcp/127.0.0.1/"$1") 2>/dev/null ; }

wait_port() { local p=$1 t=$2 i=0
  while [ "$i" -lt "$t" ]; do port_up "$p" && return 0 ; sleep 2 ; i=$((i+2)) ; done
  return 1 ; }

echo "============================================================"
echo " WSL keeper - holding the distro open for HDFS + Hive"
echo " keep this window open; closing it stops the batch layer"
echo "============================================================"

if port_up 9000; then
  echo " HDFS      :9000   already up"
else
  echo " HDFS      :9000   starting ..."
  start-dfs.sh >/dev/null 2>&1
  wait_port 9000 60 && echo " HDFS      :9000   OK" || echo " HDFS      :9000   FAILED"
fi

if port_up 9083; then
  echo " Metastore :9083   already up"
else
  echo " Metastore :9083   starting ..."
  rm -f "$HOME"/metastore_db/db.lck
  nohup hive --service metastore > /tmp/ms.log 2>&1 &
  wait_port 9083 90 && echo " Metastore :9083   OK" || echo " Metastore :9083   FAILED"
fi

if port_up 10000; then
  echo " HiveServer2 :10000 already up"
else
  echo " HiveServer2 :10000 starting ..."
  nohup hive --service hiveserver2 > /tmp/hs2.log 2>&1 &
  wait_port 10000 120 && echo " HiveServer2 :10000 OK" || echo " HiveServer2 :10000 FAILED"
fi

echo
echo " ready - batch runs will now reuse these services."
echo " press Ctrl+C (or close this window) to release the distro."

trap 'echo ; echo " keeper stopped - releasing WSL." ; exit 0' INT TERM
sleep infinity
