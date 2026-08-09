"""근무상황부 / 근무일지 추출.

근로장학금(양식5)·혁신인재지원금(붙임1)·서포터즈 근무일지가 같은 구조라
하나의 파서를 쓰고, 결과를 서류별 이름으로도 함께 노출한다.

    form5_worklog      → worklog.*
    attach1_worklog    → worklog.*  +  attach1_worklog.*
    worklog_handwrite  → worklog.*  +  worklog_handwrite.*   (신뢰도 낮음)
"""
from __future__ import annotations

import re
from typing import Any

from .. import normalize as nz
from ..models import Document, Namespace
from .base import (
    FieldBag,
    as_hours,
    as_name,
    as_period,
    clean,
    document_year,
    find_label_value,
)

_PROGRAM_LABELS = ("프로그램/역할", "프로그램명", "프로그램", "역할", "과목명", "강좌명", "업무내용")
_PERIOD_LABELS = ("근로기간", "활동기간", "근무기간", "기간")
_APPROVER_LABELS = ("확인자", "확인교수", "담당자확인", "확인")
_APPLICANT_LABELS = ("신청인", "근로장학생", "성명", "이름")
_TOTAL_HOURS_LABELS = ("총 근로시간", "총근로시간", "근로시간 합계", "총 근무시간", "합계시간", "총 시간")
_TOTAL_DAYS_LABELS = ("총 근로일수", "총 일수", "계 총 일", "총 근무일수", "근무일수")
_TOTAL_HEADCOUNT_LABELS = ("총 이용자", "이용자 수 합계", "총 이용자 수")

_DATE = (
    r"\d{2,4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}\s*\.?"
    r"|\d{1,2}\s*월\s*\d{1,2}\s*일"
    r"|\d{1,2}\s*[./]\s*\d{1,2}"
)
_TIME = r"\d{1,2}\s*[:시]\s*\d{1,2}\s*분?"

_ROW_RE = re.compile(
    rf"^\s*(?:\d{{1,2}}\s+)?"                       # 연번(있을 수도 없을 수도)
    rf"(?P<date>{_DATE})"
    rf"\s*[\(\[]?\s*(?P<weekday>[월화수목금토일])?\s*[\)\]]?"
    rf"\s*(?P<start>{_TIME})"
    rf"\s*(?:~|～|∼|-|—|부터)?\s*"
    rf"(?P<end>{_TIME})"
    rf"\s*(?P<hours>\d{{1,2}}(?:\.\d+)?)?"
    rf"\s*(?P<rest>.*)$"
)



def parse_rows(document: Document, year: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in document.lines:
        match = _ROW_RE.match(line)
        if not match:
            continue
        day = nz.parse_date(match.group("date"), default_year=year)
        if day is None:
            continue
        start = clean(match.group("start"))
        end = clean(match.group("end"))
        hours = as_hours(match.group("hours")) if match.group("hours") else None
        rest = clean(match.group("rest")) or ""

        # 손글씨 근무일지는 시간 칸 뒤에 이용자 수가 붙는다.
        headcount = None
        headcount_match = re.match(r"^(\d{1,3})\s*명?\s+(.*)$", rest)
        if headcount_match and len(rest.split()) > 1:
            headcount = int(headcount_match.group(1))
            rest = headcount_match.group(2).strip()

        rows.append({
            "date": day,
            "weekday": clean(match.group("weekday")),
            "start": start,
            "end": end,
            "hours": hours,
            "detail": rest or None,
            "content": rest or None,
            "headcount": headcount,
            "label": f"{day:%Y-%m-%d}",
        })
    return rows


def extract(document: Document, bag: FieldBag, prefix: str = "worklog") -> None:
    lines = document.lines
    year = document_year(document)

    rows = parse_rows(document, year)
    bag.put(f"{prefix}.rows", [Namespace(row, label=row["label"]) for row in rows])

    value, _ = find_label_value(lines, _PROGRAM_LABELS)
    if value:
        bag.put(f"{prefix}.program", nz.strip_spaces(value))

    value, slot = find_label_value(lines, _PERIOD_LABELS)
    period = as_period(value, year) if value else None
    if period is not None:
        # `worklog.period.start` 는 Period 객체의 속성으로 읽는다. 여기서 따로 평면
        # 필드로 넣으면 상위 경로(`worklog.period`)의 Period 가 덮여 없어진다.
        bag.put(f"{prefix}.period", period)
        # 공통 규칙(R-CMN-017)이 보는 활동 종료일
        bag.put("period.start", period.start_date)
        bag.put("period.end", period.end_date)
    elif slot is not None:
        bag.blank(f"{prefix}.period")

    value, slot = find_label_value(lines, _APPROVER_LABELS)
    bag.put_optional(f"{prefix}.approver", as_name(value) if value else None,
                     found_slot=slot is not None)

    value, _ = find_label_value(lines, _APPLICANT_LABELS)
    if value:
        bag.put(f"{prefix}.applicant", as_name(value))

    value, slot = find_label_value(lines, _TOTAL_HOURS_LABELS,
                                   value=r"(?P<value>[\d.,]+\s*(?:시간)?)")
    total = as_hours(value) if value else None
    if total is None and rows:
        # 합계칸을 못 찾았을 때만 행 합계로 대신한다. 신뢰도를 낮춰 두어야
        # '합계칸 공란'(R-SCH-006)이 정상으로 둔갑하지 않는다.
        bag.put_optional(f"{prefix}.total_hours", None, found_slot=slot is not None)
    else:
        bag.put_optional(f"{prefix}.total_hours", total, found_slot=slot is not None)

    value, slot = find_label_value(lines, _TOTAL_DAYS_LABELS,
                                   value=r"(?P<value>[\d.,]+\s*(?:일)?)")
    days = int(nz.digits_only(value)) if value and nz.digits_only(value) else None
    bag.put_optional(f"{prefix}.total_days", days, found_slot=slot is not None)

    value, slot = find_label_value(lines, _TOTAL_HEADCOUNT_LABELS,
                                   value=r"(?P<value>[\d.,]+\s*(?:명)?)")
    heads = int(nz.digits_only(value)) if value and nz.digits_only(value) else None
    if slot is not None:
        bag.put_optional(f"{prefix}.total_headcount", heads, found_slot=True)


def extract_form5(document: Document, bag: FieldBag) -> None:
    extract(document, bag, "worklog")


def extract_attach1(document: Document, bag: FieldBag) -> None:
    extract(document, bag, "worklog")
    bag.alias_prefix("worklog", "attach1_worklog")


def extract_handwrite(document: Document, bag: FieldBag) -> None:
    """손글씨 근무일지.

    이 단계에서는 텍스트 레이어만 읽으므로, 손글씨 스캔이면 값이 아예 안 나오고
    규칙은 자동으로 🔵 판독 불가가 된다. 반대로 텍스트 레이어가 멀쩡한 파일이면
    그 값은 믿어도 된다 — 손글씨라는 이유만으로 미리 깎지 않는다.

    4단계에서 Vision 판독을 붙일 때는 그쪽에서 `Confidence.VISION_HANDWRITE`(0.60)
    로 기록해야 한다. 그래야 손글씨로 읽은 값이 규칙을 통과해 버리지 않는다.
    """
    extract(document, bag, "worklog")
    bag.alias_prefix("worklog", "worklog_handwrite")
