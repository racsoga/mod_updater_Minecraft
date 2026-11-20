@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -m mod_updater --apply
) else (
    python -m mod_updater --apply
)
pause
