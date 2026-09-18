@echo off
REM capcut-auto local install (Windows - cmd.exe / Anaconda Prompt)
REM
REM   scripts\setup.bat            install and run a check
REM   scripts\setup.bat --web      install, then open the web UI
REM   scripts\setup.bat --no-venv  install into the current python
REM                                (use this inside a conda env)
REM
REM setup.ps1 does the real work. This file only translates the
REM --options into PowerShell style and passes them along.
REM
REM Keep this file ASCII + CRLF. A Korean Windows cmd reads batch
REM files as CP949, so UTF-8 Korean turns into garbage that the
REM parser then tries to run as commands.

setlocal enabledelayedexpansion
set "ARGS="

:parse
if "%~1"=="" goto run
set "A=%~1"
if /i "!A!"=="--web"     set "A=-Web"
if /i "!A!"=="--no-venv" set "A=-NoVenv"
if /i "!A!"=="-web"      set "A=-Web"
if /i "!A!"=="-no-venv"  set "A=-NoVenv"
set "ARGS=!ARGS! !A!"
shift
goto parse

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"!ARGS!
endlocal
