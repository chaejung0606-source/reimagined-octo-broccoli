"""내장 검사기 — YAML 의 `check:` 가 가리키는 판정 코드.

표현식 한 줄로 쓸 수 없는 판정(서류 완비성, 교차 대사, 중복 검출 등)을 여기 모았다.
등록되지 않은 이름은 엔진이 ⚪ 미검사로 표시한다 — 조용히 통과시키지 않는다.

OCR·Vision 이 있어야 하는 검사(서명 유무, 신분증 마스킹, 스캔 품질)는 4단계 몫이라
`unsupported()` 로 명시해 둔다. 무엇을 아직 못 보고 있는지가 화면에 남아야 한다.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Callable

from . import normalize as nz
from .classify import SATISFIED_BY
from .context import CheckResult, RuleContext, failed, ok, review, unsupported
from .fields import distinct_values
from .models import MISSING, Document, FieldStatus, Namespace, Status, format_value
from .rules import Rule

Checker = Callable[[RuleContext, Rule], CheckResult | list[CheckResult]]

CHECKS: dict[str, Checker] = {}


def register(name: str) -> Callable[[Checker], Checker]:
    def decorator(func: Checker) -> Checker:
        CHECKS[name] = func
        return func
    return decorator


_NORMALIZERS = {
    "strip_spaces": nz.strip_spaces,
    "digits_only": nz.digits_only,
    "bank_alias": nz.bank_alias,
    "money": nz.money,
}


# ============================================================ L0 서류 완비성

#: 여러 벌 제출되는 것이 정상인 서류
_REPEATABLE = {"transport_receipts", "stay_receipts", "purpose_evidence", "unknown"}


@register("document_set_complete")
def document_set_complete(ctx: RuleContext, rule: Rule) -> CheckResult:
    """지출종류별 필수 서류가 모두 왔는가 (R-CMN-001)."""
    present = {doc.kind for doc in ctx.case.documents}
    missing: list[str] = []
    staff_missing: list[str] = []

    for required in ctx.ruleset.required_documents:
        if required.optional:
            continue
        if required.key in present:
            continue
        if any(provider in present for provider in SATISFIED_BY.get(required.key, ())):
            continue
        (staff_missing if required.provided_by == "staff" else missing).append(required.label)

    if not missing and not staff_missing:
        return ok()

    labels = missing + [f"{label}(사업단 작성분)" for label in staff_missing]
    return failed(
        evidence=[f"제출 확인된 서류: {', '.join(sorted(present)) or '없음'}"],
        missing=", ".join(labels),
    )


@register("duplicate_documents")
def duplicate_documents(ctx: RuleContext, rule: Rule) -> CheckResult:
    """같은 성격의 서류가 여러 벌 왔는가 (R-CMN-002)."""
    patterns = ctx.param(rule.params, "suspicious_name_patterns", []) or []
    duplicates: list[str] = []

    grouped: dict[str, list[Document]] = defaultdict(list)
    for document in ctx.case.documents:
        if document.kind not in _REPEATABLE:
            grouped[document.kind].append(document)
    for kind, documents in grouped.items():
        if len(documents) > 1:
            names = ", ".join(sorted({doc.file.name for doc in documents}))
            duplicates.append(f"{documents[0].label or kind}: {names}")

    for document in ctx.case.documents:
        if any(pattern in document.file.name for pattern in patterns):
            entry = f"파일명 의심: {document.file.name}"
            if entry not in duplicates:
                duplicates.append(entry)

    if not duplicates:
        return ok()
    return failed(
        anchors=[doc.source() for doc in ctx.case.documents],
        duplicates="; ".join(duplicates),
    )


@register("block_present")
def block_present(ctx: RuleContext, rule: Rule) -> CheckResult:
    """서식 안에 특정 블록이 있는가 (R-TRV-002/003)."""
    if not rule.requires:
        return unsupported("검사할 블록이 지정되지 않았습니다")
    path = rule.requires[0]
    field = ctx.index.best(path)
    if field is None or field.is_missing:
        return review(f"{path} 를 확인할 수 없습니다")
    if field.value:
        return ok()
    return failed(anchors=[field.source] if field.source else [])


@register("approval_complete")
def approval_complete(ctx: RuleContext, rule: Rule) -> CheckResult:
    """출장신청서가 결재까지 끝난 문서인가 (R-TRV-001)."""
    missing: list[str] = []
    labels = {
        "trip_request.doc_no": "문서번호",
        "trip_request.issued_at": "시행일자",
        "trip_request.approvers": "결재선",
    }
    anchors = []
    for path, label in labels.items():
        field = ctx.index.best(path)
        if field is None or field.is_missing:
            return review(f"{label} 을(를) 읽지 못했습니다")
        if field.source:
            anchors.append(field.source)
        if not field.value:
            missing.append(label)
    if not missing:
        return ok()
    return failed(evidence=[f"비어 있는 항목: {', '.join(missing)}"], anchors=anchors,
                  missing=", ".join(missing))


# ============================================================ L1 문서 내부

@register("rrn_valid")
def rrn_valid(ctx: RuleContext, rule: Rule) -> CheckResult:
    """주민등록번호 13자리 + 생년월일 유효성 + 성별코드 (R-CMN-008)."""
    field = ctx.index.best("person.rrn")
    if field is None or field.is_missing:
        return review("주민등록번호를 읽지 못했습니다")
    digits = nz.digits_only(field.value)
    anchors = [field.source] if field.source else []

    if not digits or len(digits) != 13:
        return failed(evidence=[f"자릿수 {len(digits or '')}자리"], anchors=anchors)

    gender = int(digits[6])
    if gender not in range(1, 9):
        return failed(evidence=[f"성별코드 {gender}"], anchors=anchors)

    century = {1: 1900, 2: 1900, 3: 2000, 4: 2000, 5: 1900, 6: 1900, 7: 2000, 8: 2000}[gender]
    try:
        date(century + int(digits[0:2]), int(digits[2:4]), int(digits[4:6]))
    except ValueError:
        return failed(evidence=["생년월일이 실재하지 않는 날짜입니다"], anchors=anchors)
    return ok()


#: R-CMN-012 가 보는 '필수 입력칸'. 서식마다 칸이 다르므로 인적사항만 본다.
_REQUIRED_PATHS = {
    "person.name": "성명",
    "person.student_id": "학번",
    "person.bank": "은행명",
    "person.account_no": "계좌번호",
}


@register("required_fields_filled")
def required_fields_filled(ctx: RuleContext, rule: Rule) -> list[CheckResult]:
    """서류별로 비어 있는 필수 입력칸을 모은다 (R-CMN-012)."""
    results: list[CheckResult] = []
    for document in ctx.case.documents:
        if not document.readable:
            continue
        blanks = [
            label for path, label in _REQUIRED_PATHS.items()
            if (field := document.fields.get(path)) is not None
            and field.status is FieldStatus.BLANK
        ]
        if blanks:
            results.append(failed(
                anchors=[document.source()],
                label=str(document),
                document=str(document),
                blanks=", ".join(blanks),
            ))
    return results or [ok()]


@register("not_blank")
def not_blank(ctx: RuleContext, rule: Rule) -> CheckResult:
    """`requires` 의 칸이 실제로 채워져 있는가 (R-SCH-006)."""
    blanks: list[str] = []
    anchors = []
    for path in rule.requires:
        field = ctx.index.best(path)
        if field is None or field.is_missing:
            return review(f"{path} 칸을 찾지 못했습니다")
        if field.source:
            anchors.append(field.source)
        if field.status is FieldStatus.BLANK or field.value in (None, ""):
            blanks.append(path.rsplit(".", 1)[-1])
    if not blanks:
        return ok()
    return failed(evidence=[f"비어 있는 칸: {', '.join(blanks)}"], anchors=anchors,
                  blanks=", ".join(blanks))


@register("overlapping_time_ranges")
def overlapping_time_ranges(ctx: RuleContext, rule: Rule) -> CheckResult:
    """같은 날 시간대가 겹치는 근로 기록 (R-SCH-004)."""
    path = ctx.param(rule.params, "field", "worklog.rows")
    field = ctx.index.best(path)
    if field is None or field.is_missing or not field.value:
        return review(f"{path} 를 읽지 못했습니다")

    by_date: dict[Any, list[tuple[int, int, Namespace]]] = defaultdict(list)
    for row in field.value:
        start, end = nz.parse_time(row.start), nz.parse_time(row.end)
        if row.date is None or start is None or end is None:
            continue
        by_date[row.date].append((start[0] * 60 + start[1], end[0] * 60 + end[1], row))

    clashes: list[str] = []
    for day, spans in by_date.items():
        spans.sort()
        for (start_a, end_a, _), (start_b, end_b, _) in zip(spans, spans[1:]):
            if start_b < end_a:
                clashes.append(f"{format_value(day)} ({start_a // 60:02d}시~{end_a // 60:02d}시 / "
                               f"{start_b // 60:02d}시~{end_b // 60:02d}시)")
    if not clashes:
        return ok()
    return failed(evidence=clashes, anchors=[field.source] if field.source else [],
                  dates=", ".join(clashes))


@register("detail_text_quality")
def detail_text_quality(ctx: RuleContext, rule: Rule) -> CheckResult:
    """근로상세내역이 공란이거나 전 행 같은 문구인가 (R-SCH-005)."""
    path = ctx.param(rule.params, "field", "worklog.rows[].detail")
    base, _, key = path.partition("[].")
    field = ctx.index.best(base)
    if field is None or field.is_missing or not field.value:
        return review(f"{base} 를 읽지 못했습니다")

    minimum = int(ctx.param(rule.params, "min_length", 5) or 5)
    flag_identical = bool(ctx.param(rule.params, "flag_if_all_identical", True))

    details = [nz.strip_spaces(row[key]) or "" for row in field.value]
    if not details:
        return review("근로상세내역 칸을 찾지 못했습니다")

    blanks = [i + 1 for i, text in enumerate(details) if len(text) < minimum]
    identical = flag_identical and len(set(details)) == 1 and len(details) > 1

    if not blanks and not identical:
        return ok()
    evidence = []
    if blanks:
        evidence.append(f"{len(blanks)}개 행이 {minimum}자 미만입니다 (행 {', '.join(map(str, blanks[:8]))})")
    if identical:
        evidence.append(f"모든 행이 같은 문구입니다: '{details[0]}'")
    return failed(evidence=evidence, anchors=[field.source] if field.source else [])


@register("member_list_sanity")
def member_list_sanity(ctx: RuleContext, rule: Rule) -> CheckResult:
    """팀원 명단의 중복·연락처 형식 (R-INN-015)."""
    path = ctx.param(rule.params, "field", "form7_1_report.members")
    field = ctx.index.best(path)
    if field is None or field.is_missing:
        return review("팀원 명단을 읽지 못했습니다")
    members = list(field.value or [])
    if not members:
        return review("팀원 명단이 비어 있습니다")

    issues: list[str] = []
    counter = Counter((nz.strip_spaces(m.name), nz.digits_only(m.student_id)) for m in members)
    for (name, student_id), count in counter.items():
        if count > 1 and name:
            issues.append(f"중복 인원: {name}({student_id}) {count}회")

    for member in members:
        phone = nz.digits_only(member.phone)
        if member.phone and (phone is None or len(phone) not in (10, 11)):
            issues.append(f"{member.name} 연락처 형식 오류: {member.phone}")

    if not issues:
        return ok()
    return failed(evidence=issues, anchors=[field.source] if field.source else [],
                  issues="; ".join(issues))


@register("outcome_table_filled")
def outcome_table_filled(ctx: RuleContext, rule: Rule) -> CheckResult:
    """성과표 실적이 전부 공란/0인가 (R-INN-018)."""
    path = ctx.param(rule.params, "field", "form7_1_report.outcomes")
    field = ctx.index.best(path)
    if field is None or field.is_missing:
        return review("성과표를 읽지 못했습니다")
    outcomes = list(field.value or [])
    if not outcomes:
        return review("성과표 행을 찾지 못했습니다")

    def empty(value: Any) -> bool:
        return value is None or value == 0

    if all(empty(o.this_month) and empty(o.cumulative) for o in outcomes):
        return failed(
            evidence=[f"{o.category}: 이번 달 {format_value(o.this_month)} / 누적 {format_value(o.cumulative)}"
                      for o in outcomes[:5]],
            anchors=[field.source] if field.source else [],
        )
    return ok()


@register("checkbox_matches_attachments")
def checkbox_matches_attachments(ctx: RuleContext, rule: Rule) -> CheckResult:
    """신청서에 체크한 증빙서류가 실제로 첨부되었는가 (R-INN-019)."""
    path = ctx.param(rule.params, "field", "form8_application.attachments_checked")
    field = ctx.index.best(path)
    if field is None or field.is_missing:
        return review("증빙서류 체크박스를 읽지 못했습니다")

    checked = list(field.value or [])
    if not checked:
        return review("체크된 증빙서류 항목이 없습니다 — 체크박스 판독은 OCR 단계 필요")

    present = {doc.kind for doc in ctx.case.documents}
    labels = {r.key: r.label for r in ctx.ruleset.required_documents}
    missing = [
        labels.get(key, key) for key in checked
        if key not in present
        and not any(provider in present for provider in SATISFIED_BY.get(key, ()))
    ]
    if not missing:
        return ok()
    return failed(evidence=[f"체크된 항목: {', '.join(checked)}"],
                  anchors=[field.source] if field.source else [],
                  missing=", ".join(missing))


_TYPO_PATTERNS = [
    (re.compile(r"(\d{1,2})\s*원\s*(\d{1,2})\s*일"), "'{0}원 {1}일' → '{0}월 {1}일' 로 보입니다"),
    (re.compile(r"(\d{1,2})\s*월\s*(3[2-9]|[4-9]\d)\s*일"), "'{0}월 {1}일' 은 없는 날짜입니다"),
    (re.compile(r"(1[3-9]|[2-9]\d)\s*월\s*(\d{1,2})\s*일"), "'{0}월 {1}일' 은 없는 달입니다"),
]


@register("text_anomaly")
def text_anomaly(ctx: RuleContext, rule: Rule) -> CheckResult:
    """본문 오탈자·날짜 표기 오류 (R-INN-020). 샘플의 `5원 4일` 이 대표 사례."""
    paths = ctx.param(rule.params, "fields", []) or []
    chunks: list[str] = []
    anchors = []
    for path in paths:
        field = ctx.index.best(path)
        if field is None or field.is_missing or not field.value:
            continue
        if field.source:
            anchors.append(field.source)
        value = field.value
        chunks.extend(value if isinstance(value, list) else [str(value)])

    if not chunks:
        return review("검사할 본문을 읽지 못했습니다")

    found: list[str] = []
    for chunk in chunks:
        for pattern, template in _TYPO_PATTERNS:
            for match in pattern.finditer(str(chunk)):
                found.append(template.format(*match.groups()))
    if not found:
        return ok()
    return failed(evidence=found, anchors=anchors, found="; ".join(dict.fromkeys(found)))


# ============================================================ L2 교차 대사

@register("cross_field_equal")
def cross_field_equal(ctx: RuleContext, rule: Rule) -> list[CheckResult]:
    """같은 항목이 서류마다 같은 값인가 (R-CMN-003~009, R-TRV-015, R-INN-005/007).

    정규화 후 비교한다. `59220101565992` 와 `592201-01-565992` 는 같은 계좌다 —
    여기서 오탐이 나면 앱을 못 쓴다.
    """
    params = rule.params
    paths = params.get("fields") or ([params["field"]] if params.get("field") else [])
    if not paths:
        return [unsupported("비교할 필드가 지정되지 않았습니다")]

    sources = set(params.get("sources") or ())
    normalizer = _NORMALIZERS.get(params.get("normalize", ""), nz.strip_spaces)

    results: list[CheckResult] = []
    for path in paths:
        entries = ctx.index.present_entries(path)
        if sources:
            entries = [(d, f) for d, f in entries if d is not None and d.kind in sources]
        if len(entries) < 2:
            # 비교 대상이 한 곳뿐이면 '다르다' 고 말할 근거가 없다. 주민번호처럼
            # 원래 한 서류에만 적는 항목까지 🔵 로 올리면 결과가 못 쓰게 된다.
            results.append(ok())
            continue

        groups = distinct_values(entries, normalizer)
        if len(groups) <= 1:
            results.append(ok())
            continue

        expected = max(groups.items(), key=lambda item: len(item[1]))[0]
        detail = " / ".join(
            f"{format_value(value)} ({', '.join(sorted(set(docs)))})"
            for value, docs in groups.items()
        )
        results.append(failed(
            evidence=[detail],
            anchors=[f.source for _, f in entries if f.source],
            label=path,
            values=detail,
            expected=format_value(expected),
        ))
    return results or [review("비교할 값이 한 곳에만 있습니다")]


@register("present_in_payment_roster")
def present_in_payment_roster(ctx: RuleContext, rule: Rule) -> CheckResult:
    """지급내역에 대상자가 실제로 있는가 (R-CMN-019)."""
    rows_field = ctx.index.best("roster.rows")
    if rows_field is None or rows_field.is_missing:
        return review("지급내역을 읽지 못했습니다")
    rows = list(rows_field.value or [])
    if not rows:
        return review("지급내역에서 행을 찾지 못했습니다")

    name = nz.strip_spaces((ctx.index.best("person.name") or _EMPTY).value)
    student_id = nz.digits_only((ctx.index.best("person.student_id") or _EMPTY).value)
    if not name and not student_id:
        return review("제출 서류에서 성명·학번을 읽지 못했습니다")

    for row in rows:
        if student_id and nz.digits_only(row.student_id) == student_id:
            return ok()
        if name and nz.strip_spaces(row.name) == name:
            return ok()

    listed = ", ".join(str(row.name) for row in rows[:8] if row.name)
    return failed(evidence=[f"지급내역 대상자: {listed}"],
                  anchors=[rows_field.source] if rows_field.source else [])


class _Empty:
    value = None
    source = None
    is_missing = True


_EMPTY = _Empty()


# ---------------------------------------------------------------- 영수증

def _receipts(ctx: RuleContext, path: str = "receipts") -> list[Namespace] | None:
    field = ctx.index.best(path)
    if field is None or field.is_missing:
        return None
    return list(field.value or [])


@register("receipts_within_period")
def receipts_within_period(ctx: RuleContext, rule: Rule) -> list[CheckResult]:
    """영수증 일시가 출장기간 안에 있는가 (R-TRV-011).

    기간 밖 영수증에는 성격이 다른 두 가지가 섞여 있다. 하나로 묶어 ERROR 를 내면
    샘플의 이성재(다른 날짜 영수증 5건을 함께 제출했지만 청구는 기간 내 3건만)가
    통째로 오탐이 된다.

    - 출장 경계에서 몇 시간 이내 → **출장기간 기재가 틀린 것** → ERROR
      (이동재: 종료 7/3 12:00, 귀로 통행료 7/3 13:20)
    - 며칠 떨어진 날짜 → **다른 건의 영수증이 섞인 것** → WARN
    """
    period_field = ctx.index.best("trip_request.period")
    if period_field is None or period_field.is_missing or not period_field.value:
        return [review("출장기간을 읽지 못했습니다")]
    period = period_field.value

    receipts = _receipts(ctx)
    if receipts is None:
        return [review("영수증을 읽지 못했습니다")]
    dated = [r for r in receipts if isinstance(r.datetime, datetime)]
    if not dated:
        return [review("일시를 읽은 영수증이 없습니다 — 이미지 영수증은 OCR 단계 필요")]

    window = timedelta(hours=float(ctx.param(rule.params, "near_boundary_hours", 24) or 24))
    near: list[Namespace] = []
    far: list[Namespace] = []
    for receipt in dated:
        if receipt.datetime in period:
            continue
        (near if _distance_to(period, receipt.datetime) <= window else far).append(receipt)

    if not near and not far:
        return [ok()]

    results: list[CheckResult] = []
    if near:
        results.append(failed(
            evidence=[f"{r.label} — {format_value(r.datetime)} ({format_value(r.amount)}원)"
                      for r in near],
            anchors=[period_field.source] if period_field.source else [],
            receipts=", ".join(str(r.label) for r in near),
        ))
    if far:
        results.append(CheckResult(
            ok=False,
            status=Status.WARN,
            evidence=[f"{r.label} — {format_value(r.datetime)} ({format_value(r.amount)}원)"
                      for r in far],
            reason=("출장기간에서 하루 이상 떨어진 영수증입니다. 다른 건의 영수증이 "
                    "섞였는지 확인하세요 — 정산 대상이 아니라면 빼고 제출하면 됩니다."),
            extras={"receipts": ", ".join(str(r.label) for r in far)},
        ))
    return results


def _distance_to(period, moment: datetime) -> timedelta:
    """출장기간 경계로부터 얼마나 떨어져 있는가."""
    candidates = []
    for edge in (period.start, period.end):
        if isinstance(edge, datetime):
            candidates.append(abs(moment - edge))
        elif isinstance(edge, date):
            candidates.append(abs(moment - datetime(edge.year, edge.month, edge.day)))
    return min(candidates) if candidates else timedelta.max


@register("duplicate_receipts")
def duplicate_receipts(ctx: RuleContext, rule: Rule) -> CheckResult:
    """같은 영수증이 두 번 들어왔는가 (R-TRV-019)."""
    receipts = _receipts(ctx)
    if receipts is None:
        return review("영수증을 읽지 못했습니다")
    if not receipts:
        return review("영수증을 한 건도 추출하지 못했습니다 — 이미지 영수증은 OCR 단계 필요")

    keys = ctx.param(rule.params, "keys", ["approval_no", "datetime", "amount"])
    grouped: dict[tuple, list[Namespace]] = defaultdict(list)
    for receipt in receipts:
        signature = tuple(format_value(receipt[key]) for key in keys)
        if all(part in ("(공란)", "(미추출)") for part in signature):
            continue
        grouped[signature].append(receipt)

    duplicates = [group for group in grouped.values() if len(group) > 1]
    if not duplicates:
        return ok()
    detail = "; ".join(
        f"{group[0].label} × {len(group)}건" for group in duplicates
    )
    return failed(evidence=[detail], duplicates=detail)


@register("receipt_totals_match")
def receipt_totals_match(ctx: RuleContext, rule: Rule) -> list[CheckResult]:
    """영수증에 적힌 합계와 개별 건의 합이 맞는가 (R-TRV-010).

    두 가지 형태를 모두 본다.
    - 나열형(하이패스 `총 8건 / 합계 33,900원`) → 문서 단위로 건수·금액 대조
    - 전표형(편의점 품목표)                     → 영수증 단위로 품목 합계 대조
    """
    receipts = _receipts(ctx)
    if receipts is None:
        return [review("영수증을 읽지 못했습니다")]

    results: list[CheckResult] = []

    pages: dict[str, list[Namespace]] = defaultdict(list)
    for receipt in receipts:
        if receipt.page_total is not MISSING:
            pages[str(receipt.file)].append(receipt)
    for file, group in pages.items():
        stated = group[0].page_total
        total = sum(r.amount for r in group if isinstance(r.amount, (int, float)))
        count = group[0].page_count
        problems = []
        if stated is not MISSING and total != stated:
            problems.append(f"개별 건 합계 {total:,}원 vs 표기 합계 {stated:,}원")
        if count is not MISSING and len(group) != count:
            problems.append(f"추출된 건수 {len(group)}건 vs 표기 건수 {count}건")
        if problems:
            results.append(failed(evidence=problems, label=file,
                                  receipt=file, computed=total))

    for receipt in receipts:
        items = list(receipt.items or [])
        if not items or receipt.stated_total is MISSING:
            continue
        total = sum(item.amount for item in items if isinstance(item.amount, (int, float)))
        if total != receipt.stated_total:
            results.append(failed(
                evidence=[f"품목 합계 {total:,}원 vs 표기 총액 {receipt.stated_total:,}원"],
                label=str(receipt.label), receipt=str(receipt.label), computed=total,
            ))

    if results:
        return results
    if not pages and not any(r.items for r in receipts):
        return [review("합계가 표기된 영수증이 없습니다 — 전표 판독은 OCR 단계 필요")]
    return [ok()]


@register("card_consistency")
def card_consistency(ctx: RuleContext, rule: Rule) -> CheckResult:
    """영수증 카드번호가 서로 다른가 (R-TRV-022). 타인 명의 결제 의심."""
    receipts = _receipts(ctx)
    if receipts is None:
        return review("영수증을 읽지 못했습니다")
    cards = Counter(str(r.card_no) for r in receipts if r.card_no)
    if len(cards) <= 1:
        return ok()
    detail = ", ".join(f"{card}({count}건)" for card, count in cards.most_common())
    return failed(evidence=[detail], receipt=detail)


@register("contains_keyword")
def contains_keyword(ctx: RuleContext, rule: Rule) -> list[CheckResult]:
    """영수증 품목에 정산 불가 항목이 있는가 (R-TRV-023)."""
    keywords = ctx.param(rule.params, "keywords", []) or []
    if not keywords:
        return [unsupported("검사할 키워드가 설정되지 않았습니다")]
    receipts = _receipts(ctx)
    if receipts is None:
        return [review("영수증을 읽지 못했습니다")]

    results: list[CheckResult] = []
    inspected = 0
    for receipt in receipts:
        items = list(receipt.items or [])
        if not items:
            continue
        inspected += 1
        hits = [item.name for item in items
                if any(keyword in str(item.name) for keyword in keywords)]
        if hits:
            results.append(failed(
                evidence=[f"{receipt.label}: {', '.join(hits)}"],
                label=str(receipt.label),
                receipt=str(receipt.label),
                found=", ".join(hits),
            ))
    if results:
        return results
    if inspected == 0:
        return [review("품목이 적힌 영수증이 없습니다 — 편의점 전표는 OCR 단계 필요")]
    return [ok()]


@register("tollgate_route_continuity")
def tollgate_route_continuity(ctx: RuleContext, rule: Rule) -> CheckResult:
    """하이패스 입구/출구가 이동경로로 이어지는가 (R-TRV-014)."""
    receipts = _receipts(ctx, "transport_receipts")
    if receipts is None:
        return review("교통비 영수증을 읽지 못했습니다")
    tolls = [r for r in receipts if r.kind == "tollgate" and r.datetime]
    if len(tolls) < 2:
        return review("하이패스 영수증이 2건 미만이라 연속성을 볼 수 없습니다")

    tolls.sort(key=lambda r: r.datetime)
    breaks: list[str] = []
    for previous, current in zip(tolls, tolls[1:]):
        exit_gate = nz.strip_spaces(previous.tollgate_out)
        enter_gate = nz.strip_spaces(current.tollgate_in)
        if exit_gate and enter_gate and exit_gate != enter_gate:
            breaks.append(f"{previous.label} 출구 '{exit_gate}' → {current.label} 입구 '{enter_gate}'")
    if not breaks:
        return ok()
    return failed(evidence=breaks, breaks="; ".join(breaks))


@register("spatiotemporal_conflict")
def spatiotemporal_conflict(ctx: RuleContext, rule: Rule) -> list[CheckResult]:
    """같은 시간대에 서로 먼 곳의 영수증이 있는가 (R-TRV-024)."""
    window = int(ctx.param(rule.params, "window_minutes", 60) or 60)
    receipts = _receipts(ctx)
    if receipts is None:
        return [review("영수증을 읽지 못했습니다")]

    located = [r for r in receipts if r.datetime and r.merchant_address]
    if len(located) < 2:
        return [review("소재지가 적힌 영수증이 2건 미만입니다 — 이미지 전표는 OCR 단계 필요")]

    located.sort(key=lambda r: r.datetime)
    results: list[CheckResult] = []
    for previous, current in zip(located, located[1:]):
        if current.datetime - previous.datetime > timedelta(minutes=window):
            continue
        region_a = nz.region_of(previous.merchant_address)
        region_b = nz.region_of(current.merchant_address)
        if region_a and region_b and region_a != region_b:
            results.append(failed(
                evidence=[f"{previous.label}({region_a}) / {current.label}({region_b})"],
                time=format_value(current.datetime),
                receipts=f"{previous.label}, {current.label}",
            ))
    return results or [ok()]


@register("purpose_supported")
def purpose_supported(ctx: RuleContext, rule: Rule) -> CheckResult:
    """출장목적을 뒷받침하는 근거자료가 있는가 (R-TRV-018)."""
    if ctx.case.has("purpose_evidence"):
        return ok()
    purpose = ctx.index.best("trip_request.purpose")
    return failed(
        evidence=["출장목적 근거자료로 분류된 파일이 없습니다"],
        anchors=[purpose.source] if purpose and purpose.source else [],
    )


# ======================================================= OCR·Vision 필요분

@register("signature_present")
def signature_present(ctx: RuleContext, rule: Rule) -> CheckResult:
    return unsupported("서명란 판독은 이미지 분석이 필요합니다 (4단계)")


@register("id_card_rrn_full_visible")
def id_card_rrn_full_visible(ctx: RuleContext, rule: Rule) -> CheckResult:
    return unsupported("신분증 사본 판독은 Vision 단계가 필요합니다 (4단계)")


@register("consent_all_agreed")
def consent_all_agreed(ctx: RuleContext, rule: Rule) -> CheckResult:
    """개인정보 동의 3항목이 모두 `동의함` 인가 (R-CMN-011).

    동의서에 텍스트 레이어가 있으면 여기서 판정하고, 스캔본이면 4단계로 넘긴다.
    """
    consent_kinds = {"form2_privacy_consent", "privacy_consent", "id_bankbook_enrollment"}
    documents = [doc for doc in ctx.case.documents if doc.kind in consent_kinds]
    if not documents:
        # 혁신인재지원금은 동의 항목이 신청서(양식8) 안에 들어 있다.
        inline = ctx.index.best("form8_application.consent")
        if inline is not None and not inline.is_missing:
            return ok() if inline.value else failed(
                evidence=["신청서의 개인정보 동의란에 '동의함' 표기가 없습니다"],
                anchors=[inline.source] if inline.source else [],
                items="개인정보 수집·이용 동의",
            )
        return review("개인정보 동의서를 찾지 못했습니다")

    readable = [doc for doc in documents if doc.readable]
    if not readable:
        return unsupported("동의서가 스캔본입니다 — 체크 판독은 4단계(OCR)")

    items: list[str] = []
    for document in readable:
        for line in document.lines:
            if "동의" not in line:
                continue
            packed = nz.strip_spaces(line) or ""
            if "동의하지" in packed or "미동의" in packed:
                items.append(line.strip())
    if not items:
        return ok()
    return failed(evidence=items, items="; ".join(items[:3]))


@register("scan_quality")
def scan_quality(ctx: RuleContext, rule: Rule) -> list[CheckResult]:
    """자동 검토가 가능한 상태인가 (R-CMN-018).

    해상도·기울기 측정은 이미지 분석이 필요하지만, **텍스트 레이어가 아예 없는 서류**는
    지금도 알 수 있다. 그 목록만이라도 올려 두어야 무엇이 검토에서 빠졌는지 남는다.
    """
    blind = [doc for doc in ctx.case.documents if not doc.readable]
    if not blind:
        return [ok()]
    return [review(
        reason="텍스트 레이어가 없어 내용을 대조하지 못했습니다 (해상도·기울기 판정은 4단계)",
        evidence=[f"{doc} — {doc.read_error or '스캔 이미지'}" for doc in blind],
        anchors=[doc.source() for doc in blind],
    )]


@register("shared_trip_duplicate_claim")
def shared_trip_duplicate_claim(ctx: RuleContext, rule: Rule) -> CheckResult:
    return unsupported("동승 중복 청구는 여러 사람을 함께 넣는 묶음 모드가 필요합니다 (5단계)")
