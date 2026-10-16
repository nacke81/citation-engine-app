@echo off
rem Citation Engine weekly entry point (Task Scheduler). Runs from the runtime clone; logs to %LOCALAPPDATA%\citation-engine\logs\.
set "PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
set "JOB=%LOCALAPPDATA%\citation-engine\app\job\run.py"
set "PYTHONIOENCODING=utf-8"
if not exist "%LOCALAPPDATA%\citation-engine\logs" mkdir "%LOCALAPPDATA%\citation-engine\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "TS=%%i"
"%PY%" "%JOB%" > "%LOCALAPPDATA%\citation-engine\logs\run-%TS%.log" 2>&1
