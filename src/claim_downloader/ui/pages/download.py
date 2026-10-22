"""증빙 다운로드 화면(업무 id 는 download — 2026-10-22 담당자 지정으로 '청구서 받기' 에서 이름만 바꿈) — 할 차례인 단계만 위에서 아래로 떠오른다(ui/flow.py, 담당자 요청 2026-10-21).

    ① 무엇을 받을까요?(받을 서류) → ② 어느 과제(과제 칸) → ③ ERP 에 로그인(브라우저는 앱이 열고 로그인은 사람이)
    → ④ 받을 청구서 확인하고 받기(표 · [N건 받기] · [앞 1건만 시험])
    서류가 과제보다 먼저다(담당자 2026-10-22) — 구매요청(계약) 서류는 고른 과제의 기간으로 일자 범위를 정한다.

담당자: "업무카드를 열면 모든 기능들이 다 펼쳐져 있어 어디부터 클릭해야 하는지 헷갈림 — 순서대로 하나 둘 떠오르게". 그래서 처음에는 ① 만 보이고,
[다음] 을 누르면 ② · ③ 이 차례로, 로그인하고 목록을 읽으면 ④ 가 떠오른다. 마친 단계는 한 줄로 접혀 고른 값을 보이고 [바꾸기] 로 다시 편다.
로그인 뒤 고른 과제의 결의서내역까지 앱이 가서 목록을 읽고, 받을 건이 있으면 '받을까요?' 를 한 번 묻는다(9절 — 그 확인은 그대로).
받을 서류는 청구서 · 구매요청(계약) 서류 중 고른다(같은 날 요청, 여럿 가능) — 구매요청(계약)은 구매·자산 메뉴에서(purchase.py, 23절). 두 서류의 줄이 한 표에 섞인다.
진행 기록 · 도구(받지 않는 결의서 · 대응자금 파일 정리 · 로그 파일)는 머리 오른쪽 [진행 기록] · [도구] 에 둔다 — 늘 펼쳐 두지 않는다.

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
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import archive, navigate, project_folders, purchase, rebudget, settings, skiplist
from .. import project_box
from ...targets import volume_warning
from ..art import Art
from ..report_dialog import ReportRow, show_report
from ..flow import CURRENT, FlowStep
from ..flowlogic import DOWNLOAD_ORDER, download_stage, flow_states
from ..widgets import Card, EmptyState, Pill, PillDelegate, muted_label
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

GUIDE_LOGIN = ("[브라우저 열기] 로 열린 창에서 ERP 에 로그인하세요 — 아이디 · 비밀번호는 저장하지 않습니다. 로그인하면 앱이 고른 과제의 "
               "결의서내역으로 가서 안 받은 청구서를 찾습니다.")
GUIDE_BROWSER = ("열린 브라우저에서 로그인하세요. 그 뒤 고른 과제의 [청구서] → '결의서내역' 목록까지 앱이 가서 "
                 "안 받은 청구서를 찾습니다(못 가면 직접 띄우세요).")
GUIDE_LISTED = "받을 건을 확인하고 [받기] 를 누르세요. 처음이라면 '앞 1건만 시험' 으로 흐름부터 확인하세요."
GUIDE_DETAIL = (
    "• ① 무엇을 받을까요 — 받을 서류(청구서 · 구매요청(계약) 서류)를 고릅니다.\n"
    "• ② 어느 과제 — 과제(폴더 만든 과제 모두 · 여러 과제 · 하나)를 고릅니다. 구매요청(계약) 서류는 이 과제의 기간으로 일자 범위를 둡니다.\n"
    "• ③ ERP 에 로그인 — 앱이 새 브라우저 창을 엽니다. 평소 쓰는 Edge/크롬이 아니라 이 창에서 로그인해야 합니다. "
    "아이디·비밀번호는 어디에도 저장하지 않습니다. 로그인하면 고른 과제의 결의서내역 목록을 끝까지 읽어 "
    "승인 + 문서번호 + 지출예정일 조건의 건만 고르고, 문서번호가 보관 폴더에 이미 있는 건은 뺍니다.\n"
    "• ④ 받기 — 건마다 상세조회 → 청구서출력 → PDF 저장. 비목을 판정해 '0N_(지출예정일) 적요_이체자_(금액).pdf' "
    "이름으로 비목 폴더 바로 아래에 둡니다. 플랫폼에 올린 파일은 직접 '업로드' 폴더로 옮기세요.\n"
    "• 상세화면이 멈추면 ERP 를 새로 열고(로그인이 그대로면 묻지 않고) 같은 건부터 이어받습니다(건당 최대 2번). "
    "청구서출력이 없는 결의서는 건너뛰고 '받지 않는 결의서' 목록에 넣습니다."
)
# 받을 서류(담당자 요청 2026-10-21 — 과제처럼 여럿 고를 수 있게). 구매요청(계약) 서류는 그 화면을 실측한 뒤에 만든다
DOC_CLAIM, DOC_CONTRACT = "claim", "contract"


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
        self._reading = False                 # 목록을 읽는 중 — ④ 가 떠올라 '읽는 중' 을 보인다
        self._docs_picked = False             # ① 받을 서류를 골랐는지([다음]) — 그 전에는 ② 부터 안 보인다
        self._picked = False                  # ② 과제를 골랐는지([다음]) — 그 전에는 ③ · ④ 가 안 보인다
        self._run_ok = 0
        self._run_failed = 0
        self._attempted = False               # 한 번이라도 받기를 시작했는지 (이어서 작업하기 판단)
        self._auto_run = False                # ③ 을 눌렀다 — 목록을 읽으면 이어서 받는다(받기 전 확인은 그대로)
        self._rebudget_asked = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 26)
        layout.setSpacing(12)
        layout.addLayout(self._build_head())
        layout.addWidget(self._build_banner())

        # 단계 — 할 차례인 것만 보인다(flow.py)
        self.step_docs = self._build_docs()
        self.step_what = self._build_what()
        self.step_login = self._build_login()
        self.step_list = self._build_list()
        self.steps = {"docs": self.step_docs, "project": self.step_what, "login": self.step_login, "list": self.step_list}
        layout.addWidget(self.step_docs)
        layout.addWidget(self.step_what)
        layout.addWidget(self.step_login)
        layout.addWidget(self.step_list, 1)
        self.filler = QWidget()                # ④ 가 아직 없을 때 남는 높이를 채운다 — 단계가 화면 위쪽에 모여 있게
        self.filler.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout.addWidget(self.filler, 1)
        layout.addWidget(self._build_log(), 1)    # 펼치면 남는 높이를 단계와 나눠 받는다(높이를 숫자로 박지 않는다)

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
        w.list_ready.connect(self._on_list_ready)
        w.projects_read.connect(self._refresh_projects)
        w.rebudget_planned.connect(self._on_rebudget_planned)
        w.rebudget_applied.connect(self._on_rebudget_applied)
        w.sites_changed.connect(lambda _sites: self._sync_buttons())

        self.refresh_counts()
        self._set_state("준비", "neutral", "")
        self._sync_buttons()

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        """머리 — 그림 · 제목 · 한 줄 설명 / 오른쪽에 지금 상태 · 저장 폴더 · [진행 기록] · [도구]."""
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(Art("receive", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("증빙 다운로드")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        self.page_desc = muted_label("승인된 청구서를 ERP 에서 받아 과제 폴더 · 비목 폴더에 둡니다. ERP 에 입력 · 제출하지 않습니다.")
        texts.addWidget(self.page_desc)
        head.addLayout(texts, 1)
        self.state_pill = Pill("준비", "neutral")
        head.addWidget(self.state_pill, 0, Qt.AlignVCenter)
        self.folder_button = QPushButton()
        self.folder_button.setObjectName("ghost")
        self.folder_button.clicked.connect(self.need_settings.emit)
        head.addWidget(self.folder_button, 0, Qt.AlignVCenter)
        self.log_button = QPushButton("진행 기록")
        self.log_button.setObjectName("ghost")
        self.log_button.setCheckable(True)
        self.log_button.setToolTip("앱이 한 일을 차례로 적은 기록을 아래에 펼칩니다")
        self.log_button.toggled.connect(lambda on: self.log_card.setVisible(on))
        head.addWidget(self.log_button, 0, Qt.AlignVCenter)
        self.tools_button = QPushButton("도구")
        self.tools_button.setObjectName("ghost")
        self.tools_menu = QMenu(self.tools_button)
        self.unwanted_action = self.tools_menu.addAction("받지 않는 결의서", self._show_unwanted)
        self.rebudget_action = self.tools_menu.addAction("대응자금 파일 정리", self._rebudget)
        self.tools_menu.addSeparator()
        self.tools_menu.addAction("로그 파일 열기", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.log_path()))))
        self.tools_menu.addAction("자세한 안내", lambda: QMessageBox.information(self, "증빙 다운로드 — 자세한 안내", GUIDE_DETAIL))
        self.tools_button.setMenu(self.tools_menu)
        head.addWidget(self.tools_button, 0, Qt.AlignVCenter)
        return head

    def _build_docs(self) -> FlowStep:
        """① 받을 서류 — 청구서 · 구매요청(계약) 서류(준비 중). [다음] 으로 마친다.

        서류를 과제보다 먼저 고른다(담당자 2026-10-22 "받을 서류를 먼저 고르고 그다음 과제를 선택하도록") — 구매요청(계약) 서류는
        ERP 에서 과제를 고르지 않고 구매·자산 메뉴로 들어가되, 일자 범위를 ② 에서 고른 과제의 기간으로 둔다.
        """
        step = FlowStep("1", "무엇을 받을까요?", "받을 서류를 고르고 [다음] 을 누르세요. 여럿을 함께 고를 수 있습니다.")
        step.edit.connect(self._edit_docs)
        docs = QHBoxLayout()
        docs.setSpacing(16)
        docs_label = QLabel("받을 서류")
        docs_label.setObjectName("fieldLabel")
        docs.addWidget(docs_label, 0, Qt.AlignVCenter)
        self.doc_claim = QCheckBox("청구서(지출요구 및 결의서)")
        self.doc_claim.setChecked(True)
        self.doc_claim.toggled.connect(lambda _on: self._sync_buttons())
        docs.addWidget(self.doc_claim, 0, Qt.AlignVCenter)
        self.doc_contract = QCheckBox("구매요청(계약) 서류")
        self.doc_contract.setToolTip("구매·자산 메뉴 — 구매요청 때 올린 첨부 · 검사처리 때 올린 첨부 · 물품 사진을 받아 "
                                     "저장 폴더의 '구매요청(계약) 서류' 안에 과제별로 둡니다. 일자 범위는 ② 과제의 과제기간(2년씩)")
        self.doc_contract.toggled.connect(lambda _on: self._sync_buttons())
        docs.addWidget(self.doc_contract, 0, Qt.AlignVCenter)
        docs.addStretch(1)
        step.add_layout(docs)
        step.add(muted_label("구매요청(계약) 서류는 구매·자산 메뉴에서 구매요청 · 검사처리 때 올린 첨부와 물품 사진을 받아 "
                             "'구매요청(계약) 서류' 폴더에 과제별로 둡니다. 건마다 상세를 열어 보므로 이미 있는 파일은 건너뛰고 새 파일만 받습니다."))
        buttons = QHBoxLayout()
        self.docs_button = QPushButton("다음")
        self.docs_button.setObjectName("primary")
        self.docs_button.clicked.connect(self._confirm_docs)
        buttons.addWidget(self.docs_button)
        buttons.addStretch(1)
        step.add_layout(buttons)
        return step

    def _build_what(self) -> FlowStep:
        """② 어느 과제 — 과제 칸. [다음] 으로 마친다."""
        step = FlowStep("2", "어느 과제의 서류를 받을까요?", "과제를 고르고 [다음] 을 누르세요. 과제는 여러 개를 골라 차례로 받을 수 있습니다.")
        step.edit.connect(self._edit_what)
        row = QHBoxLayout()
        row.setSpacing(10)
        project_label = QLabel("과제")
        project_label.setObjectName("fieldLabel")
        row.addWidget(project_label, 0, Qt.AlignVCenter)
        # ERP 과제 — 일반청구와 같은 칸 · 같은 기본값(ui/project_box.py). 목록 읽기가 이 과제의 결의서내역으로 간다
        self.project_box = project_box.project_box()
        # 저장 폴더가 과제 폴더로 나뉘어 있으면 '폴더 만든 과제 모두' · '고른 과제 여럿' · 과제 하나씩 — 담당자 2026-10-21. 마지막 고른 것을 다시 쓴다
        scope = settings.load().download_scope
        start = {"some": project_folders.SOME, "one": project_box.last_project()}.get(scope, project_folders.ALL)
        if start == project_folders.SOME and not project_box.chosen_projects():
            start = project_folders.ALL
        project_box.fill_download_box(self.project_box, start)
        self._folders_seen = project_folders.signature(settings.load().out_root)
        self.project_box.currentIndexChanged.connect(self._project_changed)
        self.project_box.activated.connect(self._project_activated)
        project_label.setBuddy(self.project_box)
        row.addWidget(self.project_box, 0, Qt.AlignVCenter)
        row.addStretch(1)
        step.add_layout(row)
        buttons = QHBoxLayout()
        self.next_button = QPushButton("다음")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self._confirm_what)
        buttons.addWidget(self.next_button)
        buttons.addStretch(1)
        step.add_layout(buttons)
        return step

    def _build_login(self) -> FlowStep:
        """③ ERP 에 로그인 — [브라우저 열기] (열려 있으면 [안 받은 청구서 찾기])."""
        step = FlowStep("3", "ERP 에 로그인", editable=False)
        self.login_state = Pill("브라우저 닫힘", "neutral")
        step.add_side(self.login_state)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.open_button = QPushButton("브라우저 열기")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self._open)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        step.add_layout(buttons)
        return step

    def _build_list(self) -> FlowStep:
        """④ 받을 청구서 확인하고 받기 — 건수 한 줄 · 표 · [N건 받기] [앞 1건만 시험] [멈추기]."""
        step = FlowStep("4", "받을 서류를 확인하고 받으세요", editable=False)
        self.list_button = QPushButton("목록 다시 읽기")
        self.list_button.setObjectName("ghost")
        self.list_button.clicked.connect(self._read_list)
        step.add_side(self.list_button)
        self.counts = muted_label("")
        step.add(self.counts)
        self.list_stack = QStackedWidget()
        self.empty = EmptyState("receive", "", "")
        self.empty_settings_button = QPushButton("설정으로 이동")
        self.empty_settings_button.setObjectName("primary")
        self.empty_settings_button.clicked.connect(self.need_settings.emit)
        self.empty.add_action(self.empty_settings_button)
        self.list_stack.addWidget(self.empty)
        self.list_stack.addWidget(self._build_table())
        step.add(self.list_stack, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.all_button = QPushButton("받기")
        self.all_button.setObjectName("primary")
        self.all_button.clicked.connect(lambda: self._download(limit=0))
        actions.addWidget(self.all_button)
        self.test_button = QPushButton("앞 1건만 시험")
        self.test_button.clicked.connect(lambda: self._download(limit=1))
        actions.addWidget(self.test_button)
        self.stop_button = QPushButton("멈추기")
        self.stop_button.setObjectName("danger")
        self.stop_button.setToolTip("지금 받는 건을 마치고 멈춥니다")
        self.stop_button.clicked.connect(self._stop)
        actions.addWidget(self.stop_button)
        actions.addStretch(1)
        self.progress = muted_label("")
        actions.addWidget(self.progress, 0, Qt.AlignVCenter)
        step.add_layout(actions)
        return step

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

    def _build_log(self) -> QWidget:
        """진행 기록 — 머리의 [진행 기록] 을 눌렀을 때만 아래에 펼친다."""
        self.log_card = Card(margins=(16, 10, 16, 12))
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("foldLog")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_card.add(self.log_view, 1)
        self.log_card.hide()
        return self.log_card

    def _build_table(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
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
        waiting = sum(f.waiting for f in folders) if folders else 0
        if cfg.out_root:
            name = cfg.out_root.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            self.folder_button.setText(f"저장 폴더 · {name}" + (f" · 업로드 대기 {waiting}" if waiting else ""))
            self.folder_button.setToolTip(f"{cfg.out_root}\n업로드 대기 = 비목 폴더 바로 아래의 PDF {waiting}개\n누르면 설정에서 바꿀 수 있습니다")
        else:
            self.folder_button.setText("저장 폴더 지정하기")
            self.folder_button.setToolTip("")
        names = {p.no: p.name for p in navigate.load_projects()[0]}
        self.rebudget_action.setVisible(bool(rebudget.fund_folders(cfg.out_root, names)) if cfg.out_root else False)
        unwanted = len(skiplist.load())
        self.unwanted_action.setText(f"받지 않는 결의서 ({unwanted}건)")
        self.unwanted_action.setEnabled(unwanted > 0)
        self._sync_empty()
        self.counts_changed.emit()

    def _sync_counts(self) -> None:
        """④ 의 건수 한 줄과 진행 한 줄 — 같은 목록 기준으로 센다."""
        skipped = self._selection.skipped if self._selection else 0
        excluded = self._selection.excluded if self._selection else 0
        remaining = len(self._remaining())
        if self._reading and not self._listed:
            self.counts.setText("결의서내역 목록을 읽는 중입니다…")
        elif self._listed:
            self.counts.setText(f"받을 청구서 {len(self._targets)}건 · 이미 받아 둔 것 {skipped}건 제외"
                                + (f" · 받지 않는 결의서 {excluded}건 제외" if excluded else "")
                                + (f" · 남은 {remaining}건" if self._attempted else ""))
        else:
            self.counts.setText("")
        self.progress.setText(f"이번에 받음 {self._run_ok}건" + (f" · 실패 {self._run_failed}건" if self._run_failed else "")
                              if self._attempted else "")

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
                + "). 목록이 바뀌면 [목록 다시 읽기] 를 누르세요.")
            self.list_stack.setCurrentIndex(0)
        else:
            self.empty.set_content("receive", "결의서내역 목록을 읽는 중입니다", "다 읽으면 받을 청구서가 여기에 나옵니다.")
            self.list_stack.setCurrentIndex(0)

    def _set_state(self, text: str, status: str, guide: str | None = None) -> None:
        """머리의 상태 배지 + 지금 단계 아래 한 줄(guide)."""
        self.state_pill.set_status(text, status)
        if guide is not None:
            self._guide = guide
            self._sync_flow()

    def _remaining(self) -> list[int]:
        return [i for i, s in enumerate(self._status) if s not in ("done", "unwanted")]

    def _stage_guide(self) -> str:
        """지금 단계의 기본 안내 — 도구(대응자금 파일 정리 등)를 쓴 뒤 단계 안내로 돌아갈 때."""
        stage = download_stage(self._docs_picked, self._picked, self._reading, self._listed)
        if stage == "login":
            return GUIDE_BROWSER if self._browser_open else GUIDE_LOGIN
        if stage == "list" and self._listed and self._remaining():
            return GUIDE_LISTED
        return ""

    def _docs(self) -> tuple[bool, bool]:
        """(청구서, 구매요청(계약) 서류) 가 체크됐는지."""
        return self.doc_claim.isChecked(), self.doc_contract.isChecked()

    def _docs_text(self) -> str:
        docs = [name for box, name in ((self.doc_claim, "청구서"), (self.doc_contract, "구매요청(계약) 서류")) if box.isChecked()]
        return " · ".join(docs) or "고른 서류 없음"

    def _sync_flow(self) -> None:
        """할 차례인 단계만 보이게 — ① 마치기 전에는 ① 만, 목록을 읽으면 ④ 까지(ui/flowlogic.download_stage)."""
        stage = download_stage(self._docs_picked, self._picked, self._reading, self._listed)
        states = flow_states(DOWNLOAD_ORDER, stage)
        sites = getattr(self.worker, "sites", {}) or {}
        summaries = {"docs": self._docs_text(), "project": self._project_text(),
                     "login": "ERP 로그인됨" if sites.get("erp_login") else "브라우저 열림"}
        for key, step in self.steps.items():
            step.set_state(states[key], summaries.get(key))
            step.set_note(getattr(self, "_guide", "") if states[key] == CURRENT else "")
        self.filler.setVisible(states["list"] != CURRENT)

    def _sync_buttons(self) -> None:
        busy = self._busy
        self.project_box.setEnabled(not busy)
        self.docs_button.setEnabled(not busy and any(self._docs()))
        self.next_button.setEnabled(not busy and any(self._docs()))
        self.step_docs.edit_button.setEnabled(not busy)
        self.step_what.edit_button.setEnabled(not busy)
        # ③ — 브라우저가 열려 있으면 '고른 과제의 목록을 읽고 받기'(담당자 요청 2026-10-21)
        sites = getattr(self.worker, "sites", {}) or {}
        self.open_button.setEnabled(not busy)
        self.open_button.setText(("안 받은 청구서 찾기" if self._docs() == (True, False) else "받을 서류 찾기")
                                 if self._browser_open else "브라우저 열기")
        self.open_button.setToolTip("고른 과제의 목록을 읽고 아직 안 받은 서류를 찾습니다(받기 전에 묻습니다)"
                                    if self._browser_open else "ERP 창을 엽니다. 로그인하면 고른 과제의 안 받은 서류를 찾습니다")
        if not self._browser_open:
            self.login_state.set_status("브라우저 닫힘", "neutral")
        elif sites.get("erp_login"):
            self.login_state.set_status("로그인됨", "success")
        else:
            self.login_state.set_status("로그인 기다리는 중", "warning")
        # ④
        self.list_button.setEnabled(not busy and self._browser_open)
        remaining = len(self._remaining())
        can_run = not busy and self._browser_open and remaining > 0 and self._listed
        running = busy and bool(self._running_rows)
        self.all_button.setVisible(remaining > 0 and not running)
        self.test_button.setVisible(remaining > 0 and not running)
        self.all_button.setEnabled(can_run)
        self.all_button.setText(f"{remaining}건 받기" if remaining else "받기")
        self.test_button.setEnabled(can_run)
        self.stop_button.setVisible(running)
        self.stop_button.setEnabled(running)
        self.tools_button.setEnabled(not busy)
        self._sync_counts()
        self._sync_flow()

    # ── 단계 ① · ② ──────────────────────────────────────────────────────
    def _confirm_docs(self) -> None:
        if not any(self._docs()):
            return
        self._docs_picked = True
        self._set_state("과제 차례", "info", "")
        self._sync_buttons()

    def _edit_docs(self) -> None:
        if self._busy:
            return
        self._docs_picked = False
        self._edit_what()

    def _confirm_what(self) -> None:
        if not any(self._docs()):
            return
        if not settings.load().out_root:
            QMessageBox.information(
                self, "저장 폴더",
                "받은 청구서를 넣을 폴더를 먼저 지정해 주세요.\n과제 폴더('(과제번호)_…')나 비목 폴더(01. 인건비 …)가 바로 아래 있는 폴더입니다.")
            self.need_settings.emit()
            return
        if self._all() and not self._projects():
            self._set_state("과제 없음", "warning", "받을 과제를 고르세요 — 과제 칸의 '여러 과제 고르기…'.")
            return
        self._picked = True
        if self._browser_open and (getattr(self.worker, "sites", {}) or {}).get("erp_login"):
            # 다른 업무에서 이미 로그인해 둔 ERP — ③ 을 건너뛰고 바로 목록을 읽는다
            self._auto_run = True
            self._read_list()
            return
        self._set_state("로그인 차례", "info", GUIDE_LOGIN if not self._browser_open else GUIDE_BROWSER)
        self._sync_buttons()

    def _edit_what(self) -> None:
        if self._busy:
            return
        self._picked = False
        self._auto_run = False
        self._set_state("준비", "neutral", "")
        self._sync_buttons()

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
        self._docs_picked = self._picked = True
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
                self._picked = False
                self._set_state("과제 없음", "warning", "받을 과제를 고르세요 — 과제 칸의 '여러 과제 고르기…'.")
                return
            self._reading = True
            if self._docs()[1]:
                self._set_state("목록 읽는 중", "info", f"{self._project_text()}의 {self._lists_text()}을 읽고 있습니다…")
                self.worker.read_docs(projects, *self._docs())
                return
            self._set_state("목록 읽는 중", "info", f"{self._project_text()}의 결의서내역을 차례로 읽고 있습니다…")
            self.worker.read_lists(projects)
            return
        self._reading = True
        if self._docs()[1]:
            self._set_state("목록 읽는 중", "info", f"과제 {self._project()} 의 {self._lists_text()}을 읽고 있습니다…")
            self.worker.read_docs([self._project()], *self._docs())
            return
        self._set_state("목록 읽는 중", "info", f"과제 {self._project()} 의 결의서내역을 읽고 있습니다…")
        self.worker.read_list(self._project())

    def _lists_text(self) -> str:
        claims, purchases = self._docs()
        return " · ".join(name for on, name in ((claims, "결의서내역"), (purchases, "구매진행관리(구매·자산)")) if on)

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
            self._set_state("과제 바뀜", "info", f"과제가 바뀌었습니다. [다음] 을 누르면 {self._project_text()}의 결의서내역을 읽고 안 받은 청구서를 찾습니다.")
            self._sync_empty()
        self._sync_buttons()

    def _refresh_projects(self) -> None:
        """로그인 뒤 과제현황을 새로 읽었으면(또는 저장 폴더 · 과제 폴더가 바뀌면) 보기를 다시 채운다 — 고른 과제는 그대로."""
        self._folders_seen = project_folders.signature(settings.load().out_root)
        project_box.fill_download_box(self.project_box, self._project())

    def showEvent(self, event) -> None:  # noqa: N802
        """화면을 열 때 저장 폴더 아래 과제 폴더가 늘거나 줄었으면 과제 칸을 다시 채운다 — 담당자가 앱을 켠 채 과제 폴더를 더 만든 날
        (2026-10-22 연구지원비 다섯, "과제옵션에 추가해주세요") 앱을 다시 켜지 않아도 '폴더 만든 과제 모두 (N개)' 와 과제 하나씩이 바로 맞게."""
        super().showEvent(event)
        if project_folders.signature(settings.load().out_root) != self._folders_seen:
            self._refresh_projects()

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
                self._set_state("저장 폴더 바뀜", "warning", "저장 폴더가 바뀌었습니다. [안 받은 청구서 찾기] 를 다시 누르면 새 폴더를 훑고 받을 건을 다시 고릅니다.")
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
        """브라우저를 연 뒤 결의서내역 목록이 보인다 — ② 까지 마쳤고 아직 안 읽었고 다른 일이 없으면 목록을 대신 읽는다(읽기만)."""
        if self._busy or not self._browser_open or not self._picked:
            return
        if not self._auto_run and (self._listed or not settings.load().auto_read_list):
            return
        self._set_state("목록 발견", "info", "결의서내역 목록이 보여 저절로 읽습니다…")
        self._read_list()

    def _on_browser_state(self, alive: bool) -> None:
        """사용자가 브라우저 창을 닫아 버렸으면 ③ 부터 다시 하게 한다."""
        if self._browser_open and not alive:
            self._browser_open = False
            self._auto_run = False
            self._reading = False
            self._set_state("브라우저 닫힘", "neutral", "브라우저 창이 닫혔습니다. [브라우저 열기] 로 다시 여세요.")
        self._sync_buttons()
        self.counts_changed.emit()

    def _on_listed(self, selection) -> None:
        self._selection = selection
        self._listed = True
        self._reading = False
        self._docs_picked = self._picked = True
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
            if t.get("kind") == purchase.KIND and t.get("existing"):
                self._set_status(row, "waiting", f"폴더 있음(파일 {t['existing']}개) — 새 파일만 받습니다")
            else:
                self._set_status(row, "waiting")
        auto, self._auto_run = self._auto_run, False
        if self._targets:
            self._set_state("확인 대기", "info", GUIDE_LISTED)
            if auto:
                QTimer.singleShot(0, lambda: self._download(limit=0))     # 받기 전 확인 창은 그대로(9절)
        else:
            self._set_state("받을 건 없음", "warning" if selection.blocked else "success",
                            f"{self._project_text()}에 새로 받을 서류가 없습니다(이미 받은 {selection.skipped}건은 건너뜀). "
                            "목록이 바뀌면 [목록 다시 읽기] 를 누르세요.")
        if selection.blocked:
            # 폴더가 없거나 목록을 못 띄운 과제 — 받지 않은 까닭을 알린다(받을 것이 있는 과제는 그대로 받는다)
            self._set_state(self.state_pill.text(), "warning",
                            getattr(self, "_guide", "") + "\n받지 않은 과제: " + " · ".join(no or "(모름)" for no, _ in selection.blocked))
            QMessageBox.information(
                self, "받지 않은 과제",
                "아래 과제는 받지 않았습니다.\n\n" + "\n".join(f"· {no or '(모름)'}: {why}" for no, why in selection.blocked)
                + "\n\n목록을 못 띄운 과제는 브라우저에서 그 과제의 과제정보 → 청구서를 띄운 뒤, ② 의 과제 칸에서 그 과제를 골라 다시 하세요.")
        self._sync_empty()
        self._sync_buttons()
        self.counts_changed.emit()

    def _on_list_failed(self, message: str) -> None:
        self._auto_run = False
        self._reading = False
        self._set_state("목록 못 찾음", "danger", GUIDE_BROWSER)
        QMessageBox.warning(
            self, "목록을 찾지 못했습니다",
            f"{message}\n\n앱이 연 브라우저 창에서 로그인하고 [과제관리 → 과제정보 → 청구서] 의 "
            "'결의서내역' 목록을 띄웠는지 확인한 뒤 [안 받은 청구서 찾기] 를 다시 누르세요.\n열린 창 구조는 [진행 기록] 에 남겼습니다.")
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
        psum = getattr(summary, "purchase", None)
        if psum is not None:
            text += (f" 구매요청(계약) 서류 {len(psum.cases)}건 · 새 파일 {psum.files}개는 저장 폴더의 '{purchase.FOLDER_NAME}' 안 과제 폴더에 있습니다."
                     + (f" ({psum.note})" if psum.note else ""))
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
                "③ [브라우저 열기] 로 ERP 에 로그인한 뒤 [도구] → [대응자금 파일 정리] 를 다시 누르세요. (받기를 묻는 창이 뜨면 [아니요] 로 닫아도 됩니다)")
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
            self._set_state("준비", "neutral", self._stage_guide())
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
            self._set_state("준비", "neutral", self._stage_guide())

    def _on_rebudget_applied(self, moves) -> None:
        done = [m for m in moves if m.done]
        failed = [m for m in moves if not m.done]
        root = Path(settings.load().out_root or ".")
        notes = [f"{m.project} {m.place()} — {m.why}" for m in failed]
        empty = rebudget.emptied(moves)
        if empty:
            notes.append("비게 된 옛 폴더(필요 없으면 지우세요): " + " · ".join(_rel_name(p, root) for p in empty))
        self.refresh_counts()
        self._set_state("대응자금 파일 정리 끝", "success" if not failed else "warning", self._stage_guide())
        show_report(self, title="대응자금 파일 정리", heading=f"옮김 {len(done)}개" + (f" · 못 옮김 {len(failed)}개" if failed else ""),
                    tone="success" if not failed else "warning", notes=notes,
                    columns=[("결과", 104), ("과제", 118), ("전 (과제 폴더 안)", 400), ("후", None)],
                    rows=[ReportRow("옮김" if m.done else "못 옮김", "success" if m.done else "danger",
                                    [m.project, m.place(), m.to()], detail=m.why) for m in moves])

    def _on_failed(self, owner: str, message: str) -> None:
        """이 화면이 넣은 명령의 오류만 — 일반청구가 넣은 명령의 오류는 그 화면이 알린다."""
        if owner != "download":
            return
        self._rebudget_asked = False
        self._on_error(message)

    def _on_error(self, message: str) -> None:
        self._auto_run = False
        self.banner.hide()
        if "Executable doesn't exist" in message or "msedge" in message:
            message = ("브라우저를 띄우지 못했습니다. [앱 실행.bat] 을 다시 실행해 준비를 마치거나, "
                       "Microsoft Edge 가 설치되어 있는지 확인하세요.\n\n" + message)
        self._reading = False
        self._set_state("오류", "danger")
        QMessageBox.warning(self, "문제가 생겼습니다", f"{message}\n\n자세한 내용은 위쪽 [진행 기록] 과 로그 파일에 있습니다.")
        self._sync_buttons()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """창이 낮으면 머리 설명을 접어 표에 자리를 준다. 글씨는 줄이지 않는다."""
        super().resizeEvent(event)
        self.page_desc.setVisible(self.height() >= 600)

    def shutdown(self) -> None:
        if self._owns_worker:
            self.worker.shutdown()
