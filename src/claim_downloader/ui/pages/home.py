"""COSS 업무데스크 홈 — 어떤 업무를 시작할지 고르는 곳.

업무 타일(그림 + 이름뿐)은 늘 한 줄. 아래에는

  이어서 작업하기   실제로 재개할 수 있는 일만 — 지금은 청구서 받기가 중간에 멈춰 남은 건이
                    있을 때뿐이다. 준비 중 화면을 열어 봤다는 것은 여기에 넣지 않는다.
  최근 받은 청구서  보관 폴더의 PDF 를 바꾼 시각순으로 — 실제로 받은 결과만 보인다.

가짜 통계나 자리 채우기용 카드는 두지 않는다. 빈 영역은 짧은 안내 한 줄로 끝낸다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import ai, archive, settings
from ..art import Art
from ..shell import TaskCard
from ..tasks import TASKS
from ..widgets import Pill, WrapLabel, muted_label

RECENT_LIMIT = 3


def _recent_files(out_root: str) -> list[tuple[Path, float]]:
    """보관 폴더(업로드/ 포함)의 PDF 를 바꾼 시각순으로. 실제로 받은 파일만."""
    root = Path(out_root) if out_root else None
    if root is None or not root.is_dir():
        return []
    found = []
    for path in root.rglob("*.pdf"):
        try:
            found.append((path, path.stat().st_mtime))
        except OSError:
            continue
    found.sort(key=lambda item: item[1], reverse=True)
    return found[:RECENT_LIMIT]


class HomePage(QWidget):
    open_task = Signal(str)
    apply_update = Signal()
    restart_requested = Signal()     # 업데이트를 받은 뒤 [새로고침]
    ai_login = Signal()              # AI 띠 [로그인]
    ai_check = Signal()              # AI 띠 [다시 확인]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("home")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("home")
        scroll.setWidget(body)
        outer.addWidget(scroll)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(36, 28, 36, 30)
        layout.setSpacing(18)

        # 업데이트 띠 — 새 버전이 있을 때만 보인다
        self.update_banner = QFrame()
        self.update_banner.setObjectName("updateBanner")
        banner = QHBoxLayout(self.update_banner)
        banner.setContentsMargins(16, 10, 12, 10)
        banner.setSpacing(10)
        self.update_pill = Pill("새 버전", "info")
        banner.addWidget(self.update_pill, 0, Qt.AlignVCenter)
        self.update_text = WrapLabel("")
        self.update_text.setObjectName("body")
        banner.addWidget(self.update_text, 1)
        self.apply_button = QPushButton("지금 적용")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply_update.emit)
        banner.addWidget(self.apply_button)
        # 적용이 끝난 뒤 — 껐다 켤 필요 없이 새 앱이 뜨고 이 창은 닫힌다
        self.restart_button = QPushButton("새로고침")
        self.restart_button.setObjectName("primary")
        self.restart_button.setToolTip("창이 닫혔다가 새 버전으로 다시 열립니다 (2~3초)")
        self.restart_button.clicked.connect(self.restart_requested.emit)
        self.restart_button.hide()
        banner.addWidget(self.restart_button)
        self.update_banner.hide()
        layout.addWidget(self.update_banner)

        # AI 플랫폼 띠 — 회의록 생성 · 일반청구에 쓰는 AI 가 로그인이 풀렸거나 쓸 수 없을 때만 보인다(담당자 요청 2026-10-14).
        # 로그인돼 있으면 띠는 숨고, 위쪽 바의 AI 단추가 초록 '로그인됨' 으로 늘 상태를 보여 준다.
        self.ai_banner = QFrame()
        self.ai_banner.setObjectName("banner")
        ai_row = QHBoxLayout(self.ai_banner)
        ai_row.setContentsMargins(16, 10, 12, 10)
        ai_row.setSpacing(10)
        self.ai_pill = Pill("로그인 필요", "warning")
        ai_row.addWidget(self.ai_pill, 0, Qt.AlignVCenter)
        self.ai_text = WrapLabel("")
        self.ai_text.setObjectName("bannerText")
        self.ai_text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)     # 단추 높이에 맞춰 가운데 — 한 줄일 때 위로 붙지 않게
        ai_row.addWidget(self.ai_text, 1)
        self.ai_login_button = QPushButton("로그인")
        self.ai_login_button.setObjectName("primary")
        self.ai_login_button.clicked.connect(self.ai_login.emit)
        ai_row.addWidget(self.ai_login_button)
        self.ai_check_button = QPushButton("다시 확인")
        self.ai_check_button.clicked.connect(self.ai_check.emit)
        ai_row.addWidget(self.ai_check_button)
        self.ai_banner.hide()
        layout.addWidget(self.ai_banner)

        self.welcome = self._build_welcome()
        layout.addWidget(self.welcome)

        title = QLabel("어떤 업무를 시작할까요?")
        title.setObjectName("homeTitle")
        layout.addWidget(title)
        sub = QLabel("청구부터 회의록까지, 필요한 업무를 한곳에서.")
        sub.setObjectName("homeSub")
        layout.addWidget(sub)

        self._grid = QGridLayout()
        self._grid.setSpacing(8)
        self.cards: dict[str, TaskCard] = {}
        for task in TASKS:
            card = TaskCard(task)
            card.activated.connect(self.open_task.emit)
            self.cards[task.id] = card
        layout.addLayout(self._grid)
        self._columns = 0
        self._relayout(len(TASKS))

        layout.addSpacing(6)
        bottom = QHBoxLayout()
        bottom.setSpacing(18)
        bottom.addWidget(self._build_continue(), 1)
        bottom.addWidget(self._build_recent(), 1)
        layout.addLayout(bottom)
        layout.addStretch(1)

    # ── 업데이트 ─────────────────────────────────────────────────────
    def show_update(self, count: int, messages: tuple[str, ...]) -> None:
        if count <= 0:
            self.update_banner.hide()
            return
        head = messages[0] if messages else ""
        self.update_pill.set_status("새 버전", "info")
        self.update_text.setText(f"업데이트 {count}건을 받을 수 있습니다." + (f"  — {head}" if head else "")
                                 + "  적용한 뒤 새로고침하면 바로 반영됩니다.")
        self.apply_button.show()
        self.restart_button.hide()
        self.update_banner.show()

    def show_restart(self) -> None:
        """업데이트를 받았다 — 이제 할 일은 새로고침뿐."""
        self.update_pill.set_status("받음", "success")
        self.update_text.setText("업데이트를 받았습니다. 새로고침하면 바로 반영됩니다 (창이 닫혔다가 다시 열립니다).")
        self.apply_button.hide()
        self.restart_button.show()
        self.update_banner.show()

    # ── AI 플랫폼 ────────────────────────────────────────────────────
    def show_ai(self, status: "ai.Status | None", checking: bool = False) -> None:
        """로그인이 필요하거나 쓸 수 없을 때만 띠를 보인다. 확인 중에는 이전 상태를 그대로 둔다."""
        if status is not None and not (checking and status.state == ai.CHECKING):
            self._ai_state = status
            if self.welcome.isVisible():
                self.refresh_welcome()
        if status is None or status.state in (ai.OK, ai.CHECKING):
            if not checking:
                self.ai_banner.hide()
            return
        name = ai.short_label(status.key)
        uses = " · ".join(title for use, (title, _f) in ai.USES.items() if ai.chosen(use) == status.key)
        self.ai_pill.set_status(status.text, status.tone)
        if status.state == ai.NO_LOGIN:
            text = f"{uses} 에 쓰는 {name} 에 로그인되어 있지 않습니다. [로그인] 을 누르면 로그인 창이 열립니다."
        elif status.state == ai.MISSING:
            text = f"{uses} 에 쓰는 {name} 을(를) 이 PC 에서 찾지 못했습니다. 설치한 뒤 [다시 확인] 을 누르세요."
        else:
            text = f"{name} 상태를 확인하지 못했습니다: {status.note or '알 수 없는 문제'}"
        self.ai_text.setText(text)
        self.ai_login_button.setVisible(status.state == ai.NO_LOGIN and ai.can_login(status.key))
        self.ai_check_button.setEnabled(not checking)
        self.ai_check_button.setText("확인 중…" if checking else "다시 확인")
        self.ai_banner.show()

    # ── 처음 쓰시나요? ───────────────────────────────────────────────
    def _build_welcome(self) -> QFrame:
        """동료 PC 에 처음 깔았을 때 — 무엇을 준비해야 하고 무엇은 몰라도 되는지. 닫으면 다시 안 보인다(사용자 메뉴에서 다시 볼 수 있다).
        자리 채우기 카드가 아니다: 할 일이 남았는지(저장 폴더 · AI) 실제 상태를 보여 준다."""
        box = QFrame()
        box.setObjectName("card")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(18, 14, 14, 14)
        layout.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("처음 쓰시나요?")
        title.setObjectName("cardTitle")
        head.setSpacing(10)
        head.addWidget(title, 0, Qt.AlignVCenter)
        head.addWidget(muted_label("준비할 것은 저장 폴더 하나뿐입니다. 나머지는 쓰는 업무에 따라 필요할 때만."), 1, Qt.AlignVCenter)
        close = QPushButton("다시 보지 않기")
        close.setObjectName("ghost")
        close.clicked.connect(self._dismiss_welcome)
        head.addWidget(close)
        layout.addLayout(head)
        self._welcome_rows: dict[str, tuple[Pill, QPushButton | None]] = {}
        rows = (
            ("folder", "저장 폴더", "받은 청구서를 넣을 폴더 — 01. 인건비 · 02. 장학금 … 이 바로 아래 있는 폴더를 고릅니다.",
             "설정 열기", lambda: self.open_task.emit("settings")),
            ("ai", "AI 로그인", "회의록 생성 · 일반청구 [내용 읽기] 에만 씁니다. 청구서 받기 · 장학금 · 혁신인재지원금에는 필요 없습니다.",
             "로그인", self.ai_login.emit),
            ("erp", "ERP 로그인", "앱이 연 브라우저에서 직접 합니다 — 아이디 · 비밀번호는 어디에도 저장하지 않습니다. "
             "결의서내역 목록을 띄우면 앱이 목록을 읽습니다. 처음 받을 때는 '앞 1건만 시험'.", "", None),
            ("help", "막히면", "오른쪽 위 사용자 메뉴 → [문제 보내기] 를 누르면 개인정보를 가린 실행 기록이 복사됩니다. 채팅에 붙여 넣어 물어보세요.",
             "", None),
        )
        for key, name, text, button_text, action in rows:
            row = QHBoxLayout()
            row.setSpacing(10)
            pill = Pill("안내", "neutral")
            pill.setFixedWidth(72)
            row.addWidget(pill, 0, Qt.AlignVCenter)
            label = WrapLabel(f"<b>{name}</b> — {text}")
            label.setObjectName("body")
            row.addWidget(label, 1)
            button = None
            if button_text:
                button = QPushButton(button_text)
                button.clicked.connect(action)
                row.addWidget(button, 0, Qt.AlignVCenter)
            layout.addLayout(row)
            self._welcome_rows[key] = (pill, button)
        self._ai_state = None
        box.hide()
        return box

    def _dismiss_welcome(self) -> None:
        settings.update(welcome_dismissed=True)
        self._welcome_forced = False
        self.welcome.hide()

    def refresh_welcome(self, force: bool = False) -> None:
        """force 는 사용자 메뉴의 '처음 안내 다시 보기'. 이미 청구서를 받아 본 PC(받은 기록이 있음)에는 저절로 띄우지 않는다 —
        이 안내가 들어오기 전부터 쓰던 담당자 PC 에 업데이트 뒤 갑자기 뜨지 않게."""
        cfg = settings.load()
        self._welcome_forced = force or getattr(self, "_welcome_forced", False)
        if cfg.welcome_dismissed or (not self._welcome_forced and settings.done_path().exists()):
            self.welcome.hide()
            return
        folder_ok = bool(cfg.out_root) and Path(cfg.out_root).is_dir()
        pill, button = self._welcome_rows["folder"]
        pill.set_status("완료" if folder_ok else "할 일", "success" if folder_ok else "warning")
        button.setVisible(not folder_ok)
        pill, button = self._welcome_rows["ai"]
        state = self._ai_state
        if state is None or state.state == ai.CHECKING:
            pill.set_status("확인 중", "neutral")
            button.hide()
        elif state.state == ai.OK:
            pill.set_status("완료", "success")
            button.hide()
        else:
            pill.set_status("필요할 때", "neutral")
            button.setVisible(state.state == ai.NO_LOGIN and ai.can_login(state.key))
        self.welcome.show()

    # ── 업무 카드 배열 ───────────────────────────────────────────────
    def _relayout(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for card in self.cards.values():
            self._grid.removeWidget(card)
        for i, card in enumerate(self.cards.values()):
            self._grid.addWidget(card, i // columns, i % columns, Qt.AlignLeft)
        # 타일은 고정 폭. 남는 폭은 오른쪽 빈 칸이 가져간다
        for col in range(columns + 1):
            self._grid.setColumnStretch(col, 1 if col == columns else 0)

    # 업무 타일은 늘 한 줄에 둔다(담당자 요청). 장학금 청구가 들어와 다섯(2026-10-14) — 196 × 5 + 간격도 최소 창(1120)에 들어간다.
    # 업무가 다섯 이상으로 늘면 여기서 창 폭에 따라 줄을 나누면 된다.

    # ── 이어서 작업하기 ──────────────────────────────────────────────
    def _build_continue(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        head = QLabel("이어서 작업하기")
        head.setObjectName("homeSection")
        layout.addWidget(head)
        self._continue_rows = QVBoxLayout()
        self._continue_rows.setSpacing(8)
        layout.addLayout(self._continue_rows)
        self._continue_empty = muted_label("이어서 할 작업이 없습니다.")
        layout.addWidget(self._continue_empty)
        layout.addStretch(1)
        return box

    def set_resumable(self, items: list[tuple[str, str, str, str]]) -> None:
        """(업무 id, 그림, 이름, 상태 문구). 실제로 재개할 수 있는 일만 넘어온다."""
        while self._continue_rows.count():
            item = self._continue_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for task_id, art, name, status in items:
            self._continue_rows.addWidget(self._row(art, name, status, task_id, "이어서"))
        self._continue_empty.setVisible(not items)

    # ── 최근 받은 청구서 ─────────────────────────────────────────────
    def _build_recent(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        head = QLabel("최근 받은 청구서")
        head.setObjectName("homeSection")
        layout.addWidget(head)
        self._recent_rows = QVBoxLayout()
        self._recent_rows.setSpacing(8)
        layout.addLayout(self._recent_rows)
        self._recent_empty = muted_label("")
        layout.addWidget(self._recent_empty)
        layout.addStretch(1)
        return box

    def refresh_recent(self) -> None:
        """보관 폴더에서 읽은 실제 파일만 보인다. 없으면 비었다고 말한다."""
        while self._recent_rows.count():
            item = self._recent_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        cfg = settings.load()
        folders = archive.folder_status(cfg.out_root)
        waiting = sum(f.waiting for f in folders)
        # 타일에는 숫자를 쓰지 않는다 — 말풍선에만. 정의는 요약 카드와 같다(비목 폴더 바로 아래 = 업로드 대기)
        self.cards["download"].set_status(f"업로드 대기 {waiting}건" if folders else "")

        files = _recent_files(cfg.out_root)
        for path, mtime in files:
            when = dt.datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
            where = "업로드 완료" if "업로드" in path.relative_to(cfg.out_root).parts else "업로드 대기"
            self._recent_rows.addWidget(self._row("approved", path.stem, f"{when} · {path.parent.name} · {where}",
                                                  "download", "열기", path=path))
        if files:
            self._recent_empty.hide()
        elif not cfg.out_root:
            self._recent_empty.setText("저장 폴더를 지정하면 받은 청구서가 여기에 보입니다.")
            self._recent_empty.show()
        else:
            self._recent_empty.setText("아직 받은 청구서가 없습니다.")
            self._recent_empty.show()

    def _row(self, art: str, name: str, status: str, task_id: str, button: str, path=None) -> QWidget:
        """path 가 있으면 [열기] 가 그 파일을 연다 — 전에는 받기 화면만 열려 '열기' 와 맞지 않았다(2026-10-14 점검)."""
        row = QFrame()
        row.setObjectName("recentRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)
        layout.addWidget(Art(art, 42))
        texts = QVBoxLayout()
        texts.setSpacing(1)
        label = QLabel(name)
        label.setObjectName("fieldLabel")
        label.setToolTip(name)
        texts.addWidget(label)
        detail = QLabel(status)
        detail.setObjectName("muted")
        texts.addWidget(detail)
        layout.addLayout(texts, 1)
        go = QPushButton(button)
        go.setObjectName("ghost")
        go.setAccessibleName(f"{name} {button}")
        if path is not None:
            go.setToolTip(str(path))
            go.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        else:
            go.clicked.connect(lambda: self.open_task.emit(task_id))
        layout.addWidget(go)
        return row
