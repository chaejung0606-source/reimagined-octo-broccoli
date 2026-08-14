"""마스코트와 스티커 드로잉.

시안(귀여운 인형 스티커 콜라주)의 분위기를 옮겼다. 캐릭터는 직접 그린
오리지널 봉제인형풍 마스코트다 — 시판 캐릭터를 그대로 쓰지 않는다.

모두 QPainter 로 그린다. 이미지 파일을 두지 않으니 배포·해상도 걱정이 없고,
테마 색이 바뀌면 그대로 따라간다.
"""
from __future__ import annotations

import math

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from .. import config
from .theme import COLORS

# ── 사용자 이미지 ─────────────────────────────────────────────────────────
# ~/.expense-review/mascot/ 에 happy.png / worried.png / sleepy.png (또는
# mascot.png 하나)를 넣으면 기본 그림 대신 그 이미지를 쓴다. 배경이 투명한
# PNG(누끼 딴 이미지)를 권한다. 앱은 파일을 그대로 표시만 한다.

IMAGE_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg", ".gif")

_pixmap_cache: dict[tuple[str, float], QPixmap] = {}


def custom_mascot_path(mood: str) -> Path | None:
    """표정별 이미지 → 기본(happy) → 공용(mascot) 순으로 찾는다."""
    base = config.mascot_dir()
    for name in (mood, "happy", "mascot"):
        for suffix in IMAGE_SUFFIXES:
            path = base / f"{name}{suffix}"
            if path.exists():
                return path
    return None


def load_user_image(path: Path) -> QPixmap | None:
    """mtime 을 캐시 키에 넣어, 파일을 바꿔치기하면 자동으로 다시 읽는다."""
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return None
    pixmap = _pixmap_cache.get(key)
    if pixmap is None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        if len(_pixmap_cache) > 32:
            _pixmap_cache.clear()
        _pixmap_cache[key] = pixmap
    return pixmap


def sticker_images() -> list[Path]:
    return sorted(
        path for path in config.stickers_dir().iterdir()
        if path.suffix.lower() in IMAGE_SUFFIXES
    )


def _draw_fitted(painter: QPainter, pixmap: QPixmap, rect: QRectF) -> None:
    """비율을 지키며 rect 안에 맞춰 그린다."""
    scaled = pixmap.scaled(int(rect.width()), int(rect.height()),
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
    x = rect.x() + (rect.width() - scaled.width()) / 2
    y = rect.y() + (rect.height() - scaled.height()) / 2
    painter.drawPixmap(int(x), int(y), scaled)


# ── 마스코트 ──────────────────────────────────────────────────────────────

def paint_mascot(painter: QPainter, rect: QRectF, mood: str = "happy") -> None:
    """동그란 얼굴의 봉제인형 마스코트.

    mood: 'happy'(기본) | 'worried'(지적이 많을 때) | 'sleepy'(대기 중)
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    size = min(rect.width(), rect.height())
    cx = rect.center().x()
    cy = rect.center().y()

    fur = QColor(COLORS["fur"])
    fur_dark = QColor(COLORS["fur_dark"])
    face = QColor(COLORS["face"])
    ink = QColor(COLORS["ink"])

    painter.setPen(Qt.NoPen)

    # 몸통 — 머리 아래로 살짝만 보이게. 인형은 머리가 커야 귀엽다.
    body = QRectF(cx - size * 0.23, cy + size * 0.16, size * 0.46, size * 0.40)
    painter.setBrush(fur)
    painter.drawRoundedRect(body, size * 0.18, size * 0.18)

    # 팔 — 몸통보다 진한 색으로 두어 실루엣이 붙어 보이지 않게 한다
    for direction in (-1, 1):
        arm = QRectF(cx + direction * size * 0.30 - size * 0.085,
                     cy + size * 0.22, size * 0.17, size * 0.24)
        painter.setBrush(fur_dark)
        painter.drawRoundedRect(arm, size * 0.085, size * 0.085)

    # 발
    for direction in (-1, 1):
        foot = QRectF(cx + direction * size * 0.12 - size * 0.085,
                      cy + size * 0.46, size * 0.17, size * 0.12)
        painter.setBrush(fur_dark)
        painter.drawRoundedRect(foot, size * 0.06, size * 0.06)

    # 귀
    for direction in (-1, 1):
        ear = QRectF(cx + direction * size * 0.35 - size * 0.095,
                     cy - size * 0.15, size * 0.19, size * 0.19)
        painter.setBrush(fur)
        painter.drawEllipse(ear)
        painter.setBrush(face)
        painter.drawEllipse(ear.adjusted(size * 0.055, size * 0.055,
                                         -size * 0.055, -size * 0.055))

    # 머리
    head = QRectF(cx - size * 0.35, cy - size * 0.40, size * 0.70, size * 0.66)
    painter.setBrush(fur)
    painter.drawEllipse(head)

    # 정수리 털 한 가닥
    painter.setBrush(fur_dark)
    painter.drawEllipse(QRectF(cx - size * 0.05, cy - size * 0.46,
                               size * 0.10, size * 0.11))

    # 얼굴(밝은 면)
    face_rect = QRectF(cx - size * 0.25, cy - size * 0.24, size * 0.50, size * 0.46)
    painter.setBrush(face)
    painter.drawEllipse(face_rect)

    # 눈
    eye_y = cy - size * 0.06
    for direction in (-1, 1):
        eye = QRectF(cx + direction * size * 0.11 - size * 0.052,
                     eye_y - size * 0.062, size * 0.104, size * 0.124)
        painter.setBrush(ink)
        if mood == "sleepy":
            pen = QPen(ink, max(1.5, size * 0.022), Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(eye, 0, 180 * 16)
            painter.setPen(Qt.NoPen)
            continue
        painter.drawEllipse(eye)
        # 하이라이트 — 이게 있어야 인형 눈처럼 보인다
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(eye.x() + eye.width() * 0.52,
                                   eye.y() + eye.height() * 0.16,
                                   eye.width() * 0.34, eye.height() * 0.30))

    # 볼
    painter.setBrush(QColor(COLORS["blush"]))
    for direction in (-1, 1):
        painter.drawEllipse(QRectF(cx + direction * size * 0.19 - size * 0.045,
                                   cy + size * 0.045, size * 0.09, size * 0.062))

    # 코
    painter.setBrush(QColor(COLORS["nose"]))
    painter.drawEllipse(QRectF(cx - size * 0.035, cy + size * 0.035,
                               size * 0.07, size * 0.055))

    # 입
    pen = QPen(ink, max(1.4, size * 0.018), Qt.SolidLine, Qt.RoundCap)
    painter.setPen(pen)
    mouth = QRectF(cx - size * 0.06, cy + size * 0.075, size * 0.12, size * 0.075)
    if mood == "worried":
        painter.drawArc(mouth, 30 * 16, 120 * 16)
    else:
        painter.drawArc(mouth, 200 * 16, 140 * 16)
    painter.setPen(Qt.NoPen)

    # 머리 리본
    _paint_bow(painter, QPointF(cx + size * 0.23, cy - size * 0.35), size * 0.21,
               QColor(COLORS["accent"]))

    painter.restore()


def _paint_bow(painter: QPainter, center: QPointF, size: float, color: QColor) -> None:
    """리본. 사이드바처럼 작게 그릴 때 '점 세 개'로 보이지 않도록 고리를 겹친다."""
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)

    # 고리를 삼각형에 가깝게 눕혀 두면 작은 크기에서도 리본으로 읽힌다.
    for direction in (-1, 1):
        loop = QPainterPath()
        loop.moveTo(center)
        loop.cubicTo(center.x() + direction * size * 0.95, center.y() - size * 0.62,
                     center.x() + direction * size * 0.95, center.y() + size * 0.62,
                     center.x(), center.y())
        painter.drawPath(loop)

    painter.setBrush(color.darker(115))
    painter.drawEllipse(center, size * 0.20, size * 0.20)
    painter.restore()


class MascotWidget(QWidget):
    """마스코트 하나를 그리는 위젯. 상태에 따라 표정이 바뀐다.

    갤럭시 테마 분위기에 맞춰 위아래로 아주 천천히 떠다닌다. 진폭 3px,
    한 주기 6초 — 눈에 거슬리지 않을 만큼만. 창에서 사라지면 타이머를 멈춘다.
    """

    FLOAT_AMPLITUDE = 3.0
    FLOAT_PERIOD_MS = 6000

    def __init__(self, size: int = 96, parent: QWidget | None = None):
        super().__init__(parent)
        # 떠오를 여유 공간을 위아래로 조금 남긴다.
        self.setFixedSize(size, size + int(self.FLOAT_AMPLITUDE * 2))
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._mood = "happy"
        self._phase = 0.0
        self._float_timer = QTimer(self)
        self._float_timer.setInterval(80)
        self._float_timer.timeout.connect(self._advance_float)

    def set_mood(self, mood: str) -> None:
        if mood != self._mood:
            self._mood = mood
            self.update()

    def _advance_float(self) -> None:
        self._phase += 2 * math.pi * self._float_timer.interval() / self.FLOAT_PERIOD_MS
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._float_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._float_timer.stop()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        offset = math.sin(self._phase) * self.FLOAT_AMPLITUDE
        area = QRectF(0, self.FLOAT_AMPLITUDE + offset,
                      self.width(), self.height() - self.FLOAT_AMPLITUDE * 2)
        path = custom_mascot_path(self._mood)
        if path is not None and (pixmap := load_user_image(path)) is not None:
            _draw_fitted(painter, pixmap, area)
            return
        paint_mascot(painter, area, self._mood)


# ── 스티커 ────────────────────────────────────────────────────────────────

STICKER_KINDS = ("star", "heart", "cherry", "flower", "ribbon", "cloud")


def paint_sticker(painter: QPainter, rect: QRectF, kind: str, color: QColor) -> None:
    """스티커 한 장. 흰 테두리를 둘러 '오려 붙인' 느낌을 낸다."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    path = _sticker_path(kind, rect)
    painter.setPen(QPen(QColor(255, 255, 255, 235), max(2.0, rect.width() * 0.09),
                        Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPath(path)
    painter.restore()


def _sticker_path(kind: str, rect: QRectF) -> QPainterPath:
    path = QPainterPath()
    cx, cy = rect.center().x(), rect.center().y()
    radius = min(rect.width(), rect.height()) / 2

    if kind == "star":
        for index in range(10):
            angle = math.pi / 2 + index * math.pi / 5
            length = radius if index % 2 == 0 else radius * 0.46
            point = QPointF(cx + length * math.cos(angle), cy - length * math.sin(angle))
            path.moveTo(point) if index == 0 else path.lineTo(point)
        path.closeSubpath()

    elif kind == "heart":
        path.moveTo(cx, cy + radius * 0.85)
        path.cubicTo(cx - radius * 1.5, cy - radius * 0.15,
                     cx - radius * 0.45, cy - radius * 1.15, cx, cy - radius * 0.32)
        path.cubicTo(cx + radius * 0.45, cy - radius * 1.15,
                     cx + radius * 1.5, cy - radius * 0.15, cx, cy + radius * 0.85)

    elif kind == "cherry":
        path.addEllipse(QRectF(cx - radius, cy + radius * 0.02, radius * 0.92, radius * 0.92))
        path.addEllipse(QRectF(cx + radius * 0.06, cy + radius * 0.10, radius * 0.88, radius * 0.88))
        # 꼭지 — 없으면 그냥 동그라미 두 개로 보인다
        stem = QPainterPath()
        stem.moveTo(cx - radius * 0.55, cy + radius * 0.12)
        stem.quadTo(cx, cy - radius * 1.05, cx + radius * 0.52, cy + radius * 0.18)
        stroke = QPainterPathStroker()
        stroke.setWidth(radius * 0.22)
        stroke.setCapStyle(Qt.RoundCap)
        path.addPath(stroke.createStroke(stem))

    elif kind == "flower":
        for index in range(5):
            angle = math.pi / 2 + index * 2 * math.pi / 5
            px = cx + radius * 0.52 * math.cos(angle)
            py = cy - radius * 0.52 * math.sin(angle)
            path.addEllipse(QPointF(px, py), radius * 0.48, radius * 0.48)

    elif kind == "ribbon":
        path.addEllipse(QRectF(cx - radius, cy - radius * 0.55, radius * 0.95, radius * 1.1))
        path.addEllipse(QRectF(cx + radius * 0.05, cy - radius * 0.55, radius * 0.95, radius * 1.1))
        path.addEllipse(QPointF(cx, cy), radius * 0.26, radius * 0.26)

    else:  # cloud
        path.addEllipse(QRectF(cx - radius, cy - radius * 0.2, radius * 0.9, radius * 0.9))
        path.addEllipse(QRectF(cx - radius * 0.45, cy - radius * 0.72, radius * 1.1, radius * 1.1))
        path.addEllipse(QRectF(cx + radius * 0.12, cy - radius * 0.24, radius * 0.88, radius * 0.88))

    return path


class StickerStrip(QWidget):
    """스티커를 한 줄로 흩뿌린 장식 띠. 카드 사이 여백을 채운다."""

    def __init__(self, kinds: tuple[str, ...] = STICKER_KINDS,
                 height: int = 30, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._kinds = kinds

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        count = len(self._kinds)
        if count == 0 or self.width() <= 0:
            return
        step = self.width() / count
        side = min(self.height() * 0.82, step * 0.6)

        images = sticker_images()
        palette = [COLORS["accent"], COLORS["mint"], COLORS["butter"],
                   COLORS["berry"], COLORS["sky"], COLORS["blush"]]
        for index, kind in enumerate(self._kinds):
            # 살짝 위아래로 어긋나게 둬야 '붙인 스티커'처럼 보인다
            offset = (self.height() - side) / 2 + (3 if index % 2 else -3)
            rect = QRectF(step * index + (step - side) / 2, offset, side, side)
            if images:
                pixmap = load_user_image(images[index % len(images)])
                if pixmap is not None:
                    _draw_fitted(painter, pixmap, rect)
                    continue
            paint_sticker(painter, rect, kind, QColor(palette[index % len(palette)]))


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
                    nebula: QColor) -> None:
    """딥 퍼플 배경에 성운 몇 덩이와 별을 얹는다."""
    painter.save()
    painter.fillRect(rect, base)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)

    width, height = rect.width(), rect.height()

    # 성운 — 반투명 라디얼 그라데이션 몇 덩이로 배경 명도에 흐름을 만든다
    for fx, fy, fr, alpha in ((0.82, 0.10, 0.55, 46), (0.16, 0.85, 0.50, 38),
                              (0.45, 0.40, 0.65, 22)):
        center = QPointF(rect.left() + width * fx, rect.top() + height * fy)
        glow = QRadialGradient(center, max(width, height) * fr)
        tint = QColor(nebula)
        tint.setAlpha(alpha)
        glow.setColorAt(0.0, tint)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(center, max(width, height) * fr, max(width, height) * fr)

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


class GinghamBackground(QWidget):
    """깅엄 무늬 배경판. 페이지 맨 아래에 깔고 위에 카드를 얹는다."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.lower()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_gingham(painter, QRectF(self.rect()),
                      QColor(COLORS["bg"]), QColor(COLORS["gingham"]))
