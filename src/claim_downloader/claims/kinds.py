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
INNOVATION = "innovation"      # 혁신인재지원금 — 장학금과 ERP 흐름이 같고 비목만 다르다(담당자 2026-10-14)
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
    Kind(INNOVATION, "혁신인재지원금", "장학금과 같은 폴더 모양 · 같은 흐름(인건비 탭, 소득구분 장학금) — 비목만 교육·연구프로그램개발·운영비",
         "scholarship", True),
    Kind(TRAVEL, "출장비", "출장명령부 · 여비 블록 자동화는 준비 중입니다", "travel", False),
    Kind(CARD, "카드", "ERP 카드청구 화면을 실측한 뒤 만듭니다", "card", False),
)

ROSTER_KINDS = (SCHOLARSHIP, INNOVATION)     # 명단 엑셀 + 공통/개별증빙 폴더로 사람마다 인건비 탭에 넣는 종류
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


def uses_roster(key: str) -> bool:
    """명단 엑셀로 사람마다 넣는 종류(장학금 · 혁신인재지원금) — 화면은 같은 학생 표 패널을 쓴다."""
    return key in ROSTER_KINDS


def roster_kind(folder: str) -> str:
    """명단 폴더가 장학금인지 혁신인재지원금인지 — 명단 엑셀 이름 → 폴더 이름 → 위 폴더 이름(세 칸까지) 순으로
    '혁신인재' 나 '장학금' 이 든 첫 이름을 따른다. 둘 다 든 이름('4. 장학금 및 혁신인재지원금' 같은 묶음 폴더)은 건너뛴다. 못 정하면 장학금."""
    try:
        excels = sorted(n for n in os.listdir(folder) if n.lower().endswith(EXCEL_SUFFIXES) and not n.startswith(("~$", ".")))
    except OSError:
        excels = []
    names = excels + [os.path.basename(os.path.normpath(folder))]
    up = os.path.normpath(folder)
    for _ in range(3):
        up = os.path.dirname(up)
        names.append(os.path.basename(up))
    for name in names:
        innovation, scholarship = "혁신인재" in name, "장학금" in name
        if innovation != scholarship:
            return INNOVATION if innovation else SCHOLARSHIP
    return SCHOLARSHIP


def guess(folder: str) -> str:
    """'자동' 으로 넣었을 때의 종류. 확실한 모양(명단 폴더)만 알아보고 나머지는 일반 — 담당자가 표에서 바꿀 수 있다."""
    return roster_kind(folder) if looks_like_scholarship(folder) else GENERAL


def resolve(chosen: str, folder: str) -> str:
    """고르기 칸의 값(자동 포함) → 실제 종류. 준비 안 된 종류는 받지 않는다."""
    if chosen == AUTO or not chosen:
        return guess(folder)
    kind = find(chosen)
    if not kind.ready:
        raise ValueError(f"'{kind.name}' 은 아직 준비 중입니다")
    return kind.key
