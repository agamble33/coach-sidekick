@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title Coach restart
if exist .env for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
echo Stopping the old Coach server...
taskkill /fi "WINDOWTITLE eq Coach server*" /f >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /pid %%p /f >nul 2>&1
timeout /t 2 /nobreak >nul
echo Starting Coach on http://127.0.0.1:8000 ...
start "Coach server" /min cmd /c "python -m uvicorn web.app:app --host 127.0.0.1 --port 8000 > coach_data\demo_server.log 2>&1"
timeout /t 6 /nobreak >nul
echo Coach restarted. Reload the Coach tab in your browser (F5).
timeout /t 4 /nobreak >nul
