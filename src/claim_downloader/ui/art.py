"""입체 그림 — 업무 의미 이름 → 에셋 파일.

화면 코드는 파일 이름이 아니라 업무 의미(`"receive"`, `"archive"` …)로 그림을 부른다.
더 좋은 원본을 받으면 assets/art/ 의 파일만 바꾸면 된다.

에셋은 흰 바탕에 맞춰 만들었다(tools/make_art.py). 그래서 언제나 흰 카드나
흰 판 위에 놓는다. 그림 안에 이미 그림자가 있으므로 그림자 효과를 더 씌우지 않는다.

크기 기준: 바로가기 48~72 · 요약 카드 40~56 · 빈 상태 96~144.
원본이 한 변 약 200px 이므로 그보다 크게 쓰지 않는다.

그릴 때 원본 둘레의 빈 여백을 잘라 낸다(CROP). make_art.py 가 오브젝트를 캔버스의 1/1.3(약 77%)로 앉혀서, 그대로 그리면
상자의 4분의 1 이 흰 여백이라 그림이 작아 보였다(담당자 요청 2026-10-14 '아이콘을 키워서 잘 보이게'). 잘라 낸 뒤에는
가장자리를 다시 투명하게 풀어(FEATHER) 흰 면이 아닌 곳에서도 사각 경계가 날카롭게 보이지 않게 한다. 에셋 파일은 그대로다.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

ART_DIR = Path(__file__).parent / "assets" / "art"

# 업무 의미 → 참고 이미지 속 오브젝트. 이 앱에 해당 기능이 있는 것만 쓴다.
ART = {
    "receive":   "envelope",        # 봉투 — 받을 청구서(수신)
    "approved":  "signed-doc",      # 서명 문서 — 승인된 청구서를 받아 둠
    "archive":   "folder-papers",   # 종이가 겹친 폴더 — 보관 폴더 · 저장 폴더
    "upload":    "send-tray",       # 종이비행기와 트레이 — 플랫폼 업로드 대기(발송)
    "login":     "monitor-lock",    # 모니터와 자물쇠 — ERP 접속 · 로그인은 사람이 직접
    "overview":  "panels",          # 칸 나뉜 패널 — 결의서 목록(업무 현황)
    "register":  "tray-pen",        # 트레이와 펜 — 받아서 폴더에 등록
    "journal":   "book-pen",        # 책과 펜 — 진행 기록
    "settings":  "dial",            # 원형 다이얼 — 설정
    # 업무 데스크
    "meeting":   "book-pen",        # 펼쳐진 책과 펜 — 회의록 생성
    "claim":     "signed-doc",      # 서명 문서 — 일반청구(결재)
    "scholarship": "doc-users",     # 사람이 그려진 서류 — 장학금 청구(학생 명단)
    "travel":    "send-tray",       # 종이비행기 — 출장비 청구(준비 중)
    "parking":   "monitor-lock",    # 모니터와 자물쇠 — 주차등록 사이트에 로그인해 등록(차 그림이 없어 웹 로그인 그림)
    "card":      "card-receipt",    # 카드와 영수증 — 카드 청구(일반청구 화면의 종류) (tools/make_card_art.py 로 새로 그림)
    "recent":    "folder-papers",   # 종이 겹친 폴더 — 최근 작업
    "done":      "send-tray",       # 종이비행기와 트레이 — 완료 안내
}
# 에셋은 있으나 이 앱에 맞는 기능이 없어 쓰지 않는 것:
# doc-users · keyboard-mouse · chat-bubbles · chat-mention · folder-heart

MAX_SOURCE = 200
# 둘레에서 잘라 낼 몫. 오브젝트(그림자 포함)는 원본 가장자리에서 10.5% 이상 안쪽에 있다(15개 모두 실측) — 9% 면 그림자도 다치지 않는다.
CROP = 0.09
# 잘라 낸 뒤 투명하게 풀어 줄 가장자리 몫 (make_art.py 4번과 같은 이유)
FEATHER = 0.05


class Art(QWidget):
    """입체 그림 한 장. 장식이므로 화면 읽기 프로그램이 읽지 않게 한다."""

    def __init__(self, meaning: str, size: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = min(size, MAX_SOURCE)
        self.setFixedSize(QSize(self._size, self._size))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAccessibleName("")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._source = QPixmap()
        self._scaled: tuple[float, QPixmap] | None = None
        self.set_meaning(meaning)

    def set_size(self, size: int) -> None:
        size = min(size, MAX_SOURCE)
        if size != self._size:
            self._size = size
            self.setFixedSize(QSize(size, size))
            self._scaled = None
            self.update()

    def set_meaning(self, meaning: str) -> None:
        path = ART_DIR / f"{ART.get(meaning, meaning)}.png"
        self._source = QPixmap(str(path)) if path.exists() else QPixmap()
        self._scaled = None
        self.update()

    def _pixmap_for(self, ratio: float) -> QPixmap:
        """그릴 때마다 줄이면 계단이 진다. 화면 배율에 맞춰 한 번 곱게 줄여 둔다 — 여백을 잘라 내고 가장자리를 풀어서."""
        if self._scaled is None or self._scaled[0] != ratio:
            side = round(self._size * ratio)
            w, h = self._source.width(), self._source.height()
            mx, my = round(w * CROP), round(h * CROP)
            cropped = self._source.copy(mx, my, w - 2 * mx, h - 2 * my)
            pix = cropped.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pix = QPixmap.fromImage(_feather(pix.toImage(), max(1, round(side * FEATHER))))
            pix.setDevicePixelRatio(ratio)
            self._scaled = (ratio, pix)
        return self._scaled[1]

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._source.isNull():
            return
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap_for(self.devicePixelRatioF()))


def _feather(image: QImage, band: int) -> QImage:
    """네 가장자리 band 픽셀을 바깥으로 갈수록 투명하게. 모서리는 두 번 곱해져 더 옅어진다(둥근 느낌)."""
    image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    w, h = image.width(), image.height()
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    clear, solid = QColor(0, 0, 0, 0), QColor(0, 0, 0, 255)
    for x0, y0, x1, y1, rect in (
            (0, 0, band, 0, QRectF(0, 0, band, h)),                 # 왼쪽
            (w, 0, w - band, 0, QRectF(w - band, 0, band, h)),      # 오른쪽
            (0, 0, 0, band, QRectF(0, 0, w, band)),                 # 위
            (0, h, 0, h - band, QRectF(0, h - band, w, band))):     # 아래
        gradient = QLinearGradient(QPointF(x0, y0), QPointF(x1, y1))
        gradient.setColorAt(0.0, clear)
        gradient.setColorAt(1.0, solid)
        painter.fillRect(rect, gradient)
    painter.end()
    return image
