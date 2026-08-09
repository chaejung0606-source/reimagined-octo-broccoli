"""근로장학금 서류 추출 — 청구서 / 월간 활동 결과 보고서 / [양식1] 추천·서약서.

근무상황부는 `worklog.py` 가 맡는다. 이 모듈은 그 옆의 서류들을 다룬다.
"""
from __future__ import annotations

import re
from typing import Any

from .. import normalize as nz
from ..models import Document
from .base import (
    FieldBag,
    as_hours,
    as_money,
    as_name,
    as_period,
    clean,
    document_year,
    find_label_value,
)
from .table import table_lines

_AMOUNT_LABELS = ("청구금액", "청구 금액", "지급액", "신청금액", "금액")
_PERIOD_LABELS = ("활동기간", "근로기간", "활동 기간", "기간")
_PROGRAM_LABELS = ("프로그램명", "프로그램", "사업명", "장학금명")
_HOURS_LABELS = ("활동시간", "활동 시간", "총 활동시간", "근로시간", "총 시간")
_PROFESSOR_LABELS = ("담당교수", "지도교수", "추천교수", "교수명")
_OPERATING_LABELS = ("운영일", "운영기간", "강의기간", "수업기간", "첫 수업일")
_COURSE_LABELS = ("과목명", "교과목명", "강좌명", "과목")
_CREDIT_LABELS = ("학점", "학점/구분", "이수구분")
_ACHIEVEMENT_HEADINGS = ("목표 달성", "목표달성", "달성 정도")
_SELF_REVIEW_HEADINGS = ("자체 평가", "자체평가", "개선사항", "개선 사항")



def extract_claim_form(document: Document, bag: FieldBag) -> None:
    lines = table_lines(document)
    year = document_year(document)

    value, slot = find_label_value(lines, _AMOUNT_LABELS, value=r"(?P<value>[\d,]{3,12})")
    bag.put_optional("claim_form.amount", as_money(value) if value else None,
                     found_slot=slot is not None)

    value, slot = find_label_value(lines, _PERIOD_LABELS)
    period = as_period(value, year) if value else None
    bag.put_optional("claim_form.period", period, found_slot=slot is not None)
    if period is not None:
        bag.put("period.start", period.start_date)
        bag.put("period.end", period.end_date)

    value, slot = find_label_value(lines, _PROGRAM_LABELS)
    bag.put_optional("claim_form.program", clean(value), found_slot=slot is not None)


def extract_monthly_report(document: Document, bag: FieldBag) -> None:
    lines = table_lines(document)
    year = document_year(document)

    value, slot = find_label_value(lines, _HOURS_LABELS,
                                   value=r"(?P<value>[\d.,]+\s*(?:시간)?)")
    bag.put_optional("monthly_report.hours", as_hours(value) if value else None,
                     found_slot=slot is not None)

    bag.put("monthly_report.dates", _activity_dates(document, year))

    photos = sum(page.images for page in document.pages)
    bag.put("monthly_report.photos", list(range(photos)),
            note=f"페이지에 박힌 이미지 {photos}개")

    achievement = _section(lines, _ACHIEVEMENT_HEADINGS)
    bag.put_optional("monthly_report.achievement", achievement, found_slot=achievement is not None)

    review = _section(lines, _SELF_REVIEW_HEADINGS)
    bag.put_optional("monthly_report.self_review", review, found_slot=review is not None)

    value, slot = find_label_value(lines, _PERIOD_LABELS)
    period = as_period(value, year) if value else None
    if period is not None:
        bag.put("monthly_report.period", period)


_DATE_IN_TEXT_RE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일|(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")


def _activity_dates(document: Document, year: int | None) -> list[Any]:
    found: list[Any] = []
    for match in _DATE_IN_TEXT_RE.finditer(document.text):
        if match.group(1):
            if year is None:
                continue
            day = nz.parse_date(f"{year}-{match.group(1)}-{match.group(2)}")
        else:
            day = nz.parse_date(f"{match.group(3)}-{match.group(4)}-{match.group(5)}")
        if day is not None and day not in found:
            found.append(day)
    return sorted(found)


def _section(lines: list[str], headings: tuple[str, ...]) -> str | None:
    collected: list[str] = []
    capturing = False
    for line in lines:
        packed = nz.strip_spaces(line) or ""
        if any((nz.strip_spaces(h) or "") in packed for h in headings):
            capturing = True
            remainder = clean(re.split("|".join(re.escape(h) for h in headings), line)[-1])
            if remainder:
                collected.append(remainder)
            continue
        if capturing:
            if not packed:
                if collected:
                    break
                continue
            collected.append(line.strip())
    text = " ".join(collected).strip()
    return text or None


def extract_form1(document: Document, bag: FieldBag) -> None:
    lines = table_lines(document)
    year = document_year(document)

    value, slot = find_label_value(lines, _PROFESSOR_LABELS)
    bag.put_optional("form1_recommendation.professor", as_name(value) if value else None,
                     found_slot=slot is not None)

    value, slot = find_label_value(lines, _OPERATING_LABELS)
    period = as_period(value, year) if value else None
    bag.put_optional("form1_recommendation.operating_period", period,
                     found_slot=slot is not None)

    value, slot = find_label_value(lines, _COURSE_LABELS)
    bag.put_optional("form1_recommendation.course", clean(value), found_slot=slot is not None)

    value, slot = find_label_value(lines, _CREDIT_LABELS)
    bag.put_optional("form1_recommendation.credit", clean(value), found_slot=slot is not None)
