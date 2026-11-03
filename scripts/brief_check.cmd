@echo off
cd /d "%~dp0.."
title Coach brief check
python scripts\brief_check.py > coach_data\brief_check.log 2>&1
type coach_data\brief_check.log
timeout /t 5 /nobreak >nul
