@echo off
REM ============================================================
REM  capcut-auto 웹 UI 시작하기 (더블클릭)
REM
REM  Anaconda Prompt를 열고 폴더를 옮기고 환경을 켜는 과정을
REM  대신 해 준다. 이 파일은 repo 폴더 안에 있어야 한다.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

REM capcut 환경의 파이썬을 찾는다 (conda activate 없이 바로 쓰기 위해)
set "PY="
for %%D in (
  "%USERPROFILE%\anaconda3\envs\capcut"
  "%USERPROFILE%\miniconda3\envs\capcut"
  "%USERPROFILE%\AppData\Local\anaconda3\envs\capcut"
  "%USERPROFILE%\AppData\Local\miniconda3\envs\capcut"
  "%LOCALAPPDATA%\anaconda3\envs\capcut"
  "%LOCALAPPDATA%\miniconda3\envs\capcut"
  "C:\ProgramData\anaconda3\envs\capcut"
  "C:\ProgramData\miniconda3\envs\capcut"
) do if exist "%%~D\python.exe" set "PY=%%~D\python.exe"

if not defined PY (
  echo.
  echo   capcut 환경을 찾지 못했습니다.
  echo   Anaconda Prompt 를 열어서 아래를 한 줄씩 실행해 주세요:
  echo.
  echo       conda activate capcut
  echo       cd /d "%~dp0"
  echo       capcut-auto web --open
  echo.
  pause
  exit /b 1
)

echo.
echo   capcut-auto 웹 UI를 시작합니다.
echo   브라우저가 곧 열립니다. 이 창은 끄지 마세요.
echo   끝내려면 이 창에서 Ctrl+C 를 누르세요.
echo.

"%PY%" -m capcut_auto web --open

echo.
echo   서버가 종료되었습니다.
pause
