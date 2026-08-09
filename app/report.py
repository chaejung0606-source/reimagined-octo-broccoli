"""결과 출력 — docs/04-architecture.md §1 의 ⑥⑦.

앱의 실질적 산출물은 **수정 요청서**다. 담당자가 "이거 이거 고쳐서 다시 주세요" 를
손으로 쓰는 시간을 없애는 것이 목적이므로, 조치 문구는 그대로 복사해 보낼 수 있는
완결된 문장이어야 한다.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from .models import (
    DISPLAY,
    STATUS_ORDER,
    Case,
    Document,
    Finding,
    ReviewResult,
    Status,
)

_LAYER_NAMES = {
    "L0": "서류 완비성",
    "L1": "문서 내부 정합성",
    "L2": "문서 간 교차 정합성",
    "L3": "규정·한도",
}


# --------------------------------------------------------------- 텍스트

def render_text(result: ReviewResult, show_pass: bool = False,
                show_documents: bool = True) -> str:
    lines: list[str] = []
    case = result.case

    lines.append("=" * 72)
    title = f"지출 서류 검토 결과 — {case.expense_type}"
    if case.subtype:
        title += f" ({case.subtype})"
    lines.append(title)
    if case.person_label:
        lines.append(f"대상: {case.person_label}")
    if case.root:
        lines.append(f"경로: {case.root}")
    lines.append("=" * 72)
    lines.append("")

    lines.append(_summary_line(result))
    lines.append("")

    if show_documents:
        lines.extend(_document_block(case))
        lines.append("")

    shown = [f for f in result.sorted_findings
             if show_pass or f.status is not Status.PASS]
    if not shown:
        lines.append("검출된 항목이 없습니다.")
        return "\n".join(lines)

    current: Status | None = None
    for finding in shown:
        if finding.status is not current:
            current = finding.status
            lines.append("")
            lines.append(f"── {DISPLAY[current]} " + "─" * 50)
            lines.append("")
        lines.extend(_finding_block(finding))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _summary_line(result: ReviewResult) -> str:
    counts = result.summary()
    parts = [f"{DISPLAY[status]} {counts[status.value]}건"
             for status in STATUS_ORDER
             if counts[status.value] or status in (Status.ERROR, Status.WARN, Status.REVIEW)]
    verdict = "수정 후 재제출이 필요합니다." if result.count(Status.ERROR) else \
        ("확인이 필요한 항목이 있습니다." if result.count(Status.WARN) or result.count(Status.REVIEW)
         else "자동 검토에서 문제를 찾지 못했습니다.")
    return "  ".join(parts) + f"\n{verdict}"


def _document_block(case: Case) -> list[str]:
    lines = ["[제출 서류]"]
    if not case.documents:
        lines.append("  (없음)")
        return lines
    for document in case.documents:
        mark = "  " if document.readable else "※"
        confidence = f"{document.kind_confidence:.2f}"
        note = "" if document.readable else "  ← 텍스트 판독 불가"
        pages = f"{document.page_count}p" if document.page_count else "-"
        lines.append(f" {mark} {document.file.name}")
        lines.append(f"      → {document.label or document.kind} "
                     f"[{document.kind}] 확신도 {confidence} · {pages}{note}")
        if document.kind_reason:
            lines.append(f"        근거: {document.kind_reason}")
    return lines


def _finding_block(finding: Finding) -> list[str]:
    header = f"[{finding.rule_id}] {DISPLAY[finding.status]} {finding.title}"
    if finding.scope_label:
        header += f"  ({finding.scope_label})"
    lines = [header]
    layer = _LAYER_NAMES.get(finding.layer, finding.layer)
    lines.append(f"  층위    {finding.layer} {layer}")

    if finding.message:
        lines.append(f"  내용    {finding.message}")
    if finding.reason:
        lines.append(f"  사유    {finding.reason}")
    for anchor in finding.anchors[:3]:
        lines.append(f"  근거    {anchor}")
    for item in finding.evidence[:6]:
        lines.append(f"  검출값  {item}")
    if finding.fix:
        lines.append(f"  조치    {finding.fix}")
    return lines


# -------------------------------------------------------------- 마크다운

def render_markdown(result: ReviewResult) -> str:
    """제출자에게 그대로 보낼 수 있는 수정 요청서."""
    case = result.case
    lines: list[str] = []

    heading = f"# 지출 서류 수정 요청 — {case.expense_type}"
    if case.subtype:
        heading += f" ({case.subtype})"
    lines.append(heading)
    lines.append("")
    if case.person_label:
        lines.append(f"- 대상: {case.person_label}")
    lines.append(f"- 검토일: {date.today():%Y-%m-%d}")
    counts = result.summary()
    lines.append(f"- 결과: 🔴 {counts['ERROR']}건 · 🟡 {counts['WARN']}건 · 🔵 {counts['REVIEW']}건")
    lines.append("")

    for status in (Status.ERROR, Status.WARN, Status.REVIEW):
        findings = result.of(status)
        if not findings:
            continue
        lines.append(f"## {DISPLAY[status]}")
        lines.append("")
        for index, finding in enumerate(findings, start=1):
            lines.append(f"### {index}. {finding.title}"
                         + (f" — {finding.scope_label}" if finding.scope_label else ""))
            lines.append("")
            if finding.message:
                lines.append(finding.message)
                lines.append("")
            if finding.reason:
                lines.append(f"> {finding.reason}")
                lines.append("")
            if finding.evidence:
                lines.append("| 검출값 |")
                lines.append("|---|")
                for item in finding.evidence[:8]:
                    lines.append(f"| {item.replace('|', '/')} |")
                lines.append("")
            if finding.fix:
                lines.append(f"**조치:** {finding.fix}")
                lines.append("")
            if finding.anchors:
                anchors = " · ".join(str(a) for a in finding.anchors[:3])
                lines.append(f"<sub>근거: {anchors} · 규칙 {finding.rule_id}</sub>")
                lines.append("")

    unchecked = result.of(Status.UNSUPPORTED, Status.SKIPPED)
    if unchecked:
        lines.append("## ⚪ 이번 검토에서 확인하지 못한 항목")
        lines.append("")
        lines.append("아래 항목은 자동 검토 대상이 아니었습니다. 담당자가 직접 확인해 주세요.")
        lines.append("")
        for finding in unchecked:
            lines.append(f"- **{finding.title}** ({finding.rule_id}) — {finding.reason}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ------------------------------------------------------------------ JSON

def _encode(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def to_dict(result: ReviewResult) -> dict[str, Any]:
    case = result.case
    return {
        "expense_type": case.expense_type,
        "subtype": case.subtype,
        "person": case.person_label,
        "root": str(case.root) if case.root else None,
        "summary": result.summary(),
        "documents": [
            {
                "file": document.file.name,
                "kind": document.kind,
                "label": document.label,
                "confidence": document.kind_confidence,
                "pages": document.page_count,
                "readable": document.readable,
                "reason": document.kind_reason,
                "read_error": document.read_error,
            }
            for document in case.documents
        ],
        "findings": [
            {
                "rule_id": finding.rule_id,
                "layer": finding.layer,
                "title": finding.title,
                "status": finding.status.value,
                "scope": finding.scope_label,
                "message": finding.message,
                "reason": finding.reason,
                "evidence": finding.evidence,
                "fix": finding.fix,
                "anchors": [str(a) for a in finding.anchors],
            }
            for finding in result.sorted_findings
        ],
    }


def render_json(result: ReviewResult) -> str:
    return json.dumps(to_dict(result), ensure_ascii=False, indent=2, default=_encode)


# --------------------------------------------------------------- 분류 결과

def render_classification(documents: list[Document]) -> str:
    lines = ["파일 분류 결과", "=" * 60]
    for document in documents:
        lines.append(f"{document.file.name}")
        pages = f"{document.page_count}p" if document.page_count else "판독 불가"
        lines.append(f"  → [{document.kind}] {document.label} "
                     f"(확신도 {document.kind_confidence:.2f}, {pages})")
        if document.kind_reason:
            lines.append(f"     근거: {document.kind_reason}")
        if document.read_error:
            lines.append(f"     주의: {document.read_error}")
    return "\n".join(lines) + "\n"
