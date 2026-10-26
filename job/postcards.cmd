@echo off
rem Postcard code step (Task Scheduler, EVERY 12 HOURS). Portal keeps a client's postcard code 72h, so a run must land inside every 72h window.
rem Runs from the runtime clone. The log holds row ids and outcomes only, never a code (job\postcard_step.py).
setlocal enabledelayedexpansion
(
set "PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
set "APP=%LOCALAPPDATA%\citation-engine\app"
set "PYTHONIOENCODING=utf-8"
if not exist "%LOCALAPPDATA%\citation-engine\logs" mkdir "%LOCALAPPDATA%\citation-engine\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "TS=%%i"
"!PY!" "!APP!\job\postcard_step.py" > "%LOCALAPPDATA%\citation-engine\logs\postcards-!TS!.log" 2>&1
exit /b
)
