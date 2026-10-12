"""앱 뼈대 구성 요소 — 상단 바 · 탐색기형 작업 탭 · 하단 독 · 홈 업무 카드.

세 탐색 요소의 역할은 다르다.
  홈 카드   업무를 둘러보고 새로 시작한다 (설명 · 현황)
  하단 독   어느 화면에서든 주요 업무로 바로 간다
  작업 탭   지금 열려 있는 화면 사이를 오간다 (열려 있다 ≠ 이어서 할 일이 있다)

업무 목록은 tasks.py 한 곳에서 읽는다. 카드·독·탭·[+] 메뉴가 같은 표를 보므로 새 업무를
더할 때 여기를 고칠 일이 없다.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
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

from .art import Art
from .icons import paint_icon
from .tasks import HOME_ICON, HOME_ID, TASKS, Task
from .theme import COLORS, card_shadow
from .tokens import FONT_SIZE, RADIUS
from .widgets import WrapLabel

_ICONS = Path(__file__).parent / "assets" / "icons"


def line_icon(name: str, size: int, color: str) -> QIcon:
    """선 아이콘을 QIcon 으로. 메뉴·툴버튼처럼 QIcon 만 받는 자리에 쓴다."""
    ratio = 2.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    paint_icon(painter, QRectF(0, 0, size, size), name, QColor(color))
    painter.end()
    return QIcon(pixmap)


def logo_pixmap(size: int) -> QPixmap:
    """앱 아이콘(tools/make_icon.py). 가까운 큰 그림을 골라 곱게 줄인다."""
    for side in (64, 128, 256):
        path = _ICONS / f"icon-{side}.png"
        if path.exists() and side >= size:
            return QPixmap(str(path)).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return QPixmap()


# ── 상단 바 ────────────────────────────────────────────────────────────
class IconButton(QToolButton):
    """선 아이콘 하나짜리 버튼. 이름은 접근성 이름과 말풍선으로 준다."""

    def __init__(self, icon: str, label: str, object_name: str = "topIcon", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self._icon = icon
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        side = 18
        box = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        paint_icon(painter, box, self._icon, QColor(COLORS["text_muted"]))


class TopBar(QWidget):
    """로고 · 이름 | 검색 · 설정 · 사용자 메뉴.

    창 드래그는 윈도우 기본 창틀이 맡는다. 이 바 안의 요소는 전부 클릭 대상이라 드래그와
    겹치지 않는다.
    """

    search_submitted = Signal(str)
    open_utility = Signal(str)       # 'settings' | 'updates'

    def __init__(self, app_name: str, workspace: str, user_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("topbar")
        self.setFixedHeight(56)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 0, 14, 0)
        row.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(34))
        logo.setFixedSize(34, 34)
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

        avatar = QLabel(user_name[:1] if user_name else "·")
        avatar.setObjectName("avatar")
        avatar.setAlignment(Qt.AlignCenter)
        row.addWidget(avatar)
        self.user_button = QPushButton(user_name)
        self.user_button.setObjectName("userMenu")
        self.user_button.setCursor(Qt.PointingHandCursor)
        self.user_button.setAccessibleName("사용자 메뉴")
        self.user_menu = QMenu(self.user_button)
        self.user_button.setMenu(self.user_menu)
        row.addWidget(self.user_button)


# ── 작업 탭 (파일 탐색기형) ─────────────────────────────────────────────
TAB_HEIGHT = 40
TAB_WIDTH = 164
HOME_TAB_WIDTH = 92
CLOSE_HIT = 28


class WorkTab(QWidget):
    """탭 하나 — 위만 둥근 모양을 직접 그린다.

    선택 탭은 흰색이고 아래가 트여 있어 작업 표면과 이어진다. 비선택 탭은 탭 줄과 같은
    옅은 바탕이라 글자만 보이고, 마우스가 올라오면 살짝 밝아진다.
    닫기 버튼 영역(28×28)은 탭 선택과 따로 처리해 한 번의 클릭이 두 가지 일을 하지 않게 한다.
    """

    activated = Signal(str)
    close_requested = Signal(str)

    def __init__(self, task_id: str, name: str, icon: str, closable: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.task_id = task_id
        self.name = name
        self.icon_name = icon
        self.closable = closable
        self._selected = False
        self._busy = False
        self._hover = False
        self._close_hover = False
        self.setFixedSize(HOME_TAB_WIDTH if not closable else TAB_WIDTH, TAB_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"{name} 탭")
        self.setToolTip(name)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)

    # ── 상태 ───────────────────────────────────────────────────────
    def set_selected(self, selected: bool) -> None:
        if self._selected != selected:
            self._selected = selected
            self.update()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.update()

    def _close_rect(self) -> QRect:
        return QRect(self.width() - CLOSE_HIT - 6, (self.height() - CLOSE_HIT) // 2, CLOSE_HIT, CLOSE_HIT)

    # ── 입력 ───────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if self.closable and self._close_rect().contains(event.position().toPoint()):
                self.close_requested.emit(self.task_id)
            else:
                self.activated.emit(self.task_id)
        elif event.button() == Qt.MiddleButton and self.closable:
            self.close_requested.emit(self.task_id)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        hover = self.closable and self._close_rect().contains(event.position().toPoint())
        if hover != self._close_hover:
            self._close_hover = hover
            self.update()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.HoverEnter:
            self._hover = True
            self.update()
        elif event.type() == QEvent.HoverLeave:
            self._hover = self._close_hover = False
            self.update()
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit(self.task_id)
        elif event.key() == Qt.Key_Delete and self.closable:
            self.close_requested.emit(self.task_id)
        else:
            super().keyPressEvent(event)

    # ── 그리기 ─────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = RADIUS["tab"]
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 2.5, w - 1, h + r)      # 아래쪽은 캔버스 밖으로 — 아래 모서리가 둥글지 않게

        if self._selected:
            path = QPainterPath()
            path.addRoundedRect(rect, r, r)
            painter.fillPath(path, QColor(COLORS["surface"]))
            painter.setPen(QPen(QColor(COLORS["border"]), 1))
            painter.drawPath(path)
            # 아래 테두리를 지워 작업 표면과 잇는다
            painter.setPen(Qt.NoPen)
            painter.fillRect(QRectF(1, h - 2, w - 2, 3), QColor(COLORS["surface"]))
        elif self._hover:
            path = QPainterPath()
            path.addRoundedRect(rect, r, r)
            painter.fillPath(path, QColor(COLORS["hover"]))
        if self.hasFocus():
            painter.setPen(QPen(QColor(COLORS["primary"]), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(2, 4, w - 4, h - 6), r - 2, r - 2)

        # 아이콘 → 이름 → 닫기
        x = 12
        color = COLORS["primary_hover"] if self._selected else COLORS["text_muted"]
        paint_icon(painter, QRectF(x, (h - 17) / 2 + 1, 17, 17), self.icon_name, QColor(color))
        x += 17 + 8
        font = QFont(self.font())
        font.setPixelSize(FONT_SIZE["nav"])
        font.setWeight(QFont.Weight.DemiBold if self._selected else QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["text"] if self._selected else COLORS["text_muted"]))
        right = (self._close_rect().left() - 4) if self.closable else (w - 12)
        text = QFontMetrics(font).elidedText(self.name, Qt.ElideRight, right - x)
        painter.drawText(QRectF(x, 0, right - x, h), Qt.AlignLeft | Qt.AlignVCenter, text)
        if self._busy:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["info"]))
            painter.drawEllipse(QRectF(x + QFontMetrics(font).horizontalAdvance(text) + 6, h / 2 - 3, 6, 6))
        if self.closable:
            box = self._close_rect()
            if self._close_hover:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(COLORS["divider"]))
                painter.drawRoundedRect(QRectF(box), 7, 7)
            inner = QRectF(box.x() + 7, box.y() + 7, 14, 14)
            paint_icon(painter, inner, "close", QColor(COLORS["text"] if self._close_hover else COLORS["text_faint"]))
        painter.end()


class WorkTabs(QWidget):
    """열린 작업 탭 줄 — 탭들(가로 스크롤) · [+] 새 작업 · [열린 작업] 목록.

    탭이 많아져도 글씨를 줄이지 않고 탭 영역 안에서만 가로로 밀린다(앱 전체에 가로
    스크롤이 생기지 않는다). 선택한 탭은 보이는 자리로 끌어온다.
    """

    activated = Signal(str)
    close_requested = Signal(str)
    new_task_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("tabRow")
        self.setFixedHeight(TAB_HEIGHT + 4)
        self._tabs: dict[str, WorkTab] = {}
        self._current = ""
        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 4, 8, 0)
        outer.setSpacing(4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        strip = QWidget()
        strip.setObjectName("tabRow")
        self._row = QHBoxLayout(strip)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(2)
        self._row.addStretch(1)
        self._scroll.setWidget(strip)
        outer.addWidget(self._scroll, 1)

        self.add_button = IconButton("plus", "새 작업", "tabTool")
        self._new_menu = QMenu(self.add_button)
        self.add_button.setMenu(self._new_menu)
        self.add_button.setPopupMode(QToolButton.InstantPopup)
        outer.addWidget(self.add_button, 0, Qt.AlignVCenter)

        self.more = IconButton("chevron-down", "열린 작업 목록", "tabTool")
        self._more_menu = QMenu(self.more)
        self.more.setMenu(self._more_menu)
        self.more.setPopupMode(QToolButton.InstantPopup)
        outer.addWidget(self.more, 0, Qt.AlignVCenter)
        self._refresh_new_menu()

    # ── 탭 관리 ────────────────────────────────────────────────────
    def add(self, task_id: str, name: str, icon: str, closable: bool = True) -> None:
        if task_id in self._tabs:
            return
        tab = WorkTab(task_id, name, icon, closable)
        tab.activated.connect(self.activated.emit)
        tab.close_requested.connect(self.close_requested.emit)
        self._tabs[task_id] = tab
        self._row.insertWidget(self._row.count() - 1, tab)
        self._refresh_menus()

    def remove(self, task_id: str) -> None:
        tab = self._tabs.pop(task_id, None)
        if tab is not None:
            self._row.removeWidget(tab)
            tab.deleteLater()
        self._refresh_menus()

    def has(self, task_id: str) -> bool:
        return task_id in self._tabs

    def ids(self) -> list[str]:
        return list(self._tabs)

    def neighbour(self, task_id: str) -> str:
        """탭을 닫을 때 옮겨 갈 이웃 — 왼쪽, 없으면 오른쪽, 없으면 홈."""
        ids = self.ids()
        if task_id not in ids:
            return HOME_ID
        i = ids.index(task_id)
        if i > 0:
            return ids[i - 1]
        return ids[1] if len(ids) > 1 else HOME_ID

    def set_current(self, task_id: str) -> None:
        self._current = task_id
        for tid, tab in self._tabs.items():
            tab.set_selected(tid == task_id)
        tab = self._tabs.get(task_id)
        if tab is not None:
            self._scroll.ensureWidgetVisible(tab, 24, 0)
        self._refresh_menus()

    def set_busy(self, task_id: str, busy: bool) -> None:
        tab = self._tabs.get(task_id)
        if tab is not None:
            tab.set_busy(busy)

    # ── 메뉴 ───────────────────────────────────────────────────────
    def _refresh_new_menu(self) -> None:
        self._new_menu.clear()
        for task in TASKS:
            label = task.name + ("  · 준비 중" if not task.ready else "")
            if task.id in self._tabs:
                label += "  (열려 있음)"
            action = self._new_menu.addAction(line_icon(task.icon, 16, COLORS["text_muted"]), label)
            action.triggered.connect(lambda _c=False, t=task.id: self.new_task_requested.emit(t))

    def _refresh_menus(self) -> None:
        self._refresh_new_menu()
        self._more_menu.clear()
        for tid, tab in self._tabs.items():
            current = tid == self._current
            icon = line_icon("check" if current else tab.icon_name, 16,
                             COLORS["primary_hover"] if current else COLORS["text_muted"])
            action = self._more_menu.addAction(icon, tab.name)
            action.triggered.connect(lambda _c=False, t=tid: self.activated.emit(t))

    def wheelEvent(self, event) -> None:  # noqa: N802
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y() // 2)


# ── 하단 독 ────────────────────────────────────────────────────────────
class DockButton(QToolButton):
    """독 항목 — 입체 그림 위, 이름 아래. 현재 위치는 이름 뒤 옅은 라벤더 알약과 작은 점.

    그림은 흰 바탕에 맞춘 에셋이라(art.py) 그림 뒤는 늘 흰색으로 두고, 선택 표시는 이름
    쪽에만 준다. 그래야 그림 둘레에 사각 경계가 드러나지 않는다.
    """

    def __init__(self, task_id: str, name: str, art: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.task_id = task_id
        self.name = name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip(name)
        self.setAccessibleName(name)
        self._art = Art(art, 32, self)
        self._art.hide()
        self._hover = False
        self._side = 32
        self.setAttribute(Qt.WA_Hover, True)
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        self._side = 26 if compact else 32
        self._art.set_size(self._side)
        font = QFont(self.font())
        font.setPixelSize(FONT_SIZE["nav"])
        width = max(72, QFontMetrics(font).horizontalAdvance(self.name) + 26)
        self.setFixedSize(width, self._side + 34)
        self.update()

    def event(self, event: QEvent) -> bool:
        if event.type() in (QEvent.HoverEnter, QEvent.HoverLeave):
            self._hover = event.type() == QEvent.HoverEnter
            self.update()
        return super().event(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        lift = 2 if self._hover else 0
        pix = self._art._pixmap_for(self.devicePixelRatioF())
        painter.drawPixmap(int((w - self._side) / 2), 4 - lift, pix)
        font = QFont(self.font())
        font.setPixelSize(FONT_SIZE["nav"])
        font.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Medium)
        painter.setFont(font)
        text_w = QFontMetrics(font).horizontalAdvance(self.name)
        label = QRectF((w - text_w) / 2 - 8, self._side + 8, text_w + 16, 20)
        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["selection"]))
            painter.drawRoundedRect(label, 10, 10)
        elif self._hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["hover"]))
            painter.drawRoundedRect(label, 10, 10)
        painter.setPen(QColor(COLORS["primary_hover"] if self.isChecked() else COLORS["text_muted"]))
        painter.drawText(label, Qt.AlignCenter, self.name)
        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["primary"]))
            painter.drawEllipse(QRectF(w / 2 - 2, h - 5, 4, 4))
        if self.hasFocus():
            painter.setPen(QPen(QColor(COLORS["primary"]), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 12, 12)
        painter.end()


class Dock(QFrame):
    """하단 플로팅 독. 전용 영역(DockArea) 안에 놓여 본문을 가리지 않는다."""

    activated = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dock")
        card_shadow(self, "hero")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
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
        self.layout().setContentsMargins(6, 2, 6, 2) if compact else self.layout().setContentsMargins(8, 4, 8, 4)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        buttons = list(self._buttons.values())
        focused = next((i for i, b in enumerate(buttons) if b.hasFocus()), -1)
        if focused >= 0 and event.key() in (Qt.Key_Left, Qt.Key_Right):
            step = -1 if event.key() == Qt.Key_Left else 1
            buttons[(focused + step) % len(buttons)].setFocus()
            return
        super().keyPressEvent(event)


class DockArea(QWidget):
    """독이 놓이는 하단 전용 공간. 독 높이 + 상하 여백만 차지한다 — 본문 위에 겹치지 않는다."""

    def __init__(self, dock: Dock, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dockArea")
        self.dock = dock
        layout = QHBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(dock)
        layout.addStretch(1)
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        self.dock.set_compact(compact)
        self.layout().setContentsMargins(0, 4 if compact else 8, 0, 6 if compact else 10)
        self.setFixedHeight(self.sizeHint().height())


# ── 홈 업무 카드 ────────────────────────────────────────────────────────
class TaskCard(QFrame):
    """업무 하나 — 큰 입체 그림과 이름뿐. 타일 전체가 누르는 곳이다.

    설명·현황·화살표·테두리는 두지 않는다(담당자 요청). 준비 중인 업무만 이름 아래 작게 적는다.
    그림 자리는 흰 판에 업무 색 테두리만 두른다 — 그림 에셋이 흰 바탕에 맞춰 만들어져,
    색을 채우면 그림 둘레에 사각 경계가 드러나기 때문이다.
    """

    activated = Signal(str)

    def __init__(self, task: Task, parent: QWidget | None = None):
        super().__init__(parent)
        self.task = task
        self.setObjectName("taskTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"{task.name} 열기" + ("" if task.ready else " (준비 중, 미리보기)"))
        # 타일은 폭을 못박고 왼쪽부터 늘어놓는다. 창 폭에 맞춰 늘이면 넷이 멀찍이 흩어져 '도구함' 으로 안 읽힌다
        self.setFixedSize(196, 186)
        self.setAttribute(Qt.WA_Hover, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 10)
        layout.setSpacing(10)

        self.plate = QFrame()
        self.plate.setObjectName(f"taskArt_{task.accent}")
        self.plate.setFixedSize(108, 108)
        plate_layout = QVBoxLayout(self.plate)
        plate_layout.setContentsMargins(0, 0, 0, 0)
        plate_layout.addWidget(Art(task.art, 92), 0, Qt.AlignCenter)
        layout.addWidget(self.plate, 0, Qt.AlignHCenter)

        name = QLabel(task.name)
        name.setObjectName("taskName")
        name.setAlignment(Qt.AlignCenter)
        layout.addWidget(name)

        self.badge = QLabel("준비 중")
        self.badge.setObjectName("taskStatus")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setVisible(not task.ready)
        layout.addWidget(self.badge)
        layout.addStretch(1)

    def set_status(self, text: str) -> None:
        """현황은 타일에 쓰지 않는다. 호출부 호환용으로 말풍선에만 남긴다."""
        self.setToolTip(f"{self.task.name} · {text}" if text else self.task.name)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        # 누른 자리에서 뗐을 때 한 번만. 안의 라벨은 마우스를 받지 않으므로 중복 실행이 없다
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self.task.id)
        super().mouseReleaseEvent(event)

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
        # 마우스가 올라오면 그림이 2px 떠오른다. 애니메이션 없이 위치만 바꾼다
        if event.type() == QEvent.HoverEnter:
            self.plate.setContentsMargins(0, 0, 0, 2)
        elif event.type() == QEvent.HoverLeave:
            self.plate.setContentsMargins(0, 2, 0, 0)
        return super().event(event)
