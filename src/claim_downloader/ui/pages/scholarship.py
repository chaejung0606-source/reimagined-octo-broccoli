"""일반청구 화면 오른쪽 칸의 '장학금' 패널 — 종류가 장학금인 지출 폴더를 고르면 '청구 내용' 칸 대신 보인다.

담당자 제안(2026-10-14): 장학금을 홈에 따로 두지 않고 일반청구 화면에서 폴더마다 종류를 고른다(claims/kinds.py).
이 패널은 한 폴더(claims.scholarship.Job)를 보여 주고 고치게 할 뿐이다 — 대표적요 · 지급예정년월 · 소득자 찾기 구분 · 명단 엑셀 ·
학생 표(넣을 사람 체크). ERP 에 넣는 것은 화면(pages/claim.py)이 브라우저 스레드에 맡긴다.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import settings
from ...claims import person, scholarship
from ..widgets import Field, PillDelegate, WrapLabel, muted_label

COLUMNS = [("", 30), ("상태", 84), ("이름", 76), ("학번", 104), ("금액", 84), ("첨부", 44), ("행 적요", None)]
COL_CHECK, COL_STATUS, COL_NAME, COL_STUDENT, COL_AMOUNT, COL_FILES, COL_SUMMARY = range(7)

PERSON_STATUS = {
    "ready": ("넣을 것", "neutral"),
    "skip": ("뺌", "neutral"),
    "problem": ("확인 필요", "warning"),
    "planned": ("확인함", "info"),
    "running": ("넣는 중", "info"),
    "saved": ("임시저장", "success"),
    "stopped": ("멈춤", "warning"),
    "failed": ("실패", "danger"),
}


def _money(value) -> str:
    return f"{value:,}" if isinstance(value, int) else ""


class ScholarshipPanel(QWidget):
    """장학금 폴더 하나 — 학생 표와 넣기 옵션. changed 는 넣을 사람 · 옵션이 바뀔 때마다(화면이 표의 그 줄을 새로 그린다)."""

    changed = Signal()
    reload_requested = Signal(str)        # 엑셀을 바꿔 다시 읽기 — 엑셀 경로(비우면 그대로)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pageBody")            # 스크롤 칸 안에서도 바탕이 비치게(theme.py)
        self.job: scholarship.Job | None = None
        self._status: list[str] = []
        self._loading = False
        self._locked = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 칸은 한 줄로 — 학생 표가 높이를 가져가야 한다(일반청구 오른쪽 칸 안이라 좁다). 도움말은 마우스를 올리면 보인다.
        row = QHBoxLayout()
        row.setSpacing(10)
        self.main_summary = QLineEdit()
        self.main_summary.setPlaceholderText("예: 02_2026년도 7월 (가)형 근로장학금 지급내역")
        self.main_summary.setToolTip("명단 제목에 02_ 를 붙인 것. 고치면 행 적요도 바뀝니다")
        self.main_summary.editingFinished.connect(self._options_changed)
        row.addWidget(Field("대표적요", self.main_summary), 4)
        self.pay_ym = QLineEdit()
        self.pay_ym.setPlaceholderText("YYYY-MM")
        self.pay_ym.setToolTip("지급예정년월 — 청구하는 달")
        self.pay_ym.editingFinished.connect(self._options_changed)
        row.addWidget(Field("지급예정년월", self.pay_ym), 1)
        self.tab_box = QComboBox()
        self.tab_box.addItem("인적정보 (학번)", person.TAB_STUDENT)
        self.tab_box.addItem("참여인력 (사번)", person.TAB_STAFF)
        self.tab_box.setToolTip("소득자 돋보기 팝업에서 찾을 구분 — 학생은 인적정보")
        self.tab_box.currentIndexChanged.connect(lambda _i: self._options_changed())
        row.addWidget(Field("소득자 찾기", self.tab_box), 2)
        layout.addLayout(row)

        self.excel_box = QComboBox()
        self.excel_box.setToolTip("폴더에 엑셀이 여럿이면 명단 엑셀을 고르세요")
        self.excel_box.currentIndexChanged.connect(self._excel_changed)
        self.excel_field = Field("명단 엑셀", self.excel_box)
        layout.addWidget(self.excel_field)

        self.problems = WrapLabel("")
        self.problems.setObjectName("fieldError")
        layout.addWidget(self.problems)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([name for name, _ in COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setMinimumHeight(120)          # 머리글 + 두 줄은 늘 보이게 — 모자라면 바깥 칸이 스크롤된다
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setItemDelegateForColumn(COL_STATUS, PillDelegate(self.table))
        self.table.itemChanged.connect(self._on_item_changed)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setStretchLastSection(True)
        head.setHighlightSections(False)
        for col, (_, width) in enumerate(COLUMNS):
            head.setSectionResizeMode(col, QHeaderView.Interactive)
            if width:
                self.table.setColumnWidth(col, width)
        layout.addWidget(self.table, 1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.files_note = muted_label("")
        foot.addWidget(self.files_note, 1)
        self.reload_button = QPushButton("다시 읽기")
        self.reload_button.setObjectName("ghost")
        self.reload_button.setToolTip("폴더 안 파일이나 명단을 고친 뒤 누르세요.")
        self.reload_button.clicked.connect(lambda: self.reload_requested.emit(""))
        foot.addWidget(self.reload_button)
        rules_button = QPushButton("적요 규칙 열기")
        rules_button.setObjectName("ghost")
        rules_button.setToolTip("대표적요 · 행 적요를 만드는 규칙(장학금규칙.txt). 저장한 뒤 [다시 읽기].")
        rules_button.clicked.connect(self._open_rules)
        foot.addWidget(rules_button)
        layout.addLayout(foot)

    # ── 보이기 ──────────────────────────────────────────────────────────
    def set_job(self, job: scholarship.Job | None) -> None:
        self.job = job
        self._loading = True
        self.main_summary.setText(job.main_summary if job else "")
        self.pay_ym.setText(job.pay_ym if job else "")
        index = self.tab_box.findData(job.tab if job else person.TAB_STUDENT)
        self.tab_box.setCurrentIndex(max(index, 0))
        self.excel_box.blockSignals(True)
        self.excel_box.clear()
        for candidate in (job.excel_candidates if job else []):
            self.excel_box.addItem(os.path.basename(candidate), candidate)
        if job:
            self.excel_box.setCurrentIndex(max(self.excel_box.findData(job.roster.path), 0))
        self.excel_box.blockSignals(False)
        self.excel_field.setVisible(bool(job) and len(job.excel_candidates) > 1)
        self._loading = False
        self._fill_table()
        self._sync()

    def set_locked(self, locked: bool) -> None:
        """ERP 에 넣는 동안에는 고치지 못하게."""
        self._locked = locked
        self._sync()

    def _sync(self) -> None:
        editable = self.job is not None and not self._locked
        for widget in (self.main_summary, self.pay_ym, self.tab_box, self.excel_box, self.reload_button):
            widget.setEnabled(editable)
        self.table.setEnabled(self.job is not None)

    def _fill_table(self) -> None:
        job = self.job
        self._loading = True
        self.table.setRowCount(0)
        self._status = []
        if job is None:
            self._loading = False
            self.problems.hide()
            self.files_note.setText("")
            return
        self.table.setRowCount(len(job.people))
        for row, p in enumerate(job.people):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if job.selected[row] else Qt.Unchecked)
            self.table.setItem(row, COL_CHECK, check)
            files = job.files_for(row)
            summary = job.row_summary(row)
            # 줄마다 앞의 대표적요는 같다 — 좁은 칸에서는 줄을 가르는 뒷부분(_이름 · _(이름_교과목))이 보이게 앞을 줄인다
            shown = ("…" + summary[len(job.main_summary):]
                     if job.main_summary and summary.startswith(job.main_summary) and summary != job.main_summary else summary)
            values = {COL_NAME: p.name, COL_STUDENT: p.student_no or "—", COL_AMOUNT: _money(p.amount) or "—",
                      COL_FILES: str(len(files)), COL_SUMMARY: shown}
            for col, value in values.items():
                item = QTableWidgetItem(value)
                if col == COL_FILES:
                    item.setToolTip("\n".join(os.path.relpath(f, job.folder) for f in files) or "첨부 없음")
                elif col == COL_SUMMARY:
                    item.setToolTip(summary)
                else:
                    item.setToolTip(value + (f"\n{p.note}" if p.note else ""))
                if col in (COL_AMOUNT, COL_FILES):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, item)
            self._status.append("")
            self._put_status(row, "problem" if p.note else ("ready" if job.selected[row] else "skip"))
        self._loading = False
        problems = job.problems()
        self.problems.setText("\n".join("· " + p for p in problems))
        self.problems.setVisible(bool(problems))
        self._fill_footer()

    def _fill_footer(self) -> None:
        job = self.job
        per = sum(len(v) for v in job.person_files.values())
        chosen = job.chosen()
        self.files_note.setText(f"넣을 사람 {job.count_text(chosen)} · 합계 {sum(job.people[i].amount or 0 for i in chosen):,}원 · "
                                f"공통증빙 {len(job.common_files)}개 · 개별증빙 {per}개")

    def _put_status(self, row: int, status: str) -> None:
        if not (0 <= row < len(self._status)):
            return
        self._status[row] = status
        text, tone = PERSON_STATUS[status]
        item = QTableWidgetItem(text)
        item.setData(PillDelegate.ROLE, tone)
        was = self._loading
        self._loading = True
        self.table.setItem(row, COL_STATUS, item)
        self._loading = was

    def set_person_status(self, index: int, status: str, note: str = "") -> None:
        self._put_status(index, status if status in PERSON_STATUS else "running")
        item = self.table.item(index, COL_STATUS)
        if item is not None and note:
            item.setToolTip(note)
        if status == "running" and self.table.item(index, COL_NAME) is not None:
            self.table.scrollToItem(self.table.item(index, COL_NAME))

    def mark_planned(self, indexes) -> None:
        for index in indexes:
            self._put_status(index, "planned")

    def uncheck_saved(self, indexes) -> None:
        """임시저장된 학생은 체크를 푼다 — 다시 누르면 남은 사람만, 두 번 넣지 않게."""
        if self.job is None:
            return
        self._loading = True
        for index in indexes:
            self.job.selected[index] = False
            item = self.table.item(index, COL_CHECK)
            if item is not None:
                item.setCheckState(Qt.Unchecked)
        self._loading = False
        self._fill_footer()
        self.changed.emit()

    # ── 고치기 ──────────────────────────────────────────────────────────
    def apply_options(self) -> None:
        """입력 칸의 값을 job 에 옮긴다 — 넣기 직전에도 부른다(편집 중인 칸이 아직 반영 안 됐을 수 있다)."""
        if self.job is None:
            return
        self.job.main_summary = self.main_summary.text().strip()
        ym = self.pay_ym.text().strip()
        self.job.pay_ym = ym
        self.job.tab = self.tab_box.currentData() or person.TAB_STUDENT

    def _options_changed(self) -> None:
        if self._loading or self.job is None:
            return
        self.apply_options()
        if self.pay_ym.text().strip() and not re.fullmatch(r"\d{4}-\d{2}", self.pay_ym.text().strip()):
            self.pay_ym.setToolTip("YYYY-MM 꼴로 적어 주세요")
        self._fill_table()
        self.changed.emit()

    def _excel_changed(self, _index: int) -> None:
        if self._loading or self.job is None:
            return
        path = self.excel_box.currentData()
        if path and path != self.job.roster.path:
            self.reload_requested.emit(path)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self.job is None or item.column() != COL_CHECK:
            return
        row = item.row()
        self.job.selected[row] = item.checkState() == Qt.Checked
        p = self.job.people[row]
        self._put_status(row, "problem" if p.note and self.job.selected[row] else ("ready" if self.job.selected[row] else "skip"))
        self._fill_footer()
        self.changed.emit()

    def _open_rules(self) -> None:
        scholarship.load_rules()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.scholarship_rules_path())))
