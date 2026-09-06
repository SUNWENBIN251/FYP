# -*- coding: utf-8 -*-
"""Spark ETL (Plan A): read readings.csv, compute hourly aggregates,
write the result to HDFS so Hive can query it via an external table."""
from pyspark.sql import SparkSession
from pyspark.sql.functions import avg, max as mx, min as mn, count as cnt
from pyspark.sql.functions import col, date_format, to_timestamp
from pyspark.sql.types import DoubleType

spark = SparkSession.builder.appName("iot_etl").getOrCreate()

# 1. read local CSV (copied from backend)
df = spark.read.option("header", True).csv("file:///home/swb/readings.csv")

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

print("清洗后行数:", df.count())

# 4. hourly aggregates
agg = (df
       .withColumn("hour", date_format(
           to_timestamp(col("ts"), "yyyy-MM-dd'T'HH:mm:ss'Z'"), "yyyy-MM-dd HH:00"))
       .groupBy("sensor_id", "hour")
       .agg(avg("temperature").alias("avg_temp"),
            mx("temperature").alias("max_temp"),
            mn("temperature").alias("min_temp"),
            avg("humidity").alias("avg_hum"),
            mx("humidity").alias("max_hum"),
            mn("humidity").alias("min_hum"),
            cnt("*").alias("cnt")))

# 5. show sample
print("=== agg_hour 示例（每传感器每小时）===")
agg.orderBy("hour", "sensor_id").show(8, truncate=False)
print("agg 总行数:", agg.count())

# 6. write result to HDFS without header (cleaner for Hive external table)
agg.write.mode("overwrite").csv(
    "hdfs://localhost:9000/iot/agg_hour/")
print("已写入 HDFS: /iot/agg_hour/")

spark.stop()
