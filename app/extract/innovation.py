"""혁신인재지원금 서류 추출 — [양식8] 신청서 / [양식7-1] 월별 활동 결과 보고서.

이 유형의 축은 **소학회명·회장·지도교수 3자 일치**와 정액 240,000원이다.
가장 까다로운 필드는 `form7_1_report.activity_dates` — 본문 자유서술에서 활동 일자를
뽑아내야 한다(`5월 18일 정기 성과공유회 진행` → 2026-05-18). 정규식으로 1차 추출하고,
정밀도가 필요하면 4단계에서 LLM 을 병행한다.
"""
from __future__ import annotations

import re
from typing import Any

from .. import normalize as nz
from ..models import Document, Namespace
from .base import (
    FieldBag,
    as_hours,
    as_money,
    as_name,
    as_period,
    clean,
    document_year,
    find_label_value,
    is_checked,
)
from .table import table_lines

_CLUB_LABELS = ("소학회명", "소학회", "학회명", "동아리명", "팀명")
_ADVISOR_LABELS = ("지도교수", "지도 교수", "담당교수")
_FIELD_LABELS = ("활동분야", "활동 분야", "분야")
_TOPIC_LABELS = ("활동주제", "활동 주제", "주제")
_AMOUNT_LABELS = ("지원금액", "신청금액", "지원 금액", "금액")
_APPLICANT_LABELS = ("신청인", "신청자", "성명", "대표자")
_PRESIDENT_LABELS = ("회장", "소학회장", "대표")

_HANGUL_AMOUNT_RE = re.compile(r"[\(（]?\s*(금[일이삼사오육칠팔구십백천만억\d]+원정)\s*[\)）]?")
_MONTH_DAY_RE = re.compile(r"(\d{1,2})\s*[월원]\s*(\d{1,2})\s*일")



# -------------------------------------------------------------- [양식8] 신청서

def extract_application(document: Document, bag: FieldBag) -> None:
    lines = table_lines(document)
    year = document_year(document)

    value, slot = find_label_value(lines, _APPLICANT_LABELS)
    bag.put_optional("form8_application.applicant", as_name(value) if value else None,
                     found_slot=slot is not None)

    value, slot = find_label_value(lines, _AMOUNT_LABELS, value=r"(?P<value>[\d,]{3,12})")
    amount = as_money(value) if value else None
    bag.put_optional("form8_application.amount", amount, found_slot=slot is not None)

    hangul = _HANGUL_AMOUNT_RE.search(nz.strip_spaces(document.text) or "")
    bag.put_optional("form8_application.amount_hangul",
                     hangul.group(1) if hangul else None,
                     found_slot=slot is not None)

    _put_club(bag, lines, "form8_application")

    value, slot = find_label_value(lines, _FIELD_LABELS)
    bag.put_optional("form8_application.field", clean(value), found_slot=slot is not None)
    if value:
        bag.put("club.field", clean(value))

    value, slot = find_label_value(lines, _TOPIC_LABELS)
    bag.put_optional("form8_application.topic", clean(value), found_slot=slot is not None)
    if value:
        bag.put("club.topic", clean(value))

    checked = _checked_attachments(lines)
    bag.put("form8_application.attachments_checked", checked)

    consent = any(is_checked(line) and "동의" in line for line in lines)
    bag.put("form8_application.consent", consent)

    value, slot = find_label_value(lines, ("활동기간", "지원기간", "해당월"))
    period = as_period(value, year) if value else None
    if period is not None:
        bag.put("form8_application.period", period)
        bag.put("period.start", period.start_date)
        bag.put("period.end", period.end_date)


#: 신청서 `증빙서류` 칸에 나오는 항목 → 실제 서류 키
ATTACHMENT_KEYS: dict[str, str] = {
    "활동결과보고서": "form7_1_report",
    "월별활동결과보고서": "form7_1_report",
    "활동보고서": "form7_1_report",
    "근무상황부": "attach1_worklog",
    "신분증": "id_bankbook",
    "통장사본": "id_bankbook",
    "통장": "id_bankbook",
    "재학증명서": "enrollment_cert",
}


def _checked_attachments(lines: list[str]) -> list[str]:
    """체크된 증빙서류 항목을 서류 키로 바꿔 돌려준다 (R-INN-019)."""
    found: list[str] = []
    for line in lines:
        if not is_checked(line):
            continue
        packed = nz.strip_spaces(line) or ""
        for label, key in ATTACHMENT_KEYS.items():
            if label in packed and key not in found:
                found.append(key)
    return found


def _put_club(bag: FieldBag, lines: list[str], prefix: str) -> None:
    value, slot = find_label_value(lines, _CLUB_LABELS)
    if value:
        bag.put("club.name", nz.strip_spaces(value))
        bag.put(f"{prefix}.club_name", nz.strip_spaces(value))
    elif slot is not None:
        bag.blank("club.name")

    value, slot = find_label_value(lines, _ADVISOR_LABELS)
    if value:
        bag.put("club.advisor", as_name(value))
        bag.put(f"{prefix}.advisor", as_name(value))
    elif slot is not None:
        bag.blank("club.advisor")


# ------------------------------------------------------- [양식7-1] 활동보고서

_MEMBER_RE = re.compile(
    r"^\s*(?:\d{1,2}\s+)?"
    r"(?:(?P<role>회장|부회장|총무|서기|팀원|회원|간사)\s+)?"
    r"(?P<name>[가-힣]{2,5})\s+"
    r"(?P<department>[가-힣A-Za-z·()]{2,20}(?:\s?[가-힣A-Za-z]{1,10})?)\s+"
    r"(?P<student_id>\d{7,10})"
    r"(?:\s+(?P<phone>[\d\-]{9,15}))?\s*$"
)

_OUTCOME_RE = re.compile(
    r"^\s*(?P<category>[가-힣A-Za-z /]{2,20}?)\s+"
    r"(?P<plan_goal>[\d,]+)\s+"
    r"(?P<this_month>[\d,]+|-)\s+"
    r"(?P<cumulative>[\d,]+|-)\s*$"
)

_HIGHLIGHT_HEADINGS = ("대표 성과", "대표성과", "주요 활동", "주요활동", "활동 내용", "활동내용")
_NEXT_PLAN_HEADINGS = ("향후 계획", "향후계획", "차월 계획", "개선 계획")


def extract_report(document: Document, bag: FieldBag) -> None:
    lines = table_lines(document)
    year = document_year(document)

    value, slot = find_label_value(lines, _PRESIDENT_LABELS)
    bag.put_optional("form7_1_report.president", as_name(value) if value else None,
                     found_slot=slot is not None)

    _put_club(bag, lines, "form7_1_report")

    value, slot = find_label_value(lines, _TOPIC_LABELS)
    bag.put_optional("form7_1_report.topic", clean(value), found_slot=slot is not None)

    checked_field = _checked_field(lines)
    bag.put_optional("form7_1_report.field_checked", checked_field,
                     found_slot=any("분야" in line for line in lines))

    members = _parse_members(lines)
    bag.put("form7_1_report.members",
            [Namespace(m, label=str(m.get("name") or "")) for m in members])

    outcomes = _parse_outcomes(lines)
    bag.put("form7_1_report.outcomes",
            [Namespace(o, label=str(o.get("category") or "")) for o in outcomes])

    highlights = _section_text(lines, _HIGHLIGHT_HEADINGS, stop=_NEXT_PLAN_HEADINGS)
    bag.put("form7_1_report.highlights", highlights)

    next_plan = _section_text(lines, _NEXT_PLAN_HEADINGS)
    bag.put("form7_1_report.next_plan", " ".join(next_plan) if next_plan else None)

    bag.put("form7_1_report.activity_dates", _activity_dates(highlights, year))
    bag.put("form7_1_report.page_count", document.page_count)

    value, _ = find_label_value(lines, ("활동시간", "활동 시간", "총 활동시간"))
    if value:
        bag.put("form7_1_report.hours", as_hours(value))


_FIELD_CANDIDATES = ("클라우드", "인공지능", "AI", "빅데이터", "보안", "소프트웨어",
                     "임베디드", "네트워크", "모바일", "게임", "블록체인", "로봇")


def _checked_field(lines: list[str]) -> str | None:
    for line in lines:
        if not is_checked(line):
            continue
        packed = nz.strip_spaces(line) or ""
        for candidate in _FIELD_CANDIDATES:
            if candidate in packed:
                return candidate
    return None


def _parse_members(lines: list[str]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for line in lines:
        match = _MEMBER_RE.match(line)
        if not match:
            continue
        student_id = match.group("student_id")
        members.append({
            "role": clean(match.group("role")),
            "name": match.group("name"),
            "department": nz.strip_spaces(match.group("department")),
            "student_id": student_id,
            "phone": clean(match.group("phone")),
        })
    return members


def _parse_outcomes(lines: list[str]) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    for line in lines:
        match = _OUTCOME_RE.match(line)
        if not match:
            continue
        category = clean(match.group("category"))
        if not category or category in {"구분", "성과지표", "합계"}:
            continue
        outcomes.append({
            "category": category,
            "plan_goal": as_money(match.group("plan_goal")),
            "this_month": as_money(match.group("this_month")),
            "cumulative": as_money(match.group("cumulative")),
        })
    return outcomes


#: 어느 절이든 여기를 만나면 끝난다. 문서 끝의 작성일(`2026년 5월 31일`)까지
#: 본문으로 빨아들이면 활동일 추출(R-INN-012)에 없는 날짜가 섞인다.
_SECTION_STOP = ("향후 계획", "향후계획", "차월 계획", "지도교수", "회장", "작성일",
                 "붙임", "첨부")


def _section_text(lines: list[str], headings: tuple[str, ...],
                  stop: tuple[str, ...] = ()) -> list[str]:
    """`대표 성과` 같은 소제목 아래 본문을 모은다."""
    stops = tuple(dict.fromkeys(stop + _SECTION_STOP))
    collected: list[str] = []
    capturing = False
    for line in lines:
        packed = nz.strip_spaces(line) or ""
        if any((nz.strip_spaces(h) or "") in packed for h in headings):
            capturing = True
            remainder = re.split("|".join(re.escape(h) for h in headings), line)[-1]
            remainder = clean(remainder)
            if remainder:
                collected.append(remainder)
            continue
        if capturing:
            if not packed:
                continue
            if any((nz.strip_spaces(h) or "") in packed for h in stops):
                break
            # 서류 하단의 작성일 줄에서 멈춘다.
            if re.fullmatch(r"\d{2,4}년\d{1,2}월\d{1,2}일", packed):
                break
            # 다음 소제목을 만나면 멈춘다.
            if re.match(r"^\s*[□■○●◆▶\d]+[.)]?\s*[가-힣]{2,}\s*$", line) and len(packed) < 15:
                break
            collected.append(line.strip())
    return collected


def _activity_dates(highlights: list[str], year: int | None) -> list[Any]:
    """본문에서 활동 일자를 뽑는다 (R-INN-012 의 입력).

    샘플에는 `5원 4일` 같은 오탈자가 있어 `월`/`원` 을 모두 받는다.
    (오탈자 자체는 R-INN-020 이 따로 잡는다.)
    """
    found: list[Any] = []
    for line in highlights:
        for match in _MONTH_DAY_RE.finditer(line):
            if year is None:
                continue
            day = nz.parse_date(f"{year}-{match.group(1)}-{match.group(2)}")
            if day is not None and day not in found:
                found.append(day)
        for match in re.finditer(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", line):
            day = nz.parse_date(match.group(0))
            if day is not None and day not in found:
                found.append(day)
    return sorted(found)
