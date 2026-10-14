"""바로가기 다시 만들기 — tools/create_shortcut.py 를 돌리고 결과를 _실행로그.txt 에 남긴다.

설정 화면의 [바로가기 다시 만들기] 에서만 부른다. 윈도우에서 무엇이 됐고 안 됐는지는 담당자 PC 에서만 알 수 있으므로,
도구가 찍는 글을 전부 기록에 남겨 받아 본다.

전에는 앱이 켜질 때 표시 파일(shortcut-v3)이 없으면 뒤에서 다시 만들었는데, 담당자 PC 에서는 고정된 바로가기에 이름을
못 적어(액세스 거부) 도구가 늘 실패로 끝났고 표시가 남지 않아 **켤 때마다(업데이트 뒤 새로고침마다) 바탕화면 바로가기가
다시 생겼다.** 담당자 요청(2026-10-14)으로 자동으로 만드는 일은 없앴다. 처음 설치할 때 `앱 실행.bat` 이 한 번 만들고,
그 뒤로는 사람이 설정에서 누를 때만 만든다.
"""
from __future__ import annotations

import os
import subprocess
import sys

from . import updater
from .minutes.logbook import log

SCRIPT = updater.REPO_ROOT / "tools" / "create_shortcut.py"
# 이 설치본에 바로가기를 한 번 만들었다는 표시 — `앱 실행.bat` 은 이것이 있으면 준비 단계를 다시 돌 때(의존성이 바뀐
# 업데이트) 바로가기를 만들지 않는다. 앱이 켜질 때 남긴다(만들지는 않는다).
MADE_MARK = "shortcut-made.txt"


def made_mark_path():
    return updater.REPO_ROOT / ".venv" / MADE_MARK


def remember_made() -> None:
    """이미 설치된 PC 표시 — 바로가기를 만들지 않고 표시 파일만 남긴다. 실패해도 조용히."""
    try:
        path = made_mark_path()
        if path.parent.is_dir() and not path.exists():
            path.write_text("done", encoding="utf-8")
    except OSError:
        pass


def refresh() -> tuple[bool, str]:
    """바로가기를 다시 만든다(설정 화면의 단추). (성공 여부, 도구가 찍은 글)."""
    if not SCRIPT.exists():
        return False, "tools/create_shortcut.py 가 없습니다"
    hidden = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}
    # 자식 파이썬이 파이프에 쓸 때 윈도우는 CP949 를 쓴다 — 여기서 UTF-8 로 읽으므로 자식도 UTF-8 로 쓰게 한다
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=180,
                              encoding="utf-8", errors="replace", cwd=str(updater.REPO_ROOT), env=env, **hidden)
    except Exception as error:  # noqa: BLE001
        text = f"바로가기 도구를 돌리지 못했습니다: {error}"
        log(text)
        return False, text
    text = ((done.stdout or "") + (("\n" + done.stderr) if done.stderr else "")).strip() or "(출력 없음)"
    log("바로가기 다시 만들기 (코드 %d)\n%s" % (done.returncode, text))
    return done.returncode == 0, text
