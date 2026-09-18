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

REM ---- which script to render (drag a .txt onto this file) -------
set "SCRIPT=%~1"
if "%SCRIPT%"=="" set "SCRIPT=examples\sample.txt"
if not exist "%SCRIPT%" goto no_script

echo.
echo   Rendering cards from: %SCRIPT%
echo.
%PY% -m capcut_auto cardnews "%SCRIPT%" -o cardnews-out --handle "@myaccount"
if errorlevel 1 goto render_failed

echo.
echo   Done. Opening the output folder...
start "" "%CD%\cardnews-out"
echo.
pause
exit /b 0

:no_script
echo.
echo   [!] Script file not found: %SCRIPT%
echo   Drag a .txt script onto this file, or keep the examples folder.
echo.
pause
exit /b 1

:render_failed
echo.
echo   [!] Rendering failed. Copy the messages above and send them.
echo.
pause
exit /b 1

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
