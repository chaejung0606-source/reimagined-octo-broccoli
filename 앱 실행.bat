@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 지출 서류 검토

rem 처음 실행하면 .venv 폴더를 만들고 필요한 것들을 받는다. 두 번째부터는 바로 뜬다.
rem 준비를 끝까지 마쳤을 때만 표식 파일을 남긴다. 중간에 끊기면 다음에 이어서 다시 한다.

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

if not exist ".venv\setup-done.txt" (
    echo.
    echo   ────────────────────────────────────────────────
    echo    처음 실행이라 필요한 것들을 받습니다.
    echo.
    echo    화면 그리기 라이브러리만 100MB가 넘어서
    echo    보통 3~7분, 인터넷이 느리면 그 이상 걸립니다.
    echo.
    echo    아래에 Downloading ... 진행 막대가 움직이면 정상입니다.
    echo    이 창을 닫지 마세요. 앱이 뜨면 저절로 사라집니다.
    echo   ────────────────────────────────────────────────
    echo.

    if not exist ".venv\Scripts\python.exe" (
        %PY% -m venv .venv
        if errorlevel 1 goto failed
    )
    ".venv\Scripts\python.exe" -m pip install -q --upgrade pip --disable-pip-version-check
    ".venv\Scripts\python.exe" -m pip install -e ".[gui]" --disable-pip-version-check
    if errorlevel 1 goto failed

    echo 준비를 마친 표식입니다. 지우면 다음 실행 때 다시 준비합니다. > ".venv\setup-done.txt"
    echo.
    echo   준비를 마쳤습니다. 앱을 띄웁니다.
    echo.
)

rem 조용히 띄우기 전에 한 번 확인한다. 빠진 것이 있으면 창이 닫히기 전에 알려 준다.
".venv\Scripts\python.exe" -c "import expense_review.ui.app" 2> "%TEMP%\expense-review-error.txt"
if errorlevel 1 goto broken

start "" ".venv\Scripts\pythonw.exe" -m expense_review.ui.app
exit /b 0

:failed
echo.
echo   준비 중 문제가 생겼습니다. 위에 빨간 글씨가 있으면 그대로 알려 주세요.
echo.
echo   인터넷이 끊겼던 것뿐이라면 이 파일을 다시 실행하면 이어서 받습니다.
echo.
pause
exit /b 1

:broken
echo.
echo   앱을 띄우지 못했습니다. 준비가 덜 된 것 같습니다.
echo.
type "%TEMP%\expense-review-error.txt"
echo.
echo   .venv 폴더를 통째로 지우고 이 파일을 다시 실행해 보세요.
echo.
pause
exit /b 1
