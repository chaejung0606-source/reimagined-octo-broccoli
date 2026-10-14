"""장학금 청구 화면 — 지출 1건 폴더(명단 엑셀 + 공통증빙\\ + 개별증빙\\)를 고르고 → 미리 보기 → ERP 인건비 탭에 학생마다 넣고 [저장].

    폴더 고르기(끌어다 놓기 · 버튼) → 표에서 사람·적요·첨부 확인(빼고 싶은 사람은 체크 해제)
    → 브라우저에서 결의서내역 → [일반청구] 로 새 청구서 화면 → [ERP 에 넣기]
    → 앱이 학생마다 탭 · 비목 · 소득구분 · 소득자 · 금액 · 적요 · 첨부 · [저장]
    → 앱이 확신하지 못하면 노란 띠로 묻는다(사람이 ERP 에서 하고 [계속]) → 끝나면 사람이 검토하고 [신청]

설계 docs/roadmap.md 2-1절(담당자 확인 2026-10-14), 흐름 claims/scholarship.py. 기본은 '미리 보기만'.
브라우저는 청구서 받기 · 일반청구와 같은 스레드(app.session_worker) — ERP 로그인은 한 번.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import settings
from ...claims import person, record, scholarship
from ..art import Art
from ..widgets import Card, ElideLabel, EmptyState, Field, Pill, PillDelegate, WrapLabel, muted_label
from ..worker import SessionWorker

COLUMNS = [("", 34), ("상태", 92), ("No", 44), ("이름", 90), ("학번", 100), ("금액", 96), ("첨부", 56), ("행 적요", None)]
COL_CHECK, COL_STATUS, COL_NO, COL_NAME, COL_STUDENT, COL_AMOUNT, COL_FILES, COL_SUMMARY = range(8)

ROW_STATUS = {
    "ready": ("넣을 것", "neutral"),
    "skip": ("뺌", "neutral"),
    "planned": ("확인함", "info"),
    "running": ("넣는 중", "info"),
    "saved": ("임시저장", "success"),
    "stopped": ("멈춤", "warning"),
    "failed": ("실패", "danger"),
    "problem": ("확인 필요", "warning"),
}

GUIDE_START = "지출 건 폴더를 끌어다 놓거나 [폴더 고르기] 를 누르세요. 폴더 안에 명단 엑셀 · 공통증빙 · 개별증빙 이 있어야 합니다."
GUIDE_READY = ("표를 확인한 뒤, 브라우저에서 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우고 [ERP 에 넣기] 를 누르세요. "
               "인건비 탭은 앱이 누릅니다.")


def _money(value) -> str:
    return f"{value:,}" if isinstance(value, int) else ""


class ScholarshipPage(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAcceptDrops(True)
        self.browser = worker if worker is not None else SessionWorker()
        self._owns_browser = worker is None
        self.job: scholarship.Job | None = None
        self._status: list[str] = []
        self._running = False
        self._browser_busy = False
        self._browser_open = False
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 26)
        layout.setSpacing(12)
        layout.addLayout(self._build_head())
        layout.addWidget(self._build_drop_zone())
        layout.addWidget(self._build_ask_banner())
        layout.addWidget(self._build_options())
        layout.addWidget(self._build_list_card(), 1)
        layout.addLayout(self._build_bottom_row())

        b = self.browser
        b.log.connect(self._append_log)
        b.busy.connect(self._on_browser_busy)
        b.browser_opened.connect(self._on_browser_opened)
        b.browser_state.connect(self._on_browser_state)
        b.scholarship_person.connect(self._on_person)
        b.scholarship_ask.connect(self._on_ask)
        b.scholarship_done.connect(self._on_done)
        b.error.connect(self._on_error)
        self._sync()

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("scholarship", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("장학금 청구")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        self.page_desc = muted_label(
            "명단 엑셀과 증빙 폴더로 ERP 작성 화면의 인건비(소득성 경비) 탭에 학생 한 명씩 넣고 [저장] 합니다. "
            "[신청] 은 검토한 뒤 직접 누르세요.")
        texts.addWidget(self.page_desc)
        head.addLayout(texts, 1)
        rules_button = QPushButton("적요 규칙 열기")
        rules_button.setObjectName("ghost")
        rules_button.setToolTip("대표적요 · 행 적요를 만드는 규칙. 저장한 뒤 폴더를 다시 읽으면 반영됩니다.")
        rules_button.clicked.connect(self._open_rules)
        head.addWidget(rules_button, 0, Qt.AlignVCenter)
        return head

    def _build_drop_zone(self) -> QFrame:
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setFixedHeight(76)
        row = QHBoxLayout(self.drop_zone)
        row.setContentsMargins(18, 10, 14, 10)
        row.setSpacing(12)
        row.addWidget(Art("archive", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.folder_title = QLabel("여기에 지출 건 폴더를 끌어다 놓으세요")
        self.folder_title.setObjectName("cardTitle")
        texts.addWidget(self.folder_title)
        self.folder_hint = ElideLabel("폴더 바로 아래에 명단 엑셀 하나 · '공통증빙' 폴더(모든 학생에게) · '개별증빙' 폴더(파일명이나 하위 폴더에 학생 이름)")
        self.folder_hint.setObjectName("muted")
        texts.addWidget(self.folder_hint)
        row.addLayout(texts, 1)
        self.pick_button = QPushButton("폴더 고르기")
        self.pick_button.clicked.connect(self._pick_folder)
        self.reload_button = QPushButton("다시 읽기")
        self.reload_button.setObjectName("ghost")
        self.reload_button.setToolTip("폴더 안 파일이나 명단을 고친 뒤 누르세요.")
        self.reload_button.clicked.connect(lambda: self.load_folder(self.job.folder) if self.job else None)
        row.addWidget(self.pick_button, 0, Qt.AlignVCenter)
        row.addWidget(self.reload_button, 0, Qt.AlignVCenter)
        return self.drop_zone

    def _build_ask_banner(self) -> QFrame:
        """앱이 확신하지 못하는 단계 — 사람이 ERP 에서 하고 [계속]. 받기 화면의 재로그인 띠와 같은 모양."""
        self.ask_banner = QFrame()
        self.ask_banner.setObjectName("banner")
        row = QHBoxLayout(self.ask_banner)
        row.setContentsMargins(16, 10, 10, 10)
        row.setSpacing(10)
        row.addWidget(Pill("확인 필요", "warning"), 0, Qt.AlignVCenter)
        self.ask_text = WrapLabel("")
        self.ask_text.setObjectName("bannerText")
        row.addWidget(self.ask_text, 1)
        self.continue_button = QPushButton("ERP 에서 했어요 · 계속")
        self.continue_button.setObjectName("primary")
        self.continue_button.clicked.connect(lambda: self._answer(True))
        self.halt_button = QPushButton("여기서 멈추기")
        self.halt_button.clicked.connect(lambda: self._answer(False))
        row.addWidget(self.continue_button)
        row.addWidget(self.halt_button)
        self.ask_banner.hide()
        return self.ask_banner

    def _build_options(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.main_summary = QLineEdit()
        self.main_summary.setPlaceholderText("예: 02_2026년도 7월 (가)형 근로장학금 지급내역")
        self.main_summary.editingFinished.connect(self._options_changed)
        row.addWidget(Field("대표적요", self.main_summary, "명단 제목에 02_ 를 붙인 것. 고치면 행 적요도 바뀝니다"), 3)
        self.pay_ym = QLineEdit()
        self.pay_ym.setPlaceholderText("YYYY-MM")
        self.pay_ym.setMaximumWidth(120)
        self.pay_ym.editingFinished.connect(self._options_changed)
        row.addWidget(Field("지급예정년월", self.pay_ym, "청구하는 달"), 1)
        self.tab_box = QComboBox()
        self.tab_box.addItem("인적정보 (학생 · 학번)", person.TAB_STUDENT)
        self.tab_box.addItem("참여인력 (사번)", person.TAB_STAFF)
        self.tab_box.currentIndexChanged.connect(lambda _i: self._options_changed())
        row.addWidget(Field("소득자 찾기", self.tab_box, "소득자 돋보기 팝업의 구분"), 1)
        self.excel_box = QComboBox()
        self.excel_box.currentIndexChanged.connect(self._excel_changed)
        self.excel_field = Field("명단 엑셀", self.excel_box, "폴더에 엑셀이 여럿이면 고르세요")
        row.addWidget(self.excel_field, 2)
        return box

    def _build_list_card(self) -> QWidget:
        card = Card(margins=(16, 8, 16, 12))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.list_stack = QStackedWidget()
        self.empty = EmptyState("scholarship", "지출 건 폴더를 고르면 학생 명단이 여기에 나옵니다",
                                "명단 엑셀의 이름 · 학번 · 금액과, 학생마다 붙일 첨부 수를 보여 줍니다. 빼고 싶은 학생은 체크를 푸세요.")
        self.list_stack.addWidget(self.empty)
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 10, 0, 0)
        holder_layout.setSpacing(8)
        self.problems = WrapLabel("")
        self.problems.setObjectName("fieldError")
        holder_layout.addWidget(self.problems)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([name for name, _ in COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
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
        holder_layout.addWidget(self.table, 1)
        self.files_note = muted_label("")
        holder_layout.addWidget(self.files_note)
        self.list_stack.addWidget(holder)
        self.tabs.addTab(self.list_stack, "학생 명단")
        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.setContentsMargins(0, 10, 0, 0)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        log_layout.addWidget(self.log_view, 1)
        self.tabs.addTab(log_page, "진행 기록")
        open_log = QPushButton("로그 파일 열기")
        open_log.setObjectName("ghost")
        open_log.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.log_path()))))
        self.tabs.setCornerWidget(open_log, Qt.TopRightCorner)
        card.add(self.tabs, 1)
        return card

    def _build_bottom_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.state_pill = Pill("준비", "neutral")
        row.addWidget(self.state_pill, 0, Qt.AlignVCenter)
        self.guide = QLabel(GUIDE_START)
        self.guide.setObjectName("body")
        self.guide.setWordWrap(True)
        row.addWidget(self.guide, 1)
        self.stop_button = QPushButton("멈추기")
        self.stop_button.setObjectName("danger")
        self.stop_button.setToolTip("지금 넣고 있는 학생까지 마치고 멈춥니다.")
        self.stop_button.clicked.connect(self._stop)
        row.addWidget(self.stop_button)
        self.open_button = QPushButton("브라우저 열기")
        self.open_button.setToolTip("앱이 연 브라우저에서 ERP 로그인 → 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우세요")
        self.open_button.clicked.connect(lambda: self.browser.open_browser(scan=False))
        row.addWidget(self.open_button)
        self.dry_run = QCheckBox("미리 보기만")
        self.dry_run.setChecked(True)
        self.dry_run.setToolTip("체크돼 있으면 ERP 에 넣지 않고 학생마다 무엇을 넣을지만 보여 줍니다. 풀면 실제로 넣고 [저장] 까지 합니다(신청은 직접).")
        self.dry_run.toggled.connect(lambda _c: self._sync())
        row.addWidget(self.dry_run)
        self.run_button = QPushButton("ERP 에 넣기")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self._run)
        row.addWidget(self.run_button)
        return row

    # ── 상태 ────────────────────────────────────────────────────────────
    def _sync(self) -> None:
        has_job = self.job is not None and bool(self.job.people)
        self.pick_button.setEnabled(not self._running)
        self.reload_button.setVisible(self.job is not None)
        self.reload_button.setEnabled(not self._running)
        for widget in (self.main_summary, self.pay_ym, self.tab_box, self.excel_box):
            widget.setEnabled(has_job and not self._running)
        self.excel_field.setVisible(self.job is not None and len(self.job.excel_candidates) > 1)
        self.stop_button.setVisible(self._running)
        self.open_button.setVisible(not self._browser_open)
        self.open_button.setEnabled(not self._browser_busy)
        dry = self.dry_run.isChecked()
        chosen = len(self.job.chosen()) if self.job else 0
        self.run_button.setText(f"미리 보기 ({chosen}명)" if dry else f"ERP 에 넣기 ({chosen}명)")
        self.run_button.setEnabled(has_job and chosen > 0 and not self._running and not self._browser_busy
                                   and (dry or self._browser_open))
        self.dry_run.setEnabled(not self._running)
        self.list_stack.setCurrentIndex(1 if self.job is not None else 0)
        self.tabs.setTabText(0, f"학생 명단 ({len(self.job.people)})" if self.job else "학생 명단")

    def _set_state(self, text: str, status: str, guide: str | None = None) -> None:
        self.state_pill.set_status(text, status)
        if guide is not None:
            self.guide.setText(guide)

    def _set_status(self, row: int, status: str) -> None:
        if not (0 <= row < len(self._status)):
            return
        self._status[row] = status
        text, tone = ROW_STATUS[status]
        item = QTableWidgetItem(text)
        item.setData(PillDelegate.ROLE, tone)
        self._loading = True
        self.table.setItem(row, COL_STATUS, item)
        self._loading = False

    def is_running(self) -> bool:
        return self._running

    def resumable(self) -> tuple[bool, str]:
        if self._running and self.job is not None:
            done = sum(1 for s in self._status if s == "saved")
            return True, f"넣는 중 · {done}/{len(self.job.chosen())}명"
        return False, ""

    # ── 폴더 ─────────────────────────────────────────────────────────────
    def _pick_folder(self) -> None:
        start = self.job.folder if self.job else ""
        path = QFileDialog.getExistingDirectory(self, "지출 건 폴더 고르기", start)
        if path:
            self.load_folder(path)

    def load_folder(self, path: str, excel: str | None = None) -> bool:
        if self._running or not os.path.isdir(path):
            return False
        keep_ym = self.pay_ym.text().strip() if self.job else ""
        job = scholarship.load_job(path, excel=excel)
        if keep_ym and re.fullmatch(r"\d{4}-\d{2}", keep_ym):
            job.pay_ym = keep_ym
        job.tab = self.tab_box.currentData() or person.TAB_STUDENT
        self.job = job
        self.folder_title.setText(os.path.basename(path.rstrip("\\/")) or path)
        self.folder_hint.setText(path)
        self._loading = True
        self.main_summary.setText(job.main_summary)
        self.pay_ym.setText(job.pay_ym)
        self.excel_box.blockSignals(True)
        self.excel_box.clear()
        for candidate in job.excel_candidates:
            self.excel_box.addItem(os.path.basename(candidate), candidate)
        index = self.excel_box.findData(job.roster.path)
        self.excel_box.setCurrentIndex(max(index, 0))
        self.excel_box.blockSignals(False)
        self._loading = False
        self._fill_table()
        self._append_log("폴더 읽음: " + " / ".join(job.summary_lines()))
        before = record.previous(path)
        if before:
            self._append_log(f"이 폴더는 {before.get('when')} 에 넣은 적이 있습니다 ({before.get('summary')})")
        problems = job.problems()
        if problems:
            self._set_state("확인 필요", "warning", "표 위의 빨간 글을 확인하세요. 고친 뒤 [다시 읽기].")
        else:
            self._set_state("읽음", "success", GUIDE_READY)
        self._sync()
        return True

    def _excel_changed(self, _index: int) -> None:
        if self._loading or self.job is None:
            return
        path = self.excel_box.currentData()
        if path and path != self.job.roster.path:
            self.load_folder(self.job.folder, excel=path)

    def _options_changed(self) -> None:
        if self._loading or self.job is None:
            return
        self.job.main_summary = self.main_summary.text().strip()
        self.job.pay_ym = self.pay_ym.text().strip()
        self.job.tab = self.tab_box.currentData() or person.TAB_STUDENT
        self._fill_table()
        self._sync()

    def _fill_table(self) -> None:
        job = self.job
        self._loading = True
        self.table.setRowCount(0)
        self._status = []
        if job is None:
            self._loading = False
            return
        self.table.setRowCount(len(job.people))
        for row, p in enumerate(job.people):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if job.selected[row] else Qt.Unchecked)
            self.table.setItem(row, COL_CHECK, check)
            files = job.files_for(row)
            values = {COL_NO: str(row + 1), COL_NAME: p.name, COL_STUDENT: p.student_no or "—", COL_AMOUNT: _money(p.amount) or "—",
                      COL_FILES: str(len(files)), COL_SUMMARY: job.row_summary(row)}
            for col, value in values.items():
                item = QTableWidgetItem(value)
                tip = value
                if col == COL_FILES:
                    tip = "\n".join(os.path.relpath(f, job.folder) for f in files) or "첨부 없음"
                elif p.note:
                    tip = f"{value}\n{p.note}"
                item.setToolTip(tip)
                if col in (COL_AMOUNT, COL_FILES, COL_NO):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, item)
            self._status.append("")
            self._set_status_quiet(row, "problem" if p.note else ("ready" if job.selected[row] else "skip"))
        self._loading = False
        problems = job.problems()
        self.problems.setText("\n".join("· " + p for p in problems))
        self.problems.setVisible(bool(problems))
        per = sum(len(v) for v in job.person_files.values())
        self.files_note.setText(f"공통증빙 {len(job.common_files)}개(모든 학생에게) · 개별증빙 {per}개 · "
                                f"넣을 사람 {len(job.chosen())}명 · 합계 {sum(job.people[i].amount or 0 for i in job.chosen()):,}원")

    def _set_status_quiet(self, row: int, status: str) -> None:
        self._status[row] = status
        text, tone = ROW_STATUS[status]
        item = QTableWidgetItem(text)
        item.setData(PillDelegate.ROLE, tone)
        self.table.setItem(row, COL_STATUS, item)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self.job is None or item.column() != COL_CHECK:
            return
        row = item.row()
        self.job.selected[row] = item.checkState() == Qt.Checked
        p = self.job.people[row]
        self._set_status(row, "problem" if p.note and self.job.selected[row] else ("ready" if self.job.selected[row] else "skip"))
        self._fill_table_footer()
        self._sync()

    def _fill_table_footer(self) -> None:
        job = self.job
        per = sum(len(v) for v in job.person_files.values())
        self.files_note.setText(f"공통증빙 {len(job.common_files)}개(모든 학생에게) · 개별증빙 {per}개 · "
                                f"넣을 사람 {len(job.chosen())}명 · 합계 {sum(job.people[i].amount or 0 for i in job.chosen()):,}원")

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if not self._running and any(os.path.isdir(u.toLocalFile()) for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if self.load_folder(url.toLocalFile()):
                event.acceptProposedAction()
                return

    def _open_rules(self) -> None:
        scholarship.load_rules()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.scholarship_rules_path())))

    # ── 넣기 ────────────────────────────────────────────────────────────
    def _run(self) -> None:
        job = self.job
        if job is None or self._running:
            return
        self._options_changed()
        dry = self.dry_run.isChecked()
        problems = job.problems()
        if not dry:
            hard = [p for p in problems if "대표적요" in p or "지급예정년월" in p or "합계" in p or "사람이 없" in p]
            if hard:
                QMessageBox.warning(self, "넣기 전에 고칠 것", "\n".join("· " + p for p in hard))
                return
            before = record.previous(job.folder)
            if before and QMessageBox.question(
                    self, "이미 넣은 폴더",
                    f"이 폴더는 {before.get('when')} 에 넣은 적이 있습니다 ({before.get('summary')}).\n\n다시 넣을까요?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        lines = "\n".join("· " + line for line in job.summary_lines())
        warn = ("\n\n확인: " + "\n  ".join(problems)) if problems else ""
        text = ("학생마다 무엇을 넣을지 보여 줍니다. ERP 에는 넣지 않습니다.\n\n" if dry else
                "브라우저의 작성 화면에 학생 한 명씩 넣고 [저장](임시저장) 합니다. 앱이 확신하지 못하는 단계에서는 멈추고 묻습니다.\n"
                "[신청] 은 누르지 않습니다.\n\n")
        if QMessageBox.question(self, "미리 보기" if dry else "ERP 에 넣기", text + lines + warn + "\n\n진행할까요?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        if not dry:
            self._running = True
            self.busy_changed.emit(True)
            self._set_state("넣는 중", "info", "브라우저를 건드리지 말고 기다리세요. 앱이 물으면 위의 노란 띠를 따르세요.")
        self.browser.fill_scholarship(job, dry_run=dry)
        self._sync()

    def _stop(self) -> None:
        self.browser.request_stop()
        self._set_state("멈추는 중", "warning", "지금 넣는 학생까지 마치고 멈춥니다.")

    def _answer(self, ok: bool) -> None:
        self.ask_banner.hide()
        self.browser.answer_relogin(ok)
        if ok:
            self._set_state("넣는 중", "info", "이어서 넣습니다.")

    def _on_ask(self, message: str) -> None:
        self.ask_text.setText(message)
        self.ask_banner.show()
        self._set_state("확인 필요", "warning", "위의 노란 띠를 따른 뒤 [계속] 을 누르세요.")
        self.window().raise_()
        self.window().activateWindow()

    def _on_person(self, index: int, status: str, note: str) -> None:
        self._set_status(index, status if status in ROW_STATUS else "running")
        if note:
            item = self.table.item(index, COL_STATUS)
            if item is not None:
                item.setToolTip(note)
        if status == "running":
            self.table.scrollToItem(self.table.item(index, COL_NAME))

    def _on_done(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        self.ask_banner.hide()
        was_running = self._running
        self._running = False
        if was_running:
            self.busy_changed.emit(False)
        if report.dry_run:
            for r in report.results:
                self._set_status(r.index, "planned")
            self._set_state("미리 봄", "info", "미리 보기 결과는 [진행 기록] 에 있습니다. 실제로 넣으려면 '미리 보기만' 체크를 풀고 다시 누르세요.")
            QMessageBox.information(self, "미리 보기", text if len(text) < 3000 else text[:3000] + "\n…(나머지는 [진행 기록])")
        elif report.blocked:
            self._set_state("화면 없음", "warning", report.blocked)
            QMessageBox.warning(self, "넣지 못했습니다", report.blocked)
        else:
            if report.saved and self.job is not None:
                scholarship.record_job(self.job, report)
            if report.stopped:
                self._set_state("멈춤", "warning", f"{report.saved}명까지 임시저장했습니다. 남은 학생은 표에서 끝난 사람의 체크를 풀고 다시 누르세요.")
            else:
                self._set_state("임시저장", "success", f"{report.saved}명을 임시저장했습니다. ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요.")
            for r in report.results:
                if r.status == "saved" and self.job is not None:
                    self.job.selected[r.index] = False          # 다시 누르면 남은 사람만 — 두 번 넣지 않게
            self._loading = True
            for r in report.results:
                if r.status == "saved":
                    item = self.table.item(r.index, COL_CHECK)
                    if item is not None:
                        item.setCheckState(Qt.Unchecked)
            self._loading = False
            QMessageBox.information(self, "장학금 청구", "\n".join(report.lines()[:40]))
        self._sync()

    # ── 브라우저 · 기록 ──────────────────────────────────────────────────
    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _on_browser_busy(self, busy: bool, _message: str) -> None:
        self._browser_busy = busy
        self._sync()

    def _on_browser_opened(self) -> None:
        self._browser_open = True
        self._sync()

    def _on_browser_state(self, alive: bool) -> None:
        self._browser_open = alive
        self._sync()

    def _on_error(self, message: str) -> None:
        if not self._running:
            return            # 다른 화면(받기·일반청구)의 오류 — 그 화면이 알린다
        self._running = False
        self.ask_banner.hide()
        self.busy_changed.emit(False)
        self._set_state("오류", "danger")
        self._sync()
        QMessageBox.warning(self, "문제가 생겼습니다", f"{message}\n\n자세한 내용은 [진행 기록] 탭과 로그 파일에 있습니다.")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.page_desc.setVisible(self.height() >= 600)

    def shutdown(self) -> None:
        if self._running:
            self.browser.request_stop()
        if self._owns_browser:
            self.browser.shutdown()
