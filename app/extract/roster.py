"""지급내역(마스터) 추출.

지급내역은 사업단이 작성하는 대사용 마스터다. 여기서 뽑은 `roster.*` 가
`시간 × 단가 = 금액` 삼중 대사(R-SCH-008~010)와 R-CMN-019(대상자 존재)의 기준이 된다.

표 머리행을 먼저 찾아 열 이름을 확보하고, 열 수가 맞지 않으면 토큰 성격으로 추정한다.
"""
from __future__ import annotations

import re
from typing import Any

from .. import normalize as nz
from ..models import Confidence, Document, Namespace
from .base import FieldBag, as_digits, as_hours, as_money, as_name
from .table import cells, align_to_columns, find_header, rows_from_words, row_text

#: 머리행을 찾을 때 쓰는 열 이름 후보
_HEADER_LABELS = (
    "연번", "성명", "이름", "학번", "은행", "계좌", "계좌번호", "단가", "시간",
    "금액", "지급액", "강좌", "강좌명", "과목", "소학회", "소속", "학과",
)

#: 열 이름 → 필드 이름
_COLUMN_MAP: list[tuple[tuple[str, ...], str]] = [
    (("성명", "이름", "대상자"), "name"),
    (("학번", "학생번호"), "student_id"),
    (("은행", "은행명", "거래은행"), "bank"),
    (("계좌", "계좌번호"), "account_no"),
    (("단가", "시간당", "기준단가"), "unit_price"),
    (("시간", "근로시간"), "hours"),
    (("금액", "지급액", "지급금액", "지원금액"), "amount"),
    (("강좌", "과목", "프로그램"), "course_name"),
    (("소학회", "동아리", "학회명"), "club_name"),
    (("소속", "학과", "학부"), "department"),
]

_SKIP_TOKENS = {"합계", "합 계", "계", "소계", "총계", "연번", "비고"}
_NAME_RE = re.compile(r"^[가-힣]{2,5}$")
_MONEY_RE = re.compile(r"^-?[\d,]{1,12}$")


def _field_for(label: str) -> str | None:
    packed = nz.strip_spaces(label) or ""
    for keywords, name in _COLUMN_MAP:
        if any(keyword in packed for keyword in keywords):
            return name
    return None


def _parse_by_header(document: Document) -> list[dict[str, Any]]:
    """머리행 x 좌표에 맞춰 셀을 배치한다. 좌표가 있을 때 가장 정확하다."""
    rows_out: list[dict[str, Any]] = []
    for page in document.pages:
        rows = rows_from_words(page)
        header_index = find_header(rows, _HEADER_LABELS, min_hits=3)
        if header_index is None:
            continue
        header_cells = [(x, text) for x, text in cells(rows[header_index]) if _field_for(text)]
        if len(header_cells) < 3:
            continue
        for row in rows[header_index + 1:]:
            text = row_text(row)
            if not text.strip() or (nz.strip_spaces(text) or "") in _SKIP_TOKENS:
                continue
            mapping = align_to_columns(header_cells, cells(row))
            record = _normalize_record(
                {_field_for(label): value for label, value in mapping.items() if _field_for(label)}
            )
            if record.get("name"):
                record["page"] = page.number
                rows_out.append(record)
    return rows_out


def _parse_by_tokens(document: Document) -> list[dict[str, Any]]:
    """좌표가 없을 때의 폴백. 토큰의 성격(이름/학번/금액)으로 열을 추정한다."""
    rows_out: list[dict[str, Any]] = []
    for page in document.pages:
        for line in page.lines:
            packed = nz.strip_spaces(line) or ""
            if not packed or any(packed.startswith(skip) for skip in _SKIP_TOKENS):
                continue
            tokens = line.split()
            # 맨 앞의 연번(`1`, `2` …)은 금액으로 오인되기 쉬우니 먼저 떼어 낸다.
            if tokens and re.fullmatch(r"\d{1,3}", tokens[0]):
                tokens = tokens[1:]
            if len(tokens) < 3:
                continue
            name = next((t for t in tokens if _NAME_RE.match(t) and t not in _SKIP_TOKENS), None)
            if name is None:
                continue
            numbers = [t for t in tokens if _MONEY_RE.match(t)]
            if len(numbers) < 1:
                continue
            record = _guess_record(tokens, name, numbers)
            record["page"] = page.number
            rows_out.append(record)
    return rows_out


def _guess_record(tokens: list[str], name: str, numbers: list[str]) -> dict[str, Any]:
    student_id = next((nz.digits_only(t) for t in tokens
                       if nz.digits_only(t) and len(nz.digits_only(t)) in (8, 9, 10)
                       and "-" not in t), None)
    account = next((nz.digits_only(t) for t in tokens
                    if "-" in t and nz.digits_only(t) and len(nz.digits_only(t)) >= 9), None)
    bank = next((nz.bank_alias(t) for t in tokens if nz.bank_alias(t) != t), None)

    values = [nz.money(n) for n in numbers if nz.money(n) is not None]
    # 학번·계좌로 이미 쓰인 숫자는 금액 후보에서 뺀다.
    used = {int(v) for v in (student_id,) if v}
    values = [v for v in values if v not in used]

    # 마지막 숫자 뒤에 남은 말은 강좌명/프로그램명이다.
    last_number = max((i for i, t in enumerate(tokens) if _MONEY_RE.match(t)), default=-1)
    tail = " ".join(tokens[last_number + 1:]).strip()
    department = next(
        (t for t in tokens
         if re.fullmatch(r"[가-힣A-Za-z]{2,}(?:학과|학부|전공|과)", t)),
        None,
    )

    record: dict[str, Any] = {"name": name, "student_id": student_id,
                              "account_no": account, "bank": bank,
                              "course_name": tail or None,
                              "department": department}
    if values:
        amount = max(values)
        record["amount"] = amount
        remainder = [v for v in values if v != amount]
        hours = next((v for v in remainder if 0 < v <= 300), None)
        unit_price = next((v for v in remainder if v > 300), None)
        if hours is not None:
            record["hours"] = float(hours)
        if unit_price is not None:
            record["unit_price"] = unit_price
        elif hours:
            record["unit_price"] = None
    return record


def _normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    record["name"] = as_name(raw.get("name"))
    record["student_id"] = as_digits(raw.get("student_id"), min_length=6)
    record["bank"] = nz.bank_alias(raw["bank"]) if raw.get("bank") else None
    record["account_no"] = as_digits(raw.get("account_no"), min_length=8)
    record["unit_price"] = as_money(raw.get("unit_price"))
    record["hours"] = as_hours(raw.get("hours"))
    record["amount"] = as_money(raw.get("amount"))
    record["course_name"] = nz.strip_spaces(raw.get("course_name")) if raw.get("course_name") else None
    record["club_name"] = nz.strip_spaces(raw.get("club_name")) if raw.get("club_name") else None
    record["department"] = nz.strip_spaces(raw.get("department")) if raw.get("department") else None
    return record


def extract(document: Document, bag: FieldBag) -> None:
    rows = _parse_by_header(document)
    confidence = Confidence.TABLE_REBUILD
    if not rows:
        rows = _parse_by_tokens(document)
        confidence = Confidence.TABLE_REBUILD - 0.05   # 추정이 섞였으므로 한 단계 낮춘다
    bag.put("roster.rows",
            [Namespace(row, label=str(row.get("name") or "")) for row in rows],
            confidence=confidence)

    # 소학회명이 표 밖 제목에만 있는 서식이 있다.
    club = re.search(r"소학회[명\s:：]*([A-Za-z가-힣0-9]{2,20})", document.text)
    if club:
        bag.put("roster.club_name", nz.strip_spaces(club.group(1)), confidence=confidence)


def select_row(rows: list[Namespace], name: str | None,
               student_id: str | None) -> Namespace | None:
    """지급내역에서 이 검토 건의 대상자 행을 고른다."""
    if not rows:
        return None
    target_name = nz.strip_spaces(name) if name else None
    target_id = nz.digits_only(student_id) if student_id else None

    if target_id:
        for row in rows:
            if row.student_id and nz.digits_only(row.student_id) == target_id:
                return row
    if target_name:
        for row in rows:
            if row.name and nz.strip_spaces(row.name) == target_name:
                return row
    return rows[0] if len(rows) == 1 else None
