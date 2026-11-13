@echo off
setlocal
title BioMarkHER2 stop
set "FOUND="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
  taskkill /PID %%p /F >nul 2>&1
  set "FOUND=1"
)
if defined FOUND (
  echo  BioMarkHER2 server stopped.
) else (
  echo  The server was not running.
)
timeout /t 3 >nul
