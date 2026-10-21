"""청구서 받기 화면 — 요약 → 단계 → 받을 목록 · 진행 기록.

    ① ERP 열기 → [사람: 로그인] → 고른 과제의 결의서내역(앱이 감)
    → ② 목록 읽기 → 대상 확인 → ③ 받기

① [브라우저 열기] 한 번으로 끝까지 간다(담당자 요청 2026-10-21): 브라우저가 닫혀 있으면 열고 로그인을 기다렸다가, 열려 있으면 바로
고른 과제의 결의서내역을 읽어(다른 과제 · 다른 탭이 앞이면 옮긴다) 아직 안 받은 청구서만 받는다. 받기 전 '받을까요?' 확인은 그대로다(9절).

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

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
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

from ... import archive, navigate, project_folders, rebudget, settings, skiplist
from .. import project_box
from ...targets import volume_warning
from ..art import Art
from ..report_dialog import ReportRow, show_report, show_structure_saved
from ..widgets import Card, EmptyState, KpiCard, Pill, PillDelegate, Step, WrapLabel, muted_label
from ..worker import SessionWorker

# (머리글, 너비). 너비가 None 이면 남는 폭을 채운다. 창이 좁으면 표 안에서 가로로 스크롤한다.
COLUMNS = [("상태", 128), ("과제", 140), ("No", 60), ("지출예정일", 112), ("내용", 300),
           ("금액", 120), ("결의서구분", 104), ("저장한 파일", None)]
COL_STATUS, COL_PROJECT, COL_CONT, COL_AMT, COL_FILE = 0, 1, 4, 5, 7

ROW_STATUS = {
    "waiting": ("대기", "neutral"),
    "running": ("받는 중", "info"),
    "retry": ("다시 로그인 대기", "warning"),
    "done": ("완료", "success"),
    "failed": ("실패", "danger"),
    "unwanted": ("받지 않음", "neutral"),      # 청구서출력이 없는 결의서 — 받지 않는 결의서 목록에 넣었다(skiplist)
}

GUIDE_START = ("과제를 고르고 ① 브라우저 열기를 누르세요. 열린 ERP 창에서 로그인하면 그 과제의 결의서내역에서 "
               "아직 안 받은 청구서를 찾아 받습니다(받기 전에 한 번 묻습니다).")
GUIDE_BROWSER = ("열린 브라우저에서 로그인하세요. 그 뒤 고른 과제의 [청구서] → '결의서내역' 목록까지 앱이 가서 "
                 "안 받은 청구서를 찾습니다(못 가면 직접 띄우세요).")
GUIDE_LISTED = "받을 건을 확인하고 ③ 받기를 누르세요. 처음이라면 '앞 1건만 시험'으로 흐름부터 확인하세요."
GUIDE_DETAIL = (
    "• ① ERP 열기 — 앱이 새 브라우저 창을 엽니다. 평소 쓰는 Edge/크롬이 아니라 이 창에서 로그인해야 합니다. "
    "아이디·비밀번호는 어디에도 저장하지 않습니다. 로그인하면 고른 과제의 결의서내역을 읽고 안 받은 청구서를 받습니다(받기 전에 묻습니다). "
    "브라우저가 이미 열려 있으면 이 단추가 바로 그 일을 합니다.\n"
    "• ② 목록 읽기 — 결의서내역 목록을 끝까지 읽어 승인 + 문서번호 + 지출예정일 조건의 건만 고르고, "
    "문서번호가 보관 폴더에 이미 있는 건은 제외합니다.\n"
    "• ③ 받기 — 건마다 상세조회 → 청구서출력 → PDF 저장. 비목을 판정해 '0N_(지출예정일) 적요_이체자_(금액).pdf' "
    "이름으로 비목 폴더 바로 아래에 둡니다. 플랫폼에 올린 파일은 직접 '업로드' 폴더로 옮기세요.\n"
    "• 상세화면이 멈추면 ERP 를 새로 열고 다시 로그인한 뒤 같은 건부터 이어받습니다(건당 최대 2번)."
)


def _rel_name(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


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
    attention = Signal()             # 띠에서 사람을 기다림 — 다른 탭에 있으면 이 화면으로(app._wire)

    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        # 브라우저 스레드는 앱이 하나만 만들어 일반청구와 함께 쓴다(ERP 로그인은 한 번). 없이 만들면 스스로 갖는다.
        self.worker = worker if worker is not None else SessionWorker()
        self._owns_worker = worker is None
        self._busy = False
        self._browser_open = False
        self._targets: list[dict] = []
        self._status: list[str] = []
        self._running_rows: list[int] = []   # 이번 받기 순번 → 표의 행
        self._archive_ok = True
        self._scanned_root = settings.load().out_root
        self._selection = None
        self._listed = False
        self._run_ok = 0
        self._run_failed = 0
        self._attempted = False               # 한 번이라도 받기를 시작했는지 (이어서 작업하기 판단)
        self._auto_run = False                # ① 을 눌렀다 — 목록을 읽으면 이어서 받는다(받기 전 확인은 그대로)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 26)
        layout.setSpacing(12)

        # 머리 — 한 줄
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("receive", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("청구서 받기")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        self.page_desc = muted_label("승인된 청구서를 ERP 에서 받아 과제 폴더 · 비목 폴더에 둡니다. ERP 에 입력·제출하지 않습니다.")
        texts.addWidget(self.page_desc)
        head.addLayout(texts, 1)
        # ERP 과제 — 일반청구와 같은 칸 · 같은 기본값(ui/project_box.py). 목록 읽기가 이 과제의 결의서내역으로 간다
        project_label = QLabel("과제")
        project_label.setObjectName("fieldLabel")
        head.addWidget(project_label, 0, Qt.AlignVCenter)
        self.project_box = project_box.project_box()
        # 저장 폴더가 과제 폴더로 나뉘어 있으면 '폴더 만든 과제 모두' · '고른 과제 여럿' · 과제 하나씩 — 담당자 2026-10-21. 마지막 고른 것을 다시 쓴다
        scope = settings.load().download_scope
        start = {"some": project_folders.SOME, "one": project_box.last_project()}.get(scope, project_folders.ALL)
        if start == project_folders.SOME and not project_box.chosen_projects():
            start = project_folders.ALL
        project_box.fill_download_box(self.project_box, start)
        self.project_box.currentIndexChanged.connect(self._project_changed)
        self.project_box.activated.connect(self._project_activated)
        project_label.setBuddy(self.project_box)
        head.addWidget(self.project_box, 0, Qt.AlignVCenter)
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
        w.failed.connect(self._on_failed)
        w.browser_state.connect(self._on_browser_state)
        w.structure_saved.connect(self._on_structure_saved)
        w.list_ready.connect(self._on_list_ready)
        w.projects_read.connect(self._refresh_projects)
        w.rebudget_planned.connect(self._on_rebudget_planned)
        w.rebudget_applied.connect(self._on_rebudget_applied)

        self.refresh_counts()
        self._sync_buttons()

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_steps(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.step1 = Step("1", "ERP 열기", "로그인하면 고른 과제에서 안 받은 청구서를 찾아 받습니다.", "login")
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

        corner = QWidget()
        corner_row = QHBoxLayout(corner)
        corner_row.setContentsMargins(0, 0, 0, 0)
        corner_row.setSpacing(4)
        # 진단 모드 — 새 화면(일반청구 등)을 자동화하기 전에 담당자가 그 화면을 띄우고 눌러 실측한다
        self.structure_button = QPushButton("화면 구조 저장")
        self.structure_button.setObjectName("ghost")
        self.structure_button.setToolTip(
            "지금 브라우저에 열린 ERP 화면의 창·프레임·입력 요소를 _화면구조.txt 로 저장합니다. "
            "읽기만 하고 아무것도 누르거나 넣지 않습니다. 새 화면을 자동화하기 전 실측용입니다.")
        self.structure_button.clicked.connect(self._capture_structure)
        corner_row.addWidget(self.structure_button)
        # 이미 받은 대응자금 청구서를 예산 탭 차례 번호로 고치기(담당자 2026-10-21) — 대응자금 과제 폴더가 있을 때만 보인다
        self.rebudget_button = QPushButton("대응자금 파일 정리")
        self.rebudget_button.setObjectName("ghost")
        self.rebudget_button.setToolTip(
            "이미 받은 대응자금 과제의 청구서 PDF 를 과제정보 → 예산 탭의 비목 차례(01 · 02 …)로 이름을 고치고 그 비목 폴더로 옮깁니다. "
            "다시 받지 않습니다. 옮기기 전에 표로 보여 주고 묻습니다.")
        self.rebudget_button.clicked.connect(self._rebudget)
        corner_row.addWidget(self.rebudget_button)
        # 청구서출력이 없어 받지 않는 결의서(skiplist.py, 담당자 2026-10-21) — 있을 때만 보인다. 보고 비울 수 있다
        self.unwanted_button = QPushButton("받지 않는 결의서")
        self.unwanted_button.setObjectName("ghost")
        self.unwanted_button.setToolTip("청구서출력이 없어 받을 수 없는 결의서(잔액조정 · 대체 등) — 목록 읽기에서 뺍니다. 눌러서 보고 비울 수 있습니다.")
        self.unwanted_button.clicked.connect(self._show_unwanted)
        corner_row.addWidget(self.unwanted_button)
        open_log = QPushButton("로그 파일 열기")
        open_log.setObjectName("ghost")
        open_log.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.log_path()))))
        corner_row.addWidget(open_log)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)
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
        names = {p.no: p.name for p in navigate.load_projects()[0]}
        self.rebudget_button.setVisible(bool(rebudget.fund_folders(cfg.out_root, names)) if cfg.out_root else False)
        unwanted = len(skiplist.load())
        self.unwanted_button.setText(f"받지 않는 결의서 {unwanted}")
        self.unwanted_button.setVisible(unwanted > 0)
        self._sync_empty()
        self.counts_changed.emit()

    def _sync_counts(self) -> None:
        """요약 카드 넷을 같은 목록 기준으로 다시 센다."""
        skipped = self._selection.skipped if self._selection else 0
        total = len(self._targets) + skipped
        remaining = len(self._remaining())
        if self._listed:
            excluded = self._selection.excluded if self._selection else 0
            self.kpi_total.set_value(str(total), f"보관으로 제외 {skipped}건" + (f" · 받지 않음 {excluded}건" if excluded else ""))
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
                "받은 청구서를 넣을 폴더입니다. 과제 폴더('(과제번호)_…')나 비목 폴더(01. 인건비 …)가 바로 아래 있는 폴더를 고르면 됩니다.")
            self.empty_settings_button.show()
            self.list_stack.setCurrentIndex(0)
            return
        self.empty_settings_button.hide()
        if self._targets:
            self.list_stack.setCurrentIndex(1)
        elif self._listed:
            skipped = self._selection.skipped if self._selection else 0
            excluded = self._selection.excluded if self._selection else 0
            self.empty.set_content(
                "approved", "새로 받을 청구서가 없습니다",
                f"승인된 건은 모두 보관되어 있습니다(보관으로 제외 {skipped}건"
                + (f" · 청구서출력이 없어 받지 않는 결의서 {excluded}건" if excluded else "")
                + "). 목록이 바뀌면 ② 목록 읽기를 다시 누르세요.")
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
        return [i for i, s in enumerate(self._status) if s not in ("done", "unwanted")]

    def _sync_buttons(self) -> None:
        busy = self._busy
        # 브라우저가 열려 있으면 ① 은 '고른 과제의 목록을 읽고 받기' 다(담당자 요청 2026-10-21)
        self.open_button.setEnabled(not busy)
        self.open_button.setText("안 받은 청구서 받기" if self._browser_open else "브라우저 열기")
        self.open_button.setToolTip("고른 과제의 결의서내역을 읽고 아직 안 받은 청구서를 받습니다(받기 전에 묻습니다)"
                                    if self._browser_open else "ERP 창을 엽니다. 로그인하면 고른 과제의 안 받은 청구서를 찾아 받습니다")
        self.project_box.setEnabled(not busy)
        self.list_button.setEnabled(not busy and self._browser_open)
        remaining = len(self._remaining())
        can_run = not busy and self._browser_open and remaining > 0
        self.all_button.setEnabled(can_run)
        self.all_button.setText(f"남은 {remaining}건 받기" if remaining else "받기")
        self.test_button.setEnabled(can_run)
        self.structure_button.setEnabled(not busy and self._browser_open)
        self.rebudget_button.setEnabled(not busy)
        self.unwanted_button.setEnabled(not busy)
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
                "받은 청구서를 넣을 폴더를 먼저 지정해 주세요.\n과제 폴더('(과제번호)_…')나 비목 폴더(01. 인건비 …)가 바로 아래 있는 폴더입니다.")
            self.need_settings.emit()
            return
        self._auto_run = True
        if self._browser_open:
            self._read_list()
        else:
            self.worker.open_browser(watch=True)    # 로그인 뒤 목록이 보이면 list_ready → 읽고 받기

    def _project(self) -> str:
        return str(self.project_box.currentData() or project_box.last_project())

    def _folder_label(self, target: dict) -> str:
        """표 · 확인 창의 과제 칸 — 과제 폴더 이름(번호 · 금액 뺀 것), 폴더가 없으면 과제번호."""
        no = str(target.get("project") or "")
        for folder in project_box.folder_projects():
            if folder.no == no:
                return folder.short()[len(no):].strip() or no
        return no or "—"

    def _all(self) -> bool:
        """여러 과제를 차례로 — '폴더 만든 과제 모두' 이거나 '고른 과제 여럿'."""
        return self._project() in (project_folders.ALL, project_folders.SOME)

    def _projects(self) -> list[str]:
        if self._project() == project_folders.ALL:
            return [f.no for f in project_box.folder_projects()]
        if self._project() == project_folders.SOME:
            return project_box.chosen_projects()
        return [self._project()]

    def _project_text(self) -> str:
        if self._project() == project_folders.ALL:
            return f"폴더 만든 과제 {len(project_box.folder_projects())}개"
        if self._project() == project_folders.SOME:
            return f"고른 과제 {len(project_box.chosen_projects())}개"
        return f"과제 {self._project()}"

    def _read_list(self) -> None:
        if self._all():
            projects = self._projects()
            if not projects:
                self._auto_run = False
                self._set_state("과제 없음", "warning", "받을 과제를 고르세요 — 과제 칸의 '여러 과제 고르기…'.")
                return
            self._set_state("목록 읽는 중", "info", f"{self._project_text()}의 결의서내역을 차례로 읽고 있습니다…")
            self.worker.read_lists(projects)
            return
        self._set_state("목록 읽는 중", "info", f"과제 {self._project()} 의 결의서내역을 읽고 있습니다…")
        self.worker.read_list(self._project())

    def _project_activated(self, index: int) -> None:
        """'여러 과제 고르기…' 를 누르면(이미 골라져 있어도 다시 누르면) 체크 창을 띄운다."""
        if self.project_box.itemData(index) != project_folders.SOME:
            return
        before = project_box.chosen_projects()
        if project_box.pick_projects(self):
            project_box.fill_download_box(self.project_box, project_folders.SOME)       # 칸 글자 '고른 과제 N개'
            if project_box.chosen_projects() != before:
                self._project_changed(index)
        elif not before:
            self.project_box.setCurrentIndex(max(self.project_box.findData(project_folders.ALL), 0))   # 하나도 안 골랐으면 '모두' 로

    def _project_changed(self, _index: int) -> None:
        no = self._project()
        if no == project_folders.ALL:
            settings.update(download_scope="all")
        elif no == project_folders.SOME:
            settings.update(download_scope="some")
        else:
            self.project_box.setToolTip("ERP 과제: " + navigate.label_of(no))
            project_box.remember(no)
            if project_box.folder_projects():
                settings.update(download_scope="one")
        if self._listed and not self._busy:
            # 읽어 둔 목록은 앞 과제의 것이다 — 받기 전에 새 과제의 목록을 다시 읽게 한다
            self._listed = False
            self._targets, self._status = [], []
            self.table.setRowCount(0)
            self._set_state("과제 바뀜", "info", f"과제가 바뀌었습니다. ① 을 누르면 {self._project_text()}의 결의서내역을 읽고 안 받은 청구서를 받습니다.")
            self._sync_empty()
            self._sync_buttons()

    def _refresh_projects(self) -> None:
        """로그인 뒤 과제현황을 새로 읽었으면(또는 저장 폴더가 바뀌면) 보기를 다시 채운다 — 고른 과제는 그대로."""
        project_box.fill_download_box(self.project_box, self._project())

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
            many = len({self._targets[i].get("project") for i in rows}) > 1
            preview = "\n".join(
                "· %sNo %s  %s  (%s)" % (f"[{self._folder_label(self._targets[i])}] " if many else "",
                                         self._targets[i].get("no"), (self._targets[i].get("cont") or "")[:36],
                                         _money(self._targets[i].get("amt")))
                for i in rows[:10])
            if len(rows) > 10:
                preview += "\n· … 외 %d건" % (len(rows) - 10)
            counts: dict[str, int] = {}
            for i in rows:
                counts[self._folder_label(self._targets[i])] = counts.get(self._folder_label(self._targets[i]), 0) + 1
            preview = "과제 폴더별: " + " · ".join(f"{k} {v}건" for k, v in counts.items()) + "\n\n" + preview
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
        self.worker.download([self._targets[i] for i in rows], "" if self._all() else self._project())

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

    def settings_changed(self) -> None:
        """저장 폴더가 바뀌면 이미 읽은 목록 · 보관 스캔은 옛 폴더 기준이다 — 목록을 다시 읽을 때 새 폴더를 훑게 한다."""
        root = settings.load().out_root
        if root != self._scanned_root:
            self._scanned_root = root
            self.worker.forget_archive()
            if self._listed:
                self._listed = False
                self._set_state("저장 폴더 바뀜", "warning", "저장 폴더가 바뀌었습니다. ② 목록 읽기를 다시 누르면 새 폴더를 훑고 받을 건을 다시 고릅니다.")
            if not self._busy:
                self._refresh_projects()           # 과제 폴더가 다른 저장 폴더
        self.refresh_counts()
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

    def _on_list_ready(self) -> None:
        """브라우저를 연 뒤 결의서내역 목록이 보인다 — 아직 안 읽었고 다른 일이 없으면 [목록 읽기] 를 대신 누른다(읽기만)."""
        if self._busy or not self._browser_open:
            return
        if not self._auto_run and (self._listed or not settings.load().auto_read_list):
            return
        self._set_state("목록 발견", "info", "결의서내역 목록이 보여 저절로 읽습니다…")
        self._read_list()

    def _on_browser_state(self, alive: bool) -> None:
        """사용자가 브라우저 창을 닫아 버렸으면 ① 부터 다시 하게 한다."""
        if self._browser_open and not alive:
            self._browser_open = False
            self._auto_run = False
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
            values = ["", self._folder_label(t), t.get("no", ""), t.get("expDt", ""), t.get("cont", ""),
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
        auto, self._auto_run = self._auto_run, False
        if self._targets:
            self._set_state("확인 대기", "info", GUIDE_LISTED)
            if auto:
                QTimer.singleShot(0, lambda: self._download(limit=0))     # 받기 전 확인 창은 그대로(9절)
        else:
            self._set_state("받을 건 없음", "warning" if selection.blocked else "success",
                            f"{self._project_text()}에 새로 받을 청구서가 없습니다(이미 받은 {selection.skipped}건은 건너뜀). "
                            "목록이 바뀌면 ① 을 다시 누르세요.")
        if selection.blocked:
            # 폴더가 없거나 목록을 못 띄운 과제 — 받지 않은 까닭을 알린다(받을 것이 있는 과제는 그대로 받는다)
            self.guide.setText(self.guide.text() + "\n받지 않은 과제: " + " · ".join(no or "(모름)" for no, _ in selection.blocked))
            QMessageBox.information(
                self, "받지 않은 과제",
                "아래 과제는 받지 않았습니다.\n\n" + "\n".join(f"· {no or '(모름)'}: {why}" for no, why in selection.blocked)
                + "\n\n목록을 못 띄운 과제는 브라우저에서 그 과제의 과제정보 → 청구서를 띄운 뒤, 과제 칸에서 그 과제를 골라 ① 을 누르세요.")
        self.tabs.setCurrentIndex(0)
        self._sync_empty()
        self._sync_buttons()
        self.counts_changed.emit()

    def _on_list_failed(self, message: str) -> None:
        self._auto_run = False
        self._set_state("목록 못 찾음", "danger", GUIDE_BROWSER)
        QMessageBox.warning(
            self, "목록을 찾지 못했습니다",
            f"{message}\n\n앱이 연 브라우저 창에서 로그인하고 [과제관리 → 과제정보 → 청구서] 의 "
            "'결의서내역' 목록을 띄웠는지 확인한 뒤 ① 을 다시 누르세요.\n열린 창 구조는 [진행 기록] 탭에 남겼습니다.")
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
        if summary.unwanted:
            text += f" · 받지 않음 {len(summary.unwanted)}건(청구서출력이 없는 결의서 — 다음부터 목록에서 뺍니다)"
        if summary.stopped:
            text += " — 중간에 멈췄습니다"
        if summary.missing:
            text += f" · 엑셀 대조 누락 {len(summary.missing)}건 ([진행 기록] 참고)"
        text += ". 받은 파일은 " + ("과제 폴더 안 " if project_box.folder_projects() else "") + "비목 폴더 바로 아래에 있습니다."
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
        self.attention.emit()
        self._set_state("다시 로그인", "warning", "아래 띠의 안내를 따른 뒤 [계속] 을 누르세요.")
        self.window().raise_()
        self.window().activateWindow()

    # ── 받지 않는 결의서(skiplist.py) ───────────────────────────────────
    def _show_unwanted(self) -> None:
        items = skiplist.load()
        rows = [ReportRow("받지 않음", "neutral",
                          [i.get("project", ""), i.get("seq", ""), i.get("gubun", ""), i.get("cont", ""), i.get("at", "")],
                          detail=f"까닭: {i.get('reason', '')}" + (f"\n문서번호: {i['docNo']}" if i.get("docNo") else ""))
                 for i in items]
        clear = show_report(
            self, title="받지 않는 결의서", heading=f"목록 읽기에서 빼는 결의서 {len(items)}건", tone="neutral",
            summary=["청구서출력이 없어 받을 수 없는 결의서(잔액조정 · 대체 등)입니다. 받기가 만나면 저절로 여기 들어오고, 목록 읽기에서 빠집니다.",
                     "결의서구분에 '청구' 가 든 결의서(일반청구 · 카드청구 · 대량청구)는 들어오지 않습니다 — 못 받으면 다음에 다시 해 봅니다."],
            columns=[("상태", 104), ("과제", 118), ("결의번호", 80), ("결의서구분", 140), ("내용", 300), ("넣은 때", None)], rows=rows,
            footer="목록을 비우면 다음 받기에서 다시 해 보고, 그래도 못 받으면 다시 들어옵니다.",
            accept_text="목록 비우기" if items else "")
        if clear and QMessageBox.question(self, "받지 않는 결의서", f"목록의 {len(items)}건을 비울까요? 다음 받기에서 다시 해 봅니다.",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            skiplist.clear()
            self.refresh_counts()

    # ── 대응자금 파일 정리(rebudget.py) ─────────────────────────────────
    def _rebudget(self) -> None:
        if self._busy:
            return
        if not self._browser_open:
            QMessageBox.information(
                self, "대응자금 파일 정리",
                "대응자금 과제마다 ERP 의 과제정보 → 예산 탭에서 비목 차례를 읽어야 합니다.\n\n"
                "① [브라우저 열기] 로 ERP 에 로그인한 뒤 이 단추를 다시 누르세요. (받기를 묻는 창이 뜨면 [아니요] 로 닫아도 됩니다)")
            return
        self._rebudget_asked = True
        self._set_state("대응자금 파일 보는 중", "info",
                        "대응자금 과제마다 예산 탭의 비목 차례를 읽고 받은 파일을 봅니다. 옮기기 전에 표로 보여 드립니다.")
        self.worker.plan_rebudget()

    def _on_rebudget_planned(self, plan) -> None:
        if not getattr(self, "_rebudget_asked", False):
            return
        self._rebudget_asked = False
        order = {rebudget.CHANGE: 0, rebudget.UNSURE: 1, rebudget.UPLOADED: 2, rebudget.OTHER: 3, rebudget.SAME: 4}
        tone = {rebudget.CHANGE: "info", rebudget.SAME: "success", rebudget.UNSURE: "warning",
                rebudget.UPLOADED: "warning", rebudget.OTHER: "neutral"}
        rows = [ReportRow(m.status, tone.get(m.status, "neutral"),
                          [m.project, m.place(), m.to() or "—"],
                          detail=f"{m.why}\n지금: {m.source}" + (f"\n바꿀 곳: {m.target}" if m.target else ""))
                for m in sorted(plan.moves, key=lambda m: (order.get(m.status, 9), str(m.source)))]
        summary = []
        for no, budget in plan.budgets.items():
            moves = [m for m in plan.moves if m.project == no]
            counts = " · ".join(f"{status} {n}" for status in order if (n := sum(1 for m in moves if m.status == status)))
            summary.append(f"과제 {no} 예산 탭 비목: " + " · ".join("%02d %s" % (i, name) for i, (_c, name) in enumerate(budget, 1))
                           + (f"  —  {counts}" if counts else "  —  PDF 없음"))
        notes = [f"과제 {no}: 예산 탭을 읽지 못해 그대로 둠 — {why}" for no, why in plan.blocked]
        unsure = sum(1 for m in plan.moves if m.status == rebudget.UNSURE)
        if unsure:
            notes.append(f"비목을 정하지 못한 파일 {unsure}개는 그대로 둡니다 — 열어 보고 직접 옮기세요")
        uploaded = sum(1 for m in plan.moves if m.status == rebudget.UPLOADED)
        if uploaded:
            notes.append(f"업로드 폴더 안의 파일 {uploaded}개는 앱이 옮기지 않습니다 — 바꿀 이름을 보고 직접 고치세요")
        changes = plan.changes()
        if not plan.budgets and not plan.blocked:
            QMessageBox.information(self, "대응자금 파일 정리", "저장 폴더에 대응자금 과제 폴더가 없습니다.")
            self._set_state("준비", "neutral", GUIDE_START)
            return
        self._set_state("대응자금 파일 확인", "info", "표를 보고 바꿀지 정하세요.")
        ok = show_report(
            self, title="대응자금 파일 정리",
            heading=f"이름 · 폴더를 바꿀 파일 {len(changes)}개" if changes else "바꿀 파일이 없습니다",
            tone="info" if changes else "success", summary=summary, notes=notes,
            columns=[("상태", 104), ("과제", 118), ("지금 (과제 폴더 안)", 400), ("바꿀 곳", None)], rows=rows,
            footer="앞 번호를 예산 탭 차례로 바꾸고 'NN. 비목명' 폴더로 옮깁니다. 덮어쓰지 않고(같은 이름이면 _2), 업로드 폴더의 파일은 옮기지 않습니다. 빈 옛 폴더는 지우지 않습니다.",
            accept_text=f"{len(changes)}개 바꾸기" if changes else "")
        if ok and changes:
            self._set_state("대응자금 파일 옮기는 중", "info")
            self.worker.apply_rebudget(changes)
        else:
            self._set_state("준비", "neutral", GUIDE_START)

    def _on_rebudget_applied(self, moves) -> None:
        done = [m for m in moves if m.done]
        failed = [m for m in moves if not m.done]
        root = Path(settings.load().out_root or ".")
        notes = [f"{m.project} {m.place()} — {m.why}" for m in failed]
        empty = rebudget.emptied(moves)
        if empty:
            notes.append("비게 된 옛 폴더(필요 없으면 지우세요): " + " · ".join(_rel_name(p, root) for p in empty))
        self.refresh_counts()
        self._set_state("대응자금 파일 정리 끝", "success" if not failed else "warning", GUIDE_START)
        show_report(self, title="대응자금 파일 정리", heading=f"옮김 {len(done)}개" + (f" · 못 옮김 {len(failed)}개" if failed else ""),
                    tone="success" if not failed else "warning", notes=notes,
                    columns=[("결과", 104), ("과제", 118), ("전 (과제 폴더 안)", 400), ("후", None)],
                    rows=[ReportRow("옮김" if m.done else "못 옮김", "success" if m.done else "danger",
                                    [m.project, m.place(), m.to()], detail=m.why) for m in moves])

    def _capture_structure(self) -> None:
        self._capture_asked = True              # 일반청구 화면도 같은 브라우저 스레드의 신호를 받는다 — 누른 쪽만 창을 띄운다
        self.worker.capture_structure()

    def _on_structure_saved(self, path: str) -> None:
        if not getattr(self, "_capture_asked", False):
            return
        self._capture_asked = False
        show_structure_saved(self, path)

    def _on_failed(self, owner: str, message: str) -> None:
        """이 화면이 넣은 명령의 오류만 — 일반청구가 넣은 명령의 오류는 그 화면이 알린다."""
        if owner != "download":
            return
        self._capture_asked = False
        self._rebudget_asked = False
        self._on_error(message)

    def _on_error(self, message: str) -> None:
        self._auto_run = False
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
        narrow = self.width() < 1240      # 기본 창(1320)에서 페이지는 1298 — 1300 이면 늘 접혀 단계 설명이 안 보였다
        for step in (self.step1, self.step2, self.step3):
            step.set_compact(low or narrow)
        for card in (self.kpi_total, self.kpi_remaining, self.kpi_ok, self.kpi_waiting):
            card.set_compact(low)
        self.page_desc.setVisible(not low)

    def shutdown(self) -> None:
        if self._owns_worker:
            self.worker.shutdown()
