"""화면 구성 요소 — 페이지 머리 · 카드 · 요약 카드 · 단계 카드 · 빈 상태 · 배지 · 입력 칸.

입체 그림(Art)은 요약 카드·단계 카드·빈 상태에만 놓는다. 모두 흰 면이다.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QStyle,
    QStyledItemDelegate,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .art import Art
from .theme import STATUS, card_shadow


class WrapLabel(QLabel):
    """여러 줄로 접히는 글자.

    Qt 레이아웃은 접힌 글자의 높이를 폭이 정해진 뒤에야 안다. 스크롤 영역이나 높이가
    빠듯한 카드 안에서는 그 높이를 못 받아 아래 위젯과 겹쳐 그려졌다. 폭이 바뀔 때마다
    필요한 높이를 최소 높이로 못박아 겹치지 않게 한다.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        # 높이가 글자보다 커져도 위에 붙인다. 가운데 정렬이면 제목과 사이가 벌어져 보인다.
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
        texts.setSpacing(4)
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
        self.actions.addWidget(widget, 0, Qt.AlignBottom)


class Card(QFrame):
    """흰 카드. 제목 왼쪽에 작은 입체 그림, 오른쪽에 보조 위젯을 얹을 수 있다."""

    def __init__(self, title: str = "", hint: str = "", art: str = "", variant: str = "card",
                 shadow: bool = True, margins: tuple[int, int, int, int] = (24, 20, 24, 22),
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(variant)
        if shadow:
            card_shadow(self)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(14)
        self._header = None
        if title:
            header = QHBoxLayout()
            header.setSpacing(12)
            if art:
                header.addWidget(Art(art, 40))
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
    """요약 카드 — 숫자가 먼저 읽히고, 그림은 옆에서 무엇의 숫자인지 알려 준다."""

    def __init__(self, label: str, art: str, caption: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        card_shadow(self)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(104)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 14, 14, 14)
        row.setSpacing(10)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.label = _label(label, "kpiLabel")
        self.value = _label("—", "kpiValue")
        # 보조 문구는 한 줄. 넘치면 '…' 으로 줄이고 전체는 말풍선으로 보여 준다
        self.caption = ElideLabel(caption)
        self.caption.setObjectName("kpiCaption")
        texts.addWidget(self.label)
        texts.addWidget(self.value)
        texts.addWidget(self.caption)
        row.addLayout(texts, 1)
        row.addWidget(Art(art, 56), 0, Qt.AlignTop)

    def set_value(self, value: str, caption: str | None = None) -> None:
        self.value.setText(value)
        if caption is not None:
            self.caption.setText(caption)


class StepCard(QFrame):
    """업무 단계 바로가기 — 번호 · 입체 그림 · 무엇을 하는지 · 실행 버튼."""

    def __init__(self, number: str, title: str, description: str, art: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        card_shadow(self)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 18, 16)
        outer.setSpacing(12)
        outer.addWidget(Art(art, 60), 0, Qt.AlignTop)
        body = QVBoxLayout()
        body.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(_label(number, "stepNo"))
        top.addWidget(_label(title, "cardTitle"), 1)
        body.addLayout(top)
        self.description = _label(description, "muted", wrap=True)
        body.addWidget(self.description)
        body.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        body.addLayout(self.actions)
        outer.addLayout(body, 1)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def finish_actions(self) -> None:
        self.actions.addStretch(1)


class EmptyState(QWidget):
    """보여 줄 것이 없을 때 — 큰 입체 그림 + 무엇을 하면 되는지."""

    def __init__(self, art: str, title: str, message: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
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
        side = 128 if height >= 360 else 88 if height >= 230 else 64 if height >= 170 else 0
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
        self.set_status(text, status)

    def set_status(self, text: str, status: str) -> None:
        self.setText(text)
        self.setObjectName(f"pill_{status}")
        self.style().unpolish(self)
        self.style().polish(self)


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
        # 선택·호버 바탕은 기본 그리기에 맡기고 글자만 지운다
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
        font.setWeight(font.Weight.DemiBold)
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
