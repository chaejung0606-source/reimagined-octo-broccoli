@echo off
title COSS 업무데스크 설치

rem 이 파일은 CP949(한글 윈도우 기본)로 저장한다. chcp 는 쓰지 않는다.
rem 명령과 경로는 모두 영문으로 둔다. 한글은 화면에 찍는 글자에만 쓴다.

rem 동료에게는 이 파일 하나만 보내면 된다. 윈도우만 있는 PC 에서
rem 파이썬 - Git - 앱 저장소 - 앱 준비까지 알아서 받는다 (setup.ps1 이 한다).
rem 옆에 setup.ps1 이 있으면 그것을 쓰고, 없으면 저장소에서 받아 쓴다.

set "PS1=%~dp0setup.ps1"
if exist "%PS1%" goto local

echo.
echo   설치 스크립트를 받습니다...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $u = 'https://raw.githubusercontent.com/chaejung0606-source/reimagined-octo-broccoli/claude/expense-document-review-criteria-yzji9p/setup.ps1'; $t = Join-Path $env:TEMP 'coss-setup.ps1'; Invoke-WebRequest -UseBasicParsing $u -OutFile $t; & $t"
goto done

:local
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"

:done
if errorlevel 1 (
    echo.
    echo   설치 중 문제가 생겼습니다. 위 메시지를 그대로 담당자에게 알려 주세요.
    echo.
    pause
)
