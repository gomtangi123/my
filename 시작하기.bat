@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

REM ---- find a usable python -------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (where python3 >nul 2>nul && set "PY=python3")

REM ---- fall back to a conda env named capcut ---------------------
if not defined PY (
  for %%D in (
    "%USERPROFILE%\anaconda3\envs\capcut"
    "%USERPROFILE%\miniconda3\envs\capcut"
    "%LOCALAPPDATA%\anaconda3\envs\capcut"
    "%LOCALAPPDATA%\miniconda3\envs\capcut"
    "C:\ProgramData\anaconda3\envs\capcut"
  ) do if exist "%%~D\python.exe" set "PY=%%~D\python.exe"
)

if not defined PY goto no_python

REM ---- python 3.10 or newer? ------------------------------------
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if errorlevel 1 goto old_python

REM ---- install on first run --------------------------------------
REM Checking 'import capcut_auto' is useless here: this script runs
REM from the repo root, so the folder itself satisfies the import
REM even when nothing is installed. Check real dependencies instead.
%PY% -c "import numpy, PIL" >nul 2>nul
if errorlevel 1 (
  echo.
  echo   First run - installing. This takes 1-3 minutes...
  echo.
  %PY% -m pip install -e ".[all]"
  if errorlevel 1 goto install_failed
)

echo.
echo   Starting the web UI. Your browser will open shortly.
echo   Keep this window open. Press Ctrl+C here to stop.
echo.
%PY% -m capcut_auto web --open
echo.
echo   Server stopped.
pause
exit /b 0

:no_python
echo.
echo   [!] Python was not found.
echo.
echo   1. Open https://www.python.org/downloads/
echo   2. Download and run the installer
echo   3. IMPORTANT: tick "Add python.exe to PATH" on the first screen
echo   4. Close this window and double-click this file again
echo.
pause
exit /b 1

:old_python
echo.
echo   [!] Python 3.10 or newer is required. Found:
%PY% --version
echo   Install a newer one from https://www.python.org/downloads/
echo.
pause
exit /b 1

:install_failed
echo.
echo   [!] Install failed. Copy the messages above and send them.
echo.
pause
exit /b 1
