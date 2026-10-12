"""앱 뼈대 구성 요소 — 상단 바 · 작업 탭 · 하단 독 · 홈 업무 카드.

세 탐색 요소의 역할은 다르다.
  홈 카드   업무를 둘러보고 새로 시작한다 (설명 · 현황)
  하단 독   어느 화면에서든 주요 업무로 바로 간다
  작업 탭   지금 열려 있는 작업 사이를 오간다

업무 목록은 tasks.py 한 곳에서 읽는다. 카드·독·탭이 같은 표를 보므로 새 업무를 더할 때
여기를 고칠 일이 없다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pathlib import Path

from PySide6.QtGui import QPixmap

from .art import Art
from .icons import paint_icon
from .tasks import HOME_ID, TASKS, Task
from .theme import COLORS, card_shadow
from .widgets import WrapLabel


# ── 상단 바 ────────────────────────────────────────────────────────────
_ICONS = Path(__file__).parent / "assets" / "icons"


def _logo_pixmap(size: int) -> QPixmap:
    """상단 바 로고 = 앱 아이콘(tools/make_icon.py). 가까운 큰 그림을 골라 곱게 줄인다."""
    for side in (64, 128, 256):
        path = _ICONS / f"icon-{side}.png"
        if path.exists() and side >= size:
            return QPixmap(str(path)).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return QPixmap()


class IconButton(QToolButton):
    """선 아이콘 하나짜리 버튼. 이름은 접근성 이름과 말풍선으로 준다."""

    def __init__(self, icon: str, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("topIcon")
        self._icon = icon
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        side = 18
        from PySide6.QtCore import QRectF
        box = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        paint_icon(painter, box, self._icon, QColor(COLORS["text_muted"]))


class TopBar(QWidget):
    """로고 · 이름 | 검색 · 설정 · 사용자 메뉴.

    창 드래그 영역은 윈도우 기본 창틀이 맡는다. 이 바 안의 요소는 전부 클릭할 수 있는 것이라
    드래그와 겹치지 않는다.
    """

    search_submitted = Signal(str)
    open_utility = Signal(str)       # 'settings' | 'updates'

    def __init__(self, app_name: str, workspace: str, user_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("topbar")
        self.setFixedHeight(60)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 16, 0)
        row.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(_logo_pixmap(36))
        logo.setFixedSize(36, 36)
        logo.setAccessibleName("")
        row.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        brand = QLabel(app_name)
        brand.setObjectName("brand")
        names.addWidget(brand)
        ws = QLabel(workspace)
        ws.setObjectName("workspace")
        names.addWidget(ws)
        row.addLayout(names)
        row.addStretch(1)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("업무 찾기")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("업무 찾기")
        self.search.setMinimumWidth(200)
        self.search.returnPressed.connect(lambda: self.search_submitted.emit(self.search.text().strip()))
        row.addWidget(self.search)

        settings_button = IconButton("gear", "설정")
        settings_menu = QMenu(settings_button)
        settings_menu.addAction("설정", lambda: self.open_utility.emit("settings"))
        settings_menu.addAction("업데이트", lambda: self.open_utility.emit("updates"))
        settings_button.setMenu(settings_menu)
        settings_button.setPopupMode(QToolButton.InstantPopup)
        row.addWidget(settings_button)

        self.user_button = QPushButton(user_name)
        self.user_button.setObjectName("userMenu")
        self.user_button.setCursor(Qt.PointingHandCursor)
        self.user_button.setAccessibleName("사용자 메뉴")
        avatar = QLabel(user_name[:1] if user_name else "·")
        avatar.setObjectName("avatar")
        avatar.setAlignment(Qt.AlignCenter)
        self.user_menu = QMenu(self.user_button)
        self.user_button.setMenu(self.user_menu)
        row.addWidget(avatar)
        row.addWidget(self.user_button)


# ── 작업 탭 ────────────────────────────────────────────────────────────
class WorkTab(QWidget):
    """탭 하나 — 이름 · (진행 중 점) · 닫기. 홈 탭은 닫히지 않는다."""

    activated = Signal(str)
    close_requested = Signal(str)

    def __init__(self, task_id: str, name: str, closable: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.task_id = task_id
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.button = QPushButton(name)
        self.button.setObjectName("workTab")
        self.button.setCheckable(True)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setAccessibleName(f"{name} 탭")
        self.button.clicked.connect(lambda: self.activated.emit(task_id))
        row.addWidget(self.button)
        self.dot = QLabel("●")
        self.dot.setObjectName("tabDot")
        self.dot.setToolTip("작업이 진행 중입니다")
        self.dot.hide()
        row.addWidget(self.dot)
        if closable:
            close = QToolButton()
            close.setObjectName("tabClose")
            close.setText("×")
            close.setToolTip(f"{name} 닫기")
            close.setAccessibleName(f"{name} 탭 닫기")
            close.setCursor(Qt.PointingHandCursor)
            close.clicked.connect(lambda: self.close_requested.emit(task_id))
            row.addWidget(close)
        row.addSpacing(4)

    def set_busy(self, busy: bool) -> None:
        self.dot.setVisible(busy)


class WorkTabs(QWidget):
    """열린 작업 탭 줄. 많아지면 가로로 스크롤하고 [더보기] 메뉴로도 고른다."""

    activated = Signal(str)
    close_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("tabRow")
        self.setFixedHeight(40)
        self._tabs: dict[str, WorkTab] = {}
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 0, 8, 0)
        outer.setSpacing(4)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        strip = QWidget()
        strip.setObjectName("tabRow")
        self._row = QHBoxLayout(strip)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(0)
        self._row.addStretch(1)
        self._scroll.setWidget(strip)
        outer.addWidget(self._scroll, 1)
        self.more = QToolButton()
        self.more.setObjectName("tabMore")
        self.more.setText("열린 작업 ▾")
        self.more.setToolTip("열린 작업 목록")
        self.more.setPopupMode(QToolButton.InstantPopup)
        self._more_menu = QMenu(self.more)
        self.more.setMenu(self._more_menu)
        self.more.hide()
        outer.addWidget(self.more)

    def add(self, task_id: str, name: str, closable: bool = True) -> None:
        if task_id in self._tabs:
            return
        tab = WorkTab(task_id, name, closable)
        tab.activated.connect(self.activated.emit)
        tab.close_requested.connect(self.close_requested.emit)
        self._tabs[task_id] = tab
        self._row.insertWidget(self._row.count() - 1, tab)
        self._refresh_more()

    def remove(self, task_id: str) -> None:
        tab = self._tabs.pop(task_id, None)
        if tab is not None:
            self._row.removeWidget(tab)
            tab.deleteLater()
        self._refresh_more()

    def has(self, task_id: str) -> bool:
        return task_id in self._tabs

    def ids(self) -> list[str]:
        return list(self._tabs)

    def set_current(self, task_id: str) -> None:
        for tid, tab in self._tabs.items():
            tab.button.setChecked(tid == task_id)
        tab = self._tabs.get(task_id)
        if tab is not None:
            self._scroll.ensureWidgetVisible(tab, 24, 0)

    def set_busy(self, task_id: str, busy: bool) -> None:
        tab = self._tabs.get(task_id)
        if tab is not None:
            tab.set_busy(busy)

    def _refresh_more(self) -> None:
        self._more_menu.clear()
        for tid, tab in self._tabs.items():
            self._more_menu.addAction(tab.button.text(), lambda t=tid: self.activated.emit(t))
        self.more.setVisible(len(self._tabs) > 4)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # 탭이 줄에 다 안 들어가면 [더보기] 를 보인다
        strip = self._scroll.widget()
        self.more.setVisible(len(self._tabs) > 4 or strip.sizeHint().width() > self._scroll.width())


# ── 하단 독 ────────────────────────────────────────────────────────────
class DockButton(QToolButton):
    """독 항목 — 입체 그림 + 이름. 현재 위치는 옅은 라벤더 바탕과 작은 점.

    그림은 진짜 아이콘으로 넣어 Qt 가 글자 아래·위 배치를 맡는다. 직접 그리면 글자와 겹친다.
    """

    def __init__(self, task_id: str, name: str, art: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.task_id = task_id
        self.setObjectName("dockItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip(name)
        self.setAccessibleName(name)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setText(name)
        self._art = Art(art, 32, self)
        self._art.hide()          # 그림 캐시로만 쓴다
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        side = 26 if compact else 32
        self._art.set_size(side)
        ratio = self.devicePixelRatioF() or 1.0
        self.setIcon(QIcon(self._art._pixmap_for(ratio)))
        self.setIconSize(QSize(side, side))
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        return QSize(max(base.width(), 68), base.height())

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.isChecked():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["primary"]))
            painter.drawEllipse(self.width() / 2 - 2, self.height() - 6, 4, 4)


class Dock(QFrame):
    """하단 플로팅 독. 독은 전용 영역(DockArea) 안에 놓여 본문을 가리지 않는다."""

    activated = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dock")
        card_shadow(self)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(2)
        self._buttons: dict[str, DockButton] = {}
        items = [(HOME_ID, "홈", "overview")] + [(t.id, t.name, t.art) for t in TASKS if t.dock]
        for task_id, name, art in items:
            button = DockButton(task_id, name, art)
            button.clicked.connect(lambda _c, t=task_id: self.activated.emit(t))
            self._buttons[task_id] = button
            row.addWidget(button)

    def set_current(self, task_id: str) -> None:
        for tid, button in self._buttons.items():
            button.setChecked(tid == task_id)

    def set_compact(self, compact: bool) -> None:
        for button in self._buttons.values():
            button.set_compact(compact)
        layout = self.layout()
        layout.setContentsMargins(8, 4, 8, 4) if compact else layout.setContentsMargins(10, 6, 10, 6)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # 좌우 화살표로 독 항목 사이를 옮긴다
        buttons = list(self._buttons.values())
        focused = next((i for i, b in enumerate(buttons) if b.hasFocus()), -1)
        if focused >= 0 and event.key() in (Qt.Key_Left, Qt.Key_Right):
            step = -1 if event.key() == Qt.Key_Left else 1
            buttons[(focused + step) % len(buttons)].setFocus()
            return
        super().keyPressEvent(event)


class DockArea(QWidget):
    """독이 놓이는 하단 전용 공간. 창이 낮아지면 독과 여백을 함께 줄인다."""

    def __init__(self, dock: Dock, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dockArea")
        self.dock = dock
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 12)
        layout.addStretch(1)
        layout.addWidget(dock)
        layout.addStretch(1)
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        self.dock.set_compact(compact)
        self.layout().setContentsMargins(0, 4 if compact else 8, 0, 8 if compact else 12)
        self.setFixedHeight(self.sizeHint().height())


# ── 홈 업무 카드 ────────────────────────────────────────────────────────
class TaskCard(QFrame):
    """업무 하나 — 큰 입체 그림 · 이름 · 설명 · (실제 현황) · 화살표. 누르면 업무를 연다."""

    activated = Signal(str)

    def __init__(self, task: Task, parent: QWidget | None = None):
        super().__init__(parent)
        self.task = task
        self.setObjectName("taskCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"{task.name} 열기")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(232)
        card_shadow(self)
        self.setAttribute(Qt.WA_Hover, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(8)
        plate = QFrame()
        plate.setObjectName(f"taskArt_{task.accent}")
        plate.setFixedSize(104, 104)
        plate_layout = QVBoxLayout(plate)
        plate_layout.setContentsMargins(0, 0, 0, 0)
        plate_layout.addWidget(Art(task.art, 88), 0, Qt.AlignCenter)
        top.addWidget(plate)
        top.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("cardHint")
        top.addWidget(self.status, 0, Qt.AlignTop)
        layout.addLayout(top)

        name = QLabel(task.name)
        name.setObjectName("taskName")
        layout.addWidget(name)
        desc = WrapLabel(task.description)
        desc.setObjectName("taskDesc")
        layout.addWidget(desc)
        layout.addStretch(1)

        bottom = QHBoxLayout()
        self.badge = QLabel("준비 중" if not task.ready else "")
        self.badge.setObjectName("pill_neutral" if not task.ready else "cardHint")
        self.badge.setVisible(not task.ready)
        bottom.addWidget(self.badge)
        bottom.addStretch(1)
        arrow = QLabel("→")
        arrow.setObjectName("taskArrow")
        bottom.addWidget(arrow)
        layout.addLayout(bottom)

    def set_status(self, text: str) -> None:
        """실제 데이터가 있을 때만 현황을 보인다. 예시 숫자를 넣지 않는다."""
        self.status.setText(text)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.task.id)
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit(self.task.id)
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        self.setProperty("focused", True)
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.setProperty("focused", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().focusOutEvent(event)

    def event(self, event: QEvent) -> bool:
        # 마우스가 올라오면 2px 떠오른다. 애니메이션 없이 위치만 바꾼다
        if event.type() == QEvent.HoverEnter:
            self.setContentsMargins(0, 0, 0, 2)
        elif event.type() == QEvent.HoverLeave:
            self.setContentsMargins(0, 2, 0, 0)
        return super().event(event)
