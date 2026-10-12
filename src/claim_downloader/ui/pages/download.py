"""청구서 받기 화면 — 요약 → 단계 → 받을 목록 · 진행 기록.

    ① ERP 열기 → [사람: 로그인 · 결의서내역 목록 띄우기]
    → ② 목록 읽기 → 대상 확인 → ③ 받기

로그인과 '받을까요?' 확인은 언제나 사람이 한다. 이 화면은 그 차례가 왔을 때
무엇을 해야 하는지 알려 주고 기다린다.

높이 배분: 요약 카드와 단계 띠는 낮게 고정하고, 남는 높이는 전부 받을 목록 표가 쓴다.
화면 전체를 스크롤하지 않는다 — 표가 스스로 스크롤하고 머리글은 고정된다.

건수의 뜻(모두 같은 목록을 기준으로 센다):
  목록 대상   = 승인 + 문서번호 + 지출예정일 조건을 만족한 행 전부 (받을 건 + 보관으로 제외한 건)
  보관 제외   = 그중 문서번호가 받은 기록·보관 폴더에 이미 있는 건
  이번 완료   = 이번 실행에서 저장에 성공한 건
  남은 대상   = 목록 대상 − 보관 제외 − 이번 완료 (실패한 건은 남은 대상에 남는다)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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

from ... import archive, settings
from ...targets import volume_warning
from ..art import Art
from ..widgets import Card, EmptyState, KpiCard, Pill, PillDelegate, Step, WrapLabel, muted_label
from ..worker import SessionWorker

# (머리글, 너비). 너비가 None 이면 남는 폭을 채운다. 창이 좁으면 표 안에서 가로로 스크롤한다.
COLUMNS = [("상태", 128), ("No", 60), ("지출예정일", 112), ("내용", 320),
           ("금액", 120), ("결의서구분", 104), ("저장한 파일", None)]
COL_STATUS, COL_CONT, COL_AMT, COL_FILE = 0, 3, 4, 6

ROW_STATUS = {
    "waiting": ("대기", "neutral"),
    "running": ("받는 중", "info"),
    "retry": ("다시 로그인 대기", "warning"),
    "done": ("완료", "success"),
    "failed": ("실패", "danger"),
}

GUIDE_START = "① 브라우저 열기를 누르면 ERP 창이 열립니다. 그 창에서 로그인하고 결의서내역 목록을 띄우세요."
GUIDE_BROWSER = "열린 브라우저에서 로그인 → [과제관리 → 과제정보 → 청구서] → '결의서내역' 목록을 띄운 뒤 ② 목록 읽기를 누르세요."
GUIDE_LISTED = "받을 건을 확인하고 ③ 받기를 누르세요. 처음이라면 '앞 1건만 시험'으로 흐름부터 확인하세요."
GUIDE_DETAIL = (
    "• ① ERP 열기 — 앱이 새 브라우저 창을 엽니다. 평소 쓰는 Edge/크롬이 아니라 이 창에서 로그인해야 합니다. "
    "아이디·비밀번호는 어디에도 저장하지 않습니다.\n"
    "• ② 목록 읽기 — 결의서내역 목록을 끝까지 읽어 승인 + 문서번호 + 지출예정일 조건의 건만 고르고, "
    "문서번호가 보관 폴더에 이미 있는 건은 제외합니다.\n"
    "• ③ 받기 — 건마다 상세조회 → 청구서출력 → PDF 저장. 비목을 판정해 '0N_(지출예정일) 적요_이체자_(금액).pdf' "
    "이름으로 비목 폴더 바로 아래에 둡니다. 플랫폼에 올린 파일은 직접 '업로드' 폴더로 옮기세요.\n"
    "• 상세화면이 멈추면 ERP 를 새로 열고 다시 로그인한 뒤 같은 건부터 이어받습니다(건당 최대 2번)."
)


def _money(amt: str) -> str:
    try:
        return "{:,}".format(int(amt))
    except (TypeError, ValueError):
        return amt or ""


def _tabular(font: QFont) -> QFont:
    """금액 자릿수가 세로로 맞도록 고정폭 숫자. 폰트가 지원하지 않으면 그대로 둔다."""
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


class DownloadPage(QWidget):
    need_settings = Signal()
    busy_changed = Signal(bool)      # 받는 중인지 — 작업 탭의 점이 본다
    counts_changed = Signal()        # 보관·대기 숫자나 받기 상태가 바뀜 — 홈이 본다

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.worker = SessionWorker()
        self._busy = False
        self._browser_open = False
        self._targets: list[dict] = []
        self._status: list[str] = []
        self._running_rows: list[int] = []   # 이번 받기 순번 → 표의 행
        self._archive_ok = True
        self._selection = None
        self._listed = False
        self._run_ok = 0
        self._run_failed = 0
        self._attempted = False               # 한 번이라도 받기를 시작했는지 (이어서 작업하기 판단)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 26)
        layout.setSpacing(12)

        # 머리 — 한 줄
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("receive", 44), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("청구서 받기")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        self.page_desc = muted_label("승인된 청구서를 ERP 에서 받아 비목 폴더에 둡니다. ERP 에 입력·제출하지 않습니다.")
        texts.addWidget(self.page_desc)
        head.addLayout(texts, 1)
        self.folder_button = QPushButton()
        self.folder_button.setObjectName("ghost")
        self.folder_button.setToolTip("저장 폴더를 바꾸려면 누르세요")
        self.folder_button.clicked.connect(self.need_settings.emit)
        head.addWidget(self.folder_button, 0, Qt.AlignVCenter)
        layout.addLayout(head)

        # 1) 요약 — 낮게
        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self.kpi_total = KpiCard("목록 대상", "overview", "목록을 읽으면 표시")
        self.kpi_remaining = KpiCard("남은 대상", "receive", "대상 − 보관 제외 − 완료")
        self.kpi_ok = KpiCard("이번 완료", "approved", "이번 실행에서 저장한 건")
        self.kpi_waiting = KpiCard("업로드 대기", "upload", "비목 폴더 바로 아래의 PDF")
        for card in (self.kpi_total, self.kpi_remaining, self.kpi_ok, self.kpi_waiting):
            kpis.addWidget(card, 1)
        layout.addLayout(kpis)

        # 2) 단계 — 가로 띠
        layout.addLayout(self._build_steps())
        self.detail = WrapLabel(GUIDE_DETAIL)
        self.detail.setObjectName("muted")
        self.detail.hide()
        layout.addWidget(self.detail)
        layout.addLayout(self._build_status_row())
        layout.addWidget(self._build_banner())

        # 3) 받을 목록 · 진행 기록 — 남는 높이 전부
        layout.addWidget(self._build_work_card(), 1)

        w = self.worker
        w.log.connect(self._append_log)
        w.busy.connect(self._on_busy)
        w.prepared.connect(self._on_prepared)
        w.browser_opened.connect(self._on_browser_opened)
        w.listed.connect(self._on_listed)
        w.list_failed.connect(self._on_list_failed)
        w.item.connect(self._on_item)
        w.finished.connect(self._on_finished)
        w.relogin.connect(self._on_relogin)
        w.error.connect(self._on_error)
        w.browser_state.connect(self._on_browser_state)

        self.refresh_counts()
        self._sync_buttons()

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_steps(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.step1 = Step("1", "ERP 열기", "앱이 연 창에서 직접 로그인합니다.", "login")
        self.open_button = QPushButton("브라우저 열기")
        self.open_button.clicked.connect(self._open)
        self.step1.add_action(self.open_button)

        self.step2 = Step("2", "목록 읽기", "결의서내역 목록에서 받을 건만 골라 냅니다.", "overview")
        self.list_button = QPushButton("목록 읽기")
        self.list_button.clicked.connect(self._read_list)
        self.step2.add_action(self.list_button)

        self.step3 = Step("3", "받기", "이름을 붙여 비목 폴더 바로 아래에 저장합니다.", "register")
        self.all_button = QPushButton("받기")
        self.all_button.setObjectName("primary")
        self.all_button.clicked.connect(lambda: self._download(limit=0))
        self.test_button = QPushButton("앞 1건만 시험")
        self.test_button.clicked.connect(lambda: self._download(limit=1))
        self.step3.add_action(self.all_button)
        self.step3.add_action(self.test_button)
        for step in (self.step1, self.step2, self.step3):
            row.addWidget(step, 1)
        return row

    def _build_status_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.state_pill = Pill("준비", "neutral")
        row.addWidget(self.state_pill, 0, Qt.AlignVCenter)
        self.guide = QLabel(GUIDE_START)
        self.guide.setObjectName("body")
        self.guide.setWordWrap(True)
        row.addWidget(self.guide, 1)
        self.detail_button = QPushButton("자세한 안내")
        self.detail_button.setObjectName("disclosure")
        self.detail_button.setCheckable(True)
        self.detail_button.toggled.connect(self._toggle_detail)
        row.addWidget(self.detail_button)
        self.stop_button = QPushButton("멈추기")
        self.stop_button.setObjectName("danger")
        self.stop_button.setToolTip("지금 받는 건을 마치고 멈춥니다")
        self.stop_button.clicked.connect(self._stop)
        row.addWidget(self.stop_button)
        spacer = QWidget()
        spacer.setFixedSize(0, 36)
        row.addWidget(spacer)
        return row

    def _toggle_detail(self, on: bool) -> None:
        self.detail.setVisible(on)
        self.detail_button.setText("안내 접기" if on else "자세한 안내")

    def _build_banner(self) -> QFrame:
        """사람 차례 알림 — 다시 로그인해야 할 때만 보인다. 안내는 여기 한 곳에만 쓴다."""
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(16, 10, 10, 10)
        banner_layout.addWidget(Pill("확인 필요", "warning"), 0, Qt.AlignVCenter)
        self.banner_text = QLabel()
        self.banner_text.setObjectName("bannerText")
        self.banner_text.setWordWrap(True)
        banner_layout.addWidget(self.banner_text, 1)
        self.resume_button = QPushButton("목록을 띄웠어요 · 계속")
        self.resume_button.setObjectName("primary")
        self.resume_button.clicked.connect(lambda: self._answer_relogin(True))
        self.abort_button = QPushButton("그만 받기")
        self.abort_button.clicked.connect(lambda: self._answer_relogin(False))
        banner_layout.addWidget(self.resume_button)
        banner_layout.addWidget(self.abort_button)
        self.banner.hide()
        return self.banner

    def _build_work_card(self) -> QWidget:
        card = Card(margins=(16, 8, 16, 12))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)

        self.list_stack = QStackedWidget()
        self.empty = EmptyState("receive", "", "")
        self.empty_settings_button = QPushButton("설정으로 이동")
        self.empty_settings_button.setObjectName("primary")
        self.empty_settings_button.clicked.connect(self.need_settings.emit)
        self.empty.add_action(self.empty_settings_button)
        self.list_stack.addWidget(self.empty)
        self.list_stack.addWidget(self._build_table())
        self.tabs.addTab(self.list_stack, "받을 목록")

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
        open_log.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.log_path()))))
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
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setSortingEnabled(False)   # 받는 순서와 행 번호가 어긋나지 않게
        self.table.setItemDelegateForColumn(COL_STATUS, PillDelegate(self.table))
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setStretchLastSection(True)
        head.setHighlightSections(False)
        for col, (_, width) in enumerate(COLUMNS):
            head.setSectionResizeMode(col, QHeaderView.Interactive)
            if width:
                self.table.setColumnWidth(col, width)
        self.table.horizontalHeaderItem(COL_AMT).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.table)
        return holder

    # ── 상태 ────────────────────────────────────────────────────────────
    def refresh_counts(self) -> None:
        cfg = settings.load()
        folders = archive.folder_status(cfg.out_root)
        self.kpi_waiting.set_value(str(sum(f.waiting for f in folders)) if folders else "—")
        if cfg.out_root:
            name = cfg.out_root.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            self.folder_button.setText(f"저장 폴더 · {name}")
            self.folder_button.setToolTip(f"{cfg.out_root}\n누르면 설정에서 바꿀 수 있습니다")
        else:
            self.folder_button.setText("저장 폴더 지정하기")
            self.folder_button.setToolTip("")
        self._sync_empty()
        self.counts_changed.emit()

    def _sync_counts(self) -> None:
        """요약 카드 넷을 같은 목록 기준으로 다시 센다."""
        skipped = self._selection.skipped if self._selection else 0
        total = len(self._targets) + skipped
        remaining = len(self._remaining())
        if self._listed:
            self.kpi_total.set_value(str(total), f"보관으로 제외 {skipped}건")
            self.kpi_remaining.set_value(str(remaining), f"실패 {self._run_failed}건 포함" if self._run_failed else "대상 − 보관 제외 − 완료")
        else:
            self.kpi_total.set_value("—", "목록을 읽으면 표시")
            self.kpi_remaining.set_value("—", "대상 − 보관 제외 − 완료")
        self.kpi_ok.set_value(str(self._run_ok), f"실패 {self._run_failed}건" if self._run_failed else "이번 실행에서 저장한 건")

    def _sync_empty(self) -> None:
        """받을 목록 자리에 무엇을 보일지 — 처음 안내 · 받을 것 없음 · 표."""
        if not settings.load().out_root:
            self.empty.set_content(
                "archive", "저장 폴더를 먼저 지정하세요",
                "받은 청구서를 넣을 폴더입니다. 비목 폴더(01. 인건비 · 02. 장학금 …)가 바로 아래 있는 폴더를 고르면 됩니다.")
            self.empty_settings_button.show()
            self.list_stack.setCurrentIndex(0)
            return
        self.empty_settings_button.hide()
        if self._targets:
            self.list_stack.setCurrentIndex(1)
        elif self._listed:
            skipped = self._selection.skipped if self._selection else 0
            self.empty.set_content(
                "approved", "새로 받을 청구서가 없습니다",
                f"승인된 건은 모두 보관되어 있습니다(보관으로 제외 {skipped}건). 목록이 바뀌면 ② 목록 읽기를 다시 누르세요.")
            self.list_stack.setCurrentIndex(0)
        else:
            self.empty.set_content(
                "receive", "목록을 읽으면 받을 청구서가 여기에 나옵니다",
                "① 브라우저 열기 → ERP 로그인 → 결의서내역 목록을 띄운 뒤 ② 목록 읽기를 누르세요.")
            self.list_stack.setCurrentIndex(0)

    def _set_state(self, text: str, status: str, guide: str | None = None) -> None:
        self.state_pill.set_status(text, status)
        if guide is not None:
            self.guide.setText(guide)

    def _remaining(self) -> list[int]:
        return [i for i, s in enumerate(self._status) if s != "done"]

    def _sync_buttons(self) -> None:
        busy = self._busy
        self.open_button.setEnabled(not busy and not self._browser_open)
        self.list_button.setEnabled(not busy and self._browser_open)
        remaining = len(self._remaining())
        can_run = not busy and self._browser_open and remaining > 0
        self.all_button.setEnabled(can_run)
        self.all_button.setText(f"남은 {remaining}건 받기" if remaining else "받기")
        self.test_button.setEnabled(can_run)
        running = busy and bool(self._running_rows)
        self.stop_button.setVisible(running)
        self.stop_button.setEnabled(running)
        self.tabs.setTabText(0, f"받을 목록 ({len(self._targets)})" if self._listed else "받을 목록")
        # 현재 단계만 강조
        if not self._browser_open:
            states = ("current", "todo", "todo")
        elif not self._listed:
            states = ("done", "current", "todo")
        elif remaining:
            states = ("done", "done", "current")
        else:
            states = ("done", "done", "done")
        for step, state in zip((self.step1, self.step2, self.step3), states):
            step.set_state(state)
        self._sync_counts()

    # ── 다른 화면이 묻는 것 ────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._busy and bool(self._running_rows)

    def resumable(self) -> tuple[bool, str]:
        """홈 '이어서 작업하기' — 받다가 멈췄거나 실패해 남은 건이 있을 때만 참.

        목록만 읽어 둔 상태는 '이어서 할 일' 이 아니라 '아직 시작 안 함' 이다.
        """
        remaining = len(self._remaining())
        if self.is_running():
            return True, f"받는 중 · 남은 {remaining}건"
        if self._attempted and remaining > 0 and self._browser_open:
            return True, f"받다가 멈춤 · 남은 {remaining}건"
        return False, ""

    # ── 동작 ────────────────────────────────────────────────────────────
    def _open(self) -> None:
        if not settings.load().out_root:
            QMessageBox.information(
                self, "저장 폴더",
                "받은 청구서를 넣을 폴더를 먼저 지정해 주세요.\n비목 폴더(01. 인건비 …)가 바로 아래 있는 폴더입니다.")
            self.need_settings.emit()
            return
        self.worker.open_browser()

    def _read_list(self) -> None:
        self.worker.read_list()

    def _download(self, limit: int) -> None:
        rows = self._remaining()
        if limit:
            rows = rows[:limit]
        if not rows:
            return
        if not self._archive_ok:
            answer = QMessageBox.warning(
                self, "보관 폴더를 읽지 못했습니다",
                "보관 폴더를 읽지 못해 이미 받은 건을 가려내지 못했습니다.\n"
                "이대로 받으면 같은 청구서를 다시 받게 될 수 있습니다.\n\n"
                "[설정] 의 저장 폴더를 먼저 확인하세요. 그래도 받을까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        if not limit:
            preview = "\n".join(
                "· No %s  %s  (%s)" % (self._targets[i].get("no"), (self._targets[i].get("cont") or "")[:36],
                                       _money(self._targets[i].get("amt")))
                for i in rows[:10])
            if len(rows) > 10:
                preview += "\n· … 외 %d건" % (len(rows) - 10)
            warning = volume_warning(self._selection) if self._selection else ""
            box = QMessageBox.warning if warning else QMessageBox.question
            answer = box(
                self, "받기 확인",
                f"아래 {len(rows)}건을 받습니다.\n\n{preview}"
                + (f"\n\n{warning.replace('      ', '')}" if warning else "")
                + "\n\n진행할까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self._running_rows = rows
        self._attempted = True
        for row in rows:
            self._set_status(row, "waiting")
        self._set_state("받는 중", "info", f"{len(rows)}건을 받고 있습니다. 브라우저 창은 닫지 마세요.")
        self.worker.download([self._targets[i] for i in rows])

    def _stop(self) -> None:
        self.worker.request_stop()
        self.stop_button.setEnabled(False)
        self._set_state("멈추는 중", "warning", "지금 받는 건을 마치면 멈춥니다…")

    def _answer_relogin(self, ok: bool) -> None:
        self.banner.hide()
        self.worker.answer_relogin(ok)

    # ── 작업 스레드 신호 ─────────────────────────────────────────────────
    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _on_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        self.busy_changed.emit(self.is_running())
        if message:
            self.window().statusBar().showMessage(message)
        elif not busy:
            self.window().statusBar().clearMessage()
        self._sync_buttons()

    def _on_prepared(self, report) -> None:
        self._archive_ok = report.ok
        if not report.ok:
            QMessageBox.warning(self, "보관 폴더", report.warning.replace("      ", ""))
        self.refresh_counts()

    def _on_browser_opened(self) -> None:
        self._browser_open = True
        self._set_state("로그인 대기", "warning", GUIDE_BROWSER)
        self._sync_buttons()

    def _on_browser_state(self, alive: bool) -> None:
        """사용자가 브라우저 창을 닫아 버렸으면 ① 부터 다시 하게 한다."""
        if self._browser_open and not alive:
            self._browser_open = False
            self._set_state("브라우저 닫힘", "neutral", "브라우저 창이 닫혔습니다. " + GUIDE_START)
        self._sync_buttons()
        self.counts_changed.emit()

    def _on_listed(self, selection) -> None:
        self._selection = selection
        self._listed = True
        self._attempted = False
        self._run_ok = self._run_failed = 0
        self._targets = list(selection.targets)
        self._status = ["waiting"] * len(self._targets)
        self.table.setRowCount(len(self._targets))
        amount_font = _tabular(QFont(self.table.font()))
        for row, t in enumerate(self._targets):
            values = ["", t.get("no", ""), t.get("expDt", ""), t.get("cont", ""),
                      _money(t.get("amt", "")), t.get("gubun", ""), ""]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == COL_AMT:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setFont(amount_font)
                if col == COL_CONT:
                    item.setToolTip(str(value))   # 말줄임된 내용 전체 보기
                self.table.setItem(row, col, item)
            self._set_status(row, "waiting")
        if self._targets:
            self._set_state("확인 대기", "info", GUIDE_LISTED)
        else:
            self._set_state("받을 건 없음", "success", "새로 받을 건이 없습니다. 목록이 바뀌면 ② 를 다시 누르세요.")
        self.tabs.setCurrentIndex(0)
        self._sync_empty()
        self._sync_buttons()
        self.counts_changed.emit()

    def _on_list_failed(self, message: str) -> None:
        self._set_state("목록 못 찾음", "danger", GUIDE_BROWSER)
        QMessageBox.warning(
            self, "목록을 찾지 못했습니다",
            f"{message}\n\n앱이 연 브라우저 창에서 로그인하고 [과제관리 → 과제정보 → 청구서] 의 "
            "'결의서내역' 목록을 띄웠는지 확인한 뒤 ② 를 다시 누르세요.\n열린 창 구조는 [진행 기록] 탭에 남겼습니다.")
        self._sync_buttons()

    def _set_status(self, row: int, status: str, detail: str = "") -> None:
        if row >= len(self._status):
            return
        self._status[row] = status
        text, tone = ROW_STATUS[status]
        item = QTableWidgetItem(text)
        item.setData(PillDelegate.ROLE, tone)
        self.table.setItem(row, COL_STATUS, item)
        if detail:
            cell = QTableWidgetItem(detail)
            cell.setToolTip(detail)
            self.table.setItem(row, COL_FILE, cell)

    def _on_item(self, index: int, status: str, detail: str) -> None:
        if index >= len(self._running_rows):
            return
        row = self._running_rows[index]
        self._set_status(row, status, detail)
        self.table.scrollToItem(self.table.item(row, COL_STATUS))
        if status == "done":
            self._run_ok += 1
            self.refresh_counts()
        elif status == "failed":
            self._run_failed += 1
        self._sync_counts()

    def _on_finished(self, summary) -> None:
        self.banner.hide()
        self._running_rows = []
        failed = len(summary.failed)
        remaining = len(self._remaining())
        text = f"성공 {summary.ok}건 · 실패 {failed}건 · 남은 대상 {remaining}건"
        if summary.stopped:
            text += " — 중간에 멈췄습니다"
        if summary.missing:
            text += f" · 엑셀 대조 누락 {len(summary.missing)}건 ([진행 기록] 참고)"
        text += ". 받은 파일은 비목 폴더 바로 아래에 있습니다."
        if failed:
            self._set_state("일부 실패", "danger", text)
        elif summary.stopped:
            self._set_state("멈춤", "warning", text)
        else:
            self._set_state("완료", "success", text)
        self.refresh_counts()
        self._sync_buttons()

    def _on_relogin(self, message: str) -> None:
        self.banner_text.setText(message)
        self.banner.show()
        self._set_state("다시 로그인", "warning", "아래 띠의 안내를 따른 뒤 [계속] 을 누르세요.")
        self.window().raise_()
        self.window().activateWindow()

    def _on_error(self, message: str) -> None:
        self.banner.hide()
        if "Executable doesn't exist" in message or "msedge" in message:
            message = ("브라우저를 띄우지 못했습니다. [앱 실행.bat] 을 다시 실행해 준비를 마치거나, "
                       "Microsoft Edge 가 설치되어 있는지 확인하세요.\n\n" + message)
        self._set_state("오류", "danger")
        QMessageBox.warning(self, "문제가 생겼습니다", f"{message}\n\n자세한 내용은 [진행 기록] 탭과 로그 파일에 있습니다.")
        self._sync_buttons()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """창이 낮거나 좁으면 위쪽을 접어 표에 자리를 준다. 글씨는 줄이지 않는다."""
        super().resizeEvent(event)
        low = self.height() < 600
        narrow = self.width() < 1300
        for step in (self.step1, self.step2, self.step3):
            step.set_compact(low or narrow)
        for card in (self.kpi_total, self.kpi_remaining, self.kpi_ok, self.kpi_waiting):
            card.set_compact(low)
        self.page_desc.setVisible(not low)

    def shutdown(self) -> None:
        self.worker.shutdown()
