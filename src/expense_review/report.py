"""검토 결과 출력.

이 앱의 실질적 산출물은 '수정 요청서' 다. 담당자가 그대로 복사해 제출자에게
보낼 수 있어야 하므로, 조치 문구는 완결된 문장으로 낸다.

개인정보는 싣지 않는다. 주민등록번호·계좌번호는 마스킹한다(docs/04 §6).
"""
from __future__ import annotations

import re

from .models import ReviewResult, Severity

_RRN_RE = re.compile(r"\b(\d{6})-?(\d{7})\b")
# 날짜(2026-07-03)가 계좌 모양과 겹친다. 숫자 9자리 이상만 계좌로 본다.
_ACCOUNT_RE = re.compile(r"(?<!\d)(\d{2,6}-\d{2,6}-\d{2,7}|\d{11,16})(?!\d)")


def mask(text: str) -> str:
    """리포트에 주민번호·계좌번호 원문이 남지 않게 한다."""
    text = _RRN_RE.sub(lambda m: f"{m.group(1)}-{m.group(2)[0]}******", text)
    def mask_account(match: re.Match) -> str:
        raw = match.group(1)
        if len(re.sub(r"\D", "", raw)) < 9:
            return raw
        return raw[:4] + "*" * (len(raw) - 4)

    return _ACCOUNT_RE.sub(mask_account, text)


def summarize(result: ReviewResult) -> str:
    counts = result.counts
    return (
        f"🔴 수정 필요 {counts[Severity.ERROR]}건 · "
        f"🟡 확인 요망 {counts[Severity.WARN]}건 · "
        f"🔵 판독 불가 {counts[Severity.REVIEW]}건"
    )


def to_text(result: ReviewResult, show_skipped: bool = False) -> str:
    lines: list[str] = []
    owner = f" — {result.owner}" if result.owner else ""
    lines.append(f"[{result.expense_type}{owner}] {summarize(result)}")
    lines.append("")

    if result.is_clean:
        lines.append("🟢 자동 검토 항목에서 문제가 발견되지 않았습니다.")
    else:
        for finding in result.sorted_findings:
            lines.append(f"[{finding.rule_id}] {finding.severity.marker} {finding.title}")
            lines.append(f"    검출  {mask(finding.message)}")
            if finding.fix:
                lines.append(f"    조치  {mask(finding.fix)}")
            lines.append(f"    근거  {finding.evidence}")
            lines.append("")

    if show_skipped and result.skipped_rules:
        lines.append(f"자동 검사하지 않은 규칙 {len(result.skipped_rules)}건:")
        lines.append("  " + ", ".join(result.skipped_rules))

    return "\n".join(lines)


def to_markdown(results: list[ReviewResult]) -> str:
    """제출자에게 그대로 보낼 수 있는 수정 요청서."""
    lines = ["# 서류 검토 결과", ""]

    total = {Severity.ERROR: 0, Severity.WARN: 0, Severity.REVIEW: 0}
    for result in results:
        for severity, count in result.counts.items():
            total[severity] += count

    lines.append(
        f"검토 대상 {len(results)}건 · "
        f"🔴 수정 필요 {total[Severity.ERROR]} · "
        f"🟡 확인 요망 {total[Severity.WARN]} · "
        f"🔵 판독 불가 {total[Severity.REVIEW]}"
    )
    lines.append("")

    for result in results:
        heading = result.owner or result.expense_type
        lines.append(f"## {heading}")
        lines.append("")
        if result.is_clean:
            lines.append("자동 검토 항목에서 문제가 발견되지 않았습니다.")
            lines.append("")
            continue

        lines.append("| | 항목 | 검출 내용 | 조치 | 근거 |")
        lines.append("|---|---|---|---|---|")
        for finding in result.sorted_findings:
            lines.append(
                f"| {finding.severity.marker} | {finding.title} | "
                f"{_cell(mask(finding.message))} | {_cell(mask(finding.fix))} | "
                f"{_cell(finding.evidence)} |"
            )
        lines.append("")

    return "\n".join(lines)


def _cell(text: str) -> str:
    return (text or "—").replace("|", "\\|").replace("\n", " ")
