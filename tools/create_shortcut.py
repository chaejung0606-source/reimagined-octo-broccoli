"""바탕화면 바로가기 만들기.

이 저장소 폴더에서 한 번 실행하면, 바탕화면에 아이콘이 붙은
'ERP 청구서 다운로더' 바로가기가 생긴다. 더블클릭하면 앱이 뜬다.

    python tools/create_shortcut.py

윈도우는 .lnk, 리눅스는 .desktop 을 만든다. macOS 는 안내만 출력한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP_NAME = "업무 도구함"
# 이 저장소가 이전 이름이던 시절의 바로가기들. 남겨 두면 아이콘이 여럿이 돼
# 어느 쪽을 눌러야 할지 헷갈린다. 새 바로가기를 만들 때 함께 치운다.
OLD_APP_NAMES = ("지출 서류 검토", "ERP 청구서 다운로더")
MODULE = "claim_downloader.ui.app"
REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "src" / "claim_downloader" / "ui" / "assets"


def _pythonw() -> Path:
    """콘솔 창 없이 띄울 실행 파일.

    '앱 실행.bat' 이 만든 .venv 를 먼저 찾는다. 거기에 앱 의존성이 들어 있다.
    없으면 지금 이 스크립트를 돌리는 파이썬으로 돌아간다.
    """
    for base in (REPO_ROOT / ".venv" / "Scripts", Path(sys.executable).parent):
        for name in ("pythonw.exe", "python.exe", "python3", "python"):
            candidate = base / name
            if candidate.exists():
                return candidate
    return Path(sys.executable)


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
$sc.Arguments = '-m {MODULE}'
$sc.WorkingDirectory = '{REPO_ROOT}'
$sc.IconLocation = '{ASSETS / "icon.ico"}'
$sc.Description = '청구서 받기 등 업무를 한곳에서 시작합니다'
$sc.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    for old in OLD_APP_NAMES:
        (desktop / f"{old}.lnk").unlink(missing_ok=True)
    return link


def make_linux() -> Path:
    desktop_dir = Path.home() / "Desktop"
    if not desktop_dir.exists():
        desktop_dir = Path.home()
    entry = desktop_dir / "claim-downloader.desktop"
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={_pythonw()} -m {MODULE}\n"
        f"Path={REPO_ROOT}\n"
        f"Icon={ASSETS / 'icon.png'}\n"
        "Terminal=false\n",
        encoding="utf-8",
    )
    entry.chmod(0o755)
    (desktop_dir / "expense-review.desktop").unlink(missing_ok=True)
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
              f"  cd {REPO_ROOT} && {sys.executable} -m {MODULE}")
        return
    print(f"바로가기를 만들었습니다: {link}")


if __name__ == "__main__":
    main()
