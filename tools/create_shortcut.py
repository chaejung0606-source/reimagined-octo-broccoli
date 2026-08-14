"""바탕화면 바로가기 만들기.

이 저장소 폴더에서 한 번 실행하면, 바탕화면에 아이콘이 붙은
'지출 서류 검토' 바로가기가 생긴다. 더블클릭하면 앱이 뜬다.

    python tools/create_shortcut.py

윈도우는 .lnk, 리눅스는 .desktop 을 만든다. macOS 는 안내만 출력한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP_NAME = "지출 서류 검토"
REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "src" / "expense_review" / "ui" / "assets"


def _pythonw() -> Path:
    """콘솔 창 없이 띄우는 pythonw 가 있으면 그쪽을 쓴다(윈도우)."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def make_windows() -> Path:
    desktop_probe = (
        "[Environment]::GetFolderPath('Desktop')"
    )
    desktop = Path(subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", desktop_probe],
        text=True).strip())
    link = desktop / f"{APP_NAME}.lnk"
    script = f"""
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut('{link}')
$sc.TargetPath = '{_pythonw()}'
$sc.Arguments = '-m expense_review.ui.app'
$sc.WorkingDirectory = '{REPO_ROOT}'
$sc.IconLocation = '{ASSETS / "icon.ico"}'
$sc.Description = '지출 서류를 기준에 따라 자동 검토합니다'
$sc.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    return link


def make_linux() -> Path:
    desktop_dir = Path.home() / "Desktop"
    if not desktop_dir.exists():
        desktop_dir = Path.home()
    entry = desktop_dir / "expense-review.desktop"
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={sys.executable} -m expense_review.ui.app\n"
        f"Path={REPO_ROOT}\n"
        f"Icon={ASSETS / 'icon.png'}\n"
        "Terminal=false\n",
        encoding="utf-8",
    )
    entry.chmod(0o755)
    return entry


def main() -> None:
    if sys.platform.startswith("win"):
        link = make_windows()
    elif sys.platform.startswith("linux"):
        link = make_linux()
    else:
        print("macOS 는 자동 생성을 지원하지 않습니다.\n"
              "Automator 로 '응용 프로그램'을 만들어 아래 명령을 넣고,\n"
              f"아이콘은 {ASSETS / 'icon.png'} 를 지정하세요:\n"
              f"  cd {REPO_ROOT} && {sys.executable} -m expense_review.ui.app")
        return
    print(f"바로가기를 만들었습니다: {link}")


if __name__ == "__main__":
    main()
