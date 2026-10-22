@echo off
rem Citation Engine weekly entry point (Task Scheduler). Runs from the runtime clone; logs to %LOCALAPPDATA%\citation-engine\logs\.
rem Whole body is one parenthesised block: cmd parses it before job\update.py can fast-forward this very file.
rem Set WEEKLY_UPDATE_ONLY=1 to run only the update block (dry check, no Directory traffic).
setlocal enabledelayedexpansion
(
set "PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
set "APP=%LOCALAPPDATA%\citation-engine\app"
set "PYTHONIOENCODING=utf-8"
if not exist "%LOCALAPPDATA%\citation-engine\logs" mkdir "%LOCALAPPDATA%\citation-engine\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "TS=%%i"
set "LOG=%LOCALAPPDATA%\citation-engine\logs\run-!TS!.log"
"!PY!" "!APP!\job\update.py" "!APP!" > "!LOG!" 2>&1
if defined WEEKLY_UPDATE_ONLY ( echo update-only: not running run.py >> "!LOG!" ) else ( "!PY!" "!APP!\job\run.py" >> "!LOG!" 2>&1 )
exit /b
)
