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


# ── 제출 시점 ─────────────────────────────────────────────────────────────

# 서류에 적힌 작성일. 검토를 언제 돌리는지와 무관하게 '제출 시점' 을 정한다.
# dt.date.today() 를 쓰면 지난 학기 건을 다시 검토할 때 재학증명서가 전부
# 기간 초과로 잡힌다.
SUBMITTED_FIELDS = ("submitted_at", "signed_at")


def _submission_date(ctx: Context):
    """서류에 적힌 작성일 중 가장 늦은 날짜. 제출 시점의 근사값이다."""
    dates = [
        value.value
        for document in ctx.docs
        for name in SUBMITTED_FIELDS
        if (value := document.fields.get(name)) is not None and value.is_present
    ]
    if not dates:
        raise NeedsReview("서류에서 작성일을 찾지 못해 제출 시점을 알 수 없습니다")
    return max(dates)


@check("R-CMN-013")
def enrollment_cert_fresh(ctx: Context):
    if not _applies_to(ctx, "enrollment_cert"):
        return None
    document = ctx.doc("enrollment_cert")
    if document is None:
        return None  # 아예 없는 것은 R-CMN-001 이 보고한다

    issued = document.fields.get("issued_at")
    if issued is None or not issued.is_present:
        raise NeedsReview("재학증명서의 발급일을 읽지 못했습니다")

    limit = ctx.number_setting("enrollment_cert_valid_days")
    elapsed = (_submission_date(ctx) - issued.value).days
    if elapsed > limit:
        return Fail(
            {"enrollment_cert.issued_at": issued.value.isoformat(), "elapsed": elapsed},
            [document.source(1)],
        )
    return None


# ── 통장 사본 대사 ────────────────────────────────────────────────────────

def _bankbook(ctx: Context):
    """통장 사본 문서. 이 지출종류가 요구하지 않거나 안 냈으면 None."""
    if not _applies_to(ctx, "id_card_bankbook"):
        return None
    return ctx.doc("id_card_bankbook")


@check("R-CMN-015")
def bankbook_holder_is_applicant(ctx: Context):
    document = _bankbook(ctx)
    if document is None:
        return None

    holder = document.fields.get("bankbook_holder")
    if holder is None or not holder.is_present:
        raise NeedsReview("통장 사본의 예금주를 읽지 못했습니다")

    applicant = _owner_name(ctx)
    if not applicant:
        raise NeedsReview("신청인의 성명을 확인하지 못했습니다")

    if nz.strip_spaces(holder.value) != nz.strip_spaces(applicant):
        return Fail(
            {"bankbook.holder": holder.value, "person.name": applicant},
            [document.source(1)],
        )
    return None


@check("R-CMN-016")
def bankbook_account_matches(ctx: Context):
    document = _bankbook(ctx)
    if document is None:
        return None

    account = document.fields.get("bankbook_account_no")
    if account is None or not account.is_present:
        raise NeedsReview("통장 사본의 계좌번호를 읽지 못했습니다")

    # 신청서·지급내역 등 나머지 서류가 적어 낸 계좌. 서류끼리 갈리는 경우는
    # R-CMN-005 가 따로 보고하므로, 여기서는 가장 많이 쓰인 값과 비교한다.
    stated: dict[str, list[str]] = {}
    for other in ctx.docs:
        value = other.fields.get("account_no")
        if value is not None and value.is_present:
            stated.setdefault(nz.digits_only(value.value), []).append(other.name)
    if not stated:
        raise NeedsReview("신청서에 기재된 계좌번호를 읽지 못했습니다")

    expected = max(stated, key=lambda key: len(stated[key]))
    if nz.digits_only(account.value) != expected:
        return Fail(
            {"bankbook.account_no": account.value, "person.account_no": expected},
            [document.source(1)],
        )
    return None


# ── 작성일 ────────────────────────────────────────────────────────────────

# 활동이 끝난 뒤에 쓰는 서류만 본다. 개인정보 동의서는 사전 동의라 활동
# 종료일보다 앞선 것이 정상이므로 대상이 아니다.
_AFTER_ACTIVITY_TYPES = ("worklog", "claim_form", "monthly_report",
                         "club_report", "innovation_application")


@check("R-CMN-017")
def written_after_activity(ctx: Context):
    ends = [
        value.value[1]
        for document in ctx.docs
        if (value := document.fields.get("period")) is not None and value.is_present
        and isinstance(value.value, tuple) and len(value.value) == 2
    ]
    if not ends:
        return None  # 활동기간이 없는 지출종류(출장비)에는 해당하지 않는다
    activity_end = max(ends)

    failures = []
    for document in ctx.docs:
        if not (document.contains & set(_AFTER_ACTIVITY_TYPES)):
            continue
        written = document.fields.get("submitted_at")
        if written is None or not written.is_present:
            continue
        if written.value < activity_end:
            failures.append(Fail(
                {"submission.date": written.value.isoformat(),
                 "period.end": activity_end.isoformat()},
                [document.source(1)],
            ))
    return failures
