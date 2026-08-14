"""창 배경 드로잉 — 별하늘(갤럭시)과 깅엄 체크(포근한 체크).

모두 QPainter 로 그린다. 이미지 파일을 두지 않으니 배포·해상도 걱정이 없고,
테마 색이 바뀌면 그대로 따라간다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient


# ── 별하늘 배경 (갤럭시 테마) ─────────────────────────────────────────────

def _star_field(width: float, height: float) -> list[tuple[float, float, float, int]]:
    """(x, y, 반지름, 알파) 목록. 해시 기반이라 창 크기가 같으면 늘 같은 배치다.

    난수를 쓰면 창을 다시 그릴 때마다 별이 자리를 옮겨 배경이 '지글거린다'.
    """
    stars = []
    cell = 72.0
    cols = int(width / cell) + 2
    rows = int(height / cell) + 2
    for gy in range(rows):
        for gx in range(cols):
            seed = (gx * 73856093) ^ (gy * 19349663)
            # 한 칸에 별 0~2개
            for k in range(seed % 3):
                s2 = (seed >> (k * 5)) ^ (k * 83492791)
                x = gx * cell + (s2 % 997) / 997 * cell
                y = gy * cell + ((s2 // 7) % 991) / 991 * cell
                radius = 0.6 + ((s2 // 11) % 17) / 17 * 1.3
                alpha = 60 + ((s2 // 13) % 19) / 19 * 150
                stars.append((x, y, radius, int(alpha)))
    return stars


def paint_starfield(painter: QPainter, rect: QRectF, base: QColor,
                    nebula: QColor, accent: QColor | None = None) -> None:
    """딥 퍼플 배경에 뿌연 보랏빛 번짐과 별을 얹는다.

    유리판(카드)이 얹힐 바탕이라, 배경 자체가 균일하면 유리가 유리로 보이지
    않는다. 큰 라디얼 그라데이션 몇 덩이로 밝기에 흐름을 만들고, 가장자리는
    어둡게 눌러 가운데가 떠 보이게 한다.
    """
    painter.save()
    painter.fillRect(rect, base)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)

    width, height = rect.width(), rect.height()
    span = max(width, height)
    accent = accent or nebula

    # 번짐 — 넓고 옅게. 좁고 진하면 '얼룩'으로 보인다.
    blooms = (
        (0.80, 0.06, 0.72, 74, nebula),
        (0.12, 0.92, 0.66, 60, accent),
        (0.42, 0.34, 0.90, 30, nebula),
    )
    for fx, fy, fr, alpha, color in blooms:
        center = QPointF(rect.left() + width * fx, rect.top() + height * fy)
        radius = span * fr
        glow = QRadialGradient(center, radius)
        tint = QColor(color)
        tint.setAlpha(alpha)
        mid = QColor(color)
        mid.setAlpha(alpha // 3)
        glow.setColorAt(0.0, tint)
        glow.setColorAt(0.45, mid)
        glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(center, radius, radius)

    # 가장자리를 눌러 주는 비네트
    vignette = QRadialGradient(rect.center(), span * 0.78)
    vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
    vignette.setColorAt(0.62, QColor(0, 0, 0, 0))
    vignette.setColorAt(1.0, QColor(0, 0, 0, 92))
    painter.setBrush(QBrush(vignette))
    painter.drawRect(rect)

    # 별
    for x, y, radius, alpha in _star_field(width, height):
        if x > width or y > height:
            continue
        star = QColor(255, 255, 255, alpha)
        painter.setBrush(star)
        painter.drawEllipse(QPointF(rect.left() + x, rect.top() + y), radius, radius)
        # 큰 별에만 십자 빛
        if radius > 1.6:
            pen = QPen(QColor(255, 255, 255, alpha // 2), 0.8)
            painter.setPen(pen)
            painter.drawLine(QPointF(rect.left() + x - radius * 2.6, rect.top() + y),
                             QPointF(rect.left() + x + radius * 2.6, rect.top() + y))
            painter.drawLine(QPointF(rect.left() + x, rect.top() + y - radius * 2.6),
                             QPointF(rect.left() + x, rect.top() + y + radius * 2.6))
            painter.setPen(Qt.NoPen)

    painter.restore()


# ── 깅엄 체크 배경 ────────────────────────────────────────────────────────

def paint_gingham(painter: QPainter, rect: QRectF, base: QColor,
                  stripe: QColor, cell: float = 26.0) -> None:
    """깅엄(잔체크) 무늬. 가로·세로 반투명 띠를 겹쳐 만든다."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.fillRect(rect, base)
    painter.setPen(Qt.NoPen)

    soft = QColor(stripe)
    soft.setAlpha(58)
    x = rect.left()
    while x < rect.right():
        painter.fillRect(QRectF(x, rect.top(), cell, rect.height()), soft)
        x += cell * 2
    y = rect.top()
    while y < rect.bottom():
        painter.fillRect(QRectF(rect.left(), y, rect.width(), cell), soft)
        y += cell * 2
    painter.restore()
