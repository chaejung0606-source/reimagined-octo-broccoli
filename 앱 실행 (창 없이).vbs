' 지출 서류 검토 - 검은 창 없이 실행
'
' .bat 는 콘솔에서 돌기 때문에 아무리 빨라도 검은 창이 한 번 스칩니다.
' 이 파일은 같은 폴더의 준비 상태를 보고,
'   준비가 끝났으면  : 창 없이 앱만 띄우고
'   준비가 안 됐으면 : 설치 진행이 보이도록 창을 띄웁니다.

Option Explicit
Dim shell, fso, here, venvw, bat

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here

venvw = here & "\.venv\Scripts\pythonw.exe"
bat = here & "\앱 실행.bat"

If fso.FileExists(here & "\.venv\setup-done.txt") And fso.FileExists(venvw) Then
    shell.Run """" & venvw & """ -m expense_review.ui.app", 0, False
Else
    shell.Run """" & bat & """", 1, False
End If
