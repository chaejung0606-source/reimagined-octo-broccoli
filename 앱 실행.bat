@echo off
cd /d "%~dp0"
title 지출 서류 검토

rem 이 파일은 CP949(한글 윈도우 기본)로 저장한다. chcp 는 쓰지 않는다.
rem 명령과 경로는 모두 영문으로 둔다. 한글은 화면에 찍는 글자에만 쓴다.

rem 준비가 끝났으면 아무 검사도 하지 않고 곧장 띄운다.
rem 검은 창이 오래 떠 있으면 깜빡이는 것처럼 보여 불편하다. 예전에는 여기서
rem 파이썬을 한 번 불러 확인했는데, 그것만으로 1~2초가 걸렸다.

if not exist ".venv\setup-done.txt" goto setup
if not exist ".venv\Scripts\pythonw.exe" goto setup

start "" ".venv\Scripts\pythonw.exe" -m expense_review.ui.app
exit /b 0

:setup
set PY=
where py >nul 2>&1 && set PY=py
if not defined PY (
    where python >nul 2>&1 && set PY=python
)

if not defined PY (
    echo.
    echo   파이썬이 설치되어 있지 않습니다.
    echo.
    echo   https://www.python.org/downloads/  에서 내려받아 설치하세요.
    echo   설치 첫 화면의 "Add python.exe to PATH" 를 반드시 체크해야 합니다.
    echo   설치한 뒤 이 파일을 다시 실행하세요.
    echo.
    pause
    exit /b 1
)

echo.
echo   처음 실행이라 필요한 것들을 받습니다.
echo.
echo   화면 그리기 라이브러리만 100MB가 넘어서
echo   보통 3~7분, 인터넷이 느리면 그 이상 걸립니다.
echo.
echo   아래에 Downloading 진행 막대가 움직이면 정상입니다.
echo   이 창을 닫지 마세요. 앱이 뜨면 저절로 사라집니다.
echo.

if not exist ".venv\Scripts\python.exe" (
    "%PY%" -m venv .venv
    if errorlevel 1 goto failed
)

".venv\Scripts\python.exe" -m pip install -q --upgrade pip --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -e ".[gui]" --disable-pip-version-check
if errorlevel 1 goto failed

rem 준비 직후 한 번만 확인한다. 창이 이미 떠 있으므로 여기서는 시간이 들어도 된다.
".venv\Scripts\python.exe" -c "import expense_review.ui.app" 2>"%TEMP%\expense-review-error.txt"
if errorlevel 1 goto broken

echo done > ".venv\setup-done.txt"

rem 앞으로 검은 창 없이 쓰실 수 있도록 바탕화면 바로가기를 만들어 둔다.
".venv\Scripts\python.exe" tools\create_shortcut.py

echo.
echo   준비를 마쳤습니다. 앱을 띄웁니다.
echo   다음부터는 바탕화면의 [ 지출 서류 검토 ] 아이콘을 쓰시면
echo   검은 창 없이 바로 열립니다.
echo.

start "" ".venv\Scripts\pythonw.exe" -m expense_review.ui.app
exit /b 0

:failed
echo.
echo   준비 중 문제가 생겼습니다. 위 메시지를 그대로 알려 주세요.
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
