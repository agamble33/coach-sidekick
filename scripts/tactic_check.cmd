@echo off
cd /d "%~dp0.."
title Coach tactic check
python scripts\tactic_check.py > coach_data\tactic_check.log 2>&1
type coach_data\tactic_check.log
pause
