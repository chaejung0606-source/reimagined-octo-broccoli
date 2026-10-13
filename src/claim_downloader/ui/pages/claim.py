"""일반청구 화면 — 지출 폴더를 넣고 [내용 읽기] → 값을 고치고 → [ERP 에 채우기] → 사람이 입금처·첨부 → [임시저장] → 사람이 검토·신청.

    AI 플랫폼 고르기 → 지출 폴더 추가(끌어다 놓기 · 버튼) → 내용 읽기(AI) → 오른쪽 칸에서 값 확인·수정
    → 브라우저에 일반청구 작성 화면을 띄움 → [ERP 에 채우기] → ERP 에서 사람이 입금처·첨부 → [임시저장]
    → ERP 에서 사람이 검토하고 [신청]

담당자 결정(2026-10-13): 내역 작성 후 임시저장까지 앱이, 그 뒤는 사람이. 기본은 '미리 보기만'(dry-run) — 체크를
풀어야 실제로 넣는다. 신청·삭제·초기화는 코드가 절대 누르지 않는다(claims/form.py). 같은 폴더를 두 번 채우려
하면 묻는다(claims/record.py).

브라우저는 청구서 받기와 같은 스레드(app.session_worker)를 쓴다 — ERP 로그인은 한 번이면 된다.
"""
from __future__ import annotations

import os

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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import settings
from ...claims import extract, record, rules, schema
from ...minutes.backends import claude_cli
from ..art import Art
from ..claim_worker import ClaimExtractWorker
from ..widgets import Card, ElideLabel, EmptyState, Field, Pill, PillDelegate, WrapLabel, muted_label
from ..worker import SessionWorker

COLUMNS = [("상태", 96), ("지출 (폴더)", 260), ("적요", 300), ("청구액", 110), ("입금처", None)]
COL_STATUS, COL_DIR, COL_SUMMARY, COL_AMOUNT, COL_PAYEE = 0, 1, 2, 3, 4

ROW_STATUS = {
    "waiting": ("대기", "neutral"),
    "running": ("읽는 중", "info"),
    "read": ("읽음", "success"),
    "failed": ("실패", "danger"),
    "skipped": ("건너뜀", "warning"),
    "stopped": ("안 함", "neutral"),
    "filled": ("채움", "success"),
    "saved": ("임시저장", "success"),
}

GUIDE_START = "지출 폴더를 추가하고 [내용 읽기] 를 누르세요. 읽은 값은 오른쪽에서 고칠 수 있습니다."
GUIDE_READ = "값을 확인한 뒤, 브라우저에서 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우고 [ERP 에 채우기] 를 누르세요."
NO_BACKEND = ("이 기능은 Claude Code 가 필요합니다. Claude Code 를 설치하고 로그인한 뒤 [다시 확인] 을 누르세요. "
              "설치했는데도 이 안내가 보이면 컴퓨터를 다시 시작해 보세요.")


def _money(value) -> str:
    return f"{value:,}" if isinstance(value, int) else ""


class ClaimPage(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAcceptDrops(True)
        self.extractor = ClaimExtractWorker()
        self.browser = worker if worker is not None else SessionWorker()
        self._owns_browser = worker is None
        self._dirs: list[str] = []
        self._status: list[str] = []
        self._data: list[dict] = []
        self._problems: list[list[str]] = []
        self._running = False
        self._browser_busy = False
        self._browser_open = False
        self._available: bool | None = None
        self._backend_state = ""
        self._done_count = 0
        self._current = -1
        self._loading_form = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 26)
        layout.setSpacing(12)
        layout.addLayout(self._build_head())
        layout.addLayout(self._build_backend_row())
        layout.addWidget(self._build_banner())
        layout.addWidget(self._build_drop_zone())
        layout.addLayout(self._build_middle(), 1)
        layout.addLayout(self._build_bottom_row())

        e = self.extractor
        e.log.connect(self._append_log)
        e.busy.connect(self._on_extract_busy)
        e.checked.connect(self._on_checked)
        e.started.connect(self._on_started)
        e.done.connect(self._on_done)
        e.skipped.connect(self._on_skipped)
        e.stopped.connect(self._on_stopped)
        e.finished.connect(self._on_finished)
        e.error.connect(self._on_error)
        b = self.browser
        b.log.connect(self._append_log)
        b.busy.connect(self._on_browser_busy)
        b.browser_opened.connect(self._on_browser_opened)
        b.browser_state.connect(self._on_browser_state)
        b.claim_filled.connect(self._on_claim_filled)
        b.claim_saved.connect(self._on_claim_saved)
        b.payee_searched.connect(self._on_payee_searched)
        b.taxbill_searched.connect(self._on_taxbill_searched)
        b.error.connect(self._on_error)

        self._sync_buttons()
        self._show_form(-1)
        self._check_backend()

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("claim", 44), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("일반청구")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        self.page_desc = muted_label(
            "지출 자료 폴더에서 값을 뽑아 ERP 일반청구 작성 화면에 채웁니다. 입금처·첨부·저장·신청은 직접 합니다. "
            "자료는 선택한 AI 플랫폼으로 전송됩니다.")
        texts.addWidget(self.page_desc)
        head.addLayout(texts, 1)
        rules_button = QPushButton("규칙 파일 열기")
        rules_button.setObjectName("ghost")
        rules_button.setToolTip("폴더에서 무엇을 어떻게 뽑을지 적은 규칙. 저장만 하면 다음 읽기부터 반영됩니다.")
        rules_button.clicked.connect(self._open_rules)
        head.addWidget(rules_button, 0, Qt.AlignVCenter)
        return head

    def _build_backend_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel("AI 플랫폼")
        label.setObjectName("fieldLabel")
        row.addWidget(label)
        self.backend_box = QComboBox()
        self.backend_box.setMinimumWidth(300)
        current = settings.load().minutes_backend
        for key, text in extract.labels():
            self.backend_box.addItem(text, key)
        index = self.backend_box.findData(current)
        self.backend_box.setCurrentIndex(index if index >= 0 else 0)
        self.backend_box.currentIndexChanged.connect(lambda _i: self._check_backend())
        label.setBuddy(self.backend_box)
        row.addWidget(self.backend_box)
        self.backend_pill = Pill("확인 중", "neutral")
        row.addWidget(self.backend_pill, 0, Qt.AlignVCenter)
        self.backend_note = ElideLabel("")
        self.backend_note.setObjectName("muted")
        row.addWidget(self.backend_note, 1)
        self.recheck_button = QPushButton("다시 확인")
        self.recheck_button.setObjectName("ghost")
        self.recheck_button.clicked.connect(self._check_backend)
        row.addWidget(self.recheck_button)
        return row

    def _build_banner(self) -> QFrame:
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(16, 10, 16, 10)
        banner_layout.setSpacing(10)
        banner_layout.addWidget(Pill("확인 필요", "warning"), 0, Qt.AlignTop)
        self.banner_text = WrapLabel(NO_BACKEND)
        self.banner_text.setObjectName("bannerText")
        banner_layout.addWidget(self.banner_text, 1)
        self.banner.hide()
        return self.banner

    def _build_drop_zone(self) -> QFrame:
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setFixedHeight(76)
        row = QHBoxLayout(self.drop_zone)
        row.setContentsMargins(18, 10, 14, 10)
        row.setSpacing(12)
        row.addWidget(Art("archive", 44), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        hint = QLabel("여기에 지출 폴더를 끌어다 놓으세요")
        hint.setObjectName("cardTitle")
        texts.addWidget(hint)
        texts.addWidget(muted_label("폴더 1개 = 청구 1건 (지출품의서 · 세금계산서 · 통장사본 등). 상위 폴더를 넣으면 하위 폴더마다 1건."))
        row.addLayout(texts, 1)
        self.add_one_button = QPushButton("지출 폴더 추가")
        self.add_one_button.clicked.connect(self._add_one)
        self.add_parent_button = QPushButton("상위 폴더 추가")
        self.add_parent_button.clicked.connect(self._add_parent)
        self.clear_button = QPushButton("목록 비우기")
        self.clear_button.setObjectName("ghost")
        self.clear_button.clicked.connect(self._clear)
        for button in (self.add_one_button, self.add_parent_button, self.clear_button):
            row.addWidget(button, 0, Qt.AlignVCenter)
        return self.drop_zone

    def _build_middle(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._build_list_card(), 3)
        row.addWidget(self._build_form_card(), 2)
        return row

    def _build_list_card(self) -> QWidget:
        card = Card(margins=(16, 8, 16, 12))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.list_stack = QStackedWidget()
        self.empty = EmptyState("claim", "지출 폴더를 추가하면 여기에 나옵니다",
                                "폴더를 끌어다 놓거나 [지출 폴더 추가] 를 누르세요. 한 줄을 고르면 오른쪽에 값이 보입니다.")
        self.list_stack.addWidget(self.empty)
        self.list_stack.addWidget(self._build_table())
        self.tabs.addTab(self.list_stack, "지출 목록")
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

    def _build_table(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 10, 0, 0)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([name for name, _ in COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setSortingEnabled(False)
        self.table.setItemDelegateForColumn(COL_STATUS, PillDelegate(self.table))
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setStretchLastSection(True)
        head.setHighlightSections(False)
        for col, (_, width) in enumerate(COLUMNS):
            head.setSectionResizeMode(col, QHeaderView.Interactive)
            if width:
                self.table.setColumnWidth(col, width)
        layout.addWidget(self.table)
        return holder

    def _build_form_card(self) -> QWidget:
        card = Card("청구 내용", "읽은 값입니다. 틀린 곳은 여기서 고치세요 — ERP 에는 이 값이 들어갑니다.",
                    margins=(16, 14, 16, 12))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("pageBody")
        scroll.setWidget(body)
        form = QVBoxLayout(body)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(10)
        self.inputs: dict[str, QWidget] = {}

        def line(key: str, label: str, help_text: str = "", placeholder: str = "") -> None:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.editingFinished.connect(lambda k=key: self._form_changed(k))
            self.inputs[key] = edit
            form.addWidget(Field(label, edit, help_text))

        def combo(key: str, label: str, options, help_text: str = "") -> None:
            box = QComboBox()
            box.addItem("")
            for option in options:
                box.addItem(option)
            box.currentIndexChanged.connect(lambda _i, k=key: self._form_changed(k))
            self.inputs[key] = box
            form.addWidget(Field(label, box, help_text))

        line("summary", "적요", "ERP 적요 칸. 'NN_내용' 형식", "예: 09_2026년 사업단 정수기 임차료(9월)")
        combo("expCategory", "비목", schema.EXP_CATEGORIES)
        line("expDetail", "세목", "비목을 고르면 ERP 에 보기가 뜹니다. 그 이름을 적으세요")
        combo("evidence", "증빙구분", schema.EVIDENCE_KINDS)
        line("expenseDate", "지출일자", "세금계산서 작성일", "YYYY-MM-DD")
        combo("settleMethod", "결제방법", schema.SETTLE_METHODS)
        amounts = QHBoxLayout()
        amounts.setSpacing(8)
        for key, label in (("amount", "청구액"), ("supplyAmount", "공급가액"), ("taxAmount", "부가세")):
            edit = QLineEdit()
            edit.setPlaceholderText("숫자만")
            edit.editingFinished.connect(lambda k=key: self._form_changed(k))
            self.inputs[key] = edit
            amounts.addWidget(Field(label, edit))
        form.addLayout(amounts)
        line("payeeName", "입금처", "ERP 의 입금처 돋보기에서 이 이름으로 찾으세요 (아직 사람이 고릅니다)")
        line("payeeBizNo", "사업자등록번호", "", "000-00-00000")
        line("bank", "은행", "ERP 보기의 은행 이름 (예: 국민은행)")
        line("accountNo", "계좌번호")
        line("owner", "예금주")
        self.attachments_label = muted_label("")
        form.addWidget(Field("첨부 후보", self.attachments_label, "폴더 안 파일 — ERP 의 '첨부' 로 직접 올립니다"))
        self.notes_label = WrapLabel("")
        self.notes_label.setObjectName("body")
        form.addWidget(Field("확인 사항", self.notes_label))
        self.problems_label = WrapLabel("")
        self.problems_label.setObjectName("fieldError")
        form.addWidget(self.problems_label)
        form.addStretch(1)
        card.add(scroll, 1)
        self.form_card = card
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
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(160, 8)
        self.progress.setRange(0, 1)
        row.addWidget(self.progress, 0, Qt.AlignVCenter)
        self.progress_label = QLabel("0 / 0")
        self.progress_label.setObjectName("muted")
        row.addWidget(self.progress_label, 0, Qt.AlignVCenter)
        self.stop_button = QPushButton("멈추기")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self._stop)
        row.addWidget(self.stop_button)
        self.read_button = QPushButton("내용 읽기")
        self.read_button.clicked.connect(self._read_all)
        row.addWidget(self.read_button)
        self.open_button = QPushButton("브라우저 열기")
        self.open_button.setToolTip("앱이 연 브라우저에서 ERP 로그인 → 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우세요")
        self.open_button.clicked.connect(lambda: self.browser.open_browser(scan=False))
        row.addWidget(self.open_button)
        self.dry_run = QCheckBox("미리 보기만")
        self.dry_run.setChecked(True)
        self.dry_run.setToolTip("체크돼 있으면 ERP 에 넣지 않고 무엇을 넣을지만 보여 줍니다. 풀면 실제로 채웁니다 (저장·신청은 그래도 직접).")
        self.dry_run.toggled.connect(lambda _c: self._sync_buttons())
        row.addWidget(self.dry_run)
        self.fill_button = QPushButton("ERP 에 채우기")
        self.fill_button.setObjectName("primary")
        self.fill_button.clicked.connect(self._fill)
        row.addWidget(self.fill_button)
        # 채운 뒤 팝업을 닫아 버렸을 때 — 증빙 [선택] 팝업을 다시 열어 사업자번호로 조회해 둔다(고르기는 사람)
        self.taxbill_button = QPushButton("세금계산서 찾기")
        self.taxbill_button.setToolTip("증빙 [선택] 팝업을 열어 거래처 사업자번호로 조회해 둡니다. 계산서를 고르고 [확인] 은 직접 누르세요.")
        self.taxbill_button.clicked.connect(self._search_taxbill)
        row.addWidget(self.taxbill_button)
        # 채운 뒤 입금처 팝업을 닫아 버렸을 때 — 돋보기를 다시 눌러 거래처를 검색해 둔다(고르기는 사람)
        self.payee_button = QPushButton("입금처 찾기")
        self.payee_button.setToolTip("입금처 돋보기 팝업을 열어 거래처 이름으로 검색해 둡니다. 목록에서 고르고 [확인] 은 직접 누르세요.")
        self.payee_button.clicked.connect(self._search_payee)
        row.addWidget(self.payee_button)
        # 채운 뒤 사람이 입금처·첨부를 넣으면 — 앱이 ERP 의 [저장](임시저장)을 누른다. [신청] 은 끝까지 사람.
        self.save_button = QPushButton("임시저장")
        self.save_button.setObjectName("primary")
        self.save_button.setToolTip("ERP 의 [저장] 을 눌러 임시저장합니다. [신청] 은 검토 후 직접 누르세요.")
        self.save_button.clicked.connect(self._save_draft)
        row.addWidget(self.save_button)
        return row

    # ── 상태 ────────────────────────────────────────────────────────────
    def _backend_key(self) -> str:
        return self.backend_box.currentData() or extract.DEFAULT_KEY

    def _sync_buttons(self) -> None:
        running = self._running
        can_edit = not running
        for widget in (self.add_one_button, self.add_parent_button, self.backend_box, self.recheck_button):
            widget.setEnabled(can_edit)
        self.clear_button.setEnabled(can_edit and bool(self._dirs))
        unread = [i for i, s in enumerate(self._status) if s in ("waiting", "failed", "skipped", "stopped")]
        self.read_button.setEnabled(can_edit and bool(unread) and self._available is True)
        self.read_button.setText("읽는 중…" if running else f"{len(unread)}건 내용 읽기" if unread else "내용 읽기")
        self.stop_button.setVisible(running)
        self.open_button.setVisible(not self._browser_open)
        self.open_button.setEnabled(not self._browser_busy)
        has_row = 0 <= self._current < len(self._dirs) and self._status[self._current] in ("read", "filled", "saved")
        self.fill_button.setEnabled(has_row and self._browser_open and not self._browser_busy and not running)
        self.fill_button.setText("미리 보기" if self.dry_run.isChecked() else "ERP 에 채우기")
        filled = 0 <= self._current < len(self._dirs) and self._status[self._current] in ("filled", "saved")
        self.save_button.setVisible(filled)
        self.save_button.setEnabled(filled and self._browser_open and not self._browser_busy and not running)
        self.payee_button.setVisible(filled)
        self.payee_button.setEnabled(filled and self._browser_open and not self._browser_busy and not running)
        from ...claims import taxbill
        is_taxbill = filled and taxbill.wanted(self._data[self._current])
        self.taxbill_button.setVisible(is_taxbill)
        self.taxbill_button.setEnabled(is_taxbill and self._browser_open and not self._browser_busy and not running)
        self.tabs.setTabText(0, f"지출 목록 ({len(self._dirs)})" if self._dirs else "지출 목록")
        self.list_stack.setCurrentIndex(1 if self._dirs else 0)

    def _set_state(self, text: str, status: str, guide: str | None = None) -> None:
        self.state_pill.set_status(text, status)
        if guide is not None:
            self.guide.setText(guide)

    def _set_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.progress_label.setText(f"{done} / {total}")

    def _set_status(self, row: int, status: str) -> None:
        if row >= len(self._status):
            return
        self._status[row] = status
        text, tone = ROW_STATUS[status]
        item = QTableWidgetItem(text)
        item.setData(PillDelegate.ROLE, tone)
        self.table.setItem(row, COL_STATUS, item)

    def _refresh_row(self, row: int) -> None:
        data = self._data[row]
        for col, value in ((COL_SUMMARY, data.get("summary", "")), (COL_AMOUNT, _money(data.get("amount"))),
                           (COL_PAYEE, data.get("payeeName", ""))):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            if col == COL_AMOUNT:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, col, item)

    def is_running(self) -> bool:
        return self._running

    def resumable(self) -> tuple[bool, str]:
        if self._running:
            remaining = sum(1 for s in self._status if s in ("waiting", "running"))
            return True, f"읽는 중 · 남은 {remaining}건"
        return False, ""

    # ── 폴더 목록 ────────────────────────────────────────────────────────
    def add_folder(self, path: str) -> bool:
        path = os.path.abspath(path)
        if not os.path.isdir(path) or path in self._dirs or self._running:
            return False
        self._dirs.append(path)
        self._status.append("waiting")
        self._data.append(schema.normalize({}))
        self._problems.append([])
        row = self.table.rowCount()
        self.table.setRowCount(row + 1)
        name = QTableWidgetItem(f"{os.path.basename(path)}  ·  {os.path.dirname(path)}")
        name.setToolTip(path)
        self.table.setItem(row, COL_DIR, name)
        self._set_status(row, "waiting")
        self._refresh_row(row)
        self._set_progress(self._done_count, len(self._dirs))
        if self._current < 0:
            self.table.selectRow(row)
        self._sync_buttons()
        return True

    def _add_one(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "지출 자료가 들어 있는 폴더 선택")
        if path:
            self.add_folder(path)

    def _add_parent(self) -> None:
        parent = QFileDialog.getExistingDirectory(self, "여러 지출 폴더가 들어 있는 '상위' 폴더 선택")
        if not parent:
            return
        subs = [os.path.join(parent, x) for x in sorted(os.listdir(parent)) if os.path.isdir(os.path.join(parent, x))]
        if not subs:
            QMessageBox.information(self, "안내", "선택한 폴더 안에 하위 폴더가 없습니다.")
            return
        for sub in subs:
            self.add_folder(sub)

    def _clear(self) -> None:
        if self._running:
            return
        self._dirs, self._status, self._data, self._problems = [], [], [], []
        self._current = -1
        self._done_count = 0
        self.table.setRowCount(0)
        self._set_progress(0, 0)
        self._set_state("준비", "neutral", GUIDE_START)
        self._show_form(-1)
        self._sync_buttons()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if not self._running and any(os.path.isdir(u.toLocalFile()) for u in event.mimeData().urls()):
            event.acceptProposedAction()
            self._set_drop_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drop_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drop_active(False)
        if sum(1 for u in event.mimeData().urls() if self.add_folder(u.toLocalFile())):
            event.acceptProposedAction()

    def _set_drop_active(self, on: bool) -> None:
        self.drop_zone.setProperty("active", on)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    # ── 오른쪽 칸 ───────────────────────────────────────────────────────
    def _on_row_selected(self) -> None:
        rows = {item.row() for item in self.table.selectedItems()}
        self._current = min(rows) if rows else -1
        self._show_form(self._current)
        self._sync_buttons()

    def _show_form(self, row: int) -> None:
        self._loading_form = True
        data = self._data[row] if 0 <= row < len(self._data) else schema.normalize({})
        for key, widget in self.inputs.items():
            value = data.get(key)
            text = "" if value is None else str(value)
            if isinstance(widget, QComboBox):
                index = widget.findText(text)
                widget.setCurrentIndex(index if index >= 0 else 0)
                if index < 0 and text:
                    widget.setItemText(0, text)      # 보기에 없는 값은 그대로 보여 사람이 고치게
            else:
                widget.setText(text)
        self.attachments_label.setText(" · ".join(data.get("attachments") or []) or "—")
        self.notes_label.setText(data.get("notes") or "—")
        self._loading_form = False
        self.form_card.setEnabled(0 <= row < len(self._data))
        self._show_problems(row)

    def _show_problems(self, row: int) -> None:
        found = self._problems[row] if 0 <= row < len(self._problems) else []
        self.problems_label.setText(("확인: " + " · ".join(found)) if found else "")
        self.problems_label.setVisible(bool(found))

    def _form_changed(self, key: str) -> None:
        if self._loading_form or not (0 <= self._current < len(self._data)):
            return
        widget = self.inputs[key]
        text = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
        raw = dict(self._data[self._current])
        raw[key] = text
        self._data[self._current] = schema.normalize(raw)
        self._problems[self._current] = schema.problems(self._data[self._current])
        self._refresh_row(self._current)
        self._show_problems(self._current)
        self._sync_buttons()

    # ── AI 플랫폼 ───────────────────────────────────────────────────────
    def _check_backend(self) -> None:
        self._available = None
        self.backend_pill.set_status("확인 중", "neutral")
        self.backend_note.setText("")
        self._sync_buttons()
        self.extractor.check(self._backend_key())

    def _on_checked(self, key: str, ok: bool, note: str, state: str) -> None:
        if key != self._backend_key():
            return
        self._available = ok
        self._backend_state = state
        self.backend_note.setText(note.replace("\n", " "))
        if not ok:
            self.backend_pill.set_status("사용 불가", "danger")
            self.banner_text.setText(NO_BACKEND if key == claude_cli.ClaudeCliBackend.key else note)
            self.banner.show()
        else:
            self.banner.hide()
            self.backend_pill.set_status("로그인 확인" if state == "no_login" else "사용 가능",
                                         "warning" if state == "no_login" else "success")
        self._sync_buttons()

    def _open_rules(self) -> None:
        rules.load_rules()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.claims_rules_path())))

    # ── 읽기 ────────────────────────────────────────────────────────────
    def _read_all(self) -> None:
        if self._running or self._available is not True:
            return
        rows = [i for i, s in enumerate(self._status) if s in ("waiting", "failed", "skipped", "stopped")]
        if not rows:
            return
        if self._backend_state == "no_login":
            if QMessageBox.question(self, "로그인 확인", claude_cli.LOGIN_HELP,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        if QMessageBox.question(
                self, "내용 읽기",
                f"지출 {len(rows)}건의 자료가 '{self.backend_box.currentText()}' 로 전송되어 값을 뽑습니다.\n"
                "ERP 에는 아직 아무것도 넣지 않습니다.\n\n시작할까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        self._running = True
        self._pending_rows = rows
        self._done_count = 0
        for row in rows:
            self._set_status(row, "waiting")
        self._set_progress(0, len(rows))
        self._set_state("읽는 중", "info", "폴더 하나에 수십 초에서 몇 분이 걸립니다. 다른 탭으로 가도 작업은 이어집니다.")
        self._sync_buttons()
        self.busy_changed.emit(True)
        self.extractor.run([self._dirs[i] for i in rows], self._backend_key())

    def _stop(self) -> None:
        self.extractor.request_stop()
        self.stop_button.setEnabled(False)
        self._set_state("멈추는 중", "warning", "지금 읽는 폴더를 마치면 멈춥니다…")

    def _row_of(self, index: int) -> int:
        return self._pending_rows[index] if index < len(self._pending_rows) else -1

    def _on_started(self, index: int) -> None:
        row = self._row_of(index)
        if row >= 0:
            self._set_status(row, "running")
            self.table.scrollToItem(self.table.item(row, COL_STATUS))

    def _advance(self) -> None:
        self._done_count += 1
        self._set_progress(self._done_count, len(self._pending_rows))

    def _on_done(self, index: int, result) -> None:
        row = self._row_of(index)
        if row < 0:
            return
        if result.ok:
            self._data[row] = result.data
            self._problems[row] = list(result.problems)
            self._set_status(row, "read")
            self._refresh_row(row)
            if row == self._current:
                self._show_form(row)
        else:
            self._set_status(row, "failed")
            cell = QTableWidgetItem("⚠ " + result.info)
            cell.setToolTip(result.info)
            self.table.setItem(row, COL_SUMMARY, cell)
        self._advance()

    def _on_skipped(self, index: int, _kind: str) -> None:
        row = self._row_of(index)
        if row >= 0:
            self._set_status(row, "skipped")
            self.table.setItem(row, COL_SUMMARY, QTableWidgetItem("⚠ 앞의 오류로 건너뜀"))
        self._advance()

    def _on_stopped(self, index: int) -> None:
        row = self._row_of(index)
        if row >= 0:
            self._set_status(row, "stopped")
        self._advance()

    def _on_finished(self, stop: str, ok_count: int, fail_count: int) -> None:
        self._running = False
        self._sync_buttons()
        self.busy_changed.emit(False)
        summary = f"읽음 {ok_count}건 · 실패 {fail_count}건"
        if stop == "login":
            self._set_state("로그인 필요", "danger", summary + " — Claude 로그인이 풀려 남은 폴더를 건너뛰었습니다. 회의록 화면의 [Claude 로그인] 뒤 다시 읽으세요.")
        elif stop == "limit":
            self._set_state("한도 초과", "danger", summary + " — 한도가 풀린 뒤 [내용 읽기] 를 다시 누르세요.")
        elif stop == "balance":
            self._set_state("잔액 부족", "danger", summary + " — 결제 상태를 확인한 뒤 다시 읽으세요.")
        elif fail_count:
            self._set_state("일부 실패", "danger", summary + ". 실패한 건은 표의 사유를 확인하세요.")
        else:
            self._set_state("읽음", "success", summary + ". " + GUIDE_READ)

    # ── ERP 에 채우기 ────────────────────────────────────────────────────
    def _fill(self) -> None:
        row = self._current
        if not (0 <= row < len(self._data)) or not self._browser_open or self._browser_busy:
            return
        data = self._data[row]
        found = schema.problems(data)
        missing = [f for f in found if f.endswith("없음") and "계좌번호" not in f]
        if missing:
            QMessageBox.warning(self, "값이 모자랍니다", "오른쪽 칸을 채운 뒤 다시 누르세요.\n\n· " + "\n· ".join(missing))
            return
        dry_run = self.dry_run.isChecked()
        if not dry_run:
            before = record.previous(self._dirs[row])
            if before and QMessageBox.question(
                    self, "이미 채운 폴더",
                    f"이 폴더는 {before.get('when')} 에 이미 채웠습니다 (적요 '{before.get('summary')}', "
                    f"청구액 {_money(before.get('amount')) or '—'}).\n\n다시 채울까요?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        lines = "\n".join("· " + line for line in schema.summary_lines(data))
        warn = ("\n\n확인: " + " · ".join(found)) if found else ""
        answer = QMessageBox.question(
            self, "미리 보기" if dry_run else "ERP 에 채우기",
            (("무엇을 넣을지 확인만 합니다. ERP 에는 넣지 않습니다.\n\n" if dry_run
              else "브라우저의 일반청구 작성 화면에 아래 값을 넣습니다. 입금처·첨부·저장·신청은 직접 합니다.\n\n")
             + lines + warn + "\n\n진행할까요?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        self._fill_row = row
        self.browser.fill_claim(dict(data), dry_run)

    def _on_claim_filled(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        row = getattr(self, "_fill_row", -1)
        if report.blocked:
            self._set_state("화면 없음", "warning", report.blocked)
            QMessageBox.warning(self, "채우지 못했습니다", report.blocked)
            return
        if report.dry_run:
            QMessageBox.information(self, "미리 보기", text + "\n\n실제로 넣으려면 '미리 보기만' 체크를 풀고 다시 누르세요.")
            return
        if 0 <= row < len(self._dirs) and report.ok:
            record.remember(self._dirs[row], self._data[row])
            self._set_status(row, "filled")
            payee_ok = report.payee is not None and report.payee.ok
            taxbill_ok = report.taxbill is not None and report.taxbill.ok
            if payee_ok:
                guide = "입금처 팝업에서 거래처를 고르고 [확인] 을 누른 뒤, 첨부를 넣고 앱의 [임시저장] 을 누르세요."
            elif taxbill_ok:
                guide = "세금계산서 팝업에서 계산서를 고르고 [확인] 을 누른 뒤 [입금처 찾기] 를 누르세요."
            else:
                guide = "ERP 화면에서 입금처(돋보기)·첨부를 넣고 값을 확인한 뒤 앱의 [임시저장] 을 누르세요."
            self._set_state("채움", "success", guide)
        else:
            if 0 <= row < len(self._dirs):
                self._set_status(row, "filled")
            self._set_state("일부 못 채움", "warning", "채우지 못한 칸은 ERP 에서 직접 넣은 뒤 [임시저장] 을 누르세요. 자세한 내용은 [진행 기록].")
        QMessageBox.information(self, "ERP 에 채움", text)
        self._sync_buttons()

    def _save_draft(self) -> None:
        row = self._current
        if not (0 <= row < len(self._dirs)) or not self._browser_open or self._browser_busy:
            return
        answer = QMessageBox.question(
            self, "임시저장",
            "ERP 화면에 입금처·첨부를 넣으셨나요?\n\n앱이 ERP 의 [저장] 을 눌러 임시저장합니다. "
            "[신청] 은 누르지 않습니다 — 검토한 뒤 직접 누르세요.\n\n진행할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        self._save_row = row
        self.browser.save_claim_draft()

    def _search_payee(self) -> None:
        row = self._current
        if not (0 <= row < len(self._dirs)) or not self._browser_open or self._browser_busy:
            return
        from ...claims import payee
        query = payee.query_for(self._data[row])
        if not query:
            QMessageBox.warning(self, "입금처 찾기", "오른쪽 칸의 입금처(거래처 이름)가 비어 있습니다.")
            return
        self.browser.search_payee(dict(self._data[row]))

    def _search_taxbill(self) -> None:
        row = self._current
        if not (0 <= row < len(self._dirs)) or not self._browser_open or self._browser_busy:
            return
        from ...claims import taxbill
        if not taxbill.query_for(self._data[row]):
            QMessageBox.warning(self, "세금계산서 찾기", "오른쪽 칸의 사업자등록번호(또는 입금처 이름)가 비어 있습니다.")
            return
        self.browser.search_taxbill(dict(self._data[row]))

    def _on_taxbill_searched(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        if report.ok:
            self._set_state("세금계산서 조회", "success", "팝업 목록에서 계산서를 고르고 [확인] 을 누른 뒤 [입금처 찾기] 를 누르세요.")
            QMessageBox.information(self, "세금계산서 찾기", text)
        else:
            self._set_state("세금계산서 못 찾음", "warning", report.note or "증빙 [선택] 을 직접 눌러 골라 주세요.")
            QMessageBox.warning(self, "세금계산서 찾기", text)
        self._sync_buttons()

    def _on_payee_searched(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        if report.ok:
            self._set_state("입금처 검색", "success", "팝업 목록에서 거래처를 고르고 [확인] 을 누른 뒤 [임시저장] 을 누르세요.")
            QMessageBox.information(self, "입금처 찾기", text)
        else:
            self._set_state("입금처 못 찾음", "warning", report.note or "돋보기를 직접 눌러 입금처를 골라 주세요.")
            QMessageBox.warning(self, "입금처 찾기", text)
        self._sync_buttons()

    def _on_claim_saved(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        row = getattr(self, "_save_row", -1)
        if report.ok:
            if 0 <= row < len(self._dirs):
                self._set_status(row, "saved")
            self._set_state("임시저장", "success", "ERP 에서 임시저장된 청구서를 검토한 뒤 [신청] 을 직접 누르세요.")
            QMessageBox.information(self, "임시저장", text)
        else:
            self._set_state("임시저장 안 됨", "warning", report.note or "ERP 알림을 확인하세요.")
            QMessageBox.warning(self, "임시저장 안 됨", text)
        self._sync_buttons()

    # ── 신호 ────────────────────────────────────────────────────────────
    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _on_extract_busy(self, busy: bool, message: str) -> None:
        if message:
            self.window().statusBar().showMessage(message)
        elif not busy:
            self.window().statusBar().clearMessage()

    def _on_browser_busy(self, busy: bool, _message: str) -> None:
        self._browser_busy = busy
        self._sync_buttons()

    def _on_browser_opened(self) -> None:
        self._browser_open = True
        self._sync_buttons()

    def _on_browser_state(self, alive: bool) -> None:
        self._browser_open = alive
        self._sync_buttons()

    def _on_error(self, message: str) -> None:
        self._running = False
        self._sync_buttons()
        self.busy_changed.emit(False)
        self._set_state("오류", "danger")
        QMessageBox.warning(self, "문제가 생겼습니다", f"{message}\n\n자세한 내용은 [진행 기록] 탭과 로그 파일에 있습니다.")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.page_desc.setVisible(self.height() >= 600)

    def shutdown(self) -> None:
        self.extractor.shutdown()
        if self._owns_browser:
            self.browser.shutdown()
