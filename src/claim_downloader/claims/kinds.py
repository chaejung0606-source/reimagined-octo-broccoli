"""청구 종류 — 일반청구 화면에 지출 폴더를 넣을 때 고른다(담당자 제안 2026-10-14).

장학금 · 카드 · 출장비를 홈에 따로 두지 않고, 일반청구 화면 하나에서 폴더마다 종류를 골라 앱이 처리 방법을 나눈다.
ERP 에서도 장학금은 같은 작성 화면의 인건비(소득성 경비) 탭이고(CLAUDE.md 14절), 담당자에게는 "지출 1건 = 폴더 1개" 가 같다.

준비가 안 된 종류(ready=False)는 고를 수 없게 보여 주기만 한다 — 동작하지 않는 단추를 만들지 않는다(CLAUDE.md 5절).
Qt 를 들여오지 않는다(tests/test_scholarship.py 가 PySide6 없이 본다).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

AUTO = "auto"
GENERAL = "general"
SCHOLARSHIP = "scholarship"
TRAVEL = "travel"
CARD = "card"


@dataclass(frozen=True)
class Kind:
    key: str
    name: str          # 표 · 고르기 칸에 보이는 이름
    hint: str          # 고르기 칸 도움말 · 준비 중 안내
    art: str           # ui/art.py 의 업무 의미 이름
    ready: bool


KINDS: tuple[Kind, ...] = (
    Kind(GENERAL, "일반", "세금계산서 · 물품 · 용역 등 — AI 가 폴더의 서류를 읽어 값을 뽑습니다", "claim", True),
    Kind(SCHOLARSHIP, "장학금", "명단 엑셀 + '공통증빙' · '개별증빙' 폴더 — 학생마다 인건비 탭에 넣고 저장합니다", "scholarship", True),
    Kind(TRAVEL, "출장비", "출장명령부 · 여비 블록 자동화는 준비 중입니다", "travel", False),
    Kind(CARD, "카드", "ERP 카드청구 화면을 실측한 뒤 만듭니다", "card", False),
)

COMMON_WORD = "공통"      # 장학금 폴더의 공통증빙 하위 폴더 이름에 든 글자
PERSON_WORD = "개별"      # 장학금 폴더의 개별증빙 하위 폴더 이름에 든 글자
EXCEL_SUFFIXES = (".xlsx", ".xlsm")


def find(key: str) -> Kind:
    for kind in KINDS:
        if kind.key == key:
            return kind
    raise KeyError(key)


def name_of(key: str) -> str:
    try:
        return find(key).name
    except KeyError:
        return key


def looks_like_scholarship(folder: str) -> bool:
    """폴더 바로 아래에 엑셀이 있고 '공통' 이나 '개별' 이 든 하위 폴더가 있으면 장학금 폴더 모양이다."""
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    has_excel = any(n.lower().endswith(EXCEL_SUFFIXES) and not n.startswith(("~$", ".")) for n in names)
    has_split = any((COMMON_WORD in n or PERSON_WORD in n) and os.path.isdir(os.path.join(folder, n)) for n in names)
    return has_excel and has_split


def guess(folder: str) -> str:
    """'자동' 으로 넣었을 때의 종류. 확실한 모양(장학금)만 알아보고 나머지는 일반 — 담당자가 표에서 바꿀 수 있다."""
    return SCHOLARSHIP if looks_like_scholarship(folder) else GENERAL


def resolve(chosen: str, folder: str) -> str:
    """고르기 칸의 값(자동 포함) → 실제 종류. 준비 안 된 종류는 받지 않는다."""
    if chosen == AUTO or not chosen:
        return guess(folder)
    kind = find(chosen)
    if not kind.ready:
        raise ValueError(f"'{kind.name}' 은 아직 준비 중입니다")
    return kind.key
