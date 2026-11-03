@echo off
cd /d "%~dp0.."
title Coach speed check
python scripts\speed_check.py > coach_data\speed_check.log 2>&1
type coach_data\speed_check.log
pause
