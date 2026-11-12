@echo off
rem Verify Now bridge pass (Task Scheduler, EVERY 60 s, task CitationEngineVerifyBridge). One pass = sweep, first-use cards, claim, start the send run.
rem Runs from the runtime clone only. No overlap: the task is registered with MultipleInstancesPolicy IgnoreNew, so a tick that lands while a pass runs is dropped.
rem Runs under the citation-submitter env: HERMES_HOME and BW_ENV_FILE point at that profile, and the vault helpers read BW_* from its .env themselves.
rem No credential is copied, parsed or echoed here. The log holds request ids and outcomes only (job\verify_bridge.py never prints a code).
setlocal enabledelayedexpansion
(
set "PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
set "APP=%LOCALAPPDATA%\citation-engine\app"
set "HERMES_HOME=%LOCALAPPDATA%\hermes\profiles\citation-submitter"
set "BW_ENV_FILE=!HERMES_HOME!\.env"
set "PYTHONIOENCODING=utf-8"
if not exist "%LOCALAPPDATA%\citation-engine\logs" mkdir "%LOCALAPPDATA%\citation-engine\logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "TS=%%i"
set "LOG=%LOCALAPPDATA%\citation-engine\logs\verify-bridge-!TS:~0,8!.log"
echo !TS! pass start >> "!LOG!"
"!PY!" "!APP!\job\verify_bridge.py" >> "!LOG!" 2>&1
set "RC=!ERRORLEVEL!"
echo !TS! pass end rc=!RC! >> "!LOG!"
exit /b !RC!
)
