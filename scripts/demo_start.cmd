@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title Coach demo
if exist .env for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
echo Starting Coach for the demo on http://127.0.0.1:8000 ...
start "Coach server" /min cmd /c "python -m uvicorn web.app:app --host 127.0.0.1 --port 8000 > coach_data\demo_server.log 2>&1"
timeout /t 6 /nobreak >nul
start "" "https://www.oculus.com/casting"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8000"
echo.
echo Demo setup:
echo   1. Casting tab: sign in, then on the Quest open Camera then Cast and pick Computer.
echo   2. Coach tab: click Go live, share the casting tab, then Overlay for the arrows and memes.
echo   3. Record with OBS or Win+Alt+R (Xbox Game Bar).
echo.
echo Keep this window open. Close it to stop Coach.
pause
