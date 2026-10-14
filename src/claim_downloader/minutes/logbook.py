"""회의록 기록 — 옛 도구의 오류기록.txt 를 대신해 이 앱의 _실행로그.txt 에 합류한다.

session.file_logger 와 같은 모양(시각 + 줄)으로 같은 파일에 쓴다. 다만 session.py 를 들여오지
않는다 — 회의록 코드는 ERP 쪽 모듈을 읽지 않는다. 화면에도 보이게 하려면 set_echo 로 받는다.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from .. import settings

# 화면에 보일 곳은 스레드마다 따로 — 회의록 · 일반청구 읽기 스레드가 하나의 전역 값을 서로 덮어써, 회의록 기록이
# 나중에 연 일반청구 화면에 찍혔다(2026-10-14 점검). 각 작업 스레드가 자기 스레드에서 set_echo 를 부른다.
_echoes: dict[int, Callable[[str], None]] = {}


def set_echo(fn: Callable[[str], None] | None) -> None:
    """부른 스레드에서 남기는 기록을 fn 으로도 보낸다. None 이면 그 스레드의 것을 지운다."""
    if fn is None:
        _echoes.pop(threading.get_ident(), None)
    else:
        _echoes[threading.get_ident()] = fn


def log(msg: str) -> None:
    lines = str(msg).splitlines() or [""]
    stamp = time.strftime("%H:%M:%S ")
    text = "\n".join(stamp + line for line in lines)
    echo = _echoes.get(threading.get_ident())
    if echo is not None:
        try:
            echo(text)
        except Exception:  # noqa: BLE001 — 기록 때문에 작업이 멈추면 안 된다
            pass
    try:
        with open(settings.log_path(), "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
