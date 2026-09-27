@echo off
REM Start the Flask backend in the background (no console window).
REM Used by the Startup-folder shortcut for auto-start at logon, and by the
REM demo scripts to restart the backend.
cd /d "%~dp0iot_monitor\server"
start "" "C:\Users\1\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\pythonw.exe" app.py
