"""옛 바탕화면 바로가기에서 들어온 실행을 새 앱으로 넘긴다.

이 저장소는 '지출 서류 검토' 앱이었다가 'ERP 청구서 다운로더' 로 바뀌었다.
이미 설치된 PC 의 바탕화면 바로가기는 여전히
`pythonw -m expense_review.ui.app` 을 부른다. 업데이트를 받은 뒤 그 아이콘을
눌렀을 때 아무 반응이 없으면 담당자는 앱이 망가진 줄 안다.

그래서 여기서 '앱 실행.bat' 을 띄운다. bat 은 준비 표시가 새 버전 것이 아니면
새 의존성(Playwright·브라우저)을 받고 새 바로가기를 만든 뒤 새 앱을 연다.

모든 설치본이 옮겨 가면 이 패키지는 지워도 된다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    bat = REPO_ROOT / "앱 실행.bat"
    if sys.platform.startswith("win") and bat.exists():
        # pythonw 에는 콘솔이 없다. 설치 진행이 보이도록 새 콘솔 창에서 띄운다.
        subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(REPO_ROOT),
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
        return 0
    from claim_downloader.ui.app import main as new_main
    return new_main()


if __name__ == "__main__":
    raise SystemExit(main())
