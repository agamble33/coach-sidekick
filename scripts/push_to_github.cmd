@echo off
cd /d "%~dp0.."
title Coach push to GitHub
echo Pushing main and gate13-guardrails to github.com/agamble33/coach-sidekick ...
git push origin main
git push origin gate13-guardrails
echo.
git log --oneline -1 origin/main
echo.
echo Done. If it asked you to sign in, finish that and run this again.
pause
