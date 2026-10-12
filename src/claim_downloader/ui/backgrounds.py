"""창 배경.

민트에서 하늘색을 지나 연한 남보라로 흐르는 아주 옅은 그라데이션.
QPainter 로 그리므로 이미지 파일이 없고 창을 키워도 깨지지 않는다.

옅게 두는 것이 핵심이다. 배경이 진해지면 그 위의 흰 카드가 '떠 있다'가
아니라 '뚫려 있다'로 보이고, 본문 글자의 대비도 함께 떨어진다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QRadialGradient


def paint_aurora(painter: QPainter, rect: QRectF, mint: QColor, cyan: QColor,
                 blue: QColor) -> None:
    """대각선 그라데이션 + 아주 옅은 빛 두 덩이."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)

    base = QLinearGradient(rect.topLeft(), rect.bottomRight())
    base.setColorAt(0.0, mint)
    base.setColorAt(0.52, cyan)
    base.setColorAt(1.0, blue)
    painter.fillRect(rect, QBrush(base))

    span = max(rect.width(), rect.height())
    for fx, fy, fr, tint, alpha in (
        (0.08, 0.06, 0.55, mint, 120),
        (0.94, 0.88, 0.50, blue, 96),
    ):
        center = QPointF(rect.left() + rect.width() * fx,
                         rect.top() + rect.height() * fy)
        radius = span * fr
        glow = QRadialGradient(center, radius)
        near = QColor(tint)
        near.setAlpha(alpha)
        glow.setColorAt(0.0, near)
        glow.setColorAt(1.0, QColor(tint.red(), tint.green(), tint.blue(), 0))
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(center, radius, radius)

    painter.restore()
