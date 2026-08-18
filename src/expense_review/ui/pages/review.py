"""검토 페이지 — 입력, 대시보드 요약, 제출자별 결과."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import config, sheets
from ...models import ReviewResult, Severity
from ...report import mask, to_markdown
from ...review import EXPENSE_TYPES, review_folder
from ..state import AppState
from ..theme import COLORS, SEVERITY_STYLE, card_shadow
from ..widgets import Card, DonutChart, EmptyState, StatTile, muted_label

SUBTYPES = {
    "근로장학금": [("전체", None), ("TA형 ((나)형)", "TA"), ("서포터즈형 ((가)형)", "SUPPORTERS")],
}


class ReviewWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, options: dict):
        super().__init__()
        self.options = options

    def run(self) -> None:
        try:
            options = self.options
            # 사람별로 나누는 일은 review_folder 가 알아서 한다. 사용자가 '한 명씩'과
            # '여러 명'을 고르게 두면, 잘못 고른 채로 서로 다른 사람의 개인정보를
            # 통일하라는 요청이 나간다.
            results = review_folder(options["path"], options["expense_type"],
                                    options["subtype"], options["roster"])
            self.finished.emit(results)
        except Exception:
            self.failed.emit(traceback.format_exc())


class ReviewPage(QWidget):
    def __init__(self, state: AppState, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.state = state
        self._thread: QThread | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(22)

        layout.addLayout(self._build_heading())
        layout.addWidget(self._build_input_card())
        layout.addLayout(self._build_stat_row())
        layout.addWidget(self._build_results_area(), 1)

        state.results_changed.connect(self._on_results)

    # ── 상단 ─────────────────────────────────────────────────────────────
    def _build_heading(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("서류 검토")
        title.setObjectName("pageTitle")
        box.addWidget(title)
        box.addWidget(muted_label("지출종류를 고르고 서류 폴더를 지정하면 기준에 따라 검토합니다."))
        return box

    def _build_input_card(self) -> QWidget:
        card = Card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)

        self.expense_type = QComboBox()
        self.expense_type.addItems(EXPENSE_TYPES)
        self.expense_type.currentTextChanged.connect(self._on_expense_type_changed)
        self.subtype = QComboBox()

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("서류가 담긴 폴더를 선택하세요")
        browse = QPushButton("찾아보기")
        browse.setObjectName("ghost")
        browse.clicked.connect(self._choose_folder)

        self.owner_edit = QLineEdit()
        self.owner_edit.setPlaceholderText("비우면 폴더명")

        self.roster_edit = QLineEdit()
        self.roster_edit.setPlaceholderText("폴더 밖에 있을 때만")
        roster_browse = QPushButton("파일")
        roster_browse.setObjectName("ghost")
        roster_browse.clicked.connect(self._choose_roster)

        grid.addWidget(_field_label("지출종류"), 0, 0)
        grid.addWidget(self.expense_type, 1, 0)
        grid.addWidget(_field_label("하위 유형"), 0, 1)
        grid.addWidget(self.subtype, 1, 1)
        grid.addWidget(_field_label("서류 폴더"), 0, 2)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_row.addWidget(self.path_edit, 1)
        folder_row.addWidget(browse)
        grid.addLayout(folder_row, 1, 2)
        grid.addWidget(_field_label("제출자"), 0, 3)
        grid.addWidget(self.owner_edit, 1, 3)
        grid.addWidget(_field_label("지급내역"), 0, 4)
        roster_row = QHBoxLayout()
        roster_row.setSpacing(8)
        roster_row.addWidget(self.roster_edit, 1)
        roster_row.addWidget(roster_browse)
        grid.addLayout(roster_row, 1, 4)
        grid.setColumnStretch(2, 3)
        grid.setColumnStretch(4, 2)
        card.add_layout(grid)

        actions = QHBoxLayout()
        actions.setSpacing(14)
        actions.addWidget(muted_label(
            "하위 폴더가 있으면 폴더별로, 파일만 있으면 서류에서 읽은 학번·성명으로 "
            "지급대상자를 갈라 검토합니다."))
        actions.addStretch(1)
        self.export_button = QPushButton("수정 요청서 저장")
        self.export_button.setObjectName("ghost")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        actions.addWidget(self.export_button)
        self.run_button = QPushButton("검토 시작")
        self.run_button.setObjectName("primary")
        card_shadow(self.run_button, blur=18, alpha=28, dy=4)
        self.run_button.clicked.connect(self._run)
        actions.addWidget(self.run_button)
        card.add_layout(actions)

        self._on_expense_type_changed(self.expense_type.currentText())
        stored = config.load_settings().get("last_folder", "")
        if stored:
            self.path_edit.setText(stored)
        return card

    def _build_stat_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(18)
        self.tile_total = StatTile("검토 대상", "0", "제출자 · 파일", variant="cardAccent")
        self.tile_error = StatTile("수정 필요", "0", "반드시 고쳐야 하는 항목", tone="Error")
        self.tile_warn = StatTile("확인 요망", "0", "담당자 판단이 필요", tone="Warn")
        self.tile_review = StatTile("판독 불가", "0", "원본을 직접 확인", tone="Review")
        for tile in (self.tile_total, self.tile_error, self.tile_warn, self.tile_review):
            row.addWidget(tile, 1)
        return row

    # ── 결과 ─────────────────────────────────────────────────────────────
    def _build_results_area(self) -> QWidget:
        splitter = QSplitter(Qt.Horizontal)

        left = Card("검토 결과", "제출자 · 심각도별")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._show_detail)
        left.add(self.tree, 1)
        splitter.addWidget(left)

        right = QWidget()
        right.setObjectName("page")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(18)

        donut_card = Card("구성비", "심각도")
        donut_row = QHBoxLayout()
        self.donut = DonutChart()
        donut_row.addWidget(self.donut, 1)
        self.legend = QVBoxLayout()
        self.legend.setSpacing(10)
        legend_holder = QWidget()
        legend_holder.setLayout(self.legend)
        donut_row.addWidget(legend_holder)
        donut_card.add_layout(donut_row)
        right_layout.addWidget(donut_card)

        detail_card = Card("상세", "선택한 항목")
        self.detail_stack = QStackedWidget()
        self.detail_empty = EmptyState("왼쪽에서 항목을 고르면\n무엇을 어떻게 고칠지 알려 드릴게요.")
        self.detail = QTextBrowser()
        self.detail.setFrameShape(QFrame.NoFrame)
        self.detail.setOpenExternalLinks(False)
        self.detail_stack.addWidget(self.detail_empty)
        self.detail_stack.addWidget(self.detail)
        detail_card.add(self.detail_stack, 1)
        right_layout.addWidget(detail_card, 1)

        splitter.addWidget(right)
        splitter.setSizes([620, 460])
        return splitter

    # ── 동작 ─────────────────────────────────────────────────────────────
    def _on_expense_type_changed(self, expense_type: str) -> None:
        self.subtype.clear()
        options = SUBTYPES.get(expense_type, [("해당 없음", None)])
        for label, value in options:
            self.subtype.addItem(label, value)
        self.subtype.setEnabled(len(options) > 1)

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "서류 폴더 선택", self.path_edit.text())
        if chosen:
            self.path_edit.setText(chosen)
            config.update_setting("last_folder", chosen)

    def _choose_roster(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "지급내역 선택", filter="PDF (*.pdf)")
        if chosen:
            self.roster_edit.setText(chosen)

    def _run(self) -> None:
        path = Path(self.path_edit.text().strip())
        if not path.exists():
            QMessageBox.warning(self, "경로 확인", "서류 폴더를 먼저 지정해 주세요.")
            return

        roster_text = self.roster_edit.text().strip()
        options = {
            "path": path,
            "expense_type": self.expense_type.currentText(),
            "subtype": self.subtype.currentData(),
            "owner": self.owner_edit.text().strip(),
            "roster": Path(roster_text) if roster_text else None,
        }
        config.update_setting("last_folder", str(path))

        self.run_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.state.set_busy(True, "검토 중입니다… 서류가 많으면 시간이 걸립니다.")

        self._thread = QThread()
        self._worker = ReviewWorker(options)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # 큐 연결을 명시한다. 직접 호출로 잡히면 결과 처리가 워커 스레드에서 돌아
        # 그 안에서 thread.wait() 를 부르며 교착에 빠진다.
        self._worker.finished.connect(self._on_worker_finished, Qt.QueuedConnection)
        self._worker.failed.connect(self._on_worker_failed, Qt.QueuedConnection)
        self._thread.start()

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None

    def _on_worker_finished(self, results: list) -> None:
        self._stop_thread()
        self.run_button.setEnabled(True)
        self.export_button.setEnabled(bool(results))
        self.state.set_busy(False, "검토를 마쳤습니다.")
        self.state.set_results(results)
        self._log_to_sheet(results)

    def _log_to_sheet(self, results: list) -> None:
        """설정된 경우 요약 행을 기록 시트로 보낸다. 요약뿐 — 서류 내용은 보내지 않는다."""
        settings = config.load_settings()
        url = settings.get("sheet_log_url", "").strip()
        if not settings.get("sheet_log_enabled") or not url:
            return

        import logging
        import threading

        rows = sheets.result_rows(results)

        def send():
            try:
                sheets.post_log(url, rows)
            except Exception as exc:
                logging.getLogger(__name__).warning("기록 시트 전송 실패: %s", exc)

        threading.Thread(target=send, daemon=True).start()

    def _on_worker_failed(self, message: str) -> None:
        self._stop_thread()
        self.run_button.setEnabled(True)
        self.state.set_busy(False, "검토 중 오류가 발생했습니다.")
        QMessageBox.critical(self, "오류", message)

    # ── 표시 ─────────────────────────────────────────────────────────────
    def _on_results(self, results: list[ReviewResult]) -> None:
        totals = self.state.totals()
        self.tile_total.set_value(
            str(len(results)), f"제출자 {len(results)}명 · 파일 {self.state.document_count()}개"
        )
        self.tile_error.set_value(str(totals[Severity.ERROR]))
        self.tile_warn.set_value(str(totals[Severity.WARN]))
        self.tile_review.set_value(str(totals[Severity.REVIEW]))

        segments = [
            (SEVERITY_STYLE[s.name]["label"], totals[s], SEVERITY_STYLE[s.name]["color"])
            for s in (Severity.ERROR, Severity.WARN, Severity.REVIEW)
        ]
        total = sum(count for _, count, _ in segments)
        self.donut.set_data(segments, str(total), "지적 건수")
        self._rebuild_legend(segments)
        self._rebuild_tree(results)

    def _rebuild_legend(self, segments) -> None:
        while self.legend.count():
            item = self.legend.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for label, count, color in segments:
            row = QHBoxLayout()
            row.setSpacing(7)
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 11px;")
            text = QLabel(f"{label}  {count}")
            text.setStyleSheet(f"font-size: 11px; color: {COLORS['text_muted']};")
            row.addWidget(dot)
            row.addWidget(text)
            row.addStretch(1)
            holder = QWidget()
            holder.setLayout(row)
            self.legend.addWidget(holder)
        self.legend.addStretch(1)

    def _rebuild_tree(self, results: list[ReviewResult]) -> None:
        self.tree.clear()
        for result in results:
            counts = result.counts
            root = QTreeWidgetItem([
                f"{result.owner or result.expense_type}   "
                f"🔴 {counts[Severity.ERROR]}  🟡 {counts[Severity.WARN]}  🔵 {counts[Severity.REVIEW]}"
            ])
            root.setExpanded(True)
            self.tree.addTopLevelItem(root)

            if result.is_clean:
                root.addChild(QTreeWidgetItem(["이상 없음"]))
                continue

            for severity in (Severity.ERROR, Severity.WARN, Severity.REVIEW):
                findings = result.by_severity(severity)
                if not findings:
                    continue
                style = SEVERITY_STYLE[severity.name]
                group = QTreeWidgetItem([f"{style['label']} ({len(findings)})"])
                root.addChild(group)
                group.setExpanded(severity is not Severity.REVIEW)
                for finding in findings:
                    item = QTreeWidgetItem([f"{finding.rule_id}  {finding.title}"])
                    item.setData(0, Qt.UserRole, finding)
                    group.addChild(item)

    def _show_detail(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        finding = current.data(0, Qt.UserRole) if current else None
        if finding is None:
            self.detail.clear()
            self.detail_stack.setCurrentWidget(self.detail_empty)
            return
        self.detail_stack.setCurrentWidget(self.detail)
        color = SEVERITY_STYLE[finding.severity.name]["color"]
        self.detail.setHtml(
            f"<div style='font-size:13px;font-weight:700;color:{color};'>"
            f"{SEVERITY_STYLE[finding.severity.name]['label']} · {finding.title}</div>"
            f"<p style='color:{COLORS['text_muted']};font-size:11px;'>"
            f"{finding.rule_id} · {finding.layer}</p>"
            f"<p><b>검출</b><br>{mask(finding.message)}</p>"
            f"<p><b>조치</b><br>{mask(finding.fix) or '—'}</p>"
            f"<p style='color:{COLORS['text_muted']};'><b>근거</b><br>{finding.evidence}</p>"
        )

    def _export(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self, "수정 요청서 저장", "수정요청서.md", filter="Markdown (*.md)"
        )
        if not target:
            return
        Path(target).write_text(to_markdown(self.state.results), encoding="utf-8")
        self.state.set_busy(False, f"저장했습니다: {target}")


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("statLabel")
    return label
