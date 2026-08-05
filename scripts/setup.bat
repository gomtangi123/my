@echo off
REM capcut-auto 로컬 설치 (Windows - cmd.exe / Anaconda Prompt)
REM
REM   scripts\setup.bat            설치하고 점검까지
REM   scripts\setup.bat --web      설치한 뒤 웹 UI까지 바로 실행
REM   scripts\setup.bat --no-venv  가상환경 없이 현재 파이썬에 설치
REM                                (Anaconda 환경을 그대로 쓰고 싶을 때)
REM
REM 실제 작업은 setup.ps1이 한다. 여기서는 --옵션을 PowerShell 스타일로
REM 바꿔서 넘겨 주기만 한다.

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
