@echo off
cd /d "%~dp0.."
title Coach latency probe
python scripts\latency_probe.py > coach_data\latency_probe.log 2>&1
type coach_data\latency_probe.log
pause
