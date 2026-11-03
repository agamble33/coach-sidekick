@echo off
cd /d "%~dp0.."
title Coach model speed
python scripts\model_speed.py > coach_data\model_speed.log 2>&1
type coach_data\model_speed.log
pause
