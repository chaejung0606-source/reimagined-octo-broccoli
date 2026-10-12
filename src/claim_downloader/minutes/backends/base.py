"""백엔드 규약 — 회의 폴더와 규칙을 받아 schema.py 의 dict 를 돌려주는 것.

백엔드를 하나 더 붙일 때 보는 파일은 이것뿐이어야 한다. 화면(ui/pages/minutes.py)·작업 스레드
(ui/minutes_worker.py)·문서 만들기(process.py)는 이 규약만 보고 돈다.

    class MyBackend:
        key = "anthropic"             # 설정(minutes_backend)에 저장되는 이름
        label = "Anthropic API"       # 화면의 고르는 칸에 보이는 이름

        def available(self) -> tuple[bool, str]:
            # 지금 이 PC 에서 쓸 수 있는지와 안내 한 줄(안 되면 그 이유, 되면 버전 등)
        def generate(self, meeting_dir: Path, rules: str) -> dict:
            # 회의 폴더를 읽어 dict 를 돌려준다. 실패하면 BackendError(message, kind)
            #   kind "" 는 그 회의만 실패 · "login" "limit" "balance" 는 남은 회의도 건너뜀

그리고 backends/__init__.py 의 register() 에 넣는다. 규칙(rules)은 백엔드와 무관하게 한 벌이다 —
플랫폼별로 규칙을 따로 만들지 않는다. 자료는 어느 백엔드든 외부로 나간다는 점을 화면이 알린다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..errors import BackendError

__all__ = ["BackendError", "MinutesBackend"]


@runtime_checkable
class MinutesBackend(Protocol):
    key: str
    label: str

    def available(self) -> tuple[bool, str]:
        """지금 이 PC 에서 쓸 수 있는지와, 안 되면 그 이유(한국어 한 줄)."""

    def generate(self, meeting_dir: Path, rules: str) -> dict:
        """회의 폴더를 읽어 schema.py 의 dict 를 돌려준다. 실패하면 BackendError."""
