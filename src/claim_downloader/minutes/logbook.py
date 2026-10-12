"""회의록 기록 — 옛 도구의 오류기록.txt 를 대신해 이 앱의 _실행로그.txt 에 합류한다.

session.file_logger 와 같은 모양(시각 + 줄)으로 같은 파일에 쓴다. 다만 session.py 를 들여오지
않는다 — 회의록 코드는 ERP 쪽 모듈을 읽지 않는다. 화면에도 보이게 하려면 set_echo 로 받는다.
"""
from __future__ import annotations

import time
from typing import Callable

from .. import settings

_echo: Callable[[str], None] | None = None


def set_echo(fn: Callable[[str], None] | None) -> None:
    global _echo
    _echo = fn


def log(msg: str) -> None:
    lines = str(msg).splitlines() or [""]
    stamp = time.strftime("%H:%M:%S ")
    text = "\n".join(stamp + line for line in lines)
    if _echo is not None:
        try:
            _echo(text)
        except Exception:  # noqa: BLE001 — 기록 때문에 작업이 멈추면 안 된다
            pass
    try:
        with open(settings.log_path(), "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
