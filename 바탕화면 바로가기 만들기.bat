@echo off
cd /d "%~dp0"
title 바탕화면 바로가기 만들기

rem 이 파일도 CP949 로 저장한다. chcp 는 쓰지 않는다.
rem 실제 작업은 파이썬이 한다. 배치에서 한글 경로를 다루면 깨지기 쉽다.

set PYEXE=.venv\Scripts\python.exe
if not exist "%PYEXE%" (
    echo.
    echo   먼저 [ 앱 실행.bat ] 을 한 번 실행해 주세요.
    echo   준비가 끝난 뒤에 바로가기를 만들 수 있습니다.
    echo.
    pause
    exit /b 1
)

"%PYEXE%" tools\create_shortcut.py
echo.
pause
