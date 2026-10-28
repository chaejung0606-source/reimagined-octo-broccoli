"""청구 종류 — 일반청구 화면에 지출 폴더를 넣을 때 고른다(담당자 제안 2026-10-14).

장학금 · 카드를 홈에 따로 두지 않고, 일반청구 화면 하나에서 폴더마다 종류를 골라 앱이 처리 방법을 나눈다.
ERP 에서도 장학금은 같은 작성 화면의 인건비(소득성 경비) 탭이고(CLAUDE.md 14절), 담당자에게는 "지출 1건 = 폴더 1개" 가 같다.

남은 종류는 셋 — 장학금 · 혁신인재지원금 · 카드(담당자 2026-10-28 "일반청구에서는 장학금, 혁신인재지원금, 카드만 사용할게요 그외 기능은
삭제해주세요"). 그 전에 있던 자동 · 일반(AI 읽기) · 세금계산서 · 개인 지급(기타) · 출장비(준비 중)는 그날 걷어냈고 코드는 git 이력에만 있다.
Qt 를 들여오지 않는다(tests/test_scholarship.py 가 PySide6 없이 본다).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

SCHOLARSHIP = "scholarship"
INNOVATION = "innovation"      # 혁신인재지원금 — 장학금과 ERP 흐름이 같고 비목만 다르다(담당자 2026-10-14)
CARD = "card"


@dataclass(frozen=True)
class Kind:
    key: str
    name: str          # 표 · 고르기 칸에 보이는 이름
    hint: str          # 고르기 칸 도움말
    art: str           # ui/art.py 의 업무 의미 이름
    brief: str = ""    # 일반청구 ① 의 종류 카드에 보이는 한 줄(hint 는 길어 말풍선으로)


KINDS: tuple[Kind, ...] = (
    Kind(SCHOLARSHIP, "장학금", "명단 엑셀 + '공통증빙' · '개별증빙' 폴더 — 학생마다 인건비 탭에 넣고 저장합니다", "scholarship",
         "명단 엑셀 + 공통 · 개별증빙 — 학생마다 인건비 탭에"),
    Kind(INNOVATION, "혁신인재지원금", "장학금과 같은 폴더 모양 · 같은 흐름(인건비 탭, 소득구분 장학금) — 비목만 교육·연구프로그램개발·운영비",
         "scholarship", "장학금과 같은 흐름 — 비목만 교육·연구프로그램"),
    Kind(CARD, "카드", "결제 기간 폴더('26-09(09.09. ~ 10.08.)') 안의 결제 건 폴더('<비목명> MMDD <건명>')를 읽어 비목마다 청구서로 "
         "나눕니다. 카드청구 화면은 앱이 결의서내역의 [카드청구] 로 띄웁니다", "card",
         "결제 기간 폴더 — 비목마다 청구서, 결제 건마다 한 줄"),
)

ROSTER_KINDS = (SCHOLARSHIP, INNOVATION)   # 명단 엑셀 + 공통/개별증빙 폴더로 사람마다 넣는 종류
COMMON_WORD = "공통"      # 장학금 폴더의 공통증빙 하위 폴더 이름에 든 글자
PERSON_WORD = "개별"      # 장학금 폴더의 개별증빙 하위 폴더 이름에 든 글자
EXCEL_SUFFIXES = (".xlsx", ".xlsm")
INNOVATION_WORDS = ("혁신인재", "진행요원")


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


def uses_roster(key: str) -> bool:
    """명단 엑셀로 사람마다 넣는 종류(장학금 · 혁신인재지원금) — 화면은 같은 학생 표 패널을 쓴다."""
    return key in ROSTER_KINDS


def named_kind(folder: str) -> str:
    """명단 폴더가 이름으로 보아 장학금인지 혁신인재지원금인지 — 명단 엑셀 이름 → 폴더 이름 → 위 폴더 이름(세 칸까지) 순으로 보고,
    '장학금' · '혁신인재' · '진행요원' 이 없으면 ''. 고른 종류와 다르면 알리기만 한다(scholarship.load_job) — 같은 폴더를 장학금으로 넣어
    비목이 02 로 들어간 적이 있다(2026-10-14 19:22). '4. 장학금 및 혁신인재지원금' 처럼 둘 다 든 묶음 폴더 이름은 건너뛴다."""
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
        # 진행요원비 · 시상금 쪽은 '혁신인재' 글자가 없는 폴더도 있다 — 비목 03 이라 혁신인재지원금으로 본다(14절 '장학금 밖의 청구').
        # '근로장학' 은 장학금. 이름에 둘 다 있거나 둘 다 없으면 다음 이름으로.
        innovation = any(w in name for w in INNOVATION_WORDS)
        scholarship = "장학금" in name or "근로장학" in name
        if innovation != scholarship:
            return INNOVATION if innovation else SCHOLARSHIP
    return ""


def resolve(chosen: str, folder: str = "") -> str:
    """고른 종류 → 실제 종류. 남은 셋 밖의 값(옛 '자동' · '일반' 등)은 받지 않는다."""
    try:
        return find(chosen).key
    except KeyError:
        raise ValueError("일반청구에서는 장학금 · 혁신인재지원금 · 카드만 넣습니다") from None
