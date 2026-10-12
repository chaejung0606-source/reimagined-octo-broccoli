"""청구서 받기 화면.

    ① 브라우저 열기 → [사람: ERP 로그인 · 결의서내역 목록 띄우기]
    → ② 목록 읽기 → 대상 확인 → ③ 받기

로그인과 '받을까요?' 확인은 언제나 사람이 한다. 이 화면은 그 차례가 왔을 때
무엇을 해야 하는지 알려 주고 기다린다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import archive, settings
from ...targets import volume_warning
from ..theme import COLORS, card_shadow
from ..widgets import Card, StatTile, muted_label
from ..worker import SessionWorker

COLUMNS = ["상태", "No", "지출예정일", "내용", "금액", "결의서구분", "저장한 파일"]
STATUS_TEXT = {
    "waiting": ("대기", "text_faint"),
    "running": ("받는 중", "accent_deep"),
    "retry": ("다시 로그인 대기", "warn"),
    "done": ("완료", "pass"),
    "failed": ("실패", "error"),
}

GUIDE_START = ("① 을 누르면 ERP 창이 열립니다. 그 창에서 로그인하고 "
               "[과제관리 → 과제정보 → 청구서] 의 '결의서내역' 목록을 띄우세요.")
GUIDE_BROWSER = ("열린 브라우저 창에서 로그인 → [과제관리 → 과제정보 → 청구서] → '결의서내역' 목록을 "
                 "띄운 뒤 ② 를 누르세요. 평소 쓰는 Edge/크롬이 아니라 앱이 연 창이어야 합니다.")
GUIDE_LISTED = "받을 건을 확인하고 ③ 을 누르세요. 처음이라면 '앞 1건만 시험' 으로 흐름부터 확인하세요."


def _money(amt: str) -> str:
    try:
        return "{:,}".format(int(amt))
    except (TypeError, ValueError):
        return amt or ""


class DownloadPage(QWidget):
    need_settings = Signal()

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
        self._run_ok = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 22)
        layout.setSpacing(18)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("청구서 받기")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addWidget(muted_label(
            "승인된 청구서 PDF 를 ERP 에서 받아, 내용에 맞는 이름을 붙여 비목 폴더 바로 아래에 둡니다. "
            "이미 받은 건은 문서번호로 가려 건너뜁니다. ERP 에 입력하거나 제출하는 일은 하지 않습니다."
        ))
        layout.addLayout(header)

        tiles = QHBoxLayout()
        tiles.setSpacing(16)
        self.tile_done = StatTile("보관된 청구서", "—", "받은 기록 + 보관 폴더의 문서번호")
        self.tile_waiting = StatTile("업로드 대기", "—", "비목 폴더 바로 아래 PDF", tone="Warn")
        self.tile_targets = StatTile("이번에 받을 건", "—", "목록을 읽으면 채워집니다", variant="cardAccent")
        self.tile_ok = StatTile("이번에 받은 건", "0", "")
        for tile in (self.tile_done, self.tile_waiting, self.tile_targets, self.tile_ok):
            tiles.addWidget(tile, 1)
        layout.addLayout(tiles)

        # 받을 목록이 주인공이다. 기록은 무슨 일이 있었는지 확인할 만큼만.
        layout.addWidget(self._build_run_card(), 5)
        layout.addWidget(self._build_log_card(), 2)

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
    def _build_run_card(self) -> QWidget:
        card = Card("진행")
        self.folder_hint = QLabel()
        self.folder_hint.setObjectName("cardHint")
        card.add_header_widget(self.folder_hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.open_button = QPushButton("① 브라우저 열기")
        self.open_button.clicked.connect(self._open)
        self.list_button = QPushButton("② 목록 읽기")
        self.list_button.clicked.connect(self._read_list)
        self.all_button = QPushButton("③ 모두 받기")
        self.all_button.setObjectName("primary")
        card_shadow(self.all_button, blur=18, alpha=28, dy=4)
        self.all_button.clicked.connect(lambda: self._download(limit=0))
        self.test_button = QPushButton("앞 1건만 시험")
        self.test_button.setObjectName("ghost")
        self.test_button.clicked.connect(lambda: self._download(limit=1))
        self.stop_button = QPushButton("멈추기")
        self.stop_button.setObjectName("ghost")
        self.stop_button.setToolTip("지금 받는 건을 마치고 멈춥니다")
        self.stop_button.clicked.connect(self._stop)
        for button in (self.open_button, self.list_button, self.all_button, self.test_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.stop_button)
        card.add_layout(buttons)

        self.guide = muted_label(GUIDE_START)
        card.add(self.guide)

        # 사람 차례 알림 — 다시 로그인해야 할 때만 보인다
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(18, 12, 12, 12)
        self.banner_text = QLabel()
        self.banner_text.setObjectName("bannerText")
        self.banner_text.setWordWrap(True)
        banner_layout.addWidget(self.banner_text, 1)
        self.resume_button = QPushButton("목록을 띄웠어요 · 계속")
        self.resume_button.setObjectName("primary")
        self.resume_button.clicked.connect(lambda: self._answer_relogin(True))
        self.abort_button = QPushButton("그만 받기")
        self.abort_button.setObjectName("ghost")
        self.abort_button.clicked.connect(lambda: self._answer_relogin(False))
        banner_layout.addWidget(self.resume_button)
        banner_layout.addWidget(self.abort_button)
        self.banner.hide()
        card.add(self.banner)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        head = self.table.horizontalHeader()
        for col in range(len(COLUMNS)):
            head.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(3, QHeaderView.Stretch)
        card.add(self.table, 1)
        return card

    def _build_log_card(self) -> QWidget:
        card = Card("진행 기록")
        open_log = QPushButton("로그 파일 열기")
        open_log.setObjectName("ghost")
        open_log.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.log_path()))))
        card.add_header_widget(open_log)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setMinimumHeight(90)
        card.add(self.log_view, 1)
        return card

    # ── 상태 ────────────────────────────────────────────────────────────
    def refresh_counts(self) -> None:
        cfg = settings.load()
        folders = archive.folder_status(cfg.out_root)
        self.tile_waiting.set_value(str(sum(f.waiting for f in folders)) if folders else "—",
                                    "비목 폴더 바로 아래 PDF")
        done = archive.load_done(settings.done_path())
        self.tile_done.set_value(str(len(done)), "받은 기록 + 보관 폴더의 문서번호")
        if cfg.out_root:
            self.folder_hint.setText(f"저장 폴더: {cfg.out_root}")
        else:
            self.folder_hint.setText("저장 폴더가 지정되지 않았습니다")

    def _remaining(self) -> list[int]:
        return [i for i, s in enumerate(self._status) if s != "done"]

    def _sync_buttons(self) -> None:
        busy = self._busy
        self.open_button.setEnabled(not busy and not self._browser_open)
        self.list_button.setEnabled(not busy and self._browser_open)
        remaining = len(self._remaining())
        can_run = not busy and self._browser_open and remaining > 0
        self.all_button.setEnabled(can_run)
        self.all_button.setText(f"③ {remaining}건 모두 받기" if remaining else "③ 모두 받기")
        self.test_button.setEnabled(can_run)
        self.stop_button.setEnabled(busy and bool(self._running_rows))

    # ── 동작 ────────────────────────────────────────────────────────────
    def _open(self) -> None:
        if not settings.load().out_root:
            QMessageBox.information(
                self, "저장 폴더",
                "받은 청구서를 넣을 폴더를 먼저 지정해 주세요.\n"
                "비목 폴더(01. 인건비 …)가 바로 아래 있는 폴더입니다.")
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
        self._run_ok = 0
        self.tile_ok.set_value("0", "")
        for row in rows:
            self._set_status(row, "waiting")
        self.worker.download([self._targets[i] for i in rows])

    def _stop(self) -> None:
        self.worker.request_stop()
        self.stop_button.setEnabled(False)
        self.guide.setText("지금 받는 건을 마치면 멈춥니다…")

    def _answer_relogin(self, ok: bool) -> None:
        self.banner.hide()
        self.worker.answer_relogin(ok)

    # ── 작업 스레드 신호 ─────────────────────────────────────────────────
    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _on_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
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
        self.guide.setText(GUIDE_BROWSER)
        self._sync_buttons()

    def _on_browser_state(self, alive: bool) -> None:
        """사용자가 브라우저 창을 닫아 버렸으면 ① 부터 다시 하게 한다."""
        if self._browser_open and not alive:
            self._browser_open = False
            self.guide.setText("브라우저 창이 닫혔습니다. " + GUIDE_START)
        self._sync_buttons()

    def _on_listed(self, selection) -> None:
        self._selection = selection
        self._targets = list(selection.targets)
        self._status = ["waiting"] * len(self._targets)
        self.table.setRowCount(len(self._targets))
        for row, t in enumerate(self._targets):
            values = ["", t.get("no", ""), t.get("expDt", ""), t.get("cont", ""),
                      _money(t.get("amt", "")), t.get("gubun", ""), ""]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 4:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, item)
            self._set_status(row, "waiting")
        self.tile_targets.set_value(str(len(self._targets)),
                                    f"이미 보관되어 건너뛴 건 {selection.skipped}건")
        if self._targets:
            self.guide.setText(GUIDE_LISTED)
        else:
            self.guide.setText("새로 받을 건이 없습니다. 목록이 바뀌면 ② 를 다시 누르세요.")
        self._sync_buttons()

    def _on_list_failed(self, message: str) -> None:
        self.guide.setText(GUIDE_BROWSER)
        QMessageBox.warning(
            self, "목록을 찾지 못했습니다",
            f"{message}\n\n앱이 연 브라우저 창에서 로그인하고 [과제관리 → 과제정보 → 청구서] 의 "
            "'결의서내역' 목록을 띄웠는지 확인한 뒤 ② 를 다시 누르세요.\n"
            "열린 창 구조는 아래 진행 기록에 남겼습니다.")
        self._sync_buttons()

    def _set_status(self, row: int, status: str, detail: str = "") -> None:
        if row >= len(self._status):
            return
        self._status[row] = status
        text, color = STATUS_TEXT[status]
        item = QTableWidgetItem(text)
        item.setForeground(QColor(COLORS[color]))
        self.table.setItem(row, 0, item)
        if detail:
            cell = QTableWidgetItem(detail)
            if status == "failed":
                cell.setForeground(QColor(COLORS["error"]))
            self.table.setItem(row, 6, cell)

    def _on_item(self, index: int, status: str, detail: str) -> None:
        if index >= len(self._running_rows):
            return
        row = self._running_rows[index]
        self._set_status(row, status, detail)
        self.table.scrollToItem(self.table.item(row, 0))
        if status == "done":
            self._run_ok += 1
            self.tile_ok.set_value(str(self._run_ok), "")
            self.refresh_counts()

    def _on_finished(self, summary) -> None:
        self.banner.hide()
        self._running_rows = []
        failed = len(summary.failed)
        text = f"끝: 성공 {summary.ok}건 / 실패 {failed}건"
        if summary.stopped:
            text += " — 중간에 멈췄습니다"
        if summary.missing:
            text += f" · 엑셀 대조 누락 {len(summary.missing)}건 (진행 기록 참고)"
        self.guide.setText(text + ". 받은 파일은 비목 폴더 바로 아래에 있습니다.")
        self.tile_ok.set_value(str(summary.ok), f"실패 {failed}건" if failed else "")
        self.refresh_counts()
        self._sync_buttons()

    def _on_relogin(self, message: str) -> None:
        self.banner_text.setText(message)
        self.banner.show()
        self.window().raise_()
        self.window().activateWindow()

    def _on_error(self, message: str) -> None:
        self.banner.hide()
        if "Executable doesn't exist" in message or "msedge" in message:
            message = ("브라우저를 띄우지 못했습니다. [앱 실행.bat] 을 다시 실행해 준비를 마치거나, "
                       "Microsoft Edge 가 설치되어 있는지 확인하세요.\n\n" + message)
        QMessageBox.warning(self, "문제가 생겼습니다",
                            f"{message}\n\n자세한 내용은 진행 기록과 로그 파일에 있습니다.")
        self._sync_buttons()

    def shutdown(self) -> None:
        self.worker.shutdown()
