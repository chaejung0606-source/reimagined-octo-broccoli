@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 바탕화면 바로가기 만들기

rem '앱 실행.bat' 을 가리키는 바로가기를 바탕화면에 만든다.
rem 아이콘은 저장소에 들어 있는 icon.ico 를 쓴다.

powershell -NoProfile -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '지출 서류 검토.lnk'));" ^
  "$s.TargetPath=(Join-Path '%CD%' '앱 실행.bat');" ^
  "$s.WorkingDirectory='%CD%';" ^
  "$s.IconLocation=(Join-Path '%CD%' 'src\expense_review\ui\assets\icon.ico');" ^
  "$s.Description='지출 서류를 기준에 따라 자동 검토합니다';" ^
  "$s.Save()"

if errorlevel 1 (
    echo.
    echo   바로가기를 만들지 못했습니다.
    echo.
) else (
    echo.
    echo   바탕화면에 '지출 서류 검토' 바로가기를 만들었습니다.
    echo.
)
pause
