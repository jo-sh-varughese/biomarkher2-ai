@echo off
setlocal
title BioMarkHER2 start
cd /d "%~dp0"

netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if %errorlevel%==0 (
  echo  The server is already running: http://127.0.0.1:8000
  start "" http://127.0.0.1:8000
  exit /b 0
)

echo.
echo  Starting BioMarkHER2. The model takes 1-2 minutes to load...
start "BioMarkHER2 server" cmd /k python -m app.server

:wait
powershell -NoProfile -Command "try { Invoke-WebRequest http://127.0.0.1:8000/ -UseBasicParsing -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  timeout /t 5 /nobreak >nul
  goto wait
)

echo  Ready: http://127.0.0.1:8000
start "" http://127.0.0.1:8000
echo  Keep the "BioMarkHER2 server" window open. Run stop.bat to stop it.
timeout /t 5 >nul
