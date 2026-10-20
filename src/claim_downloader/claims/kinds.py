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
PERSONAL = "personal"          # 개인 지급 — 일반청구 탭 · 증빙 기타 · 청구구분 (90) 기타로 사람마다(담당자 2026-10-19)
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
    Kind(PERSONAL, "개인 지급(기타)", "지급내역 엑셀 + '공통증빙' · '개별증빙' 폴더 — 일반청구 탭에 사람마다 입금처 · 증빙 기타로 넣고 "
         "저장합니다. 비목 · 대표적요는 공통증빙의 지급 공문에서 찾습니다(일반으로 넣어도 이 모양이면 이것으로)", "claim", True),
    Kind(TRAVEL, "출장비", "출장명령부 · 여비 블록 자동화는 준비 중입니다", "travel", False),
    # 카드는 폴더 읽기 · 미리 보기까지만(2026-10-20). ERP 카드청구 화면에 넣기는 실측 뒤 — 화면의 [ERP 에 넣기] 는 막아 둔다
    Kind(CARD, "카드", "결제 기간 폴더('26-09(09.09. ~ 10.08.)') 안의 결제 건 폴더('<비목명> MMDD <건명>')를 읽어 비목마다 청구서로 "
         "나눠 미리 봅니다. ERP 에 넣기는 카드청구 화면을 실측한 뒤 만듭니다", "card", True),
)

ROSTER_KINDS = (SCHOLARSHIP, INNOVATION, PERSONAL)
ERP_LATER = (CARD,)       # 폴더 읽기 · 미리 보기는 되고 ERP 에 넣기는 아직 없는 종류     # 명단 엑셀 + 공통/개별증빙 폴더로 사람마다 넣는 종류
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
    """명단 엑셀로 사람마다 넣는 종류(장학금 · 혁신인재지원금 · 개인 지급) — 화면은 같은 학생 표 패널을 쓴다."""
    return key in ROSTER_KINDS


INNOVATION_WORDS = ("혁신인재", "진행요원")


ROSTER_EXCEL_WORD = "지급내역"     # 장학금 · 혁신인재지원금 명단 엑셀 이름에 늘 든 말(2026학년도 (가)형 근로장학금 지급내역.xlsx)
# 개인 지급 명단 엑셀 이름에 드는 말 — '…지급내역' · '…지원내역'(프로그램참여지원비 · 재직자 교육 지원, 14절 '장학금 밖의 청구')
PERSONAL_EXCEL_WORDS = ("지급내역", "지원내역")
# 개인 지급이라도 기타가 아닌 것 — 자문료 (83) · 여비 (33) 는 증빙 창이 따로 있어 아직 일반으로 둔다(담당자 2026-10-19 4번)
NOT_PERSONAL_WORDS = ("자문", "전문가활용", "출장", "여비", "강사료")


def roster_excels(folder: str) -> list[str]:
    """폴더 바로 아래의 '지급내역' 엑셀 이름들 — 명단 청구의 원본 자료. AI 로 PDF 를 읽기 전에 이것부터 본다."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [n for n in names if n.lower().endswith(EXCEL_SUFFIXES) and not n.startswith(("~$", "."))
            and ROSTER_EXCEL_WORD in n.replace(" ", "")]


def roster_kind(folder: str) -> str:
    """명단 폴더가 장학금인지 혁신인재지원금인지 — 명단 엑셀 이름 → 폴더 이름 → 위 폴더 이름(세 칸까지) 순으로
    '혁신인재' 나 '장학금' 이 든 첫 이름을 따른다. 둘 다 든 이름('4. 장학금 및 혁신인재지원금' 같은 묶음 폴더)은 건너뛴다. 못 정하면 장학금."""
    return named_kind(folder) or SCHOLARSHIP


def named_kind(folder: str) -> str:
    """roster_kind 와 같은 순서로 이름에서만 정한다 — 이름에 '장학금' · '혁신인재' · '진행요원' 이 없으면 ''."""
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


def _excels_under(folder: str, words: tuple[str, ...]) -> list[str]:
    """폴더 바로 아래 · 공통증빙 하위 폴더 바로 아래의 엑셀 중 이름에 words 가 든 것(경로)."""
    out = []
    places = [folder]
    try:
        places += [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                   if COMMON_WORD in n and os.path.isdir(os.path.join(folder, n))]
    except OSError:
        return []
    for place in places:
        try:
            names = sorted(os.listdir(place))
        except OSError:
            continue
        out += [os.path.join(place, n) for n in names if n.lower().endswith(EXCEL_SUFFIXES) and not n.startswith(("~$", "."))
                and any(w in n.replace(" ", "") for w in words)]
    return out


def personal_folder(folder: str) -> bool:
    """개인 지급(일반청구 탭 · 증빙 기타) 폴더 모양인지 — 담당자(2026-10-19): "개인 계좌이체의 경우는 지급내역 서류가 있습니다".
    지급내역 · 지원내역 엑셀(폴더 바로 아래나 공통증빙 안)이 있고, 이름이 장학금 · 혁신인재지원금이 아니고, 자문료 · 출장(여비)도 아닐 때.
    자문료 · 여비는 증빙 창(자문료 · 출장명령부)이 따로 있어 아직 일반으로 둔다. 위 폴더 이름은 보지 않는다 —
    '3. 출장비 및 프로그램참여지원비' 처럼 묶음 폴더 이름에 '출장' 이 들어 있다."""
    excels = _excels_under(folder, PERSONAL_EXCEL_WORDS)
    if not excels or named_kind(folder):
        return False
    own = [os.path.basename(os.path.normpath(folder))] + [os.path.basename(e) for e in excels]
    return not any(w in name.replace(" ", "") for name in own for w in NOT_PERSONAL_WORDS)


def guess(folder: str) -> str:
    """'자동' 으로 넣었을 때의 종류. 확실한 모양(카드 결제 기간 폴더 · 명단 폴더)만 알아보고 나머지는 일반 — 담당자가 표에서 바꿀 수 있다.

    공통/개별 하위 폴더가 없어도 '지급내역' 엑셀이 있고 이름(엑셀 · 폴더 · 위 폴더)에 장학금 · 혁신인재지원금 말이 있으면 명단 청구로 본다
    (담당자 요청 2026-10-19: 원본이 엑셀이면 엑셀을 먼저). 그런 폴더가 일반으로 들어가 AI 가 PDF 를 읽은 적이 있다(2026-10-13 (나)형 TA).
    '지원내역' (프로그램참여지원비 · 재직자 교육 지원)이나 이름에 그 말이 없는 '자문료 지급내역' 은 일반청구라 그대로 둔다."""
    from . import card
    if card.looks_like_card_folder(folder):
        return CARD                 # 이름이 결제 기간('26-09(09.09. ~ 10.08.)')이고 안에 결제 건 폴더(MMDD)가 있다
    named = named_kind(folder)
    if looks_like_scholarship(folder) or roster_excels(folder):
        if named:
            return named
    if personal_folder(folder):
        return PERSONAL
    if looks_like_scholarship(folder) and not _excels_under(folder, PERSONAL_EXCEL_WORDS):
        return SCHOLARSHIP          # 명단 폴더 모양인데 이름으로 못 정함 — 전처럼 장학금(표 위에서 바꾼다)
    return GENERAL


def resolve(chosen: str, folder: str) -> str:
    """고르기 칸의 값(자동 포함) → 실제 종류. 준비 안 된 종류는 받지 않는다."""
    if chosen == AUTO or not chosen:
        return guess(folder)
    if chosen == GENERAL and personal_folder(folder):
        # 담당자(2026-10-19): "청구종류 일반으로 해두고 폴더 올리면 … 지급내역이 있으면 지급내역대로" — 일반으로 넣어도 개인 지급으로
        return PERSONAL
    kind = find(chosen)
    if not kind.ready:
        raise ValueError(f"'{kind.name}' 은 아직 준비 중입니다")
    return kind.key
