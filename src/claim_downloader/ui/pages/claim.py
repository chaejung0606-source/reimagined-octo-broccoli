"""일반청구 화면 — 지출 폴더를 넣고 [내용 읽기] → 값을 고치고 → [ERP 에 채우기] → 사람이 입금처·첨부 → [임시저장] → 사람이 검토·신청.

폴더마다 **청구 종류**를 고른다(claims/kinds.py, 담당자 제안 2026-10-14) — 일반(AI 가 서류를 읽음) · 장학금(명단 엑셀 + 공통/개별증빙,
오른쪽 칸이 학생 표로 바뀌고 [ERP 에 넣기] 가 학생마다 인건비 탭에 넣고 저장) · 출장비 · 카드(준비 중, 고를 수 없음). '자동' 이면 폴더 모양으로 정한다.

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
import re

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
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

from ... import ai, settings
from ...claims import kinds, record, rules, schema
from ...claims import scholarship as sch
from ...minutes.backends import claude_cli
from .. import ai_status
from ..art import Art
from ..claim_worker import ClaimExtractWorker
from ..report_dialog import ReportRow, show_report, show_structure_saved
from ..widgets import Card, EmptyState, Field, Pill, PillDelegate, WrapLabel, muted_label
from ..worker import SessionWorker
from .scholarship import ScholarshipPanel

COLUMNS = [("상태", 96), ("종류", 108), ("지출 (폴더)", 200), ("적요", 280), ("청구액", 110), ("입금처", None)]
COL_STATUS, COL_KIND, COL_DIR, COL_SUMMARY, COL_AMOUNT, COL_PAYEE = 0, 1, 2, 3, 4, 5

ROW_STATUS = {
    "waiting": ("대기", "neutral"),
    "running": ("읽는 중", "info"),
    "read": ("읽음", "success"),
    "failed": ("실패", "danger"),
    "skipped": ("건너뜀", "warning"),
    "stopped": ("안 함", "neutral"),
    "filled": ("채움", "success"),
    "saved": ("임시저장", "success"),
    "problem": ("확인 필요", "warning"),
    "erp": ("넣는 중", "info"),
    "partial": ("일부 저장", "warning"),
}

GUIDE_START = "청구 종류를 고르고 지출 폴더를 추가하세요. 일반은 [내용 읽기], 장학금 · 혁신인재지원금은 바로 오른쪽에 학생 명단이 나옵니다."
GUIDE_SCHOLARSHIP = ("학생 표를 확인한 뒤, 브라우저에서 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우고 [ERP 에 넣기] 를 누르세요. "
                     "인건비 탭은 앱이 누릅니다.")
GUIDE_READ = ("값을 확인한 뒤, 브라우저에서 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우고 [미리 보기] 로 확인하세요. "
              "실제로 넣으려면 '미리 보기만' 체크를 풀고 [ERP 에 채우기].")
NO_BACKEND = ("일반 폴더의 [내용 읽기] 는 Claude Code 가 필요합니다(장학금 · 혁신인재지원금은 AI 없이 됩니다). Claude Code 를 설치한 뒤 "
              "[다시 확인] 을 누르세요. 설치했는데도 이 안내가 보이면 컴퓨터를 다시 시작해 보세요.")


def _money(value) -> str:
    return f"{value:,}" if isinstance(value, int) else ""


# 장학금 미리 보기 · 넣기 확인 · 결과 창의 표 (ui/report_dialog.py) — 사람마다 한 줄
SCH_COLUMNS = [("상태", 104), ("No", 44), ("이름", 92), ("학번", 104), ("청구액", 92), ("개별 적요", 300), ("첨부", 56), ("확인할 것", None)]
SCH_STATUS = {"planned": ("넣을 것", "neutral"), "saved": ("임시저장", "success"), "review": ("저장·확인", "warning"),
              "stopped": ("멈춤", "warning"),
              "failed": ("실패", "danger"), "waiting": ("대기", "neutral")}


def sheet_check_rows(check) -> list[ReportRow]:
    """신청 전 대조의 줄(사람마다 · 합계) — '✓ …' 맞음, '! …' 확인(두 번 · 금액 다름), '· …' 청구내역에 없음."""
    rows = []
    for line in check.lines:
        mark, _, text = line.partition(" ")
        status, tone = {"✓": ("맞음", "success"), "!": ("확인", "warning")}.get(mark, ("없음", "neutral"))
        rows.append(ReportRow(status, tone, [text], tips={0: text}))
    return rows


def scholarship_rows(job, results) -> list[ReportRow]:
    """결과(PersonResult)마다 표 한 줄. 긴 값(첨부 목록 · 진행 단계)은 '자세히' 칸으로."""
    rows = []
    for r in results:
        status, tone = SCH_STATUS.get(r.status, (r.status, "neutral"))
        if r.status == "planned" and r.note:
            status, tone = "확인 필요", "warning"
        if r.status == "saved" and r.review:
            status, tone = SCH_STATUS["review"]
        main = job.main_summary if job is not None else ""
        # 줄마다 앞의 대표적요는 같다 — 줄을 가르는 뒷부분(_이름 · (이름_교과목))이 보이게 앞을 줄인다
        shown = "…" + r.summary[len(main):] if main and r.summary.startswith(main) and r.summary != main else r.summary
        personal = len(r.files) - r.common_count
        base = job.folder if job is not None else ""
        detail = [f"{r.index + 1}. {r.name}  ·  학번 {r.student_no or '—'}" + (f"  ·  교과목 {r.course}" if r.course else "")
                  + f"  ·  청구액 {_money(r.amount) or '—'}원",
                  f"개별 적요: {r.summary}",
                  f"첨부 {len(r.files)}개 (공통 {r.common_count} · 개별 {personal})"]
        for i, path in enumerate(r.files):
            name = os.path.relpath(path, base) if base else os.path.basename(path)
            detail.append(f"  [{'공통' if i < r.common_count else '개별'}] {name}")
        for item in r.review:
            detail.append(f"신청 전 확인: {item}")
        if r.note and not r.review:
            detail.append(f"확인할 것: {r.note}")
        if r.status != "planned" and r.lines:
            detail.append("진행:")
            detail.extend("  " + line for line in r.lines)
        rows.append(ReportRow(status, tone, [str(r.index + 1), r.name, r.student_no or "—", _money(r.amount) or "—",
                                             shown, f"{len(r.files)}개", " / ".join(r.review) or r.note],
                              detail="\n".join(detail), tips={4: r.summary}, right=(3, 5)))
    return rows


class ClaimPage(QWidget):
    busy_changed = Signal(bool)
    need_settings = Signal()        # [설정에서 바꾸기] — AI 플랫폼은 설정에서 고른다
    attention = Signal()            # 노란 띠에서 사람을 기다림 — 다른 탭에 있으면 이 화면으로(app._wire)

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
        self._kinds: list[str] = []                      # 폴더마다 청구 종류 (kinds.GENERAL · SCHOLARSHIP)
        self._jobs: list[sch.Job | None] = []            # 장학금 폴더의 명단 · 증빙
        self._running = False
        self._erp_running = False                        # 장학금을 ERP 에 넣는 중 (브라우저 스레드)
        self._stopping = False
        self._capture_asked = False
        self._erp_row = -1
        self._browser_busy = False
        self._browser_open = False
        self._available: bool | None = None
        self._backend_state = ""
        self._backend_key = ai.chosen("claim")
        self._done_count = 0
        self._current = -1
        self._loading_form = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 26)
        layout.setSpacing(12)
        layout.addLayout(self._build_head())
        self.platform = ai_status.PlatformRow("claim")
        self.platform.changed.connect(self._on_platform)
        self.platform.settings_requested.connect(self.need_settings.emit)
        layout.addWidget(self.platform)
        layout.addWidget(self._build_banner())
        layout.addWidget(self._build_ask_banner())
        layout.addWidget(self._build_drop_zone())
        layout.addLayout(self._build_middle(), 1)
        layout.addLayout(self._build_bottom_row())

        e = self.extractor
        e.log.connect(self._append_log)
        e.busy.connect(self._on_extract_busy)
        e.started.connect(self._on_started)
        e.done.connect(self._on_done)
        e.skipped.connect(self._on_skipped)
        e.stopped.connect(self._on_stopped)
        e.finished.connect(self._on_finished)
        e.error.connect(self._on_extract_error)
        b = self.browser
        b.log.connect(self._append_log)
        b.busy.connect(self._on_browser_busy)
        b.browser_opened.connect(self._on_browser_opened)
        b.browser_state.connect(self._on_browser_state)
        b.claim_filled.connect(self._on_claim_filled)
        b.claim_saved.connect(self._on_claim_saved)
        b.payee_searched.connect(self._on_payee_searched)
        b.taxbill_searched.connect(self._on_taxbill_searched)
        b.scholarship_person.connect(self._on_sch_person)
        b.scholarship_ask.connect(self._on_sch_ask)
        b.scholarship_done.connect(self._on_sch_done)
        b.sheet_checked.connect(self._on_sheet_checked)
        b.structure_saved.connect(self._on_structure_saved)
        b.failed.connect(self._on_browser_failed)

        self._show_form(-1)
        self._on_platform(self.platform.status())

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(12)
        self.head_art = Art("claim", 52)
        head.addWidget(self.head_art, 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = self.head_title = QLabel("일반청구")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        self.page_desc = muted_label(
            "지출 폴더마다 청구 종류(일반 · 장학금 …)를 고르면 ERP 일반청구 작성 화면에 채우고 임시저장까지 합니다. "
            "[신청] 은 직접 합니다. 일반 폴더의 자료는 선택한 AI 플랫폼으로 전송됩니다.")
        texts.addWidget(self.page_desc)
        head.addLayout(texts, 1)
        rules_button = QPushButton("규칙 파일 열기")
        rules_button.setObjectName("ghost")
        rules_button.setToolTip("폴더에서 무엇을 어떻게 뽑을지 적은 규칙. 저장만 하면 다음 읽기부터 반영됩니다.")
        rules_button.clicked.connect(self._open_rules)
        head.addWidget(rules_button, 0, Qt.AlignVCenter)
        return head

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

    def _build_ask_banner(self) -> QFrame:
        """장학금을 넣다가 앱이 확신하지 못하는 단계 — 사람이 ERP 에서 하고 [계속]."""
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

    @staticmethod
    def _kind_box(with_auto: bool) -> QComboBox:
        """청구 종류 고르기 칸 — 준비 중인 종류는 보이되 고를 수 없다."""
        box = QComboBox()
        if with_auto:
            box.addItem("자동 (폴더 모양으로)", kinds.AUTO)
        for kind in kinds.KINDS:
            box.addItem(kind.name if kind.ready else f"{kind.name} (준비 중)", kind.key)
            index = box.count() - 1
            box.setItemData(index, kind.hint, Qt.ToolTipRole)
            if not kind.ready:
                box.model().item(index).setEnabled(False)
        return box

    def _build_drop_zone(self) -> QFrame:
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setFixedHeight(76)
        row = QHBoxLayout(self.drop_zone)
        row.setContentsMargins(18, 10, 14, 10)
        row.setSpacing(12)
        self.drop_art = Art("archive", 52)
        row.addWidget(self.drop_art, 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        hint = QLabel("여기에 지출 폴더를 끌어다 놓으세요")
        hint.setObjectName("cardTitle")
        texts.addWidget(hint)
        # 칸 높이가 76 으로 정해져 있어 좁은 창에서 세 줄이 되면 아래가 잘렸다 — 두 줄 안에 들게 줄이고 자세한 것은 말풍선으로
        detail = muted_label("폴더 1개 = 청구 1건. '자동' 은 폴더 모양과 이름으로 종류를 정합니다.")
        detail.setToolTip("명단 엑셀 + 공통·개별증빙 폴더가 있으면 장학금, 이름에 '혁신인재' 가 있으면 혁신인재지원금, 아니면 일반으로 봅니다.")
        texts.addWidget(detail)
        row.addLayout(texts, 1)
        kind_label = QLabel("청구 종류")
        kind_label.setObjectName("fieldLabel")
        row.addWidget(kind_label, 0, Qt.AlignVCenter)
        self.add_kind = self._kind_box(with_auto=True)
        self.add_kind.setToolTip("다음에 넣는 폴더의 청구 종류. 넣은 뒤에도 오른쪽 칸 위에서 바꿀 수 있습니다.")
        kind_label.setBuddy(self.add_kind)
        row.addWidget(self.add_kind, 0, Qt.AlignVCenter)
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
        self.middle = row
        return row

    def _set_wide_form(self, wide: bool) -> None:
        """장학금은 오른쪽 학생 표가 넓어야 해서 왼쪽 목록과 폭을 바꾼다."""
        self.middle.setStretch(0, 2 if wide else 3)
        self.middle.setStretch(1, 3 if wide else 2)

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
        # [로그 파일 열기] 는 진행 기록 탭 안에 둔다 — 장학금 줄을 고르면 이 칸이 좁아져(2:3) 모서리 단추 둘이 탭 글자를
        # 밀어내 '진행 기록' 이 잘리고 화살표가 생겼다(1024px 창, 2026-10-14 점검).
        log_bar = QHBoxLayout()
        log_bar.setContentsMargins(0, 0, 0, 6)
        log_bar.addStretch(1)
        open_log = QPushButton("로그 파일 열기")
        open_log.setObjectName("ghost")
        open_log.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.log_path()))))
        log_bar.addWidget(open_log)
        log_layout.addLayout(log_bar)
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
        # 진단 모드 — 청구서 받기 화면과 같은 단추(담당자 요청 2026-10-14). 장학금 노란 띠에서 기다리는 중에도 눌러
        # 그때 열어 둔 팝업(국적 돋보기 등)을 실측할 수 있다 — 브라우저 스레드가 기다리는 자리에서 읽는다(worker._wait_resume).
        self.structure_button = QPushButton("화면 구조 저장")
        self.structure_button.setObjectName("ghost")
        self.structure_button.setToolTip(
            "지금 브라우저에 열린 ERP 화면(팝업 포함)의 창·프레임·입력 요소를 _화면구조.txt 로 저장합니다. "
            "읽기만 하고 아무것도 누르거나 넣지 않습니다. 새 화면을 자동화하기 전 실측용입니다.")
        self.structure_button.clicked.connect(self._capture_structure)
        corner_row.addWidget(self.structure_button)
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
        # 고른 폴더의 청구 종류 — 여기서 바꾸면 오른쪽 칸이 그 종류의 칸으로 바뀐다
        self.row_kind = self._kind_box(with_auto=False)
        self.row_kind.setToolTip("이 지출 폴더의 청구 종류")
        self.row_kind.currentIndexChanged.connect(self._row_kind_changed)
        card.add_header_widget(self.row_kind)
        self.form_stack = QStackedWidget()
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
        self.form_stack.addWidget(scroll)
        self.scholarship_panel = ScholarshipPanel()
        self.scholarship_panel.changed.connect(self._on_panel_changed)
        self.scholarship_panel.reload_requested.connect(self._reload_scholarship)
        # 낮은 창(720)에서는 칸 · 표 · 합계 줄이 다 안 들어간다 — 겹치지 않고 스크롤되게 감싼다
        self.scholarship_scroll = QScrollArea()
        self.scholarship_scroll.setWidgetResizable(True)
        self.scholarship_scroll.setFrameShape(QFrame.NoFrame)
        self.scholarship_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scholarship_scroll.setWidget(self.scholarship_panel)
        self.form_stack.addWidget(self.scholarship_scroll)
        card.add(self.form_stack, 1)
        self.form_card = card
        return card

    def _build_bottom_row(self) -> QVBoxLayout:
        """두 줄 — 위는 상태 · 안내 · 진행, 아래는 단추. 한 줄에 다 두면 일반 줄을 채운 뒤(세금계산서 · 입금처 · 임시저장)
        1120px 창에서 단추 글자가 잘리고 안내가 9줄로 접혔다(2026-10-14 점검)."""
        bottom = QVBoxLayout()
        bottom.setSpacing(8)
        status = QHBoxLayout()
        status.setSpacing(10)
        self.state_pill = Pill("준비", "neutral")
        status.addWidget(self.state_pill, 0, Qt.AlignVCenter)
        self.guide = QLabel(GUIDE_START)
        self.guide.setObjectName("body")
        self.guide.setWordWrap(True)
        status.addWidget(self.guide, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(160, 8)
        self.progress.setRange(0, 1)
        status.addWidget(self.progress, 0, Qt.AlignVCenter)
        self.progress_label = QLabel("0 / 0")
        self.progress_label.setObjectName("muted")
        self.progress_label.setMinimumWidth(48)
        status.addWidget(self.progress_label, 0, Qt.AlignVCenter)
        bottom.addLayout(status)
        row = QHBoxLayout()
        row.setSpacing(10)
        bottom.addLayout(row)
        self.stop_button = QPushButton("멈추기")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self._stop)
        row.addWidget(self.stop_button)
        self.read_button = QPushButton("내용 읽기")
        self.read_button.clicked.connect(self._read_all)
        row.addWidget(self.read_button)
        self.open_button = QPushButton("브라우저 열기")
        self.open_button.setToolTip("앱이 연 브라우저에서 ERP 로그인 → 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우세요")
        self.open_button.clicked.connect(lambda: self.browser.open_browser(scan=False, owner="claim"))
        row.addWidget(self.open_button)
        row.addStretch(1)
        self.dry_run = QCheckBox("미리 보기만")
        self.dry_run.setChecked(True)
        self.dry_run.setToolTip("체크돼 있으면 ERP 에 넣지 않고 무엇을 넣을지만 보여 줍니다. 풀면 실제로 채웁니다 (저장·신청은 그래도 직접).")
        self.dry_run.toggled.connect(lambda _c: self._sync_buttons())
        row.addWidget(self.dry_run)
        # 팝업(세금계산서·입금처)에서 결과가 하나로 확실하면 앱이 골라 [확인] 까지 — 애매하면 사람 (담당자 결정 2026-10-13)
        self.auto_pick = QCheckBox("팝업 자동 선택")
        self.auto_pick.setChecked(bool(settings.load().claim_auto_pick))
        self.auto_pick.setToolTip("세금계산서·입금처 팝업에서 사업자번호·금액이 맞는 결과가 하나뿐이면 앱이 고르고 [확인] 까지 누릅니다.\n"
                                  "여러 개이거나 정보가 모자라면 고르지 않고 두므로 직접 고르세요.")
        self.auto_pick.toggled.connect(lambda on: settings.update(claim_auto_pick=bool(on)))
        row.addWidget(self.auto_pick)
        self.fill_button = QPushButton("ERP 에 채우기")
        self.fill_button.setObjectName("primary")
        self.fill_button.clicked.connect(self._fill)
        row.addWidget(self.fill_button)
        # 명단 줄 — [신청] 전에 ERP 청구내역 표를 다시 읽어 명단과 맞춰 본다(읽기만). 넣기를 마치면 저절로도 한 번 한다.
        self.sheet_button = QPushButton("청구내역 대조")
        self.sheet_button.setToolTip("ERP 작성 화면의 청구내역 표를 읽어 명단과 맞춰 봅니다 — 두 번 들어간 사람 · 빠진 사람 · 다른 금액 ·\n"
                                     "명단에 없는 줄 · 합계와 공제합계. 읽기만 하고 아무것도 누르지 않습니다.")
        self.sheet_button.clicked.connect(self._check_sheet)
        row.addWidget(self.sheet_button)
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
        return bottom

    # ── 상태 ────────────────────────────────────────────────────────────
    def _kind(self, row: int) -> str:
        return self._kinds[row] if 0 <= row < len(self._kinds) else kinds.GENERAL

    def _unread_rows(self) -> list[int]:
        """AI 로 읽을 폴더 — 일반 종류만. 장학금은 넣을 때 명단을 바로 읽는다."""
        return [i for i, st in enumerate(self._status)
                if self._kinds[i] == kinds.GENERAL and st in ("waiting", "failed", "skipped", "stopped")]

    def _sync_buttons(self) -> None:
        running = self._running
        busy = running or self._erp_running
        can_edit = not busy
        for widget in (self.add_one_button, self.add_parent_button, self.add_kind):
            widget.setEnabled(can_edit)
        self.platform.set_enabled_for_run(not running)
        self.clear_button.setEnabled(can_edit and bool(self._dirs))
        self.table.setEnabled(not self._erp_running)          # 넣는 중에는 다른 줄로 옮기지 않게
        unread = self._unread_rows()
        self.read_button.setEnabled(can_edit and bool(unread) and self._available is True)
        self.read_button.setText("읽는 중…" if running else f"{len(unread)}건 내용 읽기" if unread else "내용 읽기")
        if not busy:
            self._stopping = False
        self.stop_button.setVisible(busy)
        self.stop_button.setEnabled(busy and not self._stopping)      # 한 번 멈춘 뒤 다음 작업에서 다시 눌리게
        self.open_button.setVisible(not self._browser_open)
        self.open_button.setEnabled(not self._browser_busy)
        self.row_kind.setEnabled(can_edit and 0 <= self._current < len(self._dirs))
        dry = self.dry_run.isChecked()
        is_sch = kinds.uses_roster(self._kind(self._current)) and 0 <= self._current < len(self._dirs)
        if is_sch:
            job = self._jobs[self._current]
            chosen = len(job.chosen()) if job is not None else 0
            self.fill_button.setEnabled(chosen > 0 and not busy and not self._browser_busy and (dry or self._browser_open))
            count = job.count_text() if job is not None else "0명"
            self.fill_button.setText(f"미리 보기 ({count})" if dry else f"ERP 에 넣기 ({count})")
            self.fill_button.setToolTip("" if dry or self._browser_open else "먼저 [브라우저 열기] 로 ERP 를 열고 새 청구서 화면을 띄우세요.")
            self.sheet_button.setEnabled(job is not None and self._browser_open and not busy and not self._browser_busy)
        else:
            has_row = 0 <= self._current < len(self._dirs) and self._status[self._current] in ("read", "filled", "saved")
            self.fill_button.setEnabled(has_row and self._browser_open and not self._browser_busy and not busy)
            self.fill_button.setText("미리 보기" if dry else "ERP 에 채우기")
            self.fill_button.setToolTip("" if self._browser_open else
                                        "일반 줄은 미리 보기도 ERP 작성 화면을 봅니다 — 먼저 [브라우저 열기] 로 새 청구서 화면을 띄우세요.")
        self.sheet_button.setVisible(is_sch)
        filled = (not is_sch and 0 <= self._current < len(self._dirs)
                  and self._status[self._current] in ("filled", "saved"))
        self.save_button.setVisible(filled)
        self.save_button.setEnabled(filled and self._browser_open and not self._browser_busy and not running)
        self.payee_button.setVisible(filled)
        self.payee_button.setEnabled(filled and self._browser_open and not self._browser_busy and not running)
        from ...claims import taxbill
        is_taxbill = filled and taxbill.wanted(self._data[self._current])
        self.taxbill_button.setVisible(is_taxbill)
        self.taxbill_button.setEnabled(is_taxbill and self._browser_open and not self._browser_busy and not running)
        # 브라우저가 다른 일을 하는 중에는 큐에서 기다리게 되므로 막는다 — 단, 노란 띠에서 기다리는 중이면 바로 읽힌다
        self.structure_button.setEnabled(self._browser_open and (not self._browser_busy or self.ask_banner.isVisible()))
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
        job = self._jobs[row] if row < len(self._jobs) else None
        if job is not None:
            # 장학금 — 적요는 대표적요, 금액은 넣을 사람 합계, 입금처 칸에는 사람 수
            chosen = job.chosen()
            data = {"summary": job.main_summary or "(대표적요 없음)",
                    "amount": sum(job.people[i].amount or 0 for i in chosen),
                    "payeeName": f"학생 {job.count_text(chosen)}" + (f" / 명단 {job.count_text(list(range(len(job.people))))}"
                                                                        if len(chosen) != len(job.people) else "")}
        kind_item = QTableWidgetItem(kinds.name_of(self._kind(row)))
        kind_item.setToolTip(kinds.name_of(self._kind(row)) + " — " + kinds.find(self._kind(row)).hint)
        self.table.setItem(row, COL_KIND, kind_item)
        for col, value in ((COL_SUMMARY, data.get("summary", "")), (COL_AMOUNT, _money(data.get("amount"))),
                           (COL_PAYEE, data.get("payeeName", ""))):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            if col == COL_AMOUNT:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, col, item)

    def is_running(self) -> bool:
        return self._running or self._erp_running

    def resumable(self) -> tuple[bool, str]:
        if self._running:
            remaining = sum(1 for s in self._status if s in ("waiting", "running"))
            return True, f"읽는 중 · 남은 {remaining}건"
        if self._erp_running:
            return True, "명단 청구(장학금 등)를 ERP 에 넣는 중"
        return False, ""

    # ── 폴더 목록 ────────────────────────────────────────────────────────
    def add_folder(self, path: str, kind: str | None = None) -> bool:
        """폴더 하나를 목록에 넣는다. kind 를 안 주면 위의 '청구 종류' 칸(자동이면 폴더 모양)으로 정한다."""
        path = os.path.abspath(path)
        if not os.path.isdir(path) or path in self._dirs or self._running or self._erp_running:
            return False
        try:
            kind = kinds.resolve(kind or self.add_kind.currentData() or kinds.AUTO, path)
        except ValueError as error:
            QMessageBox.information(self, "청구 종류", str(error))
            return False
        self._dirs.append(path)
        self._status.append("waiting")
        self._data.append(schema.normalize({}))
        self._problems.append([])
        self._kinds.append(kind)
        self._jobs.append(None)
        row = self.table.rowCount()
        self.table.setRowCount(row + 1)
        name = QTableWidgetItem(f"{os.path.basename(path)}  ·  {os.path.dirname(path)}")
        name.setToolTip(path)
        self.table.setItem(row, COL_DIR, name)
        self._set_status(row, "waiting")
        if kinds.uses_roster(kind):
            self._load_scholarship(row)
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
        if self._erp_running:
            return
        self._dirs, self._status, self._data, self._problems = [], [], [], []
        self._kinds, self._jobs = [], []
        self._current = -1
        self._done_count = 0
        self.table.setRowCount(0)
        self._set_progress(0, 0)
        self._set_state("준비", "neutral", GUIDE_START)
        self._show_form(-1)
        self._sync_buttons()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if not self._running and not self._erp_running and any(os.path.isdir(u.toLocalFile()) for u in event.mimeData().urls()):
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
        kind = self._kind(row)
        self._loading_form = True
        self.row_kind.blockSignals(True)
        self.row_kind.setCurrentIndex(max(self.row_kind.findData(kind), 0))
        self.row_kind.blockSignals(False)
        if kinds.uses_roster(kind) and 0 <= row < len(self._jobs):
            self.form_stack.setCurrentWidget(self.scholarship_scroll)
            self.scholarship_panel.set_job(self._jobs[row])
            self.form_card.title_label.setText(f"{kinds.name_of(kind)} 청구")
            self.form_card.hint_label.setText("학생마다 인건비 탭에 넣고 [저장] 합니다. 빼고 싶은 학생은 체크를 푸세요.")
            self._set_wide_form(True)
            self.form_card.setEnabled(True)
            self._loading_form = False
            if not self.is_running():
                self.guide.setText(GUIDE_SCHOLARSHIP)
            return
        self.form_stack.setCurrentIndex(0)
        self.form_card.title_label.setText("청구 내용")
        self.form_card.hint_label.setText("읽은 값입니다. 틀린 곳은 여기서 고치세요 — ERP 에는 이 값이 들어갑니다.")
        self._set_wide_form(False)
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
    def _on_platform(self, status: ai.Status) -> None:
        """설정에서 고른 플랫폼의 상태(ui/ai_status.py). 읽는 중에는 쓰던 플랫폼 그대로 간다."""
        if self._running:
            return
        self._backend_key = status.key
        self._backend_state = status.state
        self._available = None if status.state == ai.CHECKING else status.usable
        if status.state in (ai.MISSING, ai.ERROR):
            self.banner_text.setText(NO_BACKEND if status.key == claude_cli.ClaudeCliBackend.key and status.state == ai.MISSING
                                     else status.note or "AI 플랫폼을 확인하지 못했습니다. [다시 확인] 을 눌러 보세요.")
            self.banner.show()
        else:
            self.banner.hide()
        self._sync_buttons()

    def _open_rules(self) -> None:
        rules.load_rules()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.claims_rules_path())))

    # ── 읽기 ────────────────────────────────────────────────────────────
    def _read_all(self) -> None:
        if self._running or self._available is not True:
            return
        rows = self._unread_rows()
        # '지급내역' 엑셀이 있는 폴더는 명단 청구(장학금 · 혁신인재지원금)일 가능성이 크다 — 그 종류는 AI 없이 엑셀에서 바로 읽는다.
        # 일반으로 두면 AI 가 그 엑셀을 찍은 PDF 까지 읽어 사용량이 많이 든다(담당자 요청 2026-10-19: 원본이 엑셀이면 엑셀을 먼저).
        rosters = [i for i in rows if kinds.roster_excels(self._dirs[i])]
        if rosters:
            names = "\n".join(f"· {os.path.basename(self._dirs[i])} — {kinds.roster_excels(self._dirs[i])[0]}" for i in rosters[:6])
            answer = QMessageBox.question(
                self, "지급내역 엑셀이 있는 폴더",
                f"아래 {len(rosters)}개 폴더에는 지급내역 엑셀이 있습니다.\n{names}\n\n"
                "장학금 · 혁신인재지원금이면 표 위 '청구 종류' 를 바꾸세요 — AI 없이 엑셀에서 바로 읽습니다.\n"
                "[예] 이 폴더들은 AI 로 읽지 않고 건너뜀 · [아니요] 그래도 AI 로 읽기",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                rows = [i for i in rows if i not in rosters]
        if not rows:
            return
        if self._backend_state == ai.NO_LOGIN:
            if QMessageBox.question(self, "로그인 확인", claude_cli.LOGIN_HELP,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        if QMessageBox.question(
                self, "내용 읽기",
                f"지출 {len(rows)}건의 자료가 '{ai.label_of(self._backend_key)}' 로 전송되어 값을 뽑습니다.\n"
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
        self.extractor.run([self._dirs[i] for i in rows], self._backend_key)

    def _stop(self) -> None:
        self._stopping = True
        if self._erp_running:
            self.browser.request_stop()
            self.stop_button.setEnabled(False)
            self._set_state("멈추는 중", "warning", "지금 넣는 학생까지 마치고 멈춥니다…")
            return
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
        self._on_platform(self.platform.status())       # 읽는 동안 바뀐 설정·로그인 상태를 이제 반영
        self.busy_changed.emit(False)
        summary = f"읽음 {ok_count}건 · 실패 {fail_count}건"
        if stop == "login":
            name = ai.short_label(self._backend_key)
            self._set_state("로그인 필요", "danger", summary + f" — {name} 로그인이 풀려 남은 폴더를 건너뛰었습니다. "
                            "위쪽 AI 단추에서 로그인한 뒤 다시 읽으세요.")
            status = ai_status.instance()
            status.mark(self._backend_key, ai.NO_LOGIN, "작업 중 로그인이 풀렸습니다")
            if QMessageBox.question(
                    self, "로그인이 풀렸습니다",
                    f"{name} 로그인이 풀려 있어 지출 자료를 읽지 못했습니다.\n\n지금 로그인 창을 열까요?\n"
                    "(로그인을 마치면 위쪽 AI 단추가 '로그인됨' 으로 바뀝니다. 그 뒤 [내용 읽기] 를 다시 누르시면 됩니다.)",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
                status.login(self, self._backend_key)
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
        if kinds.uses_roster(self._kind(row)):
            self._fill_scholarship(row)
            return
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
            record.remember(self._dirs[row], self._data[row], kind=kinds.GENERAL)
            self._set_status(row, "filled")
            payee_ok = report.payee is not None and report.payee.ok
            payee_done = payee_ok and report.payee.picked
            taxbill_ok = report.taxbill is not None and report.taxbill.ok
            if payee_done:
                guide = "입금처까지 들어갔습니다. 첨부를 넣고 값을 확인한 뒤 앱의 [임시저장] 을 누르세요."
            elif payee_ok:
                guide = "입금처 팝업에서 거래처를 고르고 [확인] 을 누른 뒤, 첨부를 넣고 앱의 [임시저장] 을 누르세요."
            elif taxbill_ok and not report.taxbill.picked:
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
            self._set_state("세금계산서 조회", "success",
                            "계산서가 들어갔습니다. 이어서 [입금처 찾기] 를 누르세요." if report.picked
                            else "팝업 목록에서 계산서를 고르고 [확인] 을 누른 뒤 [입금처 찾기] 를 누르세요.")
            QMessageBox.information(self, "세금계산서 찾기", text)
        else:
            self._set_state("세금계산서 못 찾음", "warning", report.note or "증빙 [선택] 을 직접 눌러 골라 주세요.")
            QMessageBox.warning(self, "세금계산서 찾기", text)
        self._sync_buttons()

    def _on_payee_searched(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        if report.ok:
            self._set_state("입금처 검색", "success",
                            "입금처가 들어갔습니다. 첨부를 넣고 [임시저장] 을 누르세요." if report.picked
                            else "팝업 목록에서 거래처를 고르고 [확인] 을 누른 뒤 [임시저장] 을 누르세요.")
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

    # ── 청구 종류 · 장학금 ──────────────────────────────────────────────
    def _load_scholarship(self, row: int, excel: str | None = None) -> None:
        """장학금 폴더를 읽는다(명단 엑셀 · 공통/개별증빙). AI 를 쓰지 않으니 넣자마자 끝난다."""
        old = self._jobs[row]
        job = sch.load_job(self._dirs[row], excel=excel, kind=self._kinds[row])
        if old is not None:
            # 다시 읽어도 담당자가 고친 값은 남긴다
            if old.pay_ym and re.fullmatch(r"\d{4}-\d{2}", old.pay_ym):
                job.pay_ym = old.pay_ym
            job.tab = old.tab
        self._jobs[row] = job
        self._problems[row] = job.problems()
        self._set_status(row, "read" if job.people and not any("합계" in p for p in self._problems[row])
                         else "problem" if job.people else "failed")
        self._append_log(f"{job.spec.name} 폴더 읽음: " + " / ".join(job.summary_lines()))
        for problem in self._problems[row]:
            self._append_log("  확인: " + problem)

    def _row_kind_changed(self, _index: int) -> None:
        row = self._current
        if self._loading_form or not (0 <= row < len(self._dirs)) or self._running or self._erp_running:
            return
        kind = self.row_kind.currentData()
        if kind == self._kinds[row] or not kinds.find(kind).ready:
            return
        self._kinds[row] = kind
        if kinds.uses_roster(kind):
            self._load_scholarship(row)
        else:
            # 일반으로 바꾸면 AI 로 다시 읽어야 한다
            self._jobs[row] = None
            self._data[row] = schema.normalize({})
            self._problems[row] = []
            self._set_status(row, "waiting")
        self._refresh_row(row)
        self._show_form(row)
        self._sync_buttons()

    def _on_panel_changed(self) -> None:
        row = self._current
        if 0 <= row < len(self._jobs) and self._jobs[row] is not None:
            self._problems[row] = self._jobs[row].problems()
            self._refresh_row(row)
        self._sync_buttons()

    def _reload_scholarship(self, excel: str) -> None:
        row = self._current
        if not (0 <= row < len(self._jobs)) or not kinds.uses_roster(self._kinds[row]) or self._erp_running:
            return
        self._load_scholarship(row, excel=excel or None)
        self._refresh_row(row)
        self._show_form(row)
        self._sync_buttons()

    def _is_pending_roster(self, r: int) -> bool:
        """아직 넣지 않은 명단 폴더(장학금 · 혁신인재지원금) — 읽음 상태이고 넣을 사람이 있는 것."""
        job = self._jobs[r] if 0 <= r < len(self._jobs) else None
        return job is not None and kinds.uses_roster(self._kinds[r]) and self._status[r] == "read" and bool(job.chosen())

    def _next_roster_row(self, after: int) -> int | None:
        """다음에 넣을 명단 폴더 — 아래 줄부터, 그다음 위 줄."""
        order = list(range(after + 1, len(self._dirs))) + list(range(0, max(after, 0)))
        return next((r for r in order if self._is_pending_roster(r)), None)

    def _start_next(self, row: int, previous) -> None:
        """한 폴더를 끝내면 다음 폴더로 — 담당자 요청(2026-10-14). 새 청구서는 사람이 띄우고, 앱은 그 화면이 새 것인지 넣기 전에 본다."""
        if self._erp_running or not (0 <= row < len(self._jobs)):
            return
        self.table.selectRow(row)
        self._fill_scholarship(row, previous=previous)

    def _fill_scholarship(self, row: int, previous=None) -> None:
        if not (0 <= row < len(self._jobs)) or self._jobs[row] is None or self._erp_running or self._browser_busy:
            return
        self.scholarship_panel.apply_options()
        job = self._jobs[row]
        dry = self.dry_run.isChecked()
        problems = job.problems()
        if not dry:
            if not self._browser_open:
                return
            hard = [p for p in problems if "대표적요" in p or "지급예정년월" in p or "표의 합계" in p or "사람이 없" in p]
            if hard:
                QMessageBox.warning(self, "넣기 전에 고칠 것", "\n".join("· " + p for p in hard))
                return
            # 개별증빙을 학생에게 못 붙였으면 따로 묻는다 — 확인 창 아래 '확인할 것' 한 줄로만 보여 공통증빙만 붙은 채 저장됐다
            # (담당자 실제 시험 2026-10-19: 파일 이름이 소학회명이라 6명 모두 개별증빙 없이 저장)
            if job.unmatched and QMessageBox.warning(
                    self, "개별증빙이 붙지 않습니다",
                    f"개별증빙 {len(job.unmatched)}개는 어느 학생 것인지 몰라 붙이지 않습니다.\n"
                    + "\n".join("· " + os.path.basename(f) for f in job.unmatched[:6])
                    + (f"\n· … 외 {len(job.unmatched) - 6}개" if len(job.unmatched) > 6 else "")
                    + "\n\n파일 이름(또는 하위 폴더 이름)에 학생 이름이나 명단의 소학회명이 있어야 합니다. "
                      "고친 뒤 [다시 읽기] 를 누르세요.\n\n그래도 이대로(그 파일 없이) 넣을까요?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            warning = sch.record_warning(job)
            if warning and QMessageBox.warning(self, "이미 넣은 적이 있습니다", warning + "\n\n그래도 넣을까요?",
                                               QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        # 미리 보기는 ERP 를 건드리지 않으니 바로 결과 표를 보인다. 실제로 넣을 때만 같은 표로 한 번 더 묻는다.
        # 폴더마다 청구서 하나 — 앞 폴더를 끝내고 이어지는 폴더면 새 청구서를 띄우라고 먼저 말한다(앱은 넣기 전에 화면이 새 것인지 본다)
        waiting = [r for r in range(len(self._dirs)) if r != row and self._is_pending_roster(r)]
        if previous is not None:
            heading = f"다음 폴더 — {job.spec.name} {job.count_text()}을 새 청구서에 넣습니다 · [신청] 은 누르지 않습니다"
            footer = (f"앞 폴더의 청구서(결의번호 {previous.req_cnt or '?'})는 그대로 두고, ERP 에서 새 청구서(작성 화면의 [새 청구서] 또는 "
                      "결의서내역 → [일반청구])를 띄운 뒤 누르세요. 여기서 그만하려면 [취소].")
        else:
            heading = f"학생 한 명씩 넣고 [저장](임시저장) 합니다 — {job.count_text()} · [신청] 은 누르지 않습니다"
            footer = ("앱이 확신하지 못하는 단계에서는 멈추고 위의 노란 띠로 묻습니다. 브라우저에 새 청구서 작성 화면이 떠 있어야 합니다."
                      + (f" 이 폴더를 끝내면 남은 명단 폴더 {len(waiting)}개도 하나씩 이어서 묻습니다." if waiting else ""))
        if not dry and not show_report(
                self, title="ERP 에 넣기", tone="warning", heading=heading,
                summary=job.summary_lines(), columns=SCH_COLUMNS,
                rows=scholarship_rows(job, [sch.plan_person(job, i) for i in job.chosen()]), notes=problems,
                footer=footer, accept_text=f"ERP 에 넣기 ({job.count_text()})"):
            return
        self._erp_row = row
        if not dry:
            self._erp_running = True
            self.scholarship_panel.set_locked(True)
            self._set_status(row, "erp")
            self.busy_changed.emit(True)
            self._set_state("넣는 중", "info", "브라우저를 건드리지 말고 기다리세요. 앱이 물으면 위의 노란 띠를 따르세요.")
        self.browser.fill_scholarship(job, dry_run=dry)
        self._sync_buttons()

    def _answer(self, ok: bool) -> None:
        self.ask_banner.hide()
        self.browser.answer_relogin(ok)
        self._sync_buttons()
        if ok:
            self._set_state("넣는 중", "info", "이어서 넣습니다.")

    def _capture_structure(self) -> None:
        self._capture_asked = True              # 청구서 받기 화면도 같은 신호를 받는다 — 누른 쪽만 창을 띄운다
        self.browser.capture_structure(owner="claim")

    def _on_structure_saved(self, path: str) -> None:
        if not getattr(self, "_capture_asked", False):
            return
        self._capture_asked = False
        show_structure_saved(self, path)

    def _on_sch_ask(self, message: str) -> None:
        self.ask_text.setText(message)
        self.ask_banner.show()
        self._sync_buttons()
        self._set_state("확인 필요", "warning", "위의 노란 띠를 따른 뒤 [계속] 을 누르세요.")
        self.attention.emit()
        self.window().raise_()
        self.window().activateWindow()

    def _on_sch_person(self, index: int, status: str, note: str) -> None:
        if self._current == self._erp_row:
            self.scholarship_panel.set_person_status(index, status, note)

    def _on_sch_done(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        self.ask_banner.hide()
        row = self._erp_row
        was_running = self._erp_running
        self._erp_running = False
        self.scholarship_panel.set_locked(False)
        self.stop_button.setEnabled(True)
        if was_running:
            self.busy_changed.emit(False)
        job = self._jobs[row] if 0 <= row < len(self._jobs) else None
        if report.dry_run:
            if self._current == row:
                self.scholarship_panel.mark_planned(r.index for r in report.results)
            self._set_state("미리 봄", "info", "학생마다 넣을 값은 [진행 기록] 에도 있습니다. 실제로 넣으려면 '미리 보기만' 체크를 풀고 다시 누르세요.")
            if job is None:
                QMessageBox.information(self, "미리 보기", "\n".join(report.lines()[:40]))
            else:
                show_report(self, title="미리 보기", tone="info",
                            heading=f"ERP 에 넣지 않았습니다 — 이렇게 넣습니다 ({job.count_text([r.index for r in report.results])})",
                            summary=job.summary_lines(), columns=SCH_COLUMNS, rows=scholarship_rows(job, report.results),
                            notes=job.problems(),
                            footer="실제로 넣으려면 '미리 보기만' 체크를 풀고 [ERP 에 넣기] 를 누르세요.")
        elif report.blocked:
            if 0 <= row < len(self._status):
                self._set_status(row, "read")
            self._set_state("화면 없음", "warning", report.blocked)
            QMessageBox.warning(self, "넣지 못했습니다", report.blocked)
        else:
            saved = [r.index for r in report.results if r.status == "saved"]
            if saved and job is not None:
                try:
                    sch.record_job(job, report)
                except Exception as error:  # noqa: BLE001 — 기록을 못 남겨도 저장된 학생의 체크는 풀어야 다시 넣지 않는다
                    self._append_log("채운 기록을 남기지 못했습니다: %s" % (str(error).splitlines()[0] if str(error) else type(error).__name__))
            # 다 넣었으면(멈추지 않았으면) 남은 명단 폴더로 이어 간다 — 담당자 요청(2026-10-14) '하나를 끝내고 다음으로'
            nxt = self._next_roster_row(row) if saved and not report.stopped else None
            if 0 <= row < len(self._status):
                self._set_status(row, "partial" if report.stopped and saved else "saved" if saved else "read")
            if self._current == row:
                for r in report.results:
                    self.scholarship_panel.set_person_status(r.index, "review" if r.review else r.status, r.note)
                self.scholarship_panel.uncheck_saved(saved)
            elif job is not None:
                for index in saved:
                    job.selected[index] = False
            if 0 <= row < len(self._dirs):
                self._refresh_row(row)
            # 저장은 했지만 [신청] 전에 ERP 에서 고칠 것(소득구분 · 공제) — 담당자 결정(2026-10-14): 멈추지 않고 여기서 알린다
            review = report.review_items()
            for item in review:
                self._append_log("신청 전 확인: " + item)
            # 넣기를 마친 뒤 청구내역 표를 다시 읽어 명단과 맞춘 것(sheet_check) — 확인할 것은 같은 목록에 붙인다
            if report.check is not None:
                review = review + ["청구내역 대조: " + item for item in report.check.problems]
            check = f" 신청 전 확인할 것 {len(review)}건 — 결과 창과 [진행 기록] 에 있습니다." if review else ""
            if report.stopped:
                self._set_state("멈춤", "warning", f"{report.saved}명까지 임시저장했습니다. 남은 학생만 체크돼 있으니 고친 뒤 다시 누르면 이어집니다." + check)
            elif review:
                self._set_state("확인 필요", "warning", f"{report.saved}명을 임시저장했습니다." + check + " ERP 에서 고친 뒤 [신청] 을 직접 누르세요.")
            else:
                self._set_state("임시저장", "success", f"{report.saved}명을 임시저장했습니다. ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요.")
            if job is None:
                QMessageBox.information(self, "명단 청구", "\n".join(report.lines()[:40]))
            else:
                saved_text = job.count_text(saved) if saved else "0명"
                # 같은 ERP 알림이 파일마다 되풀이된다('파일명의 특수문자는 제거됩니다.') — 한 줄로 모아 몇 번인지만
                alerts = [f"{m} (×{report.messages.count(m)})" if report.messages.count(m) > 1 else m
                          for m in dict.fromkeys(report.messages)]
                show_report(self, title=f"{job.spec.name} 청구", tone="warning" if report.stopped or review else "success",
                            heading=f"임시저장 {saved_text}" + (" — 중간에 멈췄습니다" if report.stopped else "")
                                    + (f" · 신청 전 확인할 것 {len(review)}건" if review else ""),
                            summary=[f"대표적요: {job.main_summary}", f"지급예정년월: {job.pay_ym}"]
                                    + ([f"신청 전 대조: {report.check.heading()}"] if report.check is not None else [])
                                    + (["ERP 알림: " + " · ".join(alerts)] if alerts and review else []),
                            columns=SCH_COLUMNS, rows=scholarship_rows(job, report.results),
                            notes=review or alerts, notes_title="신청 전 확인할 것" if review else "ERP 알림",
                            footer="ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요 — 앱은 누르지 않습니다."
                                   + (" 위 '신청 전 확인할 것' 을 먼저 고치세요." if review else "")
                                   + (" 이 창을 닫으면 다음 폴더로 넘어갑니다." if nxt is not None else ""))
            if nxt is not None and job is not None:
                QTimer.singleShot(0, lambda: self._start_next(nxt, job))
        self._sync_buttons()

    def _check_sheet(self) -> None:
        row = self._current
        job = self._jobs[row] if 0 <= row < len(self._jobs) else None
        if job is None or not self._browser_open:
            return
        self._sheet_row = row
        self._set_state("대조 중", "info", "ERP 작성 화면의 청구내역 표를 읽어 명단과 맞추는 중입니다 (읽기만 합니다).")
        self.browser.check_sheet(job)

    def _on_sheet_checked(self, check) -> None:
        row = getattr(self, "_sheet_row", -1)
        job = self._jobs[row] if 0 <= row < len(self._jobs) else None
        name = job.spec.name if job is not None else "명단"
        if not check.read:
            self._set_state("대조 못 함", "warning", "작성 화면을 찾지 못했습니다. 넣은 청구서(작성 화면)를 띄운 뒤 다시 누르세요.")
            QMessageBox.warning(self, "청구내역 대조", "ERP 작성 화면(청구내역 표)을 찾지 못했습니다.\n"
                                "결의서내역에서 넣은 청구서를 열어 작성 화면을 띄운 뒤 다시 누르세요.")
            return
        if check.problems:
            self._set_state("확인 필요", "warning", f"청구내역 대조 — 확인할 것 {len(check.problems)}건. 고친 뒤 [신청] 을 직접 누르세요.")
        else:
            self._set_state("대조 맞음", "success", check.heading() + ". ERP 에서 검토하고 [신청] 을 직접 누르세요.")
        show_report(self, title="청구내역 대조", tone="warning" if check.problems else "success",
                    heading=f"{name} — {check.heading()}",
                    summary=[f"대표적요: {job.main_summary}"] if job is not None else None,
                    columns=[("결과", 104), ("내용", None)], rows=sheet_check_rows(check),
                    notes=check.problems, notes_title="신청 전 확인할 것",
                    footer="읽기만 했습니다 — ERP 에서 아무것도 누르지 않았습니다. [삭제] · [신청] 은 직접 하세요.")

    # ── 신호 ────────────────────────────────────────────────────────────
    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _on_extract_busy(self, busy: bool, message: str) -> None:
        if message:
            self.window().statusBar().showMessage(message)
        elif not busy:
            self.window().statusBar().clearMessage()

    def _on_browser_busy(self, busy: bool, message: str) -> None:
        self._browser_busy = busy
        # 받기 화면을 한 번도 안 열었으면 상태줄이 비어 있었다 — 팝업에서 고르기를 기다리는 안내(최대 3분)가 안 보였다
        if message:
            self.window().statusBar().showMessage(message)
        elif not busy:
            self.window().statusBar().clearMessage()
        self._sync_buttons()

    def _on_browser_opened(self) -> None:
        self._browser_open = True
        self._sync_buttons()

    def _on_browser_state(self, alive: bool) -> None:
        self._browser_open = alive
        self._sync_buttons()

    def _on_extract_error(self, message: str) -> None:
        """AI 읽기 스레드의 오류 — 브라우저 쪽 상태는 건드리지 않는다."""
        self._running = False
        self._on_platform(self.platform.status())
        self.busy_changed.emit(self.is_running())
        self._set_state("오류", "danger")
        self._sync_buttons()
        QMessageBox.warning(self, "문제가 생겼습니다", f"{message}\n\n자세한 내용은 [진행 기록] 탭과 로그 파일에 있습니다.")

    def _on_browser_failed(self, owner: str, message: str) -> None:
        """브라우저 스레드의 오류 — 이 화면이 넣은 명령의 것만. 받기 화면의 오류로 AI 읽기 상태가 풀리던 것을 막는다."""
        if owner != "claim":
            return
        self._capture_asked = False
        if self._erp_running:
            self._erp_running = False
            self.ask_banner.hide()
            self.scholarship_panel.set_locked(False)
            if 0 <= self._erp_row < len(self._status):
                self._set_status(self._erp_row, "partial")
        self.busy_changed.emit(self.is_running())
        self._set_state("오류", "danger")
        self._sync_buttons()
        QMessageBox.warning(self, "문제가 생겼습니다", f"{message}\n\n자세한 내용은 [진행 기록] 탭과 로그 파일에 있습니다.")

    def resizeEvent(self, event) -> None:  # noqa: N802
        """창이 낮으면 머리 · 끌어다 놓기 칸을 줄여 목록과 학생 표에 자리를 준다 — 1366×768 노트북(창 안쪽 ~690)에서
        학생 표가 한 줄 반만 보였다(2026-10-14 점검). 탭 이름이 이미 '일반청구' 라 제목은 접어도 된다."""
        super().resizeEvent(event)
        height = self.height()
        self.page_desc.setVisible(height >= 600)
        low = height < 720
        self.head_art.setVisible(not low)
        self.head_title.setVisible(not low)
        self.drop_art.setVisible(not low)
        self.drop_zone.setFixedHeight(58 if low else 76)
        self.form_card.hint_label.setVisible(not low)

    def shutdown(self) -> None:
        if self._erp_running:
            self.browser.request_stop()
        self.extractor.shutdown()
        if self._owns_browser:
            self.browser.shutdown()
