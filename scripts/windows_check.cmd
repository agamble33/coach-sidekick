@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "LOG=%~dp0windows_check.log"
if "%~1"=="__inner" goto :inner
rem Outer: run the inner part with everything captured to the log, then show it.
cmd /c ""%~f0" __inner "%~2"" > "%LOG%" 2>&1
type "%LOG%"
echo.
echo Log saved to %LOG%. You can close this window.
pause
exit /b 0

:inner
echo === muse-replay Windows check %date% %time%
echo repo: %cd%
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
set "PY="
python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul && set "PY=python"
if defined PY goto :havepy
py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul && set "PY=py -3"
if defined PY goto :havepy
echo no Python 3.10+ found, installing 3.12 via winget
winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "UPATH=%%b"
call set "PATH=%%UPATH%%;%%PATH%%"
python --version >nul 2>nul && set "PY=python"
if defined PY goto :havepy
py -3.12 --version >nul 2>nul && set "PY=py -3.12"
if defined PY goto :havepy
echo ERROR: could not find or install Python 3.10+
exit /b 1

:havepy
echo using: %PY%
where ffmpeg >nul 2>nul
if not errorlevel 1 goto :haveff
echo ffmpeg missing, installing via winget
winget install --id Gyan.FFmpeg -e --scope user --accept-package-agreements --accept-source-agreements
:haveff
echo --- versions
%PY% --version
ffmpeg -version | findstr /b "ffmpeg version"
echo --- pip install
%PY% -m pip install --quiet --upgrade pip
%PY% -m pip install --quiet -e ".[dev]"
echo --- pytest
set REQUIRE_FFMPEG=1
%PY% -m pytest -q -rs
echo --- live check
if "%~2"=="" (%PY% scripts\live_check.py) else (%PY% scripts\live_check.py "%~2")
echo === done
exit /b 0
