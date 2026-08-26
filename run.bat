@echo off
cd /d "%~dp0"
start "" http://127.0.0.1:8766
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m app.main
) else (
  python -m app.main
)
pause
