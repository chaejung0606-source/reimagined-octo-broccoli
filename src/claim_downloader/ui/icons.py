"""라인 아이콘.

한 벌로 통일하려고 직접 그린다. 굵기·모서리 처리·격자 크기를 한 함수에서
정하므로 화면마다 다른 모양이 섞이지 않는다. 이모지는 쓰지 않는다.

모든 아이콘은 24×24 격자에 그린 뒤 요청한 크기로 옮긴다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

GRID = 24.0
STROKE = 1.8


def _pen(color: QColor, scale: float) -> QPen:
    pen = QPen(color, STROKE * scale)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def paint_icon(painter: QPainter, rect: QRectF, name: str, color: QColor) -> None:
    """rect 안에 아이콘 하나를 그린다."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    side = min(rect.width(), rect.height())
    scale = side / GRID
    painter.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
    painter.scale(scale, scale)
    painter.setPen(_pen(color, 1.0))
    painter.setBrush(Qt.NoBrush)

    drawer = _ICONS.get(name)
    if drawer is not None:
        drawer(painter)
    painter.restore()


# ── 낱개 ──────────────────────────────────────────────────────────────────

def _document_check(painter: QPainter) -> None:
    """검토 — 서류에 체크."""
    path = QPainterPath()
    path.moveTo(14, 3)
    path.lineTo(6, 3)
    path.quadTo(4.5, 3, 4.5, 4.5)
    path.lineTo(4.5, 19.5)
    path.quadTo(4.5, 21, 6, 21)
    path.lineTo(18, 21)
    path.quadTo(19.5, 21, 19.5, 19.5)
    path.lineTo(19.5, 8.5)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(QPointF(14, 3), QPointF(14, 8.5))
    painter.drawLine(QPointF(14, 8.5), QPointF(19.5, 8.5))
    check = QPainterPath()
    check.moveTo(8, 14.4)
    check.lineTo(10.7, 17)
    check.lineTo(16, 11.6)
    painter.drawPath(check)


def _folder(painter: QPainter) -> None:
    """파일별 보완사항 — 폴더."""
    path = QPainterPath()
    path.moveTo(3.5, 7)
    path.quadTo(3.5, 5.5, 5, 5.5)
    path.lineTo(9.4, 5.5)
    path.lineTo(11.4, 8)
    path.lineTo(19, 8)
    path.quadTo(20.5, 8, 20.5, 9.5)
    path.lineTo(20.5, 18)
    path.quadTo(20.5, 19.5, 19, 19.5)
    path.lineTo(5, 19.5)
    path.quadTo(3.5, 19.5, 3.5, 18)
    path.closeSubpath()
    painter.drawPath(path)


def _sliders(painter: QPainter) -> None:
    """검토 기준 — 조절 손잡이."""
    for y in (7.0, 12.0, 17.0):
        painter.drawLine(QPointF(4, y), QPointF(20, y))
    painter.setBrush(painter.pen().color())
    for x, y in ((9.0, 7.0), (15.0, 12.0), (7.5, 17.0)):
        painter.drawEllipse(QPointF(x, y), 2.1, 2.1)
    painter.setBrush(Qt.NoBrush)


def _gear(painter: QPainter) -> None:
    """설정 — 톱니."""
    painter.drawEllipse(QPointF(12, 12), 3.1, 3.1)
    ring = QPainterPath()
    ring.addEllipse(QPointF(12, 12), 7.4, 7.4)
    painter.drawPath(ring)
    import math
    for index in range(8):
        angle = index * math.pi / 4
        inner = QPointF(12 + 7.4 * math.cos(angle), 12 + 7.4 * math.sin(angle))
        outer = QPointF(12 + 9.4 * math.cos(angle), 12 + 9.4 * math.sin(angle))
        painter.drawLine(inner, outer)


def _search(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(10.6, 10.6), 6.1, 6.1)
    painter.drawLine(QPointF(15.2, 15.2), QPointF(20, 20))


def _download(painter: QPainter) -> None:
    painter.drawLine(QPointF(12, 4), QPointF(12, 15))
    arrow = QPainterPath()
    arrow.moveTo(7.4, 10.6)
    arrow.lineTo(12, 15.2)
    arrow.lineTo(16.6, 10.6)
    painter.drawPath(arrow)
    painter.drawLine(QPointF(4.5, 19.5), QPointF(19.5, 19.5))


_ICONS = {
    "document-check": _document_check,
    "folder": _folder,
    "sliders": _sliders,
    "gear": _gear,
    "search": _search,
    "download": _download,
}
