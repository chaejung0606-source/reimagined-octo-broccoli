"""단계 흐름의 차례 셈 — Qt 없이 돈다(tests/test_flow.py). 모양은 ui/flow.py.

업무 화면마다 '지금 어느 단계인가' 를 상태 값으로 정하고, 그 단계 앞은 접고 뒤는 숨긴다(담당자 요청 2026-10-21 —
"클릭해야 하는 순서대로 버튼 및 기능이 하나 둘 떠올라서").
"""
from __future__ import annotations

HIDDEN, CURRENT, DONE, OPEN = "hidden", "current", "done", "open"


def flow_states(order: list[str], current: str, keep_open: tuple[str, ...] = ()) -> dict[str, str]:
    """차례(order)와 지금 단계로 단계마다 상태 — 앞은 접힘(keep_open 은 펼친 채), 지금은 강조, 뒤는 아직 안 보임."""
    out = {}
    at = order.index(current)
    for i, key in enumerate(order):
        if i < at:
            out[key] = OPEN if key in keep_open else DONE
        elif i == at:
            out[key] = CURRENT
        else:
            out[key] = HIDDEN
    return out


DOWNLOAD_ORDER = ["what", "login", "list"]


def download_stage(picked: bool, reading: bool, listed: bool) -> str:
    """청구서 받기 — ① 무엇을 받을지(과제 · 서류) → ② ERP 로그인 → ③ 받을 청구서 확인하고 받기.
    목록을 읽는 중이거나 읽었으면 ③. 목록을 못 읽으면(로그인 전 · 목록 못 찾음) ② 로 돌아온다."""
    if not picked:
        return "what"
    if listed or reading:
        return "list"
    return "login"
