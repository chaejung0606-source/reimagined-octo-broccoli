"""업무 도구함 홈 — 어떤 업무를 시작할지 고르는 곳.

큰 창에서는 업무 카드 넷이 한 줄, 좁은 창에서는 2×2. 아래에는 '이어서 작업하기'
(열려 있는 탭)와 '최근 작업'(받은 기록에서 읽은 실제 결과)을 둔다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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

from ... import archive, settings
from ..art import Art
from ..shell import TaskCard
from ..tasks import TASKS, Task
from ..widgets import WrapLabel, muted_label

TWO_COLUMNS_BELOW = 1240   # 이보다 좁으면 2×2


class HomePage(QWidget):
    open_task = Signal(str)

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
        layout.setContentsMargins(40, 36, 40, 24)
        layout.setSpacing(20)

        title = QLabel("어떤 업무를 시작할까요?")
        title.setObjectName("homeTitle")
        layout.addWidget(title)
        sub = QLabel("청구부터 회의록까지, 필요한 업무를 한곳에서.")
        sub.setObjectName("homeSub")
        layout.addWidget(sub)
        layout.addSpacing(6)

        self._grid = QGridLayout()
        self._grid.setSpacing(18)
        self.cards: dict[str, TaskCard] = {}
        for task in TASKS:
            card = TaskCard(task)
            card.activated.connect(self.open_task.emit)
            self.cards[task.id] = card
        layout.addLayout(self._grid)
        self._columns = 0
        self._relayout(4)

        layout.addSpacing(10)
        bottom = QHBoxLayout()
        bottom.setSpacing(18)
        bottom.addWidget(self._build_continue(), 1)
        bottom.addWidget(self._build_recent(), 1)
        layout.addLayout(bottom)
        layout.addStretch(1)

    # ── 업무 카드 배열 ───────────────────────────────────────────────
    def _relayout(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for card in self.cards.values():
            self._grid.removeWidget(card)
        for i, card in enumerate(self.cards.values()):
            self._grid.addWidget(card, i // columns, i % columns)
        for col in range(4):
            self._grid.setColumnStretch(col, 1 if col < columns else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout(2 if self.width() < TWO_COLUMNS_BELOW else 4)

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
        self._continue_empty = muted_label("열려 있는 작업이 없습니다. 위에서 업무를 골라 시작하세요.")
        layout.addWidget(self._continue_empty)
        layout.addStretch(1)
        return box

    def set_open_tasks(self, tasks: list[tuple[Task, str]]) -> None:
        """(업무, 상태 문구) 목록. 실제로 열린 탭만 넘어온다."""
        while self._continue_rows.count():
            item = self._continue_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for task, status in tasks:
            self._continue_rows.addWidget(self._row(task.art, task.name, status, task.id))
        self._continue_empty.setVisible(not tasks)

    # ── 최근 작업 ────────────────────────────────────────────────────
    def _build_recent(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        head_row = QHBoxLayout()
        head = QLabel("최근 작업")
        head.setObjectName("homeSection")
        head_row.addWidget(head)
        head_row.addStretch(1)
        layout.addLayout(head_row)
        self._recent_rows = QVBoxLayout()
        self._recent_rows.setSpacing(8)
        layout.addLayout(self._recent_rows)
        self._recent_empty = muted_label("")
        layout.addWidget(self._recent_empty)
        layout.addStretch(1)
        return box

    def refresh_recent(self) -> None:
        """받은 기록·보관 폴더에서 읽은 실제 숫자만 보인다. 없으면 비었다고 말한다."""
        while self._recent_rows.count():
            item = self._recent_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        cfg = settings.load()
        done = archive.load_done(settings.done_path())
        folders = archive.folder_status(cfg.out_root)
        rows = []
        if cfg.out_root:
            waiting = sum(f.waiting for f in folders)
            uploaded = sum(f.uploaded for f in folders)
            rows.append(("recent", "청구서 받기", f"보관 {len(done)}건 · 업로드 대기 {waiting}건 · 완료 {uploaded}건", "download"))
        for art, name, status, task_id in rows:
            self._recent_rows.addWidget(self._row(art, name, status, task_id))
        self.cards["download"].set_status(f"대기 {sum(f.waiting for f in folders)}건" if folders else "")
        if rows:
            self._recent_empty.hide()
        else:
            self._recent_empty.setText("아직 기록이 없습니다. 청구서 받기에서 저장 폴더를 지정하면 여기에 현황이 보입니다.")
            self._recent_empty.show()

    def _row(self, art: str, name: str, status: str, task_id: str) -> QWidget:
        row = QFrame()
        row.setObjectName("recentRow")
        row.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(12)
        layout.addWidget(Art(art, 40))
        texts = QVBoxLayout()
        texts.setSpacing(2)
        label = QLabel(name)
        label.setObjectName("fieldLabel")
        texts.addWidget(label)
        detail = WrapLabel(status)
        detail.setObjectName("muted")
        texts.addWidget(detail)
        layout.addLayout(texts, 1)
        go = QPushButton("열기")
        go.setObjectName("ghost")
        go.setAccessibleName(f"{name} 열기")
        go.clicked.connect(lambda: self.open_task.emit(task_id))
        layout.addWidget(go)
        row.mousePressEvent = lambda e, t=task_id: self.open_task.emit(t)  # noqa: E731
        return row
