"""화면 구성 요소 — 페이지 머리 · 카드 · 요약 카드 · 단계 · 빈 상태 · 배지 · 입력 칸.

카드는 얇은 테두리가 기본이고 그림자는 주지 않는다(그림자는 홈 업무 카드와 독에만).
입체 그림(Art)은 요약 카드·단계·빈 상태에만 놓는다. 모두 흰 면이다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .art import Art
from .theme import STATUS


def fit_to_text(widget: QWidget) -> QWidget:
    """글자 길이만큼만 차지하게 — 줄에 남는 폭을 늘려 받지 않는다. 폭을 숫자로 박지 않고 글자(sizeHint)를 따른다.

    담당자 2026-10-21: 단계 번호 · 상태 배지가 줄 폭을 나눠 받아 가로로 길게 늘어났다 — "안에 글씨에 맞춰서 자동 길이 조정".
    """
    widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return widget


class WrapLabel(QLabel):
    """여러 줄로 접히는 글자.

    Qt 레이아웃은 접힌 글자의 높이를 폭이 정해진 뒤에야 안다. 스크롤 영역이나 높이가
    빠듯한 카드 안에서는 그 높이를 못 받아 아래 위젯과 겹쳐 그려졌다. 폭이 바뀔 때마다
    필요한 높이를 최소 높이로 못박아 겹치지 않게 한다.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

    def _fit(self) -> None:
        need = self.heightForWidth(max(1, self.width()))
        if need > 0 and need != self.minimumHeight():
            self.setMinimumHeight(need)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self._fit()


class ElideLabel(QLabel):
    """한 줄 글자. 폭이 모자라면 끝을 '…' 으로 줄이고, 전체는 말풍선으로 보여 준다."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setMinimumWidth(10)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        rect = self.contentsRect()
        elided = QFontMetrics(self.font()).elidedText(self.text(), Qt.ElideRight, rect.width())
        painter.drawText(rect, int(Qt.AlignLeft | Qt.AlignVCenter), elided)


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    label = WrapLabel(text) if wrap else QLabel(text)
    label.setObjectName(name)
    return label


def muted_label(text: str) -> QLabel:
    return _label(text, "muted", wrap=True)


class PageHeader(QWidget):
    """경로 · 제목 · 설명. 오른쪽에 그 화면의 주요 실행 버튼을 둔다."""

    def __init__(self, path: str, title: str, description: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(_label(path, "breadcrumb"))
        self.title = _label(title, "pageTitle")
        texts.addWidget(self.title)
        if description:
            texts.addWidget(_label(description, "pageDesc", wrap=True))
        row.addLayout(texts, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        row.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget, 0, Qt.AlignVCenter)


class Card(QFrame):
    """흰 카드(얇은 테두리). 제목 왼쪽에 작은 입체 그림, 오른쪽에 보조 위젯을 얹을 수 있다."""

    def __init__(self, title: str = "", hint: str = "", art: str = "", variant: str = "card",
                 margins: tuple[int, int, int, int] = (20, 18, 20, 18),
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(variant)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(12)
        self._header = None
        if title:
            header = QHBoxLayout()
            header.setSpacing(12)
            if art:
                header.addWidget(Art(art, 46))
            titles = QVBoxLayout()
            titles.setSpacing(2)
            self.title_label = _label(title, "cardTitle")
            titles.addWidget(self.title_label)
            if hint:
                self.hint_label = _label(hint, "cardHint", wrap=True)
                titles.addWidget(self.hint_label)
            header.addLayout(titles, 1)
            self._header = header
            self._layout.addLayout(header)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self._layout.addWidget(widget, stretch)

    def add_layout(self, layout, stretch: int = 0) -> None:
        self._layout.addLayout(layout, stretch)

    def add_header_widget(self, widget: QWidget) -> None:
        if self._header is not None:
            self._header.addWidget(widget, 0, Qt.AlignVCenter)


class KpiCard(QFrame):
    """요약 카드 — 낮게. 숫자가 먼저 읽히고, 그림은 옆에서 무엇의 숫자인지 알려 준다."""

    def __init__(self, label: str, art: str, caption: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(88)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 12, 10)
        row.setSpacing(8)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.label = _label(label, "kpiLabel")
        self.value = _label("—", "kpiValue")
        self.caption = ElideLabel(caption)
        self.caption.setObjectName("kpiCaption")
        texts.addWidget(self.label)
        texts.addWidget(self.value)
        texts.addWidget(self.caption)
        row.addLayout(texts, 1)
        self.art = Art(art, 56)
        row.addWidget(self.art, 0, Qt.AlignVCenter)

    def set_value(self, value: str, caption: str | None = None) -> None:
        self.value.setText(value)
        if caption is not None:
            self.caption.setText(caption)

    def set_compact(self, compact: bool) -> None:
        """낮은 창 — 보조 문구를 숨기고 높이를 줄인다. 숫자와 이름은 그대로."""
        self.caption.setVisible(not compact)
        self.setFixedHeight(68 if compact else 88)
        self.art.set_size(46 if compact else 56)     # 낮은 카드(위아래 여백 10씩)에 들어가게


class Step(QFrame):
    """업무 단계 하나 — 번호 · 그림 · 제목 · 한 줄 설명 · 버튼. 가로로 나란히 놓인다.

    현재 단계만 강조(라벤더 테두리)하고, 끝난 단계는 옅게 가라앉힌다.
    """

    def __init__(self, number: str, title: str, description: str, art: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(10)
        row.addWidget(Art(art, 52), 0, Qt.AlignVCenter)
        body = QVBoxLayout()
        body.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.number = fit_to_text(_label(number, "stepNo"))
        self.number.setAlignment(Qt.AlignCenter)
        head.addWidget(self.number)
        head.addWidget(_label(title, "cardTitle"), 1)
        body.addLayout(head)
        self.description = ElideLabel(description)
        self.description.setObjectName("muted")
        body.addWidget(self.description)
        row.addLayout(body, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        row.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_compact(self, compact: bool) -> None:
        """좁거나 낮은 창 — 설명 줄을 숨겨 번호·제목·버튼만 남긴다. 글씨를 줄이지 않는다."""
        self.description.setVisible(not compact)
        self.layout().setContentsMargins(14, 8 if compact else 12, 14, 8 if compact else 12)

    def set_state(self, state: str) -> None:
        """'current' | 'done' | 'todo'"""
        self.setObjectName({"current": "cardCurrent", "done": "cardDone"}.get(state, "card"))
        self.number.setObjectName("stepNoDone" if state == "done" else "stepNo")
        for widget in (self, self.number):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class EmptyState(QWidget):
    """보여 줄 것이 없을 때 — 입체 그림 + 무엇을 하면 되는지."""

    def __init__(self, art: str, title: str, message: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(6)
        layout.addStretch(1)
        self.art = Art(art, 128)
        layout.addWidget(self.art, 0, Qt.AlignHCenter)
        self.title = _label(title, "cardTitle")
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)
        self.message = _label(message, "muted", wrap=True)
        self.message.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.message)
        self.actions = QHBoxLayout()
        self.actions.addStretch(1)
        self.actions.addStretch(1)
        layout.addLayout(self.actions)
        layout.addStretch(1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """자리가 좁으면 그림을 줄이고, 더 좁으면 숨긴다. 글자와 버튼이 먼저다."""
        super().resizeEvent(event)
        height = self.height()
        side = 112 if height >= 330 else 80 if height >= 220 else 56 if height >= 160 else 0
        self.art.setVisible(side > 0)
        if side:
            self.art.set_size(side)

    def set_content(self, art: str, title: str, message: str) -> None:
        self.art.set_meaning(art)
        self.title.setText(title)
        self.message.setText(message)

    def add_action(self, widget: QWidget) -> None:
        self.actions.insertWidget(self.actions.count() - 1, widget)


class Pill(QLabel):
    """상태 배지. 색만으로 알리지 않고 글자를 함께 쓴다."""

    def __init__(self, text: str = "", status: str = "neutral", parent: QWidget | None = None):
        super().__init__(text, parent)
        fit_to_text(self)
        self.set_status(text, status)

    def set_status(self, text: str, status: str) -> None:
        self.setText(text)
        self.setObjectName(f"pill_{status}")
        self.style().unpolish(self)
        self.style().polish(self)
        # 스타일이 바뀌면 글자 폭도 바뀐다 — 글자만큼만 차지하는 배지라(fit_to_text) 레이아웃에 다시 재게 알린다(안 하면 '로그인됨' 이 잘렸다)
        self.updateGeometry()


class Field(QWidget):
    """입력 칸 한 줄 — 늘 보이는 라벨 · 입력 · 도움말 · 오류."""

    def __init__(self, label: str, control: QWidget, help_text: str = "",
                 required: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.label = _label(label + (" *" if required else ""), "fieldLabel")
        self.label.setBuddy(control)
        layout.addWidget(self.label)
        self.row = QHBoxLayout()
        self.row.setSpacing(8)
        self.row.addWidget(control, 1)
        layout.addLayout(self.row)
        self.help = _label(help_text, "fieldHelp", wrap=True)
        self.help.setVisible(bool(help_text))
        layout.addWidget(self.help)
        self.error = _label("", "fieldError", wrap=True)
        self.error.hide()
        layout.addWidget(self.error)
        self._control = control

    def add_button(self, widget: QWidget) -> None:
        self.row.addWidget(widget)

    def set_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))
        self._control.setProperty("error", bool(message))
        self._control.style().unpolish(self._control)
        self._control.style().polish(self._control)


class PillDelegate(QStyledItemDelegate):
    """표 안의 상태 칸을 배지로 그린다. 배지 색은 항목의 ROLE 값('success' 등)."""

    ROLE = Qt.UserRole + 1

    def paint(self, painter: QPainter, option, index) -> None:
        option.text = ""
        style = option.widget.style() if option.widget else None
        if style is not None:
            style.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        text = index.data(Qt.DisplayRole) or ""
        tone = index.data(self.ROLE) or "neutral"
        fg, bg = STATUS.get(tone, STATUS["neutral"])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        font = option.font
        font.setPixelSize(12)
        font.setWeight(font.Weight.Medium)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(text) + 18
        height = 22
        rect = QRectF(option.rect.x() + 10, option.rect.center().y() - height / 2 + 1, width, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, height / 2, height / 2)
        painter.setPen(QColor(fg))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


class WheelGuard(QObject):
    """드롭다운(QComboBox) 위에서 마우스 휠 · 터치패드를 굴려도 값이 바뀌지 않게 — 앱 전체 이벤트 필터.

    담당자 2026-10-26: "드롭다운 옵션 박스 위에 마우스가 올라가 있을 때 드래그하면 옵션이 돌아가면서 바뀌는데 이거 불편함 …
    드롭다운 박스를 클릭하고 옵션을 클릭해서 선택하는 기능만". 단계 흐름 화면은 스크롤 칸이라 아래로 내리다 콤보 위를
    지나는 순간 종류 · 과제 · 할 일이 바뀌었다.

    휠 이벤트가 콤보에 닿으면 콤보의 처리기 대신 **콤보를 감싼 위젯 차례로**(부모 → 그 부모 …) 같은 휠을 넘겨, 그 자리를
    감싼 스크롤 칸은 전처럼 움직이게 한다. Qt 는 받지 않은 휠을 스스로 부모로 올리지만 **사람이 굴린 것(spontaneous)만** 그렇고
    (Qt 6.12 `QApplication::notify`), 앱이 보낸 것은 올리지 않아 시험에서 보이지 않는다 — 그래서 가드가 직접 넘기고, 받는 곳이
    있었으면 원래 이벤트를 받은 것으로 표시해 Qt 가 한 번 더 올리지 않게 한다. 펼친 목록 안의 휠 · 키보드 화살표 · 클릭은 그대로다.
    콤보는 기본 초점 규칙이 WheelFocus 라 휠이 지나가기만 해도 초점(테두리)을 가져가므로, 만들어질 때(Polish) StrongFocus 로 둔다 —
    클릭 · Tab 으로 받는 초점은 같다. `app.main()` 이 한 번 깐다 — 새 콤보를 만들 때 따로 할 일은 없다.
    """

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Polish and isinstance(obj, QComboBox) and obj.focusPolicy() == Qt.WheelFocus:
            obj.setFocusPolicy(Qt.StrongFocus)
        elif kind == QEvent.Wheel and isinstance(obj, QComboBox):
            event.setAccepted(self._pass_up(obj, event))
            return True
        return False

    @staticmethod
    def _pass_up(combo: QComboBox, event: QWheelEvent) -> bool:
        """콤보를 감싼 위젯 차례로 같은 휠을 보낸다 — 받는 것(스크롤 칸)이 있으면 True. Qt 의 전파 규칙과 같은 자리에서 멈춘다."""
        widget = combo.parentWidget()
        while widget is not None:
            pos = QPointF(widget.mapFromGlobal(event.globalPosition().toPoint()))
            copy = QWheelEvent(pos, event.globalPosition(), event.pixelDelta(), event.angleDelta(), event.buttons(),
                               event.modifiers(), event.phase(), event.inverted(), event.source(), event.pointingDevice())
            copy.setTimestamp(event.timestamp())
            QApplication.sendEvent(widget, copy)
            if copy.isAccepted():
                return True
            if widget.isWindow() or widget.testAttribute(Qt.WA_NoMousePropagation):
                return False
            widget = widget.parentWidget()
        return False
