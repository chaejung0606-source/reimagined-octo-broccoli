"""파일별 보완사항 페이지.

'어떤 파일을 무엇 때문에 고쳐야 하는지' 를 한눈에 본다. 규칙 단위로 나열하면
제출자에게 전달할 때 파일별로 다시 묶어야 하므로, 처음부터 파일 단위로 보여 준다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...models import DocumentSummary, ReviewResult, Severity
from ...report import mask
from ..state import AppState
from ..theme import COLORS, SEVERITY_STYLE
from ..widgets import Card, EmptyState, Pill, muted_label

CARD_COLUMNS = 3


class FilesPage(QWidget):
    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.state = state
        self._summaries: list[DocumentSummary] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(22)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("파일별 보완사항")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addWidget(muted_label("파일 카드를 누르면 그 파일에서 나온 지적만 모아 보여 줍니다."))
        layout.addLayout(header)

        picker = QHBoxLayout()
        picker.setSpacing(14)
        picker.addWidget(_label("제출자"))
        self.owner_combo = QComboBox()
        self.owner_combo.setMinimumWidth(220)
        self.owner_combo.currentIndexChanged.connect(self._on_owner_changed)
        picker.addWidget(self.owner_combo)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("cardHint")
        picker.addWidget(self.summary_label)
        picker.addStretch(1)
        layout.addLayout(picker)

        splitter = QSplitter(Qt.Horizontal)

        cards_card = Card("파일", "지적이 심한 순")
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_holder = QWidget()
        self.grid_holder.setObjectName("page")
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(18)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.grid_holder)
        cards_card.add(self.scroll, 1)
        splitter.addWidget(cards_card)

        self.detail_card = Card("보완사항", "파일을 선택하세요")
        self.detail_stack = QStackedWidget()
        self.detail_empty = EmptyState("파일 카드를 누르면\n그 파일에서 나온 지적만 모아 볼 수 있어요.")
        self.detail = QTextBrowser()
        self.detail.setFrameShape(QFrame.NoFrame)
        self.detail_stack.addWidget(self.detail_empty)
        self.detail_stack.addWidget(self.detail)
        self.detail_card.add(self.detail_stack, 1)
        splitter.addWidget(self.detail_card)
        splitter.setSizes([660, 440])

        layout.addWidget(splitter, 1)
        state.results_changed.connect(self._on_results)

    # ── 갱신 ─────────────────────────────────────────────────────────────
    def _on_results(self, results: list[ReviewResult]) -> None:
        self.owner_combo.blockSignals(True)
        self.owner_combo.clear()
        for index, result in enumerate(results):
            counts = result.counts
            label = (f"{result.owner or result.expense_type}  "
                     f"🔴 {counts[Severity.ERROR]} · 🟡 {counts[Severity.WARN]} · 🔵 {counts[Severity.REVIEW]}")
            self.owner_combo.addItem(label, index)
        self.owner_combo.blockSignals(False)
        if results:
            self.owner_combo.setCurrentIndex(0)
            self._on_owner_changed(0)
        else:
            self._clear_grid()

    def _on_owner_changed(self, index: int) -> None:
        if index < 0 or index >= len(self.state.results):
            return
        result = self.state.results[index]
        self._summaries = result.document_summary()
        clean = sum(1 for s in self._summaries if not s.findings)
        self.summary_label.setText(
            f"파일 {len(self._summaries)}개 중 {clean}개는 지적 없음"
        )
        self._rebuild_grid()
        self.detail.clear()
        self.detail_stack.setCurrentWidget(self.detail_empty)

    def _clear_grid(self) -> None:
        """카드를 걷어낸다.

        deleteLater 만 걸면 실제 삭제가 다음 이벤트 루프로 밀린다. 카드가
        반투명이라 그동안 새 카드 밑으로 옛 카드가 비쳐 글자가 겹쳐 보인다.
        setParent(None) 로 화면에서 먼저 떼어 내야 한다.
        """
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild_grid(self) -> None:
        from ..widgets import FileCard

        self._clear_grid()
        for position, summary in enumerate(self._summaries):
            card = FileCard(summary)
            card.clicked.connect(self._show_summary)
            self.grid.addWidget(card, position // CARD_COLUMNS, position % CARD_COLUMNS)
        for column in range(CARD_COLUMNS):
            self.grid.setColumnStretch(column, 1)
        self.grid_holder.update()

    # ── 상세 ─────────────────────────────────────────────────────────────
    def _show_summary(self, summary: DocumentSummary) -> None:
        self.detail_stack.setCurrentWidget(self.detail)
        counts = summary.counts
        parts = [
            f"<div style='font-size:13px;font-weight:700;'>{summary.name}</div>",
            f"<p style='color:{COLORS['text_muted']};font-size:11px;'>{summary.doc_label}</p>",
        ]

        if not summary.findings:
            parts.append(
                f"<p style='color:{COLORS['pass']};font-weight:700;'>"
                "이 파일에서는 지적 사항이 없습니다.</p>"
            )
        else:
            chips = " ".join(
                f"<span style='color:{SEVERITY_STYLE[s.name]['color']};font-weight:700;'>"
                f"{SEVERITY_STYLE[s.name]['label']} {counts[s]}</span>"
                for s in (Severity.ERROR, Severity.WARN, Severity.REVIEW) if counts[s]
            )
            parts.append(f"<p>{chips}</p><hr style='border:none;border-top:1px solid {COLORS['border']};'>")

            for finding in summary.findings:
                color = SEVERITY_STYLE[finding.severity.name]["color"]
                parts.append(
                    f"<div style='margin:14px 0 0 0;'>"
                    f"<span style='color:{color};font-weight:700;'>● {finding.title}</span>"
                    f"<span style='color:{COLORS['text_faint']};font-size:11px;'>  {finding.rule_id}</span>"
                    f"<div style='margin-top:4px;'>{mask(finding.message)}</div>"
                    + (f"<div style='margin-top:4px;color:{COLORS['indigo']};'>"
                       f"→ {mask(finding.fix)}</div>" if finding.fix else "")
                    + "</div>"
                )

        self.detail.setHtml("".join(parts))


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("statLabel")
    return label
