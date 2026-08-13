"""대시보드 구성 요소.

시안의 카드·KPI 타일·도넛 차트를 Qt 위젯으로 옮긴 것들. 차트는 외부 라이브러리
없이 QPainter 로 그린다 — 값이 몇 개뿐이라 라이브러리를 얹을 이유가 없다.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import COLORS, SEVERITY_STYLE, card_shadow


class Card(QFrame):
    """흰 카드. 제목과 오른쪽 보조 위젯을 얹을 수 있다."""

    def __init__(self, title: str = "", hint: str = "", variant: str = "card",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(variant)
        card_shadow(self)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 16, 18, 16)
        self._layout.setSpacing(12)

        if title or hint:
            header = QHBoxLayout()
            header.setSpacing(8)
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
                 variant: str = "card", value_color: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(variant)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        card_shadow(self, blur=22, alpha=30)

        dark = variant != "card"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(2)

        self.label = QLabel(label)
        self.label.setObjectName("statLabelDark" if dark else "statLabel")
        self.value = QLabel(value)
        self.value.setObjectName("statValueDark" if dark else "statValue")
        if value_color and not dark:
            # 숫자 자체에 심각도 색을 준다 — 시안처럼 수치가 먼저 읽히게.
            self.value.setStyleSheet(f"color: {value_color};")
        self.caption = QLabel(caption)
        self.caption.setObjectName("statLabelDark" if dark else "statCaption")
        self.caption.setWordWrap(True)

        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addWidget(self.caption)
        layout.addStretch(1)

    def set_value(self, value: str, caption: str = "") -> None:
        self.value.setText(value)
        if caption:
            self.caption.setText(caption)


class DonutChart(QWidget):
    """검토 결과 구성비 도넛. 가운데에 총계를 쓴다."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(150, 150)
        self._segments: list[tuple[str, int, str]] = []   # (라벨, 값, 색)
        self._center_value = "0"
        self._center_label = ""

    def set_data(self, segments: list[tuple[str, int, str]],
                 center_value: str, center_label: str = "") -> None:
        self._segments = [s for s in segments if s[1] > 0]
        self._center_value = center_value
        self._center_label = center_label
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 명명 규칙)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        side = min(self.width(), self.height()) - 12
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        thickness = max(14.0, side * 0.16)
        inset = rect.adjusted(thickness / 2, thickness / 2, -thickness / 2, -thickness / 2)

        total = sum(value for _, value, _ in self._segments)
        if total <= 0:
            pen = QPen(QColor(COLORS["border"]), thickness, Qt.SolidLine, Qt.FlatCap)
            painter.setPen(pen)
            painter.drawEllipse(inset)
        else:
            start = 90 * 16          # 12시 방향에서 시작
            for _, value, color in self._segments:
                span = -int(round(360 * 16 * value / total))
                pen = QPen(QColor(color), thickness, Qt.SolidLine, Qt.FlatCap)
                painter.setPen(pen)
                painter.drawArc(inset, start, span)
                start += span

        painter.setPen(QColor(COLORS["text"]))
        font = QFont(self.font())
        font.setPointSize(max(13, int(side * 0.12)))
        font.setBold(True)
        painter.setFont(font)
        center = QRectF(rect.x(), rect.y() + side * 0.34, side, side * 0.20)
        painter.drawText(center, Qt.AlignCenter, self._center_value)

        if self._center_label:
            painter.setPen(QColor(COLORS["text_muted"]))
            small = QFont(self.font())
            small.setPointSize(max(7, int(side * 0.055)))
            painter.setFont(small)
            below = QRectF(rect.x(), rect.y() + side * 0.53, side, side * 0.14)
            painter.drawText(below, Qt.AlignCenter, self._center_label)


class SeverityBar(QWidget):
    """🔴🟡🔵 구성비를 가로 막대 하나로 보여 준다. 파일 카드에 쓴다."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._parts: list[tuple[int, str]] = []

    def set_counts(self, counts: dict) -> None:
        self._parts = [
            (count, SEVERITY_STYLE[severity.name]["color"])
            for severity, count in counts.items() if count
        ]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        total = sum(count for count, _ in self._parts)
        radius = self.height() / 2

        if total == 0:
            painter.setBrush(QColor(COLORS["pass"]))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
            return

        x = 0.0
        painter.setPen(Qt.NoPen)
        for count, color in self._parts:
            width = self.width() * count / total
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(x, 0, max(width, 3.0), self.height()), radius, radius)
            x += width


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


class FileCard(QFrame):
    """파일 하나의 보완사항 요약 카드. 누르면 상세를 연다."""

    clicked = Signal(object)

    def __init__(self, summary, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.summary = summary
        card_shadow(self, blur=18, alpha=20, dy=4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)

        top = QHBoxLayout()
        top.setSpacing(8)
        status = SEVERITY_STYLE[summary.status.name]
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {status['color']}; font-size: 13px;")
        top.addWidget(dot)

        name = QLabel(summary.name)
        name.setStyleSheet("font-size: 12px; font-weight: 700;")
        name.setWordWrap(True)
        top.addWidget(name, 1)
        layout.addLayout(top)

        kind = QLabel(summary.doc_label)
        kind.setObjectName("cardHint")
        layout.addWidget(kind)

        bar = SeverityBar()
        bar.set_counts(summary.counts)
        layout.addWidget(bar)

        pills = QHBoxLayout()
        pills.setSpacing(6)
        counts = summary.counts
        if not summary.findings:
            pills.addWidget(Pill("이상 없음", COLORS["pass"]))
        else:
            for severity, count in counts.items():
                if count:
                    style = SEVERITY_STYLE[severity.name]
                    pills.addWidget(Pill(f"{style['label']} {count}", style["color"]))
        pills.addStretch(1)
        layout.addLayout(pills)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.summary)
        super().mousePressEvent(event)


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


def polar_point(center_x: float, center_y: float, radius: float, degrees: float):
    radians = math.radians(degrees)
    return center_x + radius * math.cos(radians), center_y - radius * math.sin(radians)
