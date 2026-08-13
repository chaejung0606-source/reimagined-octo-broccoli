"""페이지 사이에서 공유하는 상태.

검토 결과 하나를 여러 화면(대시보드·파일별 보완사항)이 함께 본다.
페이지끼리 직접 참조하지 않고 이 객체를 통해서만 주고받는다.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..models import ReviewResult, Severity


class AppState(QObject):
    results_changed = Signal(list)
    busy_changed = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.results: list[ReviewResult] = []

    def set_results(self, results: list[ReviewResult]) -> None:
        self.results = results
        self.results_changed.emit(results)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.busy_changed.emit(busy, message)

    # ── 집계 ─────────────────────────────────────────────────────────────
    def totals(self) -> dict[Severity, int]:
        totals = {Severity.ERROR: 0, Severity.WARN: 0, Severity.REVIEW: 0}
        for result in self.results:
            for severity, count in result.counts.items():
                totals[severity] += count
        return totals

    def document_count(self) -> int:
        return sum(len(result.documents) for result in self.results)

    def clean_document_count(self) -> int:
        return sum(
            1 for result in self.results
            for summary in result.document_summary() if not summary.findings
        )
