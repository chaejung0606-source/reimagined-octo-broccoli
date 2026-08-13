"""근로장학금 규칙 판정 (R-SCH-*).

핵심 축은 '시간 × 단가 = 금액' 의 삼중 대사다.
근무상황부(시간) → 지급내역(단가·금액) → 청구서(청구금액) 가 한 줄로 이어져야 한다.
"""
from __future__ import annotations

from .. import normalize as nz
from ..engine import Context, Fail, NeedsReview, NotApplicable, check


def _rows(ctx: Context) -> list[dict]:
    # 서포터즈형은 인쇄 서식 근무상황부 대신 손글씨 근무일지를 낸다.
    # 읽지 못한다는 사실은 추출 안내로 이미 한 번 보고되므로, 행 단위 규칙마다
    # 같은 말을 반복하지 않는다.
    if not ctx.requires_doc("worklog"):
        raise NotApplicable
    rows = ctx.value("worklog.rows")
    if rows is None or not rows.is_present:
        raise NeedsReview("근무상황부의 근로일자 표를 읽지 못했습니다")
    return rows.value


def _roster_row(ctx: Context) -> dict:
    """지급내역에서 검토 대상자의 행을 찾는다."""
    roster = ctx.doc("payment_roster")
    if roster is None:
        raise NeedsReview("지급내역을 찾지 못했습니다")
    rows = roster.fields.get("rows")
    if rows is None or not rows.is_present:
        raise NeedsReview("지급내역 표를 읽지 못했습니다")

    account = nz.digits_only(ctx.get("worklog.account_no") or "")
    name = nz.strip_spaces(ctx.docs.owner or ctx.get("worklog.name") or "")

    matched = [r for r in rows.value if account and r.get("account_no") == account]
    if not matched and name:
        matched = [r for r in rows.value if nz.strip_spaces(r.get("name") or "") == name]
    if not matched:
        raise NeedsReview("지급내역에서 대상자의 행을 찾지 못했습니다")

    # 한 사람이 여러 강좌를 맡으면 행이 여러 개다. 근무상황부의 시간과 맞는 행을 고른다.
    if len(matched) == 1:
        return matched[0]

    hours = ctx.get("worklog.total_hours")
    if hours is not None:
        same = [r for r in matched if r.get("hours") == hours]
        if len(same) == 1:
            return same[0]
        matched = same or matched

    # 근무상황부의 '프로그램/역할'(= 강좌명 + 역할)과 지급내역 강좌명을 맞춘다.
    program = ctx.get("worklog.program") or ""
    if program and len(matched) > 1:
        scored = sorted(
            ((nz.similarity(program, r.get("course_name") or ""), r) for r in matched),
            key=lambda pair: pair[0], reverse=True,
        )
        if scored[0][0] >= 0.6 and (len(scored) == 1 or scored[0][0] - scored[1][0] > 0.05):
            return scored[0][1]

    raise NeedsReview(f"지급내역에 대상자 행이 {len(matched)}개라 어느 강좌 분인지 특정할 수 없습니다")


# ── L1 : 근무상황부 내부 계산 ─────────────────────────────────────────────

@check("R-SCH-001")
def row_hours(ctx: Context):
    failures = []
    for row in _rows(ctx):
        computed = row.get("computed_hours")
        stated = row.get("hours")
        if computed is None or stated is None:
            continue
        if computed != stated:
            failures.append(Fail({
                "row.date": row["date"].isoformat() if row.get("date") else "?",
                "row.start": row.get("start"), "row.end": row.get("end"),
                "row.hours": stated, "computed": computed,
            }, ctx.sources("worklog.rows")))
    return failures


@check("R-SCH-002")
def total_hours(ctx: Context):
    rows = _rows(ctx)
    stated = ctx.require("worklog.total_hours")
    computed = round(sum(row.get("hours") or 0 for row in rows), 2)
    if computed != stated:
        return Fail({"computed": computed, "worklog.total_hours": stated},
                    ctx.sources("worklog.total_hours"))
    return None


@check("R-SCH-003")
def rows_within_period(ctx: Context):
    rows = _rows(ctx)          # 해당 없는 하위 유형이면 여기서 조용히 빠진다
    start, end = ctx.require("worklog.period")
    failures = []
    for row in rows:
        date = row.get("date")
        if date and not (start <= date <= end):
            failures.append(Fail({
                "row.date": date.isoformat(),
                "worklog.period.start": start.isoformat(),
                "worklog.period.end": end.isoformat(),
            }, ctx.sources("worklog.rows")))
    return failures


@check("R-SCH-004")
def overlapping_rows(ctx: Context):
    by_date: dict = {}
    for row in _rows(ctx):
        if row.get("date"):
            by_date.setdefault(row["date"], []).append(row)

    clashing = []
    for date, rows in by_date.items():
        spans = sorted(
            (nz.parse_time(r.get("start")), nz.parse_time(r.get("end")))
            for r in rows if r.get("start") and r.get("end")
        )
        for previous, current in zip(spans, spans[1:]):
            if previous[1] and current[0] and current[0] < previous[1]:
                clashing.append(date.isoformat())
                break
    if clashing:
        return Fail({"dates": sorted(set(clashing))}, ctx.sources("worklog.rows"))
    return None


@check("R-SCH-005")
def detail_quality(ctx: Context):
    rows = _rows(ctx)
    details = [(row.get("detail") or "").strip() for row in rows]
    if not details:
        return None
    if all(not detail for detail in details):
        return Fail({}, ctx.sources("worklog.rows"))
    if len(details) > 1 and len(set(details)) == 1:
        return Fail({}, ctx.sources("worklog.rows"))
    return None


# ── L2 : 서류 간 대사 ─────────────────────────────────────────────────────

@check("R-SCH-008")
def hours_match_roster(ctx: Context):
    if not ctx.requires_doc("worklog"):
        return None
    stated = ctx.require("worklog.total_hours")
    row = _roster_row(ctx)
    if row.get("hours") is None:
        raise NeedsReview("지급내역의 시간 칸을 읽지 못했습니다")
    if row["hours"] != stated:
        return Fail({"worklog.total_hours": stated, "roster.hours": row["hours"]})
    return None


@check("R-SCH-009")
def amount_calculation(ctx: Context):
    row = _roster_row(ctx)
    unit, hours, amount = row.get("unit_price"), row.get("hours"), row.get("amount")
    if None in (unit, hours, amount):
        raise NeedsReview("지급내역의 단가·시간·금액을 모두 읽지 못했습니다")
    computed = int(unit * hours)
    if computed != amount:
        return Fail({
            "roster.unit_price": unit, "roster.hours": hours,
            "roster.amount": amount, "computed": computed,
        })
    return None


@check("R-SCH-010")
def claim_matches_roster(ctx: Context):
    if not ctx.requires_doc("claim_form"):
        return None
    claim = ctx.require("claim_form.amount")
    row = _roster_row(ctx)
    if row.get("amount") is None:
        raise NeedsReview("지급내역의 금액을 읽지 못했습니다")
    if claim != row["amount"]:
        return Fail({"claim_form.amount": claim, "roster.amount": row["amount"]},
                    ctx.sources("claim_form.amount"))
    return None


@check("R-SCH-011")
def period_matches(ctx: Context):
    if not ctx.requires_doc("claim_form"):
        return None
    claim_period = ctx.require("claim_form.period")
    worklog_period = ctx.value("worklog.period")
    if worklog_period is None or not worklog_period.is_present:
        raise NeedsReview("근무상황부의 근로기간을 읽지 못했습니다")
    if tuple(claim_period) != tuple(worklog_period.value):
        return Fail({
            "claim_form.period": _span(claim_period),
            "worklog.period": _span(worklog_period.value),
        })
    return None


@check("R-SCH-012")
def report_hours_match(ctx: Context):
    if not ctx.requires_doc("monthly_report"):
        return None
    report_hours = ctx.require("monthly_report.hours")
    worklog_hours = ctx.get("worklog.total_hours") or ctx.get("worklog_handwrite.total_hours")
    if worklog_hours is None:
        raise NeedsReview("근무일지의 총 시간을 읽지 못했습니다(손글씨 서식)")
    if report_hours != worklog_hours:
        return Fail({"monthly_report.hours": report_hours, "worklog.total_hours": worklog_hours})
    return None


@check("R-SCH-013")
def approver_is_professor(ctx: Context):
    if not ctx.requires_doc("ta_recommendation"):
        return None
    approver = ctx.require("worklog.approver")
    professor = ctx.require("ta_recommendation.professor")
    if nz.strip_spaces(approver) != nz.strip_spaces(professor):
        return Fail({"worklog.approver": approver, "ta_recommendation.professor": professor})
    return None


@check("R-SCH-015")
def period_within_course(ctx: Context):
    if not ctx.requires_doc("ta_recommendation"):
        return None
    worklog_period = ctx.require("worklog.period")
    operating = ctx.require("ta_recommendation.operating_period")
    if not (operating[0] <= worklog_period[0] and worklog_period[1] <= operating[1]):
        return Fail({"ta_recommendation.operating_period": _span(operating)})
    return None


@check("R-SCH-016")
def report_photos(ctx: Context):
    if not ctx.requires_doc("monthly_report"):
        return None
    slots = ctx.require("monthly_report.photo_slots")
    if slots < 1:
        return Fail({}, ctx.sources("monthly_report.photo_slots"))
    return None


# ── L3 : 한도 ─────────────────────────────────────────────────────────────

@check("R-SCH-017")
def unit_price_standard(ctx: Context):
    row = _roster_row(ctx)
    unit = row.get("unit_price")
    if unit is None:
        raise NeedsReview("지급내역의 단가를 읽지 못했습니다")

    subtype = getattr(ctx, "subtype", None)
    table = ctx.settings.get("unit_price_table") or {}
    allowed = table.get(subtype) if subtype else sorted({v for values in table.values() for v in values})
    if not allowed:
        raise NeedsReview("기준단가가 설정되지 않았습니다")
    if unit not in allowed:
        return Fail({"roster.unit_price": unit, "subtype": subtype or "전체", "allowed": allowed})
    return None


@check("R-SCH-018")
def daily_hour_limit(ctx: Context):
    limit = ctx.settings.get("max_hours_per_day")
    failures = []
    for row in _rows(ctx):
        if row.get("hours") and row["hours"] > limit:
            failures.append(Fail({
                "row.date": row["date"].isoformat() if row.get("date") else "?",
                "row.hours": row["hours"],
            }, ctx.sources("worklog.rows")))
    return failures


@check("R-SCH-019")
def monthly_hour_limit(ctx: Context):
    limit = ctx.settings.get("max_hours_per_month")
    total = ctx.require("worklog.total_hours")
    if total > limit:
        return Fail({"worklog.total_hours": total}, ctx.sources("worklog.total_hours"))
    return None


@check("R-SCH-020")
def weekend_work(ctx: Context):
    failures = []
    for row in _rows(ctx):
        date = row.get("date")
        if date and date.weekday() >= 5:
            failures.append(Fail({
                "row.date": date.isoformat(), "weekday": "토요일" if date.weekday() == 5 else "일요일",
            }, ctx.sources("worklog.rows")))
    return failures


def _span(period) -> str:
    start, end = period
    return f"{start.isoformat()} ~ {end.isoformat()}"
