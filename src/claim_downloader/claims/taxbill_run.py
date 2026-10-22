"""세금계산서 청구 이어 넣기 — 청구 종류 '세금계산서'(kinds.TAXBILL) 폴더들을 일반청구 탭에 하나씩 넣고 [저장] 한 뒤 다음 폴더로.

담당자 설명(2026-10-22): 세금계산서 지출은 일반청구에서 비목을 고른 뒤 영수증(증빙구분)에서 세금계산서를 고르면 조회 창이 뜨고,
거기서 수신이메일이나 승인번호로 찾으면 그 세금계산서가 뜬다 — **뜨면 선택**, 본부가 등록하는 것이라 안 뜰 수도 있으니 **조회가 되지 않으면
다음 청구로 넘어간다**. 영수증 아래 청구종류(청구구분)는 일반청구 탭이면 무엇이든 그다음 '증빙' 창을 작성해야 한다 — 그 창(물품구매 · 용역구매 …)은
아직 실측이 없어 앱이 작성하지 않고 노란 띠로 사람에게 넘긴다(CLAUDE.md 14절 끝 '청구구분별 증빙 팝업').

이 모듈은 Qt · Playwright 를 모른다 — 폴더 묶음 · 결과 모양 · 미리 보기 계획 · 첨부 후보만. ERP 를 누르는 차례는 session.fill_taxbill_claims.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .schema import EVIDENCE_TAXBILL, summary_lines

# 사람이 하는 단계의 노란 띠 글 — 앱이 누르지 않는 것: 청구종류 라디오 · 증빙 [신규등록] 창(미실측)
EVIDENCE_ASK = ("ERP 작성 화면에서 청구종류({div})를 고르고 그 아래 증빙 [신규등록] 창을 작성해 저장한 뒤 [계속] 을 누르세요. "
                "(이 창은 아직 실측이 없어 앱이 작성하지 않습니다 — 첫 실측은 '화면 구조 저장' 으로)")
TAXBILL_ASK = "세금계산서 조회 팝업 목록에서 계산서를 고르고 [확인] 을 누른 뒤 [계속] 을 누르세요. 없으면 [멈추기]."
PAYEE_ASK = "입금처 팝업 목록에서 거래처를 고르고 [확인] 을 누른 뒤 [계속] 을 누르세요."
ATTACH_ASK = "첨부를 직접 올린 뒤 [계속] 을 누르세요(앱이 올리지 못했습니다)."
STATUS_TEXT = {"saved": "임시저장 됨", "missing": "세금계산서 없음", "stopped": "멈춤", "failed": "못 넣음", "planned": "넣을 예정",
               "waiting": "차례 기다림"}


@dataclass
class TaxbillItem:
    row: int                  # 화면 목록의 줄 번호 — 결과를 그 줄에 돌려준다
    folder: str
    data: dict
    project_no: str = ""

    @property
    def name(self) -> str:
        return os.path.basename(os.path.normpath(self.folder))

    def attachments(self) -> list[str]:
        """AI 가 고른 첨부 후보(폴더 바로 아래 파일 이름) → 있는 파일의 경로. 이름이 틀린 것은 뺀다."""
        out = []
        for name in self.data.get("attachments") or []:
            path = os.path.join(self.folder, str(name))
            if os.path.isfile(path):
                out.append(path)
        return out

    def problems(self) -> list[str]:
        found = []
        if str(self.data.get("evidence") or "").replace(" ", "") != EVIDENCE_TAXBILL:
            found.append(f"증빙구분이 '{self.data.get('evidence') or '—'}' — 세금계산서 종류는 세금계산서여야 합니다")
        if not (self.data.get("approvalNo") or self.data.get("payeeBizNo") or self.data.get("payeeName") or self.data.get("receiverEmail")):
            found.append("세금계산서를 찾을 조건(승인번호 · 사업자번호 · 거래처명 · 수신메일)이 없음")
        if not self.data.get("summary"):
            found.append("적요 없음")
        if not self.data.get("amount"):
            found.append("청구액 없음")
        if not self.attachments():
            found.append("첨부할 파일이 없음 — ERP 에서 직접 첨부")
        return found


@dataclass
class ItemResult:
    row: int
    name: str
    status: str               # saved · missing · stopped · failed · planned
    note: str = ""
    req_cnt: str = ""         # [저장] 뒤 결의번호
    review: list[str] = field(default_factory=list)    # [신청] 전에 ERP 에서 확인할 것
    detail: list[str] = field(default_factory=list)    # 진행 기록(채운 칸 · 팝업 결과)

    @property
    def label(self) -> str:
        return STATUS_TEXT.get(self.status, self.status)


@dataclass
class TaxbillRunReport:
    dry_run: bool
    results: list[ItemResult] = field(default_factory=list)
    blocked: str = ""         # 시작도 못 한 까닭(브라우저 · 작성 화면)
    stopped: bool = False     # 사람이 [멈추기] 했거나 앱이 이어 갈 수 없어 남은 폴더를 두고 끝남

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def saved(self) -> int:
        return self.count("saved")

    @property
    def missing(self) -> int:
        return self.count("missing")

    def review_items(self) -> list[str]:
        return [f"{r.name} — {item}" for r in self.results for item in r.review]

    def lines(self) -> list[str]:
        if self.dry_run:
            out = ["미리 보기 (ERP 에 넣지 않음)"]
        else:
            out = [f"세금계산서 청구: 임시저장 {self.saved}건" + (f" · 세금계산서 없음(건너뜀) {self.missing}건" if self.missing else "")
                   + (f" · 못 넣음 {self.count('failed')}건" if self.count("failed") else "") + (" — 멈춤" if self.stopped else "")]
        if self.blocked:
            out.append("✗ " + self.blocked)
        for r in self.results:
            out.append(f"· {r.name}: {r.label}" + (f" (결의번호 {r.req_cnt})" if r.req_cnt else "") + (f" — {r.note}" if r.note else ""))
            out.extend("    " + line for line in r.detail)
        out.extend("신청 전 확인: " + item for item in self.review_items())
        return out


def plan(items: list[TaxbillItem]) -> TaxbillRunReport:
    """미리 보기 — ERP 없이 폴더마다 무엇을 넣을지."""
    report = TaxbillRunReport(dry_run=True)
    for item in items:
        detail = summary_lines(item.data) + [f"첨부 {len(item.attachments())}개: " + (" · ".join(os.path.basename(f) for f in item.attachments()) or "—")]
        report.results.append(ItemResult(item.row, item.name, "planned", " · ".join(item.problems()), detail=detail))
    return report


def table_rows(report: TaxbillRunReport, items: list[TaxbillItem]) -> list[tuple[str, str, list[str], str]]:
    """결과 창 표의 줄 — (상태 글, 색, [폴더, 적요, 청구액, 승인번호, 첨부 수], 자세히). report_dialog.ReportRow 로 만든다."""
    tone = {"saved": "success", "planned": "info", "missing": "warning", "stopped": "warning", "failed": "danger", "waiting": "neutral"}
    by_row = {item.row: item for item in items}
    out = []
    for r in report.results:
        item = by_row.get(r.row)
        data = item.data if item else {}
        amount = data.get("amount")
        cells = [r.name, str(data.get("summary") or ""), f"{amount:,}" if isinstance(amount, int) else "",
                 str(data.get("approvalNo") or data.get("payeeBizNo") or ""), str(len(item.attachments())) if item else ""]
        detail = "\n".join(([r.note] if r.note else []) + r.detail + ["신청 전 확인: " + x for x in r.review])
        out.append((r.label, tone.get(r.status, "neutral"), cells, detail))
    return out
