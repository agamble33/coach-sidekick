@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title Coach Muse audit
if exist .env for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
echo Starting Coach on port 8011 for the audit...
start "Coach audit server" /min cmd /c "python -m uvicorn web.app:app --host 127.0.0.1 --port 8011 > coach_data\audit_server.log 2>&1"
python scripts\muse_audit.py 8011 > coach_data\muse_audit.log 2>&1
type coach_data\muse_audit.log
taskkill /fi "WINDOWTITLE eq Coach audit server*" /f >nul 2>&1
echo.
echo Done. Results saved in coach_data\muse_audit.log
pause
