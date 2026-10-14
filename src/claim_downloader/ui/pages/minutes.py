"""회의록 생성 화면 — 회의 폴더를 모아 [작업 시작] 하면 폴더마다 회의록(.hwpx)이 그 안에 생긴다.

    회의 폴더 추가(끌어다 놓기 · 버튼) → 작업 시작
    → 표에서 작성 중 / 완료 / 실패 / 건너뜀 → 더블클릭으로 만든 파일 열기

옛 '회의록 자동 작성 도구' 의 흐름 그대로다. 출력 폴더를 따로 고르지 않는다 — 회의록은 그 회의
자료가 있는 폴더 안에 저장한다. 자료는 선택한 AI 플랫폼으로 전송되므로 화면에 적어 둔다.

AI 플랫폼은 설정(`minutes_backend`)에서 정하고 로그인은 위쪽 바 AI 단추에서 한다(2026-10-14) — 이 화면은
ui/ai_status.py 의 상태를 보여 주기만 한다. Claude Code 가 없는 PC 에서는 화면은 보이되 안내 띠와 함께
[작업 시작] 이 비활성이다. 확인은 뒤 스레드에서 하므로 화면은 바로 뜬다. 다른 화면은 영향을 받지 않는다.

높이 배분은 청구서 받기와 같다 — 위는 낮게 고정, 남는 높이는 표가 쓴다. 화면 전체를 스크롤하지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import ai, settings
from ...minutes import rules
from ...minutes.backends import claude_cli
from .. import ai_status
from ..art import Art
from ..minutes_worker import MinutesWorker
from ..widgets import Card, EmptyState, Pill, PillDelegate, WrapLabel, muted_label

# (머리글, 너비). None 이면 남는 폭을 채운다.
COLUMNS = [("상태", 104), ("회의 (폴더)", 360), ("생성된 회의록", 300), ("보완요청", None)]
COL_STATUS, COL_DIR, COL_FILE, COL_NOTE = 0, 1, 2, 3

ROW_STATUS = {
    "waiting": ("대기", "neutral"),
    "running": ("작성 중", "info"),
    "done": ("완료", "success"),
    "failed": ("실패", "danger"),
    "skipped": ("건너뜀", "warning"),
    "stopped": ("안 함", "neutral"),
}

GUIDE_START = "회의 폴더를 추가하고 [작업 시작] 을 누르세요. 회의록은 각 회의 폴더 안에 만들어집니다."
GUIDE_RUNNING = "회의 1건에 수십 초에서 몇 분이 걸립니다. 다른 탭으로 가도 작업은 이어집니다."
NO_BACKEND = ("이 기능은 Claude Code 가 필요합니다. Claude Code 를 설치한 뒤 [다시 확인] 을 누르세요. "
              "설치했는데도 이 안내가 보이면 컴퓨터를 다시 시작해 보세요.")


class MinutesPage(QWidget):
    busy_changed = Signal(bool)     # 작업 중인지 — 작업 탭의 점이 본다
    need_settings = Signal()        # [설정에서 바꾸기] — AI 플랫폼은 설정에서 고른다

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAcceptDrops(True)
        self.worker = MinutesWorker()
        self._dirs: list[str] = []
        self._status: list[str] = []
        self._results: dict[int, str] = {}
        self._busy = False
        self._running = False
        self._available: bool | None = None     # None 이면 아직 확인 중
        self._backend_state = ""
        self._backend_key = ai.chosen("minutes")
        self._done_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 26)
        layout.setSpacing(12)
        layout.addLayout(self._build_head())
        self.platform = ai_status.PlatformRow("minutes")
        self.platform.changed.connect(self._on_platform)
        self.platform.settings_requested.connect(self.need_settings.emit)
        layout.addWidget(self.platform)
        layout.addWidget(self._build_banner())
        layout.addWidget(self._build_drop_zone())
        layout.addWidget(self._build_work_card(), 1)
        layout.addLayout(self._build_bottom_row())

        w = self.worker
        w.log.connect(self._append_log)
        w.busy.connect(self._on_busy)
        w.started.connect(self._on_started)
        w.done.connect(self._on_done)
        w.skipped.connect(self._on_skipped)
        w.stopped.connect(self._on_stopped)
        w.finished.connect(self._on_finished)
        w.error.connect(self._on_error)

        self._on_platform(self.platform.status())

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("meeting", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("회의록 생성")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        self.page_desc = muted_label(
            "회의 자료 폴더마다 정산용 회의록(.hwpx)을 만들어 그 폴더 안에 저장합니다. "
            "자료는 선택한 AI 플랫폼으로 전송됩니다.")
        texts.addWidget(self.page_desc)
        head.addLayout(texts, 1)
        rules_button = QPushButton("규칙 파일 열기")
        rules_button.setObjectName("ghost")
        rules_button.setToolTip("회의록 작성 규칙(문체·판단 기준). 저장만 하면 다음 작업부터 반영됩니다.")
        rules_button.clicked.connect(self._open_rules)
        head.addWidget(rules_button, 0, Qt.AlignVCenter)
        return head

    def _build_banner(self) -> QFrame:
        """Claude Code 가 없을 때만 보이는 띠. 화면은 그대로 두고 [작업 시작] 만 막는다."""
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
        row.addWidget(Art("archive", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        hint = QLabel("여기에 회의 폴더를 끌어다 놓으세요")
        hint.setObjectName("cardTitle")
        texts.addWidget(hint)
        texts.addWidget(muted_label("폴더 1개 = 회의 1건. 상위 폴더를 넣으면 그 안의 하위 폴더마다 1건으로 봅니다."))
        row.addLayout(texts, 1)
        self.add_one_button = QPushButton("회의 폴더 추가")
        self.add_one_button.clicked.connect(self._add_one)
        self.add_parent_button = QPushButton("상위 폴더 추가")
        self.add_parent_button.clicked.connect(self._add_parent)
        self.clear_button = QPushButton("목록 비우기")
        self.clear_button.setObjectName("ghost")
        self.clear_button.clicked.connect(self._clear)
        for button in (self.add_one_button, self.add_parent_button, self.clear_button):
            row.addWidget(button, 0, Qt.AlignVCenter)
        return self.drop_zone

    def _build_work_card(self) -> QWidget:
        card = Card(margins=(16, 8, 16, 12))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)

        self.list_stack = QStackedWidget()
        self.empty = EmptyState(
            "meeting", "회의 폴더를 추가하면 여기에 나옵니다",
            "폴더를 끌어다 놓거나 [회의 폴더 추가] 를 누르세요. 만들어진 회의록은 더블클릭으로 엽니다.")
        self.list_stack.addWidget(self.empty)
        self.list_stack.addWidget(self._build_table())
        self.tabs.addTab(self.list_stack, "회의 목록")

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
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)      # 실패 사유가 앞부터 읽히게
        self.table.setSortingEnabled(False)   # 작업 순서와 행 번호가 어긋나지 않게
        self.table.setItemDelegateForColumn(COL_STATUS, PillDelegate(self.table))
        self.table.itemDoubleClicked.connect(self._open_result)
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
        self.progress.setFixedSize(200, 8)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        row.addWidget(self.progress, 0, Qt.AlignVCenter)
        self.progress_label = QLabel("0 / 0")
        self.progress_label.setObjectName("muted")
        row.addWidget(self.progress_label, 0, Qt.AlignVCenter)
        self.stop_button = QPushButton("멈추기")
        self.stop_button.setObjectName("danger")
        self.stop_button.setToolTip("지금 쓰는 회의를 마치고 멈춥니다")
        self.stop_button.clicked.connect(self._stop)
        row.addWidget(self.stop_button)
        self.start_button = QPushButton("작업 시작")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start)
        row.addWidget(self.start_button)
        return row

    # ── 상태 ────────────────────────────────────────────────────────────
    def _sync_buttons(self) -> None:
        running = self._running
        can_edit = not running
        for button in (self.add_one_button, self.add_parent_button):
            button.setEnabled(can_edit)
        self.platform.set_enabled_for_run(can_edit)
        self.clear_button.setEnabled(can_edit and bool(self._dirs))
        self.start_button.setEnabled(can_edit and bool(self._dirs) and self._available is True)
        self.start_button.setText("작업 중…" if running else f"{len(self._dirs)}건 작업 시작" if self._dirs else "작업 시작")
        self.stop_button.setVisible(running)
        self.stop_button.setEnabled(running)
        self.tabs.setTabText(0, f"회의 목록 ({len(self._dirs)})" if self._dirs else "회의 목록")
        self.list_stack.setCurrentIndex(1 if self._dirs else 0)

    def _set_state(self, text: str, status: str, guide: str | None = None) -> None:
        self.state_pill.set_status(text, status)
        if guide is not None:
            self.guide.setText(guide)

    def _set_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.progress_label.setText(f"{done} / {total}")

    def _set_status(self, row: int, status: str, file_text: str = "", note: str = "") -> None:
        if row >= len(self._status):
            return
        self._status[row] = status
        text, tone = ROW_STATUS[status]
        item = QTableWidgetItem(text)
        item.setData(PillDelegate.ROLE, tone)
        self.table.setItem(row, COL_STATUS, item)
        for col, value in ((COL_FILE, file_text), (COL_NOTE, note)):
            cell = QTableWidgetItem(value)
            cell.setToolTip(value)
            self.table.setItem(row, col, cell)

    # ── 다른 화면이 묻는 것 ────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._running

    def resumable(self) -> tuple[bool, str]:
        """홈 '이어서 작업하기' — 지금 쓰는 중일 때만. 목록만 모아 둔 것은 아직 시작 안 한 것이다."""
        if self._running:
            remaining = sum(1 for s in self._status if s in ("waiting", "running"))
            return True, f"작성 중 · 남은 {remaining}건"
        return False, ""

    # ── 회의 폴더 목록 ───────────────────────────────────────────────────
    def add_meeting_dir(self, path: str) -> bool:
        path = os.path.abspath(path)
        if not os.path.isdir(path) or path in self._dirs or self._running:
            return False
        self._dirs.append(path)
        self._status.append("waiting")
        row = self.table.rowCount()
        self.table.setRowCount(row + 1)
        # 폴더 이름이 먼저 보이게 — 긴 전체 경로는 끝이 잘려 정작 회의 이름이 안 보인다
        name = QTableWidgetItem(f"{os.path.basename(path)}  ·  {os.path.dirname(path)}")
        name.setToolTip(path)
        self.table.setItem(row, COL_DIR, name)
        self._set_status(row, "waiting")
        self._set_progress(0, len(self._dirs))
        self._sync_buttons()
        return True

    def _add_one(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "회의 자료가 들어 있는 폴더 선택")
        if path:
            self.add_meeting_dir(path)

    def _add_parent(self) -> None:
        parent = QFileDialog.getExistingDirectory(self, "여러 회의 폴더가 들어 있는 '상위' 폴더 선택")
        if not parent:
            return
        subs = [os.path.join(parent, x) for x in sorted(os.listdir(parent))
                if os.path.isdir(os.path.join(parent, x))]
        if not subs:
            QMessageBox.information(self, "안내", "선택한 폴더 안에 하위 폴더가 없습니다.")
            return
        for sub in subs:
            self.add_meeting_dir(sub)

    def _clear(self) -> None:
        if self._running:
            return
        self._dirs, self._status, self._results = [], [], {}
        self.table.setRowCount(0)
        self._set_progress(0, 0)
        self._set_state("준비", "neutral", GUIDE_START)
        self._sync_buttons()

    # 끌어다 놓기 — 로컬 폴더만 받는다
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if not self._running and any(os.path.isdir(u.toLocalFile()) for u in event.mimeData().urls()):
            event.acceptProposedAction()
            self._set_drop_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drop_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drop_active(False)
        added = sum(1 for u in event.mimeData().urls() if self.add_meeting_dir(u.toLocalFile()))
        if added:
            event.acceptProposedAction()

    def _set_drop_active(self, on: bool) -> None:
        self.drop_zone.setProperty("active", on)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    # ── AI 플랫폼 ────────────────────────────────────────────────────────
    def _on_platform(self, status: ai.Status) -> None:
        """설정에서 고른 플랫폼의 상태가 바뀔 때마다(ui/ai_status.py). 작업 중에는 쓰던 플랫폼 그대로 간다."""
        if self._running:
            return
        self._backend_key = status.key
        self._backend_state = status.state
        if status.state == ai.CHECKING:
            self._available = None
        else:
            self._available = status.usable
        if status.state in (ai.MISSING, ai.ERROR):
            self.banner_text.setText(NO_BACKEND if status.key == claude_cli.ClaudeCliBackend.key and status.state == ai.MISSING
                                     else status.note or "AI 플랫폼을 확인하지 못했습니다. [다시 확인] 을 눌러 보세요.")
            self.banner.show()
        else:
            self.banner.hide()
        self._sync_buttons()

    def _open_rules(self) -> None:
        rules.load_rules()          # 파일이 없으면 기본 규칙으로 만들어 둔다
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.minutes_rules_path())))

    # ── 동작 ────────────────────────────────────────────────────────────
    def _start(self) -> None:
        if self._running or not self._dirs or self._available is not True:
            return
        if self._backend_state == ai.NO_LOGIN:
            # 이 확인은 틀릴 수 있으므로 막지 않고 물어본다.
            if QMessageBox.question(self, "로그인 확인", claude_cli.LOGIN_HELP,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        label = ai.label_of(self._backend_key)
        answer = QMessageBox.question(
            self, "작업 시작",
            f"회의 {len(self._dirs)}건의 자료가 '{label}' 로 전송되어 회의록이 만들어집니다.\n"
            "회의록은 각 회의 폴더 안에 저장되며 기존 파일은 덮어쓰지 않습니다.\n\n시작할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        self._running = True
        self._results = {}
        self._done_count = 0
        for row in range(len(self._dirs)):
            self._set_status(row, "waiting")
        self._set_progress(0, len(self._dirs))
        self._set_state("작성 중", "info", GUIDE_RUNNING)
        self.tabs.setCurrentIndex(0)
        self._sync_buttons()
        self.busy_changed.emit(True)
        self.worker.run(self._dirs, self._backend_key)

    def _stop(self) -> None:
        self.worker.request_stop()
        self.stop_button.setEnabled(False)
        self._set_state("멈추는 중", "warning", "지금 쓰는 회의를 마치면 멈춥니다…")

    def _open_result(self, item: QTableWidgetItem) -> None:
        path = self._results.get(item.row())
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ── 작업 스레드 신호 ─────────────────────────────────────────────────
    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _on_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        if message:
            self.window().statusBar().showMessage(message)
        elif not busy:
            self.window().statusBar().clearMessage()

    def _advance(self) -> None:
        self._done_count += 1
        self._set_progress(self._done_count, len(self._dirs))

    def _on_started(self, row: int) -> None:
        self._set_status(row, "running")
        self.table.scrollToItem(self.table.item(row, COL_STATUS))

    def _on_done(self, row: int, result) -> None:
        if result.ok:
            self._results[row] = result.info
            self._set_status(row, "done", os.path.basename(result.info), result.note)
        else:
            self._set_status(row, "failed", "⚠ " + result.info)
        self._advance()

    def _on_skipped(self, row: int, _kind: str) -> None:
        self._set_status(row, "skipped", "⚠ 앞의 오류로 건너뜀 (해결 후 다시 시작)")
        self._advance()

    def _on_stopped(self, row: int) -> None:
        self._set_status(row, "stopped", "멈춰서 하지 않음")
        self._advance()

    def _on_finished(self, stop: str, ok_count: int, fail_count: int) -> None:
        self._running = False
        self._on_platform(self.platform.status())       # 도는 동안 바뀐 설정·로그인 상태를 이제 반영
        self.busy_changed.emit(False)
        summary = f"완료 {ok_count}건 · 실패 {fail_count}건"
        if stop == "login":
            self._set_state("로그인 필요", "danger", summary + " — 로그인이 풀려 남은 회의를 건너뛰었습니다.")
            status = ai_status.instance()
            status.mark(self._backend_key, ai.NO_LOGIN, "작업 중 로그인이 풀렸습니다")
            if QMessageBox.question(
                    self, "로그인이 풀렸습니다",
                    f"{ai.short_label(self._backend_key)} 로그인이 풀려 있어 회의록을 만들지 못했습니다.\n\n지금 로그인 창을 열까요?\n"
                    "(로그인을 마치면 위쪽 AI 단추가 '로그인됨' 으로 바뀝니다. 그 뒤 [작업 시작] 을 다시 누르시면 됩니다. "
                    "목록은 그대로 두셔도 됩니다.)",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
                status.login(self, self._backend_key)
            return
        if stop == "limit":
            self._set_state("한도 초과", "danger", summary + " — 한도가 풀린 뒤 [작업 시작] 을 다시 누르세요.")
            QMessageBox.information(
                self, "사용 한도 초과",
                "Claude 사용 한도에 걸려 남은 회의를 건너뛰었습니다.\n\n한도가 풀린 뒤 [작업 시작] 을 다시 누르세요.\n"
                "(이미 만들어진 회의록은 그대로 남아 있습니다.)")
            return
        if stop == "balance":
            self._set_state("잔액 부족", "danger", summary + " — 결제 상태를 확인한 뒤 다시 시작하세요.")
            QMessageBox.information(
                self, "잔액 부족", "Claude 잔액이 부족해 남은 회의를 건너뛰었습니다.\n\n결제 상태를 확인한 뒤 [작업 시작] 을 다시 누르세요.")
            return
        stopped = any(s == "stopped" for s in self._status)
        if fail_count:
            self._set_state("일부 실패", "danger", summary + ". 실패한 건은 표의 사유를 확인하세요.")
        elif stopped:
            self._set_state("멈춤", "warning", summary + ". 남은 회의는 [작업 시작] 으로 이어서 할 수 있습니다.")
        else:
            self._set_state("완료", "success", summary + ". 회의록은 각 회의 폴더 안에 있습니다 — 더블클릭하면 열립니다.")
            QMessageBox.information(self, "완료", "작업이 끝났습니다.\n\n회의록은 각 회의 폴더 안에 만들어졌습니다.")

    def _on_error(self, message: str) -> None:
        self._running = False
        self._on_platform(self.platform.status())
        self.busy_changed.emit(False)
        self._set_state("오류", "danger")
        QMessageBox.warning(self, "문제가 생겼습니다", f"{message}\n\n자세한 내용은 [진행 기록] 탭과 로그 파일에 있습니다.")

    def resizeEvent(self, event) -> None:  # noqa: N802
        """창이 낮으면 설명 줄을 접어 표에 자리를 준다."""
        super().resizeEvent(event)
        self.page_desc.setVisible(self.height() >= 600)

    def shutdown(self) -> None:
        self.worker.shutdown()
