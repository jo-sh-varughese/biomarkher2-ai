@echo off
rem The `biomark` command, usable with no setup: builds ui/dist if needed
rem (via npm) and starts the review viewer serving it. Same entry point as
rem `pip install -e .` registers (see pyproject.toml / app/cli.py); this
rem wrapper exists so a machine that skipped that install step still gets a
rem single `biomark` command -- copy or shim this file onto PATH, or run it
rem from the repo root as `biomark.bat` / `.\biomark.bat`.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.cli %*
