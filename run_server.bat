@echo off
REM Start the Flask backend in the background (no console window).
REM Used by Windows Task Scheduler for auto-start at logon.
cd /d "%~dp0iot_monitor\server"
start "" "C:\Users\1\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\pythonw.exe" app.py
