@echo off
REM Keep the WSL2 distro open so HDFS + Hive stay running between batch runs.
REM Without this, every batch run has to cold-start the services (~1-4 min);
REM with it, a batch takes roughly 30-60 seconds.
REM
REM To start it automatically at logon, put a shortcut to this file in:
REM     Win+R  ->  shell:startup
REM (same trick as the "FYP IoT Backend" shortcut for the Flask backend).
REM
REM Closing the window releases the distro and stops HDFS/Hive.
title WSL keeper - HDFS + Hive
wsl.exe -d Ubuntu bash /mnt/c/Users/1/Desktop/FYP/iot_monitor/spark/keep_wsl_alive.sh
echo.
echo keeper stopped - HDFS and Hive are no longer running.
echo press any key to close
pause >nul
