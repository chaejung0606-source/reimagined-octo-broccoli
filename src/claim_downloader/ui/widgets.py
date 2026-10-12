"""화면 구성 요소 — 카드 · KPI 타일 · 배지."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import card_shadow


class Card(QFrame):
    """흰 카드. 제목과 오른쪽 보조 위젯을 얹을 수 있다."""

    def __init__(self, title: str = "", hint: str = "", variant: str = "card",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(variant)
        card_shadow(self)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 22, 24, 22)
        self._layout.setSpacing(16)

        if title or hint:
            header = QHBoxLayout()
            header.setSpacing(10)
            label = QLabel(title)
            label.setObjectName("cardTitle")
            header.addWidget(label)
            header.addStretch(1)
            if hint:
                hint_label = QLabel(hint)
                hint_label.setObjectName("cardHint")
                header.addWidget(hint_label)
            self._header = header
            self._layout.addLayout(header)
        else:
            self._header = None

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self._layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)

    def add_header_widget(self, widget: QWidget) -> None:
        if self._header is not None:
            self._header.addWidget(widget)



class StatTile(QFrame):
    """KPI 타일. 큰 숫자 + 라벨 + 보조 문구.

    variant: 'card'(흰색) | 'cardAccent'(남색 그라데이션) | 'cardTeal'(청록)
    """

    def __init__(self, label: str, value: str = "—", caption: str = "",
                 variant: str = "card", tone: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(variant)
        self.setMinimumHeight(116)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        card_shadow(self, blur=22, alpha=30)

        self._tone = tone
        self._variant = variant
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(4)

        self.label = QLabel(label)
        self.value = QLabel(value)
        self.caption = QLabel(caption)
        self.caption.setWordWrap(True)
        self._apply_text_roles()

        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addWidget(self.caption)
        layout.addStretch(1)

    def _apply_text_roles(self) -> None:
        """글자색 역할을 정한다.

        색을 입힌 카드(cardAccent) 위에서만 밝은 글자를 쓴다. 흰 카드에서는
        숫자에 판정 색을 입혀 수치가 먼저 읽히게 한다.
        """
        on_color = self._variant != "card"
        self.label.setObjectName("statLabelDark" if on_color else "statLabel")
        self.caption.setObjectName("statLabelDark" if on_color else "statCaption")
        if on_color:
            self.value.setObjectName("statValueDark")
        elif self._tone:
            # 인라인 스타일 대신 objectName 을 쓴다. 테마를 바꿀 때 스타일시트만
            # 다시 적용하면 색이 따라오기 때문이다.
            self.value.setObjectName(f"statValue{self._tone}")
        else:
            self.value.setObjectName("statValue")
        for widget in (self.label, self.value, self.caption):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.update()

    def set_value(self, value: str, caption: str = "") -> None:
        self.value.setText(value)
        if caption:
            self.caption.setText(caption)



class Pill(QLabel):
    """상태 배지. '🔴 3' 처럼 개수를 함께 보여 준다."""

    def __init__(self, text: str, color: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(22)
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet(
            f"background: {_tint(color, 0.13)}; color: {color};"
            f"border-radius: 11px; padding: 0 10px; font-size: 11px; font-weight: 700;"
        )


class EmptyState(QWidget):
    """아직 보여 줄 게 없을 때 안내 문구를 가운데 띄운다."""

    def __init__(self, message: str, mood: str = "sleepy", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(6)
        layout.addStretch(1)

        self.label = QLabel(message)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setObjectName("cardHint")
        layout.addWidget(self.label)
        layout.addStretch(1)

    def set_message(self, message: str, mood: str = "sleepy") -> None:
        self.label.setText(message)


def _tint(hex_color: str, alpha: float) -> str:
    """색을 흰 배경 위에 옅게 깐 값으로 바꾼다. 배지 배경에 쓴다."""
    color = QColor(hex_color)
    red = round(255 + (color.red() - 255) * alpha)
    green = round(255 + (color.green() - 255) * alpha)
    blue = round(255 + (color.blue() - 255) * alpha)
    return f"rgb({red}, {green}, {blue})"


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionHead")
    return label


def muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("cardHint")
    label.setWordWrap(True)
    return label
