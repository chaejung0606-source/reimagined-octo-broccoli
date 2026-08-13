"""공통 규칙 판정 (R-CMN-*)."""
from __future__ import annotations

import re

from .. import normalize as nz
from ..classify import DOC_LABELS
from ..engine import Context, Fail, NeedsReview, check

# 성명이 담기는 필드 이름은 서류마다 다르다. 교차 대사에서는 모두 같은 뜻으로 본다.
NAME_FIELDS = ("name", "applicant", "president")

# 파일명이 이런 꼬리를 달고 있으면 임시본·복사본일 가능성이 크다.
DUPLICATE_HINTS = ("-복사", "복사본", "(1)", "_old", "_구버전", " - 사본", "-사본")


@check("R-CMN-001")
def required_documents(ctx: Context):
    """필수 서류 완비성. 파일 개수가 아니라 '담긴 서류 종류'로 판단한다."""
    required = getattr(ctx, "required_documents", [])
    available = ctx.docs.available_types
    missing = [
        item.get("label") or DOC_LABELS.get(item["key"], item["key"])
        for item in required
        if not item.get("optional") and item["key"] not in available
    ]
    if missing:
        return Fail({"missing": missing})
    return None


@check("R-CMN-002")
def duplicate_files(ctx: Context):
    duplicates = [
        document.name for document in ctx.docs
        if any(hint in document.name for hint in DUPLICATE_HINTS)
    ]
    # 같은 서류 종류가 여러 파일에 중복으로 들어 있는 경우도 본다.
    by_type: dict[str, list[str]] = {}
    for document in ctx.docs:
        if document.doc_type in {"trip_evidence", "claim_form", "worklog", "club_report"}:
            by_type.setdefault(document.doc_type, []).append(document.name)
    for doc_type, names in by_type.items():
        if len(names) > 1:
            duplicates.extend(names)

    if duplicates:
        return Fail({"duplicates": sorted(set(duplicates))})
    return None


def _cross_field(ctx: Context, field_names: tuple[str, ...], normalizer) -> Fail | None:
    """여러 서류에서 같은 뜻의 필드를 모아 값이 갈리는지 본다."""
    seen: dict[str, list[str]] = {}
    for document in ctx.docs:
        for field_name in field_names:
            value = document.fields.get(field_name)
            if value is None or not value.is_present:
                continue
            if value.confidence < 0.85:
                raise NeedsReview(f"{document.name}의 '{field_name}' 판독 신뢰도가 낮습니다")
            key = normalizer(value.value)
            if key:
                seen.setdefault(key, []).append(document.name)

    if len(seen) <= 1:
        return None
    # 가장 많은 서류가 쓰는 값을 기준으로 제시한다.
    expected = max(seen, key=lambda key: len(seen[key]))
    detail = [f"{key} ({', '.join(names)})" for key, names in seen.items()]
    return Fail({"values": detail, "expected": expected})


@check("R-CMN-003")
def name_matches(ctx: Context):
    return _cross_field(ctx, NAME_FIELDS, nz.strip_spaces)


@check("R-CMN-004")
def student_id_matches(ctx: Context):
    return _cross_field(ctx, ("student_id",), nz.digits_only)


@check("R-CMN-005")
def account_matches(ctx: Context):
    # 하이픈 표기 차이는 정규화 후 비교하므로 오탐이 나지 않는다.
    # (신청서 '59220101565992' vs 지급내역 '592201-01-565992' → 동일)
    return _cross_field(ctx, ("account_no",), nz.digits_only)


@check("R-CMN-006")
def bank_matches(ctx: Context):
    return _cross_field(ctx, ("bank",), nz.bank_alias)


@check("R-CMN-007")
def rrn_matches(ctx: Context):
    return _cross_field(ctx, ("rrn",), nz.digits_only)


@check("R-CMN-008")
def rrn_format(ctx: Context):
    failures = []
    for document in ctx.docs:
        value = document.fields.get("rrn")
        if value is None or not value.is_present:
            continue
        digits = nz.digits_only(value.value)
        if not _valid_rrn(digits):
            failures.append(Fail({"person.rrn": digits}, ctx.sources()))
    return failures


def _valid_rrn(digits: str) -> bool:
    if len(digits) != 13:
        return False
    month, day = int(digits[2:4]), int(digits[4:6])
    return 1 <= month <= 12 and 1 <= day <= 31 and digits[6] in "1234"


@check("R-CMN-009")
def department_matches(ctx: Context):
    return _cross_field(ctx, ("department",), nz.strip_spaces)


def _applies_to(ctx: Context, doc_type: str) -> bool:
    """이 지출종류가 애초에 요구하지 않는 서류라면 규칙을 돌리지 않는다.

    출장비에는 개인정보 동의서도 지급내역도 없다. 그런데도 검사하면
    '판독 불가'가 사람마다 2건씩 쌓여 정작 봐야 할 항목이 묻힌다.
    """
    required = getattr(ctx, "required_documents", [])
    return any(item["key"] == doc_type for item in required)


@check("R-CMN-011")
def consent_agreed(ctx: Context):
    if not _applies_to(ctx, "privacy_consent"):
        return None
    document = ctx.doc("privacy_consent")
    if document is None:
        raise NeedsReview("개인정보 동의서를 찾지 못했습니다")

    consents = document.fields.get("consents")
    if consents is None or not consents.is_present:
        raise NeedsReview("동의 체크 표기를 읽지 못했습니다")

    unchecked = [item["label"] for item in consents.value if not item["agreed"]]
    if unchecked:
        return Fail({"items": unchecked}, [document.source(1)])
    return None


@check("R-CMN-019")
def present_in_roster(ctx: Context):
    if not _applies_to(ctx, "payment_roster"):
        return None
    roster = ctx.doc("payment_roster")
    if roster is None:
        raise NeedsReview("지급내역을 찾지 못했습니다")

    rows = roster.fields.get("rows")
    if rows is None or not rows.is_present:
        raise NeedsReview("지급내역 표를 읽지 못했습니다")

    owner = _owner_name(ctx)
    if not owner:
        raise NeedsReview("검토 대상자의 성명을 확인하지 못했습니다")

    names = {nz.strip_spaces(row.get("name")) for row in rows.value if row.get("name")}
    if nz.strip_spaces(owner) not in names:
        return Fail(
            {"person.name": owner, "person.student_id": ctx.get("worklog.student_id", "")},
            [roster.source(1)],
        )
    return None


def _owner_name(ctx: Context) -> str | None:
    if ctx.docs.owner:
        return ctx.docs.owner
    for document in ctx.docs:
        for field_name in NAME_FIELDS:
            value = document.fields.get(field_name)
            if value is not None and value.is_present:
                return str(value.value)
    return None


# 팀원 명단 검사는 혁신인재지원금 전용이지만, 연락처 형식 검사는 공용으로 둔다.
PHONE_RE = re.compile(r"^01[016789]-?\d{3,4}-?\d{4}$")
