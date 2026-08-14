@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 지출 서류 검토

rem 처음 실행하면 .venv 폴더를 만들고 필요한 것들을 받는다. 두 번째부터는 바로 뜬다.

set PY=
where py > nul 2>&1 && set PY=py
if "%PY%"=="" (where python > nul 2>&1 && set PY=python)

if "%PY%"=="" (
    echo.
    echo   파이썬이 설치되어 있지 않습니다.
    echo.
    echo   https://www.python.org/downloads/  에서 내려받아 설치하세요.
    echo   설치 화면에서 "Add python.exe to PATH" 를 반드시 체크해야 합니다.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   처음 실행이라 준비를 합니다. 몇 분 걸립니다...
    echo.
    %PY% -m venv .venv
    if errorlevel 1 goto failed
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -e ".[gui]"
    if errorlevel 1 goto failed
    echo.
    echo   준비를 마쳤습니다.
    echo.
)

start "" ".venv\Scripts\pythonw.exe" -m expense_review.ui.app
exit /b 0

:failed
echo.
echo   준비 중 문제가 생겼습니다. 위 메시지를 확인해 주세요.
echo.
pause
exit /b 1
