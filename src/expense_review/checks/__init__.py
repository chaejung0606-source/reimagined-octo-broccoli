"""규칙 ID별 판정 로직.

engine.CHECKS 에 등록된다. 여기 없는 규칙은 '미구현'으로 결과에 표시되며,
조용히 통과 처리되지 않는다 — 검토자가 무엇이 자동 검사되지 않았는지 알아야 한다.
"""
from . import common, innovation, scholarship, travel  # noqa: F401  (등록 목적)

__all__ = ["common", "scholarship", "innovation", "travel"]
