"""지출 서류 검토 데스크톱 앱.

  지출종류 선택 → 서류 폴더 지정 → 검토 → 결과 확인 → 수정 요청서 저장

검토는 별도 스레드에서 돌린다. PDF 수십 장을 읽는 동안 창이 멈추면
사용자는 앱이 죽은 줄 안다.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import ReviewResult, Severity
from ..report import mask, summarize, to_markdown
from ..review import EXPENSE_TYPES, review, review_batch

SUBTYPES = {
    "근로장학금": [("(선택 안 함)", None), ("TA형 ((나)형)", "TA"),
               ("서포터즈형 ((가)형)", "SUPPORTERS")],
}

SEVERITY_GROUPS = [
    (Severity.ERROR, "🔴 수정 필요"),
    (Severity.WARN, "🟡 확인 요망"),
    (Severity.REVIEW, "🔵 판독 불가 — 직접 확인"),
]


class ReviewWorker(QObject):
    """검토를 백그라운드에서 수행한다."""

    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, options: dict):
        super().__init__()
        self.options = options

    def run(self) -> None:
        try:
            options = self.options
            if options["batch"]:
                results = review_batch(
                    options["path"], options["expense_type"],
                    options["subtype"], options["roster"],
                )
            else:
                results = [review(
                    options["path"], options["expense_type"],
                    options["owner"] or options["path"].name,
                    options["subtype"], options["roster"],
                )]
            self.finished.emit(results)
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("지출 서류 검토")
        self.resize(1180, 760)
        self.results: list[ReviewResult] = []
        self._thread: QThread | None = None

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([360, 820])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("지출종류를 고르고 서류 폴더를 지정하세요.")

    # ── 왼쪽: 입력 ───────────────────────────────────────────────────────
    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        form_box = QGroupBox("검토 대상")
        form = QFormLayout(form_box)

        self.expense_type = QComboBox()
        self.expense_type.addItems(EXPENSE_TYPES)
        self.expense_type.currentTextChanged.connect(self._on_expense_type_changed)
        form.addRow("지출종류", self.expense_type)

        self.subtype = QComboBox()
        form.addRow("하위 유형", self.subtype)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("서류가 담긴 폴더")
        browse = QPushButton("폴더 선택…")
        browse.clicked.connect(self._choose_folder)
        row = QHBoxLayout()
        row.addWidget(self.path_edit)
        row.addWidget(browse)
        container = QWidget()
        container.setLayout(row)
        form.addRow("서류 폴더", container)

        self.owner_edit = QLineEdit()
        self.owner_edit.setPlaceholderText("비우면 폴더명을 씁니다")
        form.addRow("제출자", self.owner_edit)

        self.roster_edit = QLineEdit()
        self.roster_edit.setPlaceholderText("폴더 밖에 있을 때만 지정")
        roster_browse = QPushButton("파일…")
        roster_browse.clicked.connect(self._choose_roster)
        roster_row = QHBoxLayout()
        roster_row.addWidget(self.roster_edit)
        roster_row.addWidget(roster_browse)
        roster_container = QWidget()
        roster_container.setLayout(roster_row)
        form.addRow("지급내역", roster_container)

        self.batch_check = QCheckBox("하위 폴더마다 제출자로 보고 일괄 검토")
        form.addRow("", self.batch_check)

        layout.addWidget(form_box)

        self.run_button = QPushButton("검토 시작")
        self.run_button.setMinimumHeight(38)
        self.run_button.clicked.connect(self._run_review)
        layout.addWidget(self.run_button)

        self.export_button = QPushButton("수정 요청서 저장…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        layout.addWidget(self.export_button)

        self.summary_label = QLabel("아직 검토하지 않았습니다.")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addStretch(1)

        self._on_expense_type_changed(self.expense_type.currentText())
        return panel

    # ── 오른쪽: 결과 ─────────────────────────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["항목", "검출 내용"])
        self.tree.setColumnWidth(0, 300)
        self.tree.currentItemChanged.connect(self._show_detail)
        layout.addWidget(self.tree, 3)

        self.detail = QTextBrowser()
        self.detail.setFont(QFont("Noto Sans CJK KR", 10))
        layout.addWidget(self.detail, 2)
        return panel

    # ── 동작 ─────────────────────────────────────────────────────────────
    def _on_expense_type_changed(self, expense_type: str) -> None:
        self.subtype.clear()
        options = SUBTYPES.get(expense_type, [("(해당 없음)", None)])
        for label, value in options:
            self.subtype.addItem(label, value)
        self.subtype.setEnabled(len(options) > 1)

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "서류 폴더 선택")
        if chosen:
            self.path_edit.setText(chosen)

    def _choose_roster(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "지급내역 파일 선택", filter="PDF (*.pdf)")
        if chosen:
            self.roster_edit.setText(chosen)

    def _run_review(self) -> None:
        path = Path(self.path_edit.text().strip())
        if not path.exists():
            QMessageBox.warning(self, "경로 확인", "서류 폴더를 지정해 주세요.")
            return

        roster_text = self.roster_edit.text().strip()
        options = {
            "path": path,
            "expense_type": self.expense_type.currentText(),
            "subtype": self.subtype.currentData(),
            "owner": self.owner_edit.text().strip(),
            "roster": Path(roster_text) if roster_text else None,
            "batch": self.batch_check.isChecked(),
        }

        self.run_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.statusBar().showMessage("검토 중입니다… 서류가 많으면 시간이 걸립니다.")

        self._thread = QThread()
        self._worker = ReviewWorker(options)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # 큐 연결을 명시한다. 기본 연결이 직접 호출로 잡히면 결과 처리가 워커
        # 스레드에서 실행되고, 그 안에서 thread.wait() 를 부르며 교착에 빠진다.
        self._worker.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._worker.failed.connect(self._on_failed, Qt.QueuedConnection)
        self._thread.start()

    def _on_finished(self, results: list) -> None:
        self._stop_thread()
        self.results = results
        self._populate(results)
        self.run_button.setEnabled(True)
        self.export_button.setEnabled(bool(results))
        self.statusBar().showMessage("검토를 마쳤습니다.")

    def _on_failed(self, message: str) -> None:
        self._stop_thread()
        self.run_button.setEnabled(True)
        self.statusBar().showMessage("검토 중 오류가 발생했습니다.")
        QMessageBox.critical(self, "오류", message)

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None

    def _populate(self, results: list[ReviewResult]) -> None:
        self.tree.clear()
        self.detail.clear()

        totals = {severity: 0 for severity, _ in SEVERITY_GROUPS}
        for result in results:
            root = QTreeWidgetItem([result.owner or result.expense_type, summarize(result)])
            root.setExpanded(True)
            self.tree.addTopLevelItem(root)

            for severity, label in SEVERITY_GROUPS:
                findings = result.by_severity(severity)
                totals[severity] += len(findings)
                if not findings:
                    continue
                group = QTreeWidgetItem([f"{label} ({len(findings)})", ""])
                root.addChild(group)
                group.setExpanded(severity is not Severity.REVIEW)
                for finding in findings:
                    item = QTreeWidgetItem([
                        f"{finding.rule_id}  {finding.title}", mask(finding.message)
                    ])
                    item.setData(0, Qt.UserRole, finding)
                    group.addChild(item)

            if result.is_clean:
                root.addChild(QTreeWidgetItem(["🟢 이상 없음", "자동 검토 항목에서 문제가 없습니다."]))

        self.summary_label.setText(
            f"검토 {len(results)}건 · "
            f"🔴 {totals[Severity.ERROR]} · 🟡 {totals[Severity.WARN]} · 🔵 {totals[Severity.REVIEW]}"
        )

    def _show_detail(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        finding = current.data(0, Qt.UserRole) if current else None
        if finding is None:
            self.detail.clear()
            return
        self.detail.setHtml(
            f"<h3>{finding.severity.marker} {finding.title}</h3>"
            f"<p><b>규칙</b> {finding.rule_id} · {finding.layer}</p>"
            f"<p><b>검출</b><br>{mask(finding.message)}</p>"
            f"<p><b>조치</b><br>{mask(finding.fix) or '—'}</p>"
            f"<p><b>근거</b><br>{finding.evidence}</p>"
        )

    def _export(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self, "수정 요청서 저장", "수정요청서.md", filter="Markdown (*.md)"
        )
        if not target:
            return
        Path(target).write_text(to_markdown(self.results), encoding="utf-8")
        self.statusBar().showMessage(f"저장했습니다: {target}")


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
