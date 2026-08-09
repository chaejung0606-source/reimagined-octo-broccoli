"""공통 인적사항 추출 — 어느 서류에나 들어 있는 값들.

docs/03-field-dictionary.md §2 의 공통 필드에 대응한다.
여기서 뽑은 값이 R-CMN-003~009(성명·학번·계좌·은행·주민번호·학과 교차 대사)의 입력이 된다.
"""
from __future__ import annotations

import re

from .. import normalize as nz
from ..models import Document
from .base import (
    FieldBag,
    as_date,
    as_digits,
    as_name,
    clean,
    find_label_value,
)

_NAME_LABELS = ("성명", "이름", "신청인", "신청자", "학생명", "성 명", "대상자")
_STUDENT_ID_LABELS = ("학번", "학 번", "학생번호")
_DEPARTMENT_LABELS = ("소속학과", "학과(부)", "학과", "소속", "학부")
_RRN_LABELS = ("주민등록번호", "주민번호", "생년월일(주민등록번호)")
_PHONE_LABELS = ("연락처", "휴대전화", "휴대폰", "전화번호", "핸드폰")
_EMAIL_LABELS = ("이메일", "E-mail", "e-mail", "메일주소", "전자우편")
_BANK_LABELS = ("은행명", "거래은행", "입금은행", "은행")
_ACCOUNT_LABELS = ("계좌번호", "예금계좌", "계좌 번호", "입금계좌", "계좌")
_HOLDER_LABELS = ("예금주", "예금주명")
_AFFILIATION_LABELS = ("소속", "부서", "부서명", "소속부서")
_RANK_LABELS = ("직급", "직위", "직 급")
_SUBMISSION_LABELS = ("작성일", "작성일자", "신청일", "신청일자", "제출일")

# 앞뒤 자릿수를 막지 않으면 14자리 계좌번호(`59220101565992`)에서 13자리를 떼어
# 주민번호로 오인한다. 실제 샘플에 있는 값이라 반드시 경계를 둔다.
_RRN_RE = re.compile(r"(?<!\d)(\d{6})\s*[-–]\s*(\d{7})(?!\d)|(?<!\d)(\d{6})(\d{7})(?!\d)")
_ACCOUNT_RE = re.compile(r"(\d[\d\-\s]{7,})")
_TRAILING_DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def extract_person(document: Document, bag: FieldBag) -> None:
    """서류 한 장에서 인적사항을 뽑는다. 없는 항목은 기록하지 않는다."""
    lines = document.lines
    if not lines:
        return

    value, line_no = find_label_value(lines, _NAME_LABELS)
    if value:
        bag.put("person.name", as_name(value), page=_page_of(document, line_no))

    value, line_no = find_label_value(lines, _STUDENT_ID_LABELS, value=r"(?P<value>[\d\s\-]{6,12})")
    if value:
        bag.put("person.student_id", as_digits(value, min_length=6), page=_page_of(document, line_no))

    value, line_no = find_label_value(lines, _DEPARTMENT_LABELS)
    if value:
        department = nz.strip_spaces(re.split(r"[/|]", value)[0])
        if department and len(department) <= 20:
            bag.put("person.department", department, page=_page_of(document, line_no))

    match = _RRN_RE.search(document.text)
    if match:
        groups = [g for g in match.groups() if g]
        bag.put("person.rrn", "".join(groups))
    else:
        value, line_no = find_label_value(lines, _RRN_LABELS)
        if value:
            bag.put("person.rrn", as_digits(value, min_length=6), page=_page_of(document, line_no))

    value, line_no = find_label_value(lines, _PHONE_LABELS, value=r"(?P<value>[\d\-\s()]{9,15})")
    if value:
        bag.put("person.phone", as_digits(value, min_length=9), page=_page_of(document, line_no))

    value, line_no = find_label_value(lines, _EMAIL_LABELS,
                                      value=r"(?P<value>[\w.+-]+@[\w.-]+)")
    if value:
        bag.put("person.email", value.lower(), page=_page_of(document, line_no))

    _extract_account(document, bag, lines)

    value, line_no = find_label_value(lines, _SUBMISSION_LABELS)
    submitted = as_date(value) if value else None
    if submitted is None:
        # 서류 하단의 `2026년 5월 31일` 을 작성일로 본다 (서식 대부분이 그렇다).
        matches = _TRAILING_DATE_RE.findall(document.text)
        if matches:
            year, month, day = matches[-1]
            submitted = as_date(f"{year}-{month}-{day}")
    if submitted is not None:
        bag.put("submission.date", submitted)


def _extract_account(document: Document, bag: FieldBag, lines: list[str]) -> None:
    value, line_no = find_label_value(lines, _BANK_LABELS)
    if value:
        bank = nz.bank_alias(re.split(r"[\s(]", value.strip())[0])
        if bank:
            bag.put("person.bank", bank, page=_page_of(document, line_no))

    value, line_no = find_label_value(lines, _ACCOUNT_LABELS)
    if value:
        match = _ACCOUNT_RE.search(value)
        account = as_digits(match.group(1), min_length=8) if match else None
        bag.put_optional("person.account_no", account, found_slot=True,
                         page=_page_of(document, line_no))
        # `신한 110-493-878372` 처럼 은행과 계좌가 한 칸에 같이 들어오는 서식이 있다.
        if "person.bank" not in bag.fields:
            head = value[: match.start()] if match else value
            bank = nz.bank_alias(clean(head) or "")
            if bank and len(bank) <= 8:
                bag.put("person.bank", bank, page=_page_of(document, line_no))

    value, line_no = find_label_value(lines, _HOLDER_LABELS)
    if value:
        bag.put("bankbook.holder", as_name(value), page=_page_of(document, line_no))


def extract_travel_person(document: Document, bag: FieldBag) -> None:
    """출장신청서의 소속·직급 (R-TRV-015)."""
    lines = document.lines
    value, line_no = find_label_value(lines, _AFFILIATION_LABELS)
    if value:
        bag.put("person.affiliation", nz.strip_spaces(value), page=_page_of(document, line_no))
    value, line_no = find_label_value(lines, _RANK_LABELS)
    if value:
        bag.put("person.rank", nz.strip_spaces(value), page=_page_of(document, line_no))


_ISSUED_LABELS = ("발급일", "발급일자", "발행일", "증명일", "발급년월일")


def extract_enrollment(document: Document, bag: FieldBag) -> None:
    """재학증명서 발급일 (R-CMN-013). 스캔본이면 4단계에서 읽는다."""
    lines = document.lines
    value, slot = find_label_value(lines, _ISSUED_LABELS)
    issued = as_date(value) if value else None
    if issued is None and slot is None:
        matches = _TRAILING_DATE_RE.findall(document.text)
        if matches:
            year, month, day = matches[-1]
            issued = as_date(f"{year}-{month}-{day}")
            slot = 0
    bag.put_optional("enrollment_cert.issued_at", issued, found_slot=slot is not None,
                     page=_page_of(document, slot))


def extract_bankbook(document: Document, bag: FieldBag) -> None:
    """통장 사본의 예금주·계좌번호 (R-CMN-015/016).

    실제 샘플에서 이 서류는 이미지라 지금 단계에서는 값이 나오지 않는다.
    텍스트가 있는 경우에만 채우고, 없으면 미추출로 두어 🔵 로 올라가게 한다.
    """
    account = bag.fields.get("person.account_no")
    if account is not None and account.value:
        bag.put("bankbook.account_no", account.value, note="통장 사본 기재 계좌")
    holder = bag.fields.get("bankbook.holder")
    if holder is None:
        name = bag.fields.get("person.name")
        if name is not None and name.value:
            bag.put("bankbook.holder", name.value, note="통장 사본 예금주란")


def _page_of(document: Document, line_index: int | None) -> int | None:
    """줄 번호 → 페이지 번호. 결과에서 원본 위치로 점프할 때 쓴다."""
    if line_index is None:
        return None
    seen = 0
    for page in document.pages:
        count = len(page.lines)
        if line_index < seen + count:
            return page.number
        seen += count
    return document.pages[-1].number if document.pages else None
