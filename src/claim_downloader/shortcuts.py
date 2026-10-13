"""바로가기 다시 만들기 — tools/create_shortcut.py 를 돌리고 결과를 _실행로그.txt 에 남긴다.

앱이 업데이트 뒤 처음 켤 때 한 번(ui/app.py) 그리고 설정 화면의 단추에서 부른다. 윈도우에서 무엇이
됐고 안 됐는지는 담당자 PC 에서만 알 수 있으므로, 도구가 찍는 글을 전부 기록에 남겨 받아 본다.
"""
from __future__ import annotations

import os
import subprocess
import sys

from . import settings, updater
from .minutes.logbook import log

# 바로가기 규격이 바뀌면 판을 올린다 — 설치된 PC 가 앱을 켤 때 한 번 새로 만든다
MARK = "shortcut-v3.txt"
SCRIPT = updater.REPO_ROOT / "tools" / "create_shortcut.py"


def mark_path():
    return updater.REPO_ROOT / ".venv" / MARK


def needed() -> bool:
    return os.name == "nt" and SCRIPT.exists() and not mark_path().exists()


def refresh() -> tuple[bool, str]:
    """바로가기를 다시 만든다. (성공 여부, 도구가 찍은 글). 성공하면 표시를 남겨 다음 켤 때는 건너뛴다."""
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
    if done.returncode == 0:
        try:
            mark_path().parent.mkdir(parents=True, exist_ok=True)
            mark_path().write_text("done", encoding="utf-8")
        except OSError:
            pass
    return done.returncode == 0, text


def refresh_once_in_background() -> None:
    """업데이트 뒤 처음 켤 때 — 뒤에서 조용히. 실패해도 앱에는 영향이 없고 다음 켤 때 다시 해 본다."""
    if not needed():
        return
    import threading
    threading.Thread(target=refresh, name="shortcut", daemon=True).start()
