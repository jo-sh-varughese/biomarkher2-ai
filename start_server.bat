@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.server --run artifacts/phase2_unet
