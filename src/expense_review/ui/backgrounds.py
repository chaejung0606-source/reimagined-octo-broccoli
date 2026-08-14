"""창 배경 드로잉.

아이보리 바탕에 가운데가 밝은 빛을 깐다. QPainter 로 그리므로 이미지 파일이
없고, 창을 키워도 깨지지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QRadialGradient


def paint_ivory(painter: QPainter, rect: QRectF, base: QColor,
                center_light: QColor) -> None:
    """따뜻한 아이보리 바탕. 가운데를 살짝 밝혀 빛이 떨어지는 자리를 만든다.

    균일한 크림색이면 위에 놓인 유광 컨트롤이 '떠 있다'로 읽히지 않는다.
    중앙을 밝히고 네 귀퉁이를 눌러야 물체가 바닥 위에 놓인 것처럼 보인다.
    """
    painter.save()
    painter.fillRect(rect, base)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)

    span = max(rect.width(), rect.height())
    center = QPointF(rect.center().x(), rect.top() + rect.height() * 0.38)

    glow = QRadialGradient(center, span * 0.62)
    glow.setColorAt(0.0, QColor(center_light.red(), center_light.green(),
                                center_light.blue(), 150))
    glow.setColorAt(0.55, QColor(center_light.red(), center_light.green(),
                                 center_light.blue(), 52))
    glow.setColorAt(1.0, QColor(center_light.red(), center_light.green(),
                                center_light.blue(), 0))
    painter.setBrush(QBrush(glow))
    painter.drawRect(rect)

    corner = QRadialGradient(rect.center(), span * 0.72)
    corner.setColorAt(0.0, QColor(0, 0, 0, 0))
    corner.setColorAt(0.66, QColor(0, 0, 0, 0))
    corner.setColorAt(1.0, QColor(92, 78, 56, 54))
    painter.setBrush(QBrush(corner))
    painter.drawRect(rect)
    painter.restore()
