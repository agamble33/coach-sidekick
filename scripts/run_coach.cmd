@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
title Coach by Muse Replay
echo === Coach (Muse Replay) ===
echo Installing web dependencies (first run only)...
python -m pip install --quiet -e ".[web]"
if errorlevel 1 (echo pip install failed & pause & exit /b 1)
echo.
echo Starting Coach at http://127.0.0.1:8000
echo Keep this window open while you use it. Close it to stop Coach.
echo.
start "" http://127.0.0.1:8000
python -m uvicorn web.app:app --host 127.0.0.1 --port 8000
pause
