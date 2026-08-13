"""혁신인재지원금 규칙 판정 (R-INN-*).

핵심 축은 소학회명·회장·지도교수의 3자 일치, 그리고 정액 지급액 대사다.
"""
from __future__ import annotations

import re

from .. import normalize as nz
from ..engine import Context, Fail, NeedsReview, check


def _roster_row(ctx: Context) -> dict:
    roster = ctx.doc("payment_roster")
    if roster is None:
        raise NeedsReview("지급내역을 찾지 못했습니다")
    rows = roster.fields.get("rows")
    if rows is None or not rows.is_present:
        raise NeedsReview("지급내역 표를 읽지 못했습니다")

    account = nz.digits_only(ctx.get("innovation_application.account_no") or "")
    club = nz.strip_spaces(ctx.get("innovation_application.club_name") or "")

    for row in rows.value:
        if account and row.get("account_no") == account:
            return row
    for row in rows.value:
        if club and nz.strip_spaces(row.get("club_name") or "") == club:
            return row
    raise NeedsReview("지급내역에서 해당 소학회의 행을 찾지 못했습니다")


def _worklog_rows(ctx: Context) -> list[dict]:
    rows = ctx.value("worklog.rows")
    if rows is None or not rows.is_present:
        raise NeedsReview("근무상황부의 근로일자 표를 읽지 못했습니다")
    return rows.value


# ── 금액 ──────────────────────────────────────────────────────────────────

@check("R-INN-001")
def amount_matches_roster(ctx: Context):
    amount = ctx.require("innovation_application.amount")
    row = _roster_row(ctx)
    if row.get("amount") is None:
        raise NeedsReview("지급내역의 금액을 읽지 못했습니다")
    if amount != row["amount"]:
        return Fail({"innovation_application.amount": amount, "roster.amount": row["amount"]})
    return None


@check("R-INN-002")
def hangul_amount(ctx: Context):
    amount, written = ctx.require(
        "innovation_application.amount", "innovation_application.amount_hangul"
    )
    computed = nz.hangul_amount(amount)
    if nz.strip_spaces(written) != computed:
        return Fail({
            "innovation_application.amount": amount,
            "innovation_application.amount_hangul": written,
            "computed": computed,
        }, ctx.sources("innovation_application.amount_hangul"))
    return None


@check("R-INN-003")
def hourly_rate(ctx: Context):
    hours = ctx.require("worklog.total_hours")
    row = _roster_row(ctx)
    amount = row.get("amount")
    if amount is None or not hours:
        raise NeedsReview("지급액 또는 근로시간을 읽지 못했습니다")
    computed = round(amount / hours)
    if computed != ctx.settings.get("hourly_rate"):
        return Fail({"roster.amount": amount, "worklog.total_hours": hours, "computed": computed})
    return None


@check("R-INN-004")
def standard_amount(ctx: Context):
    row = _roster_row(ctx)
    if row.get("amount") != ctx.settings.get("standard_amount"):
        return Fail({"roster.amount": row.get("amount")})
    return None


# ── 소학회 3자 일치 ───────────────────────────────────────────────────────

@check("R-INN-005")
def club_name_matches(ctx: Context):
    application = ctx.require("innovation_application.club_name")
    report = ctx.require("club_report.club_name")
    row = _roster_row(ctx)
    values = {
        nz.strip_spaces(application): "신청서",
        nz.strip_spaces(report): "활동보고서",
    }
    if row.get("club_name"):
        values.setdefault(nz.strip_spaces(row["club_name"]), "지급내역")
    if len(values) > 1:
        return Fail({
            "values": [f"{name} ({source})" for name, source in values.items()],
            "expected": nz.strip_spaces(application),
        })
    return None


@check("R-INN-006")
def applicant_is_president(ctx: Context):
    applicant = ctx.require("innovation_application.applicant")
    president = ctx.require("club_report.president")
    row = _roster_row(ctx)
    names = {nz.strip_spaces(applicant), nz.strip_spaces(president)}
    if row.get("name"):
        names.add(nz.strip_spaces(row["name"]))
    if len(names) > 1:
        return Fail({
            "innovation_application.applicant": applicant,
            "club_report.president": president,
            "roster.name": row.get("name"),
        })
    return None


@check("R-INN-007")
def advisor_matches(ctx: Context):
    application = ctx.require("innovation_application.advisor")
    report = ctx.require("club_report.advisor")
    if nz.strip_spaces(application) != nz.strip_spaces(report):
        return Fail({"values": [f"{application} (신청서)", f"{report} (활동보고서)"]})
    return None


@check("R-INN-008")
def approver_is_advisor(ctx: Context):
    approver = ctx.require("worklog.approver")
    advisor = ctx.require("innovation_application.advisor")
    if nz.strip_spaces(approver) != nz.strip_spaces(advisor):
        return Fail({"worklog.approver": approver, "club.advisor": advisor})
    return None


@check("R-INN-009")
def activity_field_matches(ctx: Context):
    declared = ctx.require("innovation_application.activity_field")
    checked = ctx.require("club_report.field_checked")
    if nz.strip_spaces(declared) != nz.strip_spaces(checked):
        return Fail({
            "innovation_application.field": declared,
            "club_report.field_checked": checked,
        }, ctx.sources("club_report.field_checked"))
    return None


@check("R-INN-010")
def topic_matches(ctx: Context):
    application = ctx.require("innovation_application.topic")
    report = ctx.require("club_report.topic")
    if nz.similarity(application, report) < 0.8:
        return Fail({})
    return None


# ── 활동일 ↔ 근로일 ──────────────────────────────────────────────────────

@check("R-INN-011")
def rows_within_period(ctx: Context):
    period = ctx.require("worklog.period")
    start, end = period
    failures = []
    for row in _worklog_rows(ctx):
        date = row.get("date")
        if date and not (start <= date <= end):
            failures.append(Fail({
                "row.date": date.isoformat(),
                "worklog.period": f"{start.isoformat()} ~ {end.isoformat()}",
            }, ctx.sources("worklog.rows")))
    return failures


@check("R-INN-012")
def activity_dates_covered(ctx: Context):
    activity_dates = ctx.require("club_report.activity_dates")
    worked = {row["date"] for row in _worklog_rows(ctx) if row.get("date")}
    missing = sorted(set(activity_dates) - worked)
    if missing:
        return Fail(
            {"missing": [d.strftime("%m/%d") for d in missing]},
            ctx.sources("club_report.activity_dates"),
        )
    return None


@check("R-INN-013")
def total_hours(ctx: Context):
    stated = ctx.require("worklog.total_hours")
    computed = round(sum(row.get("hours") or 0 for row in _worklog_rows(ctx)), 2)
    if computed != stated:
        return Fail({"computed": computed, "worklog.total_hours": stated},
                    ctx.sources("worklog.total_hours"))
    return None


# ── 팀원 명단 ─────────────────────────────────────────────────────────────

@check("R-INN-014")
def member_student_ids(ctx: Context):
    members = ctx.require("club_report.members")
    pattern = ctx.settings.get("student_id_pattern", r"^\d{9}$")
    failures = []
    for member in members:
        student_id = member.get("student_id") or ""
        if not re.match(pattern, student_id):
            failures.append(Fail({
                "member.name": member.get("name"), "member.student_id": student_id,
            }, ctx.sources("club_report.members")))
    return failures


@check("R-INN-015")
def member_list_sanity(ctx: Context):
    members = ctx.require("club_report.members")
    issues = []

    names = [m.get("name") for m in members if m.get("name")]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        issues.append(f"중복 인원: {', '.join(sorted(duplicates))}")

    for member in members:
        phone = (member.get("phone") or "").replace(" ", "")
        if phone and not re.fullmatch(r"01[016789]-?\d{3,4}-?\d{4}", phone):
            issues.append(f"{member.get('name')} 연락처 형식 오류({phone})")

    if issues:
        return Fail({"issues": issues}, ctx.sources("club_report.members"))
    return None


@check("R-INN-016")
def minimum_members(ctx: Context):
    members = ctx.require("club_report.members")
    minimum = ctx.settings.get("min_members")
    if len(members) < minimum:
        return Fail({"computed": len(members)}, ctx.sources("club_report.members"))
    return None


# ── 보고서 형식 ───────────────────────────────────────────────────────────

@check("R-INN-017")
def report_page_count(ctx: Context):
    pages = ctx.require("club_report.page_count")
    limit = ctx.settings.get("report_max_pages", 1)
    if pages > limit:
        return Fail({"club_report.page_count": pages}, ctx.sources("club_report.page_count"))
    return None


@check("R-INN-020")
def text_anomalies(ctx: Context):
    found = ctx.value("club_report.text_anomalies")
    if found is not None and found.is_present and found.value:
        return Fail({"found": found.value}, ctx.sources("club_report.text_anomalies"))
    return None
