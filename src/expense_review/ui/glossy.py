"""Y2K 유광 플라스틱 컨트롤 — QPainter 로 직접 그린다.

Qt 스타일시트에는 CSS 의 `::before` / `::after` 도, inset box-shadow 도 없다.
'두께가 있는 플라스틱 버튼'은 여러 겹을 포개야 나오는 질감이라 스타일시트로는
흉내가 안 된다. 그래서 이 모듈의 컨트롤은 위젯이 스스로 그린다.

한 겹씩 쌓는 순서 — 아래로 갈수록 위에 얹힌다.

    1. 크롬 림      바깥 테두리. 위는 하양, 아래는 진회색이라 금속처럼 보인다
    2. 색면         단색이 아니라 위가 밝은 그라데이션
    3. 안쪽 그림자  아래쪽을 눌러 오목하게. 이게 있어야 '두께'가 생긴다
    4. 유광 반사    윗면에 넓고 부드러운 흰 반사
    5. 테두리 하이라이트  림 바로 안쪽 1px 흰 선

바깥 그림자는 위젯 밖으로 나가야 해서 QGraphicsDropShadowEffect 로 따로 준다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .theme import COLORS, card_shadow

RIM = 2.6          # 크롬 테두리 두께
PRESS_DROP = 1.0   # 눌렸을 때 내려가는 거리


def _tone(color: QColor, factor: int) -> QColor:
    return color.lighter(factor) if factor >= 100 else color.darker(200 - factor)


def paint_glossy(painter: QPainter, rect: QRectF, radius: float, base: QColor,
                 *, pressed: bool = False, hovered: bool = False,
                 gloss: float = 0.46, rim: float = RIM,
                 shine: int = 132) -> QRectF:
    """유광 플라스틱 면을 그리고, 내용물을 얹을 안쪽 사각형을 돌려준다."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)

    if pressed:
        rect = QRectF(rect.x(), rect.y() + PRESS_DROP, rect.width(),
                      rect.height() - PRESS_DROP)

    # 1. 크롬 림 — 위 하양 → 은색 → 아래 진회색
    outer = QPainterPath()
    outer.addRoundedRect(rect, radius, radius)
    chrome = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    chrome.setColorAt(0.0, QColor(255, 255, 255, 250))
    chrome.setColorAt(0.35, QColor(228, 228, 234, 235))
    chrome.setColorAt(0.72, QColor(168, 168, 179, 225))
    chrome.setColorAt(1.0, QColor(116, 116, 130, 235))
    painter.fillPath(outer, QBrush(chrome))

    # 2. 색면 — 아래가 진하고 위가 밝은 그라데이션 + 위쪽 라디얼 하이라이트
    body_rect = rect.adjusted(rim, rim, -rim, -rim)
    body_radius = max(1.0, radius - rim)
    body = QPainterPath()
    body.addRoundedRect(body_rect, body_radius, body_radius)

    lift = 112 if hovered else 100
    fill = QLinearGradient(body_rect.topLeft(), body_rect.bottomLeft())
    fill.setColorAt(0.0, _tone(base, 150 + (lift - 100)))
    fill.setColorAt(0.42, _tone(base, 108 + (lift - 100)))
    fill.setColorAt(0.58, base if lift == 100 else base.lighter(lift))
    fill.setColorAt(1.0, _tone(base, 62))
    painter.fillPath(body, QBrush(fill))

    warm = QRadialGradient(
        QPointF(body_rect.center().x(), body_rect.top() + body_rect.height() * 0.24),
        max(body_rect.width(), body_rect.height()) * 0.72)
    warm.setColorAt(0.0, QColor(255, 255, 255, 74))
    warm.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(body, QBrush(warm))

    painter.save()
    painter.setClipPath(body)

    # 3. 안쪽 그림자 — 아래쪽을 눌러 오목하게
    depth = QLinearGradient(body_rect.topLeft(), body_rect.bottomLeft())
    depth.setColorAt(0.0, QColor(0, 0, 0, 0))
    depth.setColorAt(0.58, QColor(0, 0, 0, 0))
    depth.setColorAt(1.0, QColor(0, 0, 0, 96 if pressed else 62))
    painter.fillRect(body_rect, QBrush(depth))
    if pressed:   # 눌리면 위쪽에도 그늘이 진다
        top_dark = QLinearGradient(body_rect.topLeft(), body_rect.bottomLeft())
        top_dark.setColorAt(0.0, QColor(0, 0, 0, 78))
        top_dark.setColorAt(0.30, QColor(0, 0, 0, 0))
        painter.fillRect(body_rect, QBrush(top_dark))

    # 4. 유광 반사 — 윗면을 덮는 넓고 부드러운 흰 타원
    if not pressed:
        # 반사는 '윗면에 걸린 빛'이라 면이 커져도 같이 커지면 안 된다.
        # 비율로만 잡으면 큰 패널이 통째로 하얘져 글자가 묻힌다. 상한을 둔다.
        above = min(body_rect.height() * 0.52, 150.0)
        visible = min(body_rect.height() * gloss, 92.0)
        shine_rect = QRectF(body_rect.x() - body_rect.width() * 0.16,
                            body_rect.y() - above,
                            body_rect.width() * 1.32,
                            above + visible)
        gradient = QLinearGradient(shine_rect.topLeft(), shine_rect.bottomLeft())
        gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
        peak = min(255, shine + 26) if hovered else shine
        gradient.setColorAt(0.55, QColor(255, 255, 255, peak))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(shine_rect)

    painter.restore()

    # 5. 림 바로 안쪽 흰 선 — 아크릴 모서리에 빛이 걸린 느낌
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 96), 1.0))
    inner_line = body_rect.adjusted(0.5, 0.5, -0.5, -0.5)
    painter.drawRoundedRect(inner_line, body_radius, body_radius)
    painter.restore()

    return body_rect.adjusted(rim, rim, -rim, -rim)


def paint_pearl_panel(painter: QPainter, rect: QRectF, radius: float,
                      cream: QColor) -> QRectF:
    """반투명 아크릴 패널. 컨트롤을 담는 판이라 반사를 약하게 둔다."""
    return paint_glossy(painter, rect, radius, cream, gloss=0.30, rim=2.0)


# ── 컨트롤 ────────────────────────────────────────────────────────────────

class GlossyButton(QPushButton):
    """유광 플라스틱 버튼. 크롬 림·색면·반사·안쪽 그림자를 직접 그린다."""

    def __init__(self, text: str = "", parent: QWidget | None = None,
                 accent: str | None = None):
        super().__init__(text, parent)
        self._accent = accent
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)

    def set_accent(self, name: str | None) -> None:
        self._accent = name
        self.update()

    def _base_color(self) -> QColor:
        if self._accent:
            return QColor(COLORS.get(self._accent, self._accent))
        role = self.objectName()
        if role == "primary":
            return QColor(COLORS["indigo"])
        if self.isChecked():
            return QColor(COLORS["blue"])
        return QColor(COLORS.get("pearl", COLORS["surface"]))

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -2)
        radius = rect.height() / 2 if self._pill() else 13.0
        base = self._base_color()
        if not self.isEnabled():
            base = QColor(206, 204, 214)

        pressed = self.isDown()
        paint_glossy(painter, rect, radius, base,
                     pressed=pressed, hovered=self._hovered and self.isEnabled())

        # 글자 — 밝은 면 위에서는 진한 남색, 진한 면 위에서는 하양
        painter.setPen(_readable_ink(base))
        painter.setFont(self.font())
        text_rect = rect if not pressed else rect.adjusted(0, PRESS_DROP, 0, PRESS_DROP)
        painter.drawText(text_rect, Qt.AlignCenter, self.text())

    def _pill(self) -> bool:
        return self.height() <= 46


class GlossyCircleButton(GlossyButton):
    """원형 버튼. 아이콘 하나만 담는다."""

    def __init__(self, glyph: str = "", diameter: int = 56,
                 parent: QWidget | None = None, accent: str | None = None):
        super().__init__(glyph, parent, accent)
        self.setFixedSize(diameter, diameter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -2)
        side = min(rect.width(), rect.height())
        square = QRectF(rect.center().x() - side / 2, rect.top(), side, side)
        base = self._base_color()
        pressed = self.isDown()
        paint_glossy(painter, square, side / 2, base,
                     pressed=pressed, hovered=self._hovered, gloss=0.40)
        painter.setPen(_readable_ink(base))
        painter.setFont(self.font())
        painter.drawText(square if not pressed else square.adjusted(0, PRESS_DROP, 0, PRESS_DROP),
                         Qt.AlignCenter, self.text())


class GlossyPanel(QFrame):
    """컨트롤을 담는 아크릴 판. 카드 자리에 쓴다."""

    def __init__(self, parent: QWidget | None = None, radius: int = 22):
        super().__init__(parent)
        self._radius = radius
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        card_shadow(self)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 16, 18, 16)
        self._layout.setSpacing(12)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_glossy(painter, QRectF(self.rect()).adjusted(1, 1, -1, -2),
                     self._radius, QColor(COLORS["pearl"]), gloss=0.30, rim=2.0)


def _readable_ink(base: QColor) -> QColor:
    """면 색에 맞춰 글자색을 고른다. 밝으면 남색 먹, 어두우면 하양."""
    luminance = 0.299 * base.red() + 0.587 * base.green() + 0.114 * base.blue()
    return QColor("#141B34") if luminance > 150 else QColor("#FFFFFF")
