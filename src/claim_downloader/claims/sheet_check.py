"""신청 전 대조 — 작성 화면의 '청구내역' 표를 다시 읽어 명단과 맞춰 본다. 읽기만 한다(누르는 것 없음).

담당자가 [신청] 을 누르기 전에 사람마다 한 줄씩 제대로 들어갔는지 눈으로 다 세던 것을 앱이 대신 센다.
잡는 것: 두 번 들어간 사람(멈췄다 다시 넣다가) · 빠진 사람 · 명단과 다른 청구액 · 명단에 없는 줄(다른 폴더 · 옛 판으로 넣은 줄 —
2026-10-14 결의번호 324 처럼) · 합계 줄의 청구액 · 공제합계.

표의 모양은 실측 ⑤(CLAUDE.md 14절)만큼만 안다 — 줄마다 선택 라디오(CUR_REQ)가 있고 그 줄 글자에 적요와 금액이 있으며, '합계' 줄에
청구액 · 실지급액 · 공제합계가 차례로 있다. 열 위치는 모르므로 줄 글자 전체에서 적요(공백 무시)와 금액(숫자 묶음)을 찾는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .form import PROBE_JS

_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def numbers_in(text: str) -> set[int]:
    """줄 글자 속의 숫자 묶음(콤마 든 것 포함)."""
    return {int(n.replace(",", "")) for n in _NUMBER.findall(str(text or ""))}


@dataclass
class SheetCheck:
    read: bool = False                                   # 표를 읽었는지(작성 화면이 없으면 False)
    rows: int = 0
    lines: list[str] = field(default_factory=list)       # 결과 창 · 진행 기록
    problems: list[str] = field(default_factory=list)    # 신청 전 확인할 것

    @property
    def ok(self) -> bool:
        return self.read and not self.problems

    def heading(self) -> str:
        if not self.read:
            return "청구내역 표를 읽지 못했습니다"
        if self.problems:
            return f"청구내역 {self.rows}줄 — 확인할 것 {len(self.problems)}건"
        return f"청구내역 {self.rows}줄 — 명단과 맞습니다"


def compare(job, sheet_rows: list[str], totals: list[int], expect_no_deduction: bool = True,
            partial: bool = False) -> SheetCheck:
    """명단(job.people 전부 — 이번에 체크한 사람만이 아니다)과 청구내역 줄을 맞춘다. partial 이면(넣다가 멈춤) 빠진 사람은 확인할 것이 아니다."""
    check = SheetCheck(read=True, rows=len(sheet_rows))
    wanted = [(i, _squash(job.row_summary(i))) for i in range(len(job.people))]
    hits: dict[int, list[int]] = {}
    strangers: list[int] = []
    for r, text in enumerate(sheet_rows):
        flat = _squash(text)
        # '…_김민' 과 '…_김민수' 처럼 한 적요가 다른 적요를 품을 수 있다 — 가장 긴 것 하나에만 붙인다
        matched = [(len(s), i) for i, s in wanted if s and s in flat]
        if not matched:
            strangers.append(r)
            continue
        hits.setdefault(max(matched)[1], []).append(r)

    if strangers and not hits:
        # 한 줄도 맞추지 못했으면 줄마다 '명단에 없음' 을 늘어놓지 않는다 — 다른 청구서이거나 표 글자가 예상(실측 ⑤)과 다르다
        check.problems.append(f"청구내역 {len(sheet_rows)}줄의 적요를 이 명단과 하나도 맞추지 못했습니다 — 다른 청구서가 떠 있거나 "
                              "대표적요를 바꾸셨거나 표 글자가 예상과 다릅니다. ERP 에서 직접 확인하세요")
        return check
    matched_sum = 0
    for i, p in enumerate(job.people):
        rows = hits.get(i, [])
        label = f"{i + 1}. {p.name}"
        if not rows:
            check.lines.append(f"· {label} — 청구내역에 없음")
            continue
        if len(rows) > 1:
            check.problems.append(f"{label} — 청구내역에 {len(rows)}번 들어가 있습니다(줄 {', '.join(str(r + 1) for r in rows)}). "
                                  "하나만 남기고 ERP 에서 [삭제] 하세요")
        bad = [r for r in rows if p.amount and p.amount not in numbers_in(sheet_rows[r])]
        if bad:
            check.problems.append(f"{label} — 청구내역 줄 {bad[0] + 1} 의 금액이 명단({p.amount:,}원)과 다릅니다")
        matched_sum += (p.amount or 0) * len(rows)
        mark = "!" if len(rows) > 1 or bad else "✓"       # 두 번 · 금액 다름은 표에서도 '확인' 으로
        check.lines.append(f"{mark} {label} — 줄 {', '.join(str(r + 1) for r in rows)}" + (f" · {p.amount:,}원" if p.amount else ""))
    missing = [i for i in range(len(job.people)) if i not in hits]
    if missing and len(missing) < len(job.people):
        # 일부러 빼신 사람일 수 있어 막지 않는다 — 신청 전에 한 번 보시라고만. 넣다가 멈췄으면 빠진 것이 당연하다
        (check.lines if partial else check.problems).append("명단에 있는데 청구내역에 없는 사람 %d명: %s" % (
            len(missing), ", ".join(job.people[i].name for i in missing[:8]) + (" …" if len(missing) > 8 else "")))
    for r in strangers:
        check.problems.append(f"명단에 없는 줄 {r + 1}: {sheet_rows[r][:70]} — 다른 폴더나 옛 판으로 넣은 줄이면 ERP 에서 [삭제]")
    if len(totals) >= 1 and not strangers and hits:
        if totals[0] != matched_sum:
            check.problems.append(f"합계 줄 청구액 {totals[0]:,}원 ≠ 명단으로 맞춘 줄의 합 {matched_sum:,}원")
        else:
            check.lines.append(f"✓ 합계 줄 청구액 {totals[0]:,}원 = 명단으로 맞춘 줄의 합")
    if expect_no_deduction and len(totals) >= 3 and totals[2]:
        check.problems.append(f"합계 줄 공제합계가 {totals[2]:,}원입니다 — 소득구분이 '장학금' 이 아닌 줄이 있습니다(장학금 · 혁신인재지원금은 0)")
    return check


def read_and_compare(frame, job, wait=None, expect_no_deduction: bool = True, partial: bool = False) -> SheetCheck:
    """작성 화면에서 청구내역 표를 읽어 맞춘다. 화면이 다시 뜨는 중이면(저장 직후) 잠깐 기다린다."""
    from .payee import wait_until
    from .scholarship import SHEET_ROWS_JS, SUMMARY_JS
    if wait is not None and not wait_until(lambda: frame.evaluate(PROBE_JS) is True, wait, tries=20):
        return SheetCheck()
    try:
        rows = [str(t) for t in (frame.evaluate(SHEET_ROWS_JS) or [])]
        totals = [int(n) for n in (frame.evaluate(SUMMARY_JS) or {}).get("totals", [])]
    except Exception:  # noqa: BLE001 — 읽지 못하면 대조하지 않는다(확인할 것이 아니라 '못 읽음')
        return SheetCheck()
    if not rows:
        check = SheetCheck(read=True)
        check.lines.append("청구내역 표에 저장된 줄이 없습니다")
        return check
    return compare(job, rows, totals, expect_no_deduction, partial)
