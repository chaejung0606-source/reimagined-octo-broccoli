"""백엔드 등록·선택.

1단계는 Claude Code CLI 하나다. 설정(minutes_backend)에 저장된 key 로 고르고, 모르는 key 면
기본값으로 돌아간다 — 설정 파일 하나 때문에 화면이 비면 담당자는 손쓸 방법이 없다.
새 백엔드는 base.py 규약대로 만들고 register() 로 넣는다. 그 라이브러리가 없으면 available() 이
False 를 돌려주게 하고 **앱은 정상으로 떠야 한다** — 들여오기(import)를 generate() 안으로 미룬다.
"""
from __future__ import annotations

from .base import BackendError, MinutesBackend
from .claude_cli import ClaudeCliBackend

DEFAULT_KEY = ClaudeCliBackend.key

_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    """백엔드 클래스를 등록한다. 데코레이터로도 쓴다."""
    _REGISTRY[cls.key] = cls
    return cls


register(ClaudeCliBackend)


def keys() -> list[str]:
    return list(_REGISTRY)


def labels() -> list[tuple[str, str]]:
    """(key, 화면 이름) — 고르는 칸에 보이는 순서."""
    return [(key, cls.label) for key, cls in _REGISTRY.items()]


def get(key: str = "") -> MinutesBackend:
    cls = _REGISTRY.get(key) or _REGISTRY[DEFAULT_KEY]
    return cls()


__all__ = ["BackendError", "DEFAULT_KEY", "MinutesBackend", "get", "keys", "labels", "register"]
