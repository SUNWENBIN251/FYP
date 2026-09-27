# -*- coding: utf-8 -*-
"""Spark ETL: read readings.csv, compute hourly aggregates, write the result
to HDFS partitioned by day so Hive can query it via an external table.

Environment variables:
  CSV_IN    input CSV path/URI (default file:///home/swb/readings.csv)
  AGG_OUT   HDFS output path    (default hdfs://localhost:9000/iot/agg_hour/)
  TS_FROM   optional window start, exclusive  (ISO-8601 UTC, e.g. 2026-09-18T00:00:00Z)
  TS_TO     optional window end,   inclusive  (ISO-8601 UTC)

With no window the job processes everything, which makes it both the
incremental path and the full-rebuild path. Output is partitioned by dt
(YYYY-MM-DD) and written in dynamic overwrite mode, so a run only replaces
the days it actually touched — re-running a window is idempotent.
"""
import json
import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import avg, max as mx, min as mn, count as cnt
from pyspark.sql.functions import col, date_format, to_timestamp
from pyspark.sql.types import DoubleType

CSV_IN = os.environ.get("CSV_IN", "file:///home/swb/readings.csv")
AGG_OUT = os.environ.get("AGG_OUT", "hdfs://localhost:9000/iot/agg_hour/")
TS_FROM = os.environ.get("TS_FROM", "").strip()
TS_TO = os.environ.get("TS_TO", "").strip()

# dynamic partition overwrite: mode("overwrite") then replaces only the
# partitions present in this DataFrame instead of wiping the whole table.
spark = (SparkSession.builder
         .appName("iot_etl")
         .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
         .getOrCreate())

# 1. read the source CSV (path configurable via CSV_IN)
df = spark.read.option("header", True).csv(CSV_IN)

# 2. rename + cast
df = (df
      .withColumnRenamed("timestamp", "ts")
      .withColumnRenamed("temperature_c", "temperature")
      .withColumnRenamed("humidity_rh", "humidity")
      .withColumn("temperature", col("temperature").cast(DoubleType()))
      .withColumn("humidity", col("humidity").cast(DoubleType())))

# 3. clean
df = df.filter(
    col("temperature").isNotNull() & col("humidity").isNotNull() &
    col("temperature").between(0, 50) & col("humidity").between(0, 100))

# 4. restrict to the batch window. ISO-8601 UTC strings sort chronologically,
#    so a plain string comparison is correct. Left-open / right-closed keeps a
#    reading on a boundary out of two consecutive batches.
if TS_FROM:
    df = df.filter(col("ts") > TS_FROM)
if TS_TO:
    df = df.filter(col("ts") <= TS_TO)

rows_in = df.count()
print("rows after cleaning:", rows_in)

# 5. hourly aggregates, plus the day used as the partition key
agg = (df
       .withColumn("ts_parsed", to_timestamp(col("ts"), "yyyy-MM-dd'T'HH:mm:ss'Z'"))
       .withColumn("hour", date_format(col("ts_parsed"), "yyyy-MM-dd HH:00"))
       .withColumn("dt", date_format(col("ts_parsed"), "yyyy-MM-dd"))
       .groupBy("sensor_id", "hour", "dt")
       .agg(avg("temperature").alias("avg_temp"),
            mx("temperature").alias("max_temp"),
            mn("temperature").alias("min_temp"),
            avg("humidity").alias("avg_hum"),
            mx("humidity").alias("max_hum"),
            mn("humidity").alias("min_hum"),
            cnt("*").alias("cnt")))

# 6. show sample
print("=== agg_hour sample (per sensor, per hour) ===")
agg.orderBy("hour", "sensor_id").show(8, truncate=False)
rows_out = agg.count()
print("agg total rows:", rows_out)

# 7. write to HDFS, one directory per day, no header
print("writing hourly aggregates to HDFS ...")
agg.write.mode("overwrite").partitionBy("dt").csv(AGG_OUT)
print("written to HDFS:", AGG_OUT)

# 8. machine-readable summary for the calling script (a JSON line is far more
#    reliable to parse than the multi-line human output above)
partitions = sorted(r["dt"] for r in agg.select("dt").distinct().collect())
print("BATCH_RESULT " + json.dumps({
    "rows_in": rows_in,
    "rows_out": rows_out,
    "partitions": partitions,
    "from": TS_FROM or None,
    "to": TS_TO or None,
}))

spark.stop()
