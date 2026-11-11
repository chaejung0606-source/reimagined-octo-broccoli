"""출장증빙 쪽 짜임(model.Page) → A4 PDF. PySide6(QPdfWriter · QPainter · QPdfDocument) — 새 의존성 없이 앱에 있는 것으로 그린다.

모양은 담당자가 만들던 것(2026-10-27 그림): 쪽 둘레 테두리 · 머리 줄(왼쪽 '* … 증빙', 오른쪽 일자 · 금액 칸, 굵게) · 아래에 영수증 그림.
PDF 영수증은 쪽마다 그림으로 바꿔 넣는다. 영수증은 둘레의 빈 여백을 잘라 내고 칸에 꽉 차게 키워 가운데에 둔다
(담당자 2026-10-27 "증빙내용이 잘보이도록 확대 및 여백부분 자르기, 가운데 정렬" — A4 PDF 영수증은 내용이 쪽 위 한 귀퉁이뿐이라 작게 보였다).
QGuiApplication 이 떠 있어야 한다(앱 안에서 부른다).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QImageReader, QPageLayout, QPageSize, QPainter, QPainterPath,
                           QPdfWriter, QPen, QTransform)

from ..ui.tokens import COLORS
from .model import Block, Page, rows_for

DPI = 150
MARGIN = 40          # 쪽 바깥 여백(점)
HEAD_H = 46          # 머리 줄 높이
TITLE_H = 36         # 묶음 머리 줄 높이
CAPTION_H = 30       # 칸 위 일자 글
GAP = 10
PDF_WIDTH = 1400     # PDF 영수증을 그림으로 바꿀 폭(점)
TRIM_SCAN = 600      # 여백을 찾을 때 줄여 볼 크기(긴 변) — 원본을 다 훑으면 느리다
TRIM_INK = 232       # 이보다 어두운(0~255) 점이 내용
TRIM_MIN_DOTS = 2    # 한 줄에 내용 점이 이만큼 있어야 내용 줄 — 먼지 한 점으로 여백을 남기지 않게
TRIM_PAD = 0.015     # 잘라 낸 둘레에 남길 여백(긴 변 비율)

# 색은 앱 디자인 토큰(ui/tokens.py)에서 — 엑셀로 만들던 검은 칸 양식 대신 앱과 같은 맑은 바탕 · 라벤더 강조색(담당자 2026-11-10
# "어플 디자인에서 메인디자인 및 색상을 가져와서 서식을 수정"). 출력해도 읽히게 글자는 진하게, 면은 옅게.
INK = QColor(COLORS["text"])
MUTED = QColor(COLORS["text_muted"])
ACCENT = QColor(COLORS["primary"])            # 머리 띠 아래 선 · 묶음 줄 왼쪽 선
ACCENT_TEXT = QColor(COLORS["primary_hover"])  # 칩 글자(옅은 바탕 위 대비)
BAND = QColor(COLORS["lavender_bg"])          # 머리 띠
BAR_BG = QColor(COLORS["surface_alt"])        # 묶음 줄 · 칸 이름표
CHIP_BG = QColor(COLORS["surface"])
RULE = QColor(COLORS["border"])               # 얇은 선
FRAME = QColor(COLORS["border_strong"])       # 쪽 틀
FRAME_RADIUS = 14
ACCENT_W = 5


def _font(px: int, bold: bool = False) -> QFont:
    font = QFont("Pretendard")
    font.setPixelSize(px)
    font.setBold(bold)
    return font


def _content_span(lines: list[bytes]) -> tuple[int, int] | None:
    table = bytes(1 if b < TRIM_INK else 0 for b in range(256))
    marks = [line.translate(table).count(1) >= TRIM_MIN_DOTS for line in lines]
    if not any(marks):
        return None
    return marks.index(True), len(marks) - 1 - marks[::-1].index(True)


def _rows(image: QImage) -> list[bytes]:
    gray = image.convertToFormat(QImage.Format_Grayscale8)
    data = bytes(gray.constBits())
    stride = gray.bytesPerLine()
    return [data[y * stride: y * stride + gray.width()] for y in range(gray.height())]


def trim(image: QImage) -> QImage:
    """둘레의 흰(옅은) 여백을 잘라 낸다. 내용을 못 찾거나 거의 그대로면 원본."""
    if image.isNull() or image.width() < 8 or image.height() < 8:
        return image
    small = image.scaled(TRIM_SCAN, TRIM_SCAN, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    # 투명한 곳은 흰 바탕으로 본다
    flat = QImage(small.size(), QImage.Format_RGB32)
    flat.fill(QColor("white"))
    painter = QPainter(flat)
    painter.drawImage(0, 0, small)
    painter.end()
    rows = _content_span(_rows(flat))
    cols = _content_span(_rows(flat.transformed(QTransform().rotate(90))))
    if rows is None or cols is None:
        return image
    sx, sy = image.width() / flat.width(), image.height() / flat.height()
    pad = TRIM_PAD * max(image.width(), image.height())
    left = max(0, int(cols[0] * sx - pad))
    top = max(0, int(rows[0] * sy - pad))
    right = min(image.width(), int((cols[1] + 1) * sx + pad))
    bottom = min(image.height(), int((rows[1] + 1) * sy + pad))
    if (right - left) * (bottom - top) > 0.97 * image.width() * image.height():
        return image
    return image.copy(left, top, right - left, bottom - top)


FRAME_SCAN = 500     # 영수증 테두리를 찾을 때 줄여 볼 폭
FRAME_INK = 235      # 테두리 선으로 볼 어두움 — 줄이면 1점 선이 옅은 회색이 되므로 넉넉히
FRAME_MIN_W = 0.12   # 테두리 상자로 볼 최소 크기(쪽 폭 · 높이 비율)
FRAME_MIN_H = 0.08


def frames(image: QImage) -> list[tuple[int, int, int, int]]:
    """쪽 안의 영수증 테두리 상자들(원본 좌표 x, y, w, h) — 위에서 아래, 왼쪽에서 오른쪽 차례.
    하이패스 홈페이지에서 인쇄한 PDF(담당자 2026-10-27 견본 둘)는 테두리 친 영수증 상자가 있고 둘레에 인쇄 날짜 · 주소 · '총 N 건' 글이 있어
    여백 자르기로는 안 줄어든다. 여러 장이면 상자들이 테두리를 나눠 쓰는 격자다 — 그래서 선이 아니라 **선에 갇힌 흰 곳**을 찾는다:
    쪽 가장자리에서 이어지는 흰 곳(바깥)을 지우고 남은 흰 곳 중 큰 것 하나가 상자 하나의 안쪽. 글자 속 구멍은 작아서 빠진다.
    다른 상자 안에 든 상자(영수증 안의 표)는 뺀다."""
    small = image.scaledToWidth(min(FRAME_SCAN, image.width()), Qt.SmoothTransformation)
    flat = QImage(small.size(), QImage.Format_RGB32)
    flat.fill(QColor("white"))
    painter = QPainter(flat)
    painter.drawImage(0, 0, small)
    painter.end()
    w, h = flat.width(), flat.height()
    table = bytes(0 if b < FRAME_INK else 1 for b in range(256))      # 1 = 흰 곳
    open_ = bytearray(b"".join(line.translate(table) for line in _rows(flat)))

    def fill(start: int) -> tuple[int, int, int, int]:
        """start 에서 이어진 흰 곳(상하좌우)을 지우고 그 둘레 상자를 돌려준다."""
        open_[start] = 0
        stack = [start]
        x0 = x1 = start % w
        y0 = y1 = start // w
        while stack:
            i = stack.pop()
            x, y = i % w, i // w
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            for j in (i - w if y else -1, i + w if y < h - 1 else -1, i - 1 if x else -1, i + 1 if x < w - 1 else -1):
                if j >= 0 and open_[j]:
                    open_[j] = 0
                    stack.append(j)
        return x0, y0, x1 - x0 + 1, y1 - y0 + 1

    for i in list(range(w)) + list(range((h - 1) * w, h * w)) + list(range(0, h * w, w)) + list(range(w - 1, h * w, w)):
        if open_[i]:
            fill(i)                                                    # 바깥
    found = []
    for i in range(w * h):
        if open_[i]:
            box = fill(i)
            if box[2] >= FRAME_MIN_W * w and box[3] >= FRAME_MIN_H * h:
                found.append(box)
    found = [f for f in found if not any(o is not f and o[0] <= f[0] and o[1] <= f[1]
                                         and o[0] + o[2] >= f[0] + f[2] and o[1] + o[3] >= f[1] + f[3] for o in found)]
    found.sort(key=lambda f: (round(f[1] / (0.05 * h)), f[0]))
    sx, sy = image.width() / w, image.height() / h
    # 상자 안쪽만 — 테두리까지 넣으면 격자에서 이웃 상자의 선 끄트머리가 귀퉁이에 묻어 나온다(테두리는 _boxed 가 새로 그린다)
    return [(int(x * sx), int(y * sy), int(bw * sx), int(bh * sy)) for x, y, bw, bh in found]


def _boxed(image: QImage) -> QImage:
    """오려 낸 영수증 둘레에 견본처럼 얇은 테두리."""
    out = QImage(image.size(), QImage.Format_RGB32)
    out.fill(QColor("white"))
    painter = QPainter(out)
    painter.drawImage(0, 0, image)
    painter.setPen(QPen(QColor("#555555"), 3))
    painter.drawRect(QRectF(1.5, 1.5, image.width() - 3, image.height() - 3))
    painter.end()
    return out


def load_images(path: Path) -> list[QImage]:
    """그림 파일은 둘레 여백만 잘라 내고, PDF 는 쪽마다 영수증 테두리 상자가 있으면 상자마다 하나씩 오려 낸다(없으면 쪽을 여백만 잘라).
    상자 찾기는 PDF 만 — 휴대폰 캡처의 카드 모양 칸을 영수증으로 잘못 오리지 않게."""
    out = []
    for image in _load(path):
        boxes = frames(image) if path.suffix.lower() == ".pdf" else []
        out += [_boxed(image.copy(*box)) for box in boxes] if boxes else [trim(image)]
    return out


def _load(path: Path) -> list[QImage]:
    if path.suffix.lower() == ".pdf":
        from PySide6.QtPdf import QPdfDocument
        doc = QPdfDocument()
        doc.load(str(path))
        out = []
        for i in range(doc.pageCount()):
            size = doc.pagePointSize(i)
            if size.width() <= 0:
                continue
            scale = PDF_WIDTH / size.width()
            image = doc.render(i, (size * scale).toSize())
            if not image.isNull():
                out.append(image)
        doc.close()
        return out
    # 휴대폰을 옆으로 들고 찍은 영수증은 눕힌 채 저장되고 EXIF 회전 표시만 붙는다 — QImage(경로) 는 그 표시를 무시해
    # 출장증빙 · 미리 보기에 옆으로 누운 영수증이 들어가고 글자 높이도 누운 그림으로 쟀다. 회의록 영수증(minutes/receipt.py)과 같이 읽는다.
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    return [] if image.isNull() else [image]


# ── 증빙이 잘 보이는 크기 ──────────────────────────────────────────────────
# 담당자 2026-11-10 "모든 증빙서류에서 원본 증빙서류가 잘보이게 배치하기 … 증빙을 보고 잘보이는 선으로 편집을 했을 때 다음페이지로
# 넘어가서 만드는게 좋다고 판단되면 최대한 증빙이 잘보이는 방향으로". 그래서 칸 수 · 쪽 수를 미리 정하지 않는다:
# 증빙마다 안의 글자 한 줄 높이를 재어(text_height) 쪽에서 그 글자가 MIN_TEXT 점은 되게 할 배율(need)을 정하고,
# 모든 증빙이 그만큼 보이는 짜임 중 쪽이 가장 적은 것을 고른 뒤(_plan), 쪽에 남는 높이는 증빙을 더 키우는 데 쓴다(_allot).
# 쪽 폭을 다 써도 그만큼 안 되는 증빙(지도 그림 · 큰 표)은 쪽 폭에 맞춘다.
MIN_TEXT = 14.0      # 쪽(150 DPI)에서 증빙 글자 한 줄의 최소 높이(점) — 약 2.4mm, 8pt 글씨
TEXT_SCAN = 1400     # 글자 높이를 잴 때 볼 폭 — 이보다 크면 줄여 재고 되돌려 셈한다
TEXT_INK = 150       # 이보다 어두운 점이 글자 — 옅은 바탕색 · 그림자는 빼고
TEXT_EDGE = 0.04     # 둘레(테두리 선 · 그림자)는 빼고 잰다
TEXT_BAR = 0.7       # 한 줄이 이만큼 넘게 칠해진 띠는 글자가 아니라 막대 · 선
FALLBACK_CHARS = 40  # 글자 높이를 못 재면(사진 · 빈 그림) 한 줄에 글자가 이만큼 든 영수증으로 본다
MAX_COLS = 4
CELL_PAD = 6
MIN_CELL = 160       # 칸 하나의 최소 높이(위 설명 글 포함)


def text_height(image: QImage) -> float | None:
    """증빙 안 글자 한 줄의 높이(원본 점). 가로로 훑어 글자가 있는 줄이 이어진 띠들의 높이를 모아 작은 쪽 30% 값 —
    큰 제목이 아니라 본문 글자로 본다. 거의 모든 줄에 걸친 세로선(표 · 테두리)은 지우고 센다. 띠가 셋보다 적으면 못 잰 것(None)."""
    if image.isNull() or image.width() < 32 or image.height() < 32:
        return None
    scan = image.scaledToWidth(TEXT_SCAN, Qt.SmoothTransformation) if image.width() > TEXT_SCAN else image
    flat = QImage(scan.size(), QImage.Format_RGB32)
    flat.fill(QColor("white"))
    painter = QPainter(flat)
    painter.drawImage(0, 0, scan)
    painter.end()
    edge_x, edge_y = int(flat.width() * TEXT_EDGE), int(flat.height() * TEXT_EDGE)
    flat = flat.copy(edge_x, edge_y, flat.width() - 2 * edge_x, flat.height() - 2 * edge_y)
    width, height = flat.width(), flat.height()
    table = bytes(1 if b < TEXT_INK else 0 for b in range(256))
    rows = [line.translate(table) for line in _rows(flat)]
    columns = [line.translate(table).count(1) for line in _rows(flat.transformed(QTransform().rotate(90)))]
    lines = [x for x, n in enumerate(columns[:width]) if n > height / 2]
    if lines:
        mask = bytearray(b"\x01" * width)
        for x in lines:
            mask[x] = 0
        keep = int.from_bytes(mask, "big")
        counts = [(int.from_bytes(r, "big") & keep).bit_count() for r in rows]
    else:
        counts = [r.count(1) for r in rows]
    least = max(3, width * 0.01)
    runs, run, peak = [], 0, 0
    for n in counts + [0]:
        if n >= least:
            run, peak = run + 1, max(peak, n)
        elif run:
            if peak <= TEXT_BAR * width:
                runs.append(run)
            run, peak = 0, 0
    runs = sorted(r for r in runs if 4 <= r <= height / 8)
    if len(runs) < 3:
        return None
    return runs[len(runs) * 3 // 10] * image.width() / scan.width()


def legible_scale(image: QImage) -> float:
    """이 증빙을 쪽에 몇 배로 놓아야 글자가 잘 보이는지(MIN_TEXT / 글자 높이)."""
    w = max(1, image.width())
    text = text_height(image) or w / FALLBACK_CHARS
    text = min(max(text, w / 90), w / 12)
    return MIN_TEXT / text


@dataclass
class _Cell:
    image: QImage | None
    caption: str
    need: float          # 잘 보일 배율
    w: float
    h: float
    ref: tuple = ()      # 어느 증빙인지(model.Evidence.ref) — 미리 보기에서 눌러 고칠 때


def _cells(block: Block, cache: dict, needs: dict) -> list[_Cell]:
    """묶음의 칸들 — 증빙 파일 하나가 PDF 여러 쪽이면 칸도 여럿(설명 글은 첫 칸에만)."""
    out = []
    for i, path in enumerate(block.images):
        caption = block.captions[i] if i < len(block.captions) else ""
        ref = block.refs[i] if i < len(block.refs) else ()
        images = cache.setdefault(path, load_images(path))
        part = block.parts[i] if i < len(block.parts) else None
        if part is not None and part < len(images):
            images = [images[part]]
        if not images:
            out.append(_Cell(None, caption or path.name, 1.0, 600, 260, ref))
        for j, image in enumerate(images):
            if id(image) not in needs:
                needs[id(image)] = legible_scale(image)
            out.append(_Cell(image, caption if j == 0 else "", needs[id(image)], image.width(), image.height(), ref))
    return out


@dataclass
class _Grid:
    cols: int
    rows: int
    ratio: float         # 가장 덜 보이는 증빙의 (배율 / 잘 보일 배율) — 1 이상이면 모두 잘 보인다
    area: float


def _caption_h(cells: list[_Cell]) -> float:
    return CAPTION_H if any(c.caption for c in cells) else 0


def _grid(cells: list[_Cell], width: float, height: float, cols: int) -> _Grid | None:
    rows = rows_for(len(cells), cols)
    cw = width / cols - 2 * CELL_PAD
    ch = height / rows - _caption_h(cells) - 2 * CELL_PAD
    if cw <= 0 or ch <= 0:
        return None
    scales = [min(cw / c.w, ch / c.h) for c in cells]
    return _Grid(cols, rows, min(s / c.need for s, c in zip(scales, cells)), sum(s * s * c.w * c.h for s, c in zip(scales, cells)))


def best_grid(cells: list[_Cell], width: float, height: float) -> _Grid:
    """주어진 넓이에서 칸 나누기 — 모두 잘 보이는 것 중 증빙이 가장 크게 보이는 것, 그런 것이 없으면 가장 덜 보이는 증빙이 가장 크게."""
    options = [g for cols in range(1, min(len(cells), MAX_COLS) + 1) if (g := _grid(cells, width, height, cols))]
    if not options:
        return _Grid(1, len(cells), 0.0, 0.0)
    return max(options, key=lambda g: (min(g.ratio, 1.0), g.area))


def min_height(cells: list[_Cell], width: float) -> float:
    """모든 증빙이 잘 보이는 칸 나누기 중 가장 낮은 높이. 쪽 폭을 다 써도 모자라는 증빙은 쪽 폭에 맞춘 높이(한 줄에 하나)."""
    if not cells:
        return 0.0
    cap = _caption_h(cells)
    best = None
    for cols in range(1, min(len(cells), MAX_COLS) + 1):
        cw = width / cols - 2 * CELL_PAD
        if cols > 1 and any(cw / c.w < c.need for c in cells):
            continue
        row = max(MIN_CELL, max(c.h * min(c.need, cw / c.w) for c in cells) + cap + 2 * CELL_PAD)
        h = rows_for(len(cells), cols) * row
        best = h if best is None else min(best, h)
    return best


@dataclass
class _Slot:
    block: int           # 쪽 짜임(Page)의 몇 번째 묶음인지
    start: int           # 그 묶음의 몇 번째 칸부터
    count: int
    need_h: float        # 잘 보이는 가장 낮은 높이
    room_h: float = 0.0  # 실제로 준 높이


def _fit(cells: list[_Cell], start: int, limit: int, room: float, title_h: float, width: float) -> tuple[int, float]:
    """start 부터 몇 칸이 room 안에 잘 보이게 들어가는지 — (칸 수, 그 높이). 높이는 칸이 늘수록 줄지 않으므로 처음 넘칠 때 멈춘다."""
    best = (0, 0.0)
    for k in range(1, limit + 1):
        h = min_height(cells[start:start + k], width)
        if title_h + h > room:
            break
        best = (k, h)
    return best


def _chunks(cells: list[_Cell], start: int, title_h: float, width: float, room: float) -> list[int]:
    """start 부터 남은 칸을 빈 쪽들에 담으면 쪽마다 몇 칸인지."""
    out = []
    while start < len(cells):
        k = max(1, _fit(cells, start, len(cells) - start, room, title_h, width)[0])
        out.append(k)
        start += k
    return out


def _plan(cells_of: list[list[_Cell]], titles: list[list[str]], width: float, first_room: float, full_room: float) -> list[list[_Slot]]:
    """쪽 짜임 하나를 실제 쪽들로 — 묶음 차례대로 담되, 모든 증빙이 잘 보이게 들어가는 만큼만 한 쪽에 두고 나머지는 다음 쪽.
    묶음이 쪽을 넘기면 남은 쪽들에 고르게 나누고(7장이 6 + 1 이 아니라 4 + 3), 새 쪽에서 시작해도 쪽이 늘지 않으면 갈라 놓지 않는다."""
    pages: list[list[_Slot]] = []
    current: list[_Slot] = []
    room = first_room
    spread: dict[int, int] = {}         # 쪽을 넘기는 묶음 — 남은 칸을 담을 쪽 수(쪽마다 남은 칸 ÷ 남은 쪽 수만큼)
    bi = start = 0

    def turn() -> None:
        nonlocal current, room
        pages.append(current)
        current, room = [], full_room

    while bi < len(cells_of):
        cells = cells_of[bi]
        title_h = TITLE_H + GAP if titles[bi] else 0
        if not cells:                                       # 글 줄만 있는 묶음(실비 합계)
            if current and title_h > room:
                turn()
            current.append(_Slot(bi, 0, 0, 0.0))
            room -= title_h + GAP
            bi += 1
            continue
        left = len(cells) - start
        limit = math.ceil(left / spread[bi]) if spread.get(bi) else left
        k, h = _fit(cells, start, limit, room, title_h, width)
        if k < left and bi not in spread:
            fresh = _chunks(cells, start, title_h, width, full_room)
            rest = _chunks(cells, start + k, title_h, width, full_room) if k else []
            if current and (k == 0 or len(fresh) <= len(rest)):
                spread[bi] = len(fresh)                     # 새 쪽에서 시작해도 쪽이 늘지 않으면 갈라 놓지 않는다
                turn()
                continue
            if k == 0:                                      # 빈 쪽에도 잘 보이게 안 들어가는 증빙 — 하나라도 놓고 줄여 그린다
                k, h = 1, min_height(cells[start:start + 1], width)
                rest = _chunks(cells, start + 1, title_h, width, full_room)
            spread[bi] = len(rest) + 1
        elif k == 0:
            if current:
                turn()
                continue
            k, h = 1, min_height(cells[start:start + 1], width)
        current.append(_Slot(bi, start, k, h))
        room -= title_h + h + GAP
        start += k
        if bi in spread:
            spread[bi] = max(1, spread[bi] - 1)
        if start >= len(cells):
            bi, start = bi + 1, 0
        else:
            turn()
    if current:
        pages.append(current)
    return pages


def _row_heights(cells: list[_Cell], width: float, height: float, grid: _Grid) -> list[float]:
    """칸 나누기대로 놓았을 때 줄마다 실제로 쓰는 높이 — 그 줄에서 가장 큰 증빙 + 설명 글."""
    cw = width / grid.cols - 2 * CELL_PAD
    ch = height / grid.rows - _caption_h(cells) - 2 * CELL_PAD
    out = []
    for r in range(grid.rows):
        row = cells[r * grid.cols:(r + 1) * grid.cols]
        if cw <= 0 or ch <= 0:
            out.append(height / grid.rows)
            continue
        tallest = max(c.h * min(cw / c.w, ch / c.h) for c in row)
        out.append(min(height / grid.rows, max(MIN_CELL, tallest + _caption_h(cells) + 2 * CELL_PAD)))
    return out


def _used(cells: list[_Cell], width: float, height: float) -> float:
    return sum(_row_heights(cells, width, height, best_grid(cells, width, height)))


def _allot(slots: list[_Slot], cells_of: list[list[_Cell]], titles: list[list[str]], width: float, room: float) -> None:
    """한 쪽의 묶음들에 높이를 나눠 준다 — 잘 보이는 높이부터 주고, 남는 높이는 아직 더 커질 수 있는 묶음에 그 높이 비율대로.
    준 높이를 다 못 쓰는 묶음(폭이 모자라 더 안 커지는 증빙)은 쓰는 만큼으로 줄이고 남은 것을 다른 묶음에 다시 나눈다 — 남으면 쪽 아래 여백."""
    grids = [s for s in slots if s.count]
    if not grids:
        return
    space = room - sum(TITLE_H + GAP for s in slots if titles[s.block]) - GAP * (len(slots) - 1)
    need = sum(s.need_h for s in grids)
    if need >= space:
        for s in grids:
            s.room_h = s.need_h * space / need if need else 0
        return
    sub = {id(s): cells_of[s.block][s.start:s.start + s.count] for s in grids}
    for s in grids:
        s.room_h = s.need_h
    done: set[int] = set()
    for _ in range(6):
        extra = space - sum(s.room_h for s in grids)
        active = [s for s in grids if id(s) not in done]
        if extra < 1 or not active:
            break
        weight = sum(s.need_h for s in active) or 1
        for s in active:
            s.room_h += extra * s.need_h / weight
        for s in active:
            used = _used(sub[id(s)], width, s.room_h)
            if used < s.room_h - 1:                     # 더 줘도 안 커진다
                s.room_h = max(s.need_h, used)
                done.add(id(s))


def _bar_cells(cells: list[str]) -> list[str]:
    """그릴 칸 — 맨 앞 '* ' 는 엑셀 양식의 흔적이라 떼고, 끝의 빈 칸은 그리지 않는다(체류 증빙 머리 줄 오른쪽 — 담당자 2026-11-10 그림)."""
    out = list(cells) or [""]
    out[0] = out[0][2:] if out[0].startswith("* ") else out[0]
    while len(out) > 1 and not out[-1].strip():
        out.pop()
    return out


def _draw_bar(p: QPainter, rect: QRectF, cells: list[str], px: int, head: bool = False) -> None:
    """틀에 붙은 띠 한 줄 — 첫 칸은 왼쪽 제목, 나머지 칸(금액 · 연료 · 구간 km …)은 오른쪽에 둥근 칩으로.
    head 면 쪽 머리 띠(연보라 · 아래 강조선), 아니면 묶음 줄(옅은 면 · 위아래 얇은 선 · 왼쪽 강조선). 칩이 넘치면 글자를 줄인다."""
    cells = _bar_cells(cells)
    title, chips = cells[0], cells[1:]
    chip_h = rect.height() - (16 if head else 12)
    pad, space = 14, 8
    while px > 11:
        fm = QFontMetrics(_font(px, True))
        widths = [fm.horizontalAdvance(c) + 2 * pad for c in chips]
        need = sum(widths) + space * len(chips) + min(fm.horizontalAdvance(title), rect.width() * 0.25) + 40
        if need <= rect.width():
            break
        px -= 1
    fm = QFontMetrics(_font(px, True))
    widths = [fm.horizontalAdvance(c) + 2 * pad for c in chips]
    if head:
        p.fillRect(rect, BAND)
        p.fillRect(QRectF(rect.left(), rect.bottom() - 3, rect.width(), 3), ACCENT)
    else:
        p.fillRect(rect, BAR_BG)
        p.setPen(QPen(RULE, 1.5))
        p.drawLine(rect.topLeft(), rect.topRight())
        p.drawLine(rect.bottomLeft(), rect.bottomRight())
        p.fillRect(QRectF(rect.left(), rect.top(), ACCENT_W, rect.height()), ACCENT)
    p.setFont(_font(px, True))
    right = rect.right() - 12
    for text, w in reversed(list(zip(chips, widths))):
        chip = QRectF(right - w, rect.center().y() - chip_h / 2, w, chip_h)
        p.setPen(QPen(RULE, 1.5))
        p.setBrush(CHIP_BG)
        p.drawRoundedRect(chip, chip_h / 2, chip_h / 2)
        p.setBrush(Qt.NoBrush)
        p.setPen(ACCENT_TEXT)
        p.drawText(chip, Qt.AlignCenter, text)
        right -= w + space
    left = rect.left() + (20 if head else ACCENT_W + 14)
    p.setPen(INK)
    room = max(10, right - left - 8)
    p.drawText(QRectF(left, rect.top(), room, rect.height()), Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(title, Qt.ElideRight, int(room)))


def _draw_cell(p: QPainter, rect: QRectF, cell: _Cell, cap_h: float) -> None:
    if cap_h:
        if cell.caption:
            # 칸 이름표 — 칸 폭을 다 채운 상자 대신 글자만큼의 둥근 이름표를 가운데에
            room = rect.width() - 2 * CELL_PAD
            px = 17          # 긴 설명(대중교통 '열차 · 춘천 → 서울 · 8,000원')은 칸 폭에 맞게 글자를 줄인다
            while px > 11 and QFontMetrics(_font(px, True)).horizontalAdvance(cell.caption) + 28 > room:
                px -= 1
            fm = QFontMetrics(_font(px, True))
            w = min(room, fm.horizontalAdvance(cell.caption) + 28)
            cap = QRectF(rect.center().x() - w / 2, rect.top() + 3, w, cap_h - 6)
            # 묶음 줄의 칩과 같은 색(흰 면 · 옅은 선 · 강조 글자) — 담당자 2026-11-10 "색상은 다른 증빙서식과 동일하게"
            p.setPen(QPen(RULE, 1.5))
            p.setBrush(CHIP_BG)
            p.drawRoundedRect(cap, cap.height() / 2, cap.height() / 2)
            p.setBrush(Qt.NoBrush)
            p.setFont(_font(px, True))
            p.setPen(ACCENT_TEXT)
            p.drawText(cap, Qt.AlignCenter, fm.elidedText(cell.caption, Qt.ElideRight, int(cap.width() - 16)))
        rect = rect.adjusted(0, cap_h, 0, 0)
    box = rect.adjusted(CELL_PAD, CELL_PAD, -CELL_PAD, -CELL_PAD)
    if cell.image is None:
        p.setFont(_font(15))
        p.setPen(MUTED)
        p.drawText(box, Qt.AlignCenter | Qt.TextWordWrap, "그림을 읽지 못한 파일")
        return
    if box.width() <= 0 or box.height() <= 0:
        return
    image = cell.image
    scale = min(box.width() / image.width(), box.height() / image.height())
    w, h = image.width() * scale, image.height() * scale
    target = QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)      # 가운데(담당자 2026-10-27)
    p.drawImage(target, image)


def _draw_grid(p: QPainter, rect: QRectF, cells: list[_Cell], grid: _Grid, mark=None) -> None:
    """줄마다 실제 높이로 위에서부터 — 설명 글 바로 아래에 증빙. 줄 안에서는 가운데. mark(칸, ref) 는 미리 보기가 칸 자리를 받는다."""
    col_w = rect.width() / grid.cols
    cap_h = _caption_h(cells)
    heights = _row_heights(cells, rect.width(), rect.height(), grid)
    y = rect.top()
    for r, row_h in enumerate(heights):
        row = cells[r * grid.cols:(r + 1) * grid.cols]
        # 마지막 줄이 덜 차면 그 줄을 가운데로
        left = rect.left() + (grid.cols - len(row)) * col_w / 2
        for c, cell in enumerate(row):
            box = QRectF(left + c * col_w, y, col_w, row_h)
            _draw_cell(p, box, cell, cap_h)
            if mark is not None and cell.ref:
                mark(box, cell.ref, "cell")
        y += row_h


PAGE_SIZE = QSizeF(QPageSize(QPageSize.A4).sizePixels(DPI))      # 쪽 크기(점) — PDF 와 미리 보기가 같은 자리에 그린다
LANDSCAPE_SIZE = QSizeF(PAGE_SIZE.height(), PAGE_SIZE.width())  # 가로 쪽
# 쪽 짜임마다 세로 · 가로 중 증빙이 더 잘 보이는 쪽으로(담당자 2026-11-11 "증빙에 따라서 증빙이 잘보이는 형식으로 용지를 세로,가로형 변경" —
# 네이버 지도 길찾기 그림은 가로로 길어 세로 쪽에서는 작았다). 기본은 세로, 가로는 쪽이 줄거나 · 같은 쪽 수에서 증빙이 이만큼 넘게 커질 때만
LANDSCAPE_GAIN = 1.15


def size_of(image: QImage) -> QSizeF:
    """미리 보기 쪽 그림의 쪽 크기(점) — 가로로 긴 그림이면 가로 쪽. 누를 자리(Hit.rect)는 이 좌표다."""
    return LANDSCAPE_SIZE if image.width() > image.height() else PAGE_SIZE


@dataclass
class Hit:
    """미리 보기에서 누를 자리 — 몇째 쪽(0부터)의 어느 칸이 어느 증빙(또는 이동경로 · 연료)인지. rect 는 쪽 좌표(그 쪽의 크기 — size_of)."""
    page: int
    rect: QRectF
    ref: tuple
    where: str           # cell(증빙 칸) · bar(묶음 줄) · head(머리 줄)


def _layout(size: QSizeF) -> QPageLayout:
    landscape = size.width() > size.height()
    return QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape if landscape else QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))


class _PdfTarget:
    def __init__(self, out: Path):
        self.writer = QPdfWriter(str(out))
        self.writer.setResolution(DPI)
        self.writer.setPageLayout(_layout(PAGE_SIZE))
        self.writer.setTitle(out.stem)
        self.painter: QPainter | None = None

    def begin(self, size: QSizeF = PAGE_SIZE) -> QPainter:
        self.writer.setPageLayout(_layout(size))          # 첫 쪽의 방향은 그리기 전에
        self.painter = QPainter(self.writer)
        return self.painter

    def next(self, size: QSizeF = PAGE_SIZE) -> QPainter:
        self.writer.setPageLayout(_layout(size))          # 다음 쪽의 방향은 newPage 바로 전에(Qt 규칙)
        self.writer.newPage()
        return self.painter

    def end(self) -> None:
        if self.painter is not None:
            self.painter.end()


class _ImageTarget:
    """미리 보기 — 쪽마다 그림 하나(PAGE_SIZE × scale)에 PDF 와 같은 좌표로 그린다."""

    def __init__(self, scale: float):
        self.scale = scale
        self.images: list[QImage] = []
        self.painter: QPainter | None = None

    def _new(self, size: QSizeF) -> QPainter:
        image = QImage(int(size.width() * self.scale), int(size.height() * self.scale), QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.images.append(image)
        self.painter = QPainter(image)
        self.painter.setRenderHint(QPainter.Antialiasing)
        self.painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self.painter.scale(self.scale, self.scale)
        return self.painter

    def begin(self, size: QSizeF = PAGE_SIZE) -> QPainter:
        return self._new(size)

    def next(self, size: QSizeF = PAGE_SIZE) -> QPainter:
        self.painter.end()
        return self._new(size)

    def end(self) -> None:
        if self.painter is not None:
            self.painter.end()


def render(pages: list[Page], out: Path) -> int:
    """쪽들을 out 에 쓰고 실제 쪽 수를 돌려준다. 쪽 짜임 하나가 증빙이 잘 보이게 한 쪽에 안 들어가면 같은 머리 줄 '(계속)' 으로 다음 쪽에 이어 그린다."""
    return _paint(pages, _PdfTarget(out))


def preview(pages: list[Page], scale: float = 0.6, cache: dict | None = None, needs: dict | None = None) -> tuple[list[QImage], list[Hit]]:
    """앱 안 미리 보기 — PDF 와 똑같이 짠 쪽 그림들과 누를 자리(Hit)들. 담당자 2026-11-10 "확인필요한 건은 어플내에서 증빙양식 미리보기 처럼".
    cache · needs 를 넘기면 증빙 그림 · 글자 높이를 다시 읽지 않는다(고칠 때마다 다시 그리므로)."""
    target = _ImageTarget(scale)
    hits: list[Hit] = []
    _paint(pages, target, hits, cache, needs)
    return target.images, hits


@dataclass
class _Frame:
    """쪽 크기 하나의 자리 — 틀 · 안쪽 폭 · 아래 끝 · 빈 쪽에서 증빙에 쓸 높이."""
    size: QSizeF
    frame: QRectF
    inner_left: float
    inner_w: float
    bottom: float
    full_room: float


def _frame(size: QSizeF) -> _Frame:
    frame = QRectF(MARGIN, MARGIN, size.width() - 2 * MARGIN, size.height() - 2 * MARGIN)
    bottom = frame.bottom() - 12
    return _Frame(size, frame, frame.left() + 16, frame.width() - 32, bottom, bottom - (frame.top() + HEAD_H + GAP))


def _first_room(f: _Frame, page: Page) -> float:
    return f.bottom - (f.frame.top() + HEAD_H + GAP + 28 * len(page.notes))


def _visibility(plan: list[list[_Slot]], cells_of: list[list[_Cell]], titles: list[list[str]], f: _Frame, first_room: float) -> float:
    """짠 쪽들에서 증빙이 얼마나 크게 보이는지 — 증빙마다 (놓인 배율 / 잘 보일 배율) 의 기하평균. 높이를 나눠 준다(_allot — 그릴 때 다시 한다)."""
    total, n = 0.0, 0
    for i, slots in enumerate(plan):
        _allot(slots, cells_of, titles, f.inner_w, first_room if i == 0 else f.full_room)
        for slot in slots:
            if not slot.count:
                continue
            cells = cells_of[slot.block][slot.start:slot.start + slot.count]
            grid = best_grid(cells, f.inner_w, slot.room_h)
            heights = _row_heights(cells, f.inner_w, slot.room_h, grid)
            cw = f.inner_w / grid.cols - 2 * CELL_PAD
            for r, row_h in enumerate(heights):
                ch = row_h - _caption_h(cells) - 2 * CELL_PAD
                for cell in cells[r * grid.cols:(r + 1) * grid.cols]:
                    if cw > 0 and ch > 0 and cell.w and cell.h:
                        total += math.log(max(1e-6, min(cw / cell.w, ch / cell.h) / cell.need))
                        n += 1
    return math.exp(total / n) if n else 1.0


def _orient(page: Page, cells_of: list[list[_Cell]], titles: list[list[str]]) -> tuple[_Frame, list[list[_Slot]]]:
    """쪽 짜임 하나를 세로 · 가로로 짜 보고 증빙이 잘 보이는 쪽 — 쪽이 줄거나, 같은 쪽 수에서 증빙이 LANDSCAPE_GAIN 배 넘게 커지면 가로."""
    options = []
    for size in (PAGE_SIZE, LANDSCAPE_SIZE):
        f = _frame(size)
        first = _first_room(f, page)
        plan = _plan(cells_of, titles, f.inner_w, first, f.full_room)
        options.append((f, plan, _visibility(plan, cells_of, titles, f, first)))
    (fp, pp, vp), (fl, pl, vl) = options
    if any(cells_of) and (len(pl) < len(pp) or (len(pl) == len(pp) and vl > vp * LANDSCAPE_GAIN)):
        return fl, pl
    return fp, pp


def _paint(pages: list[Page], target, hits: list | None = None, cache: dict | None = None, needs: dict | None = None) -> int:
    painter = None
    cache = {} if cache is None else cache
    needs = {} if needs is None else needs
    count = 0

    def mark(rect: QRectF, ref: tuple, where: str) -> None:
        if hits is not None and ref:
            hits.append(Hit(count - 1, QRectF(rect), ref, where))

    def new_page(page: Page, cont: bool, f: _Frame) -> float:
        nonlocal count, painter
        painter = target.next(f.size) if count else target.begin(f.size)
        count += 1
        frame = f.frame
        head = list(page.head)
        if cont:
            head[0] += " (계속)"
        head_rect = QRectF(frame.left(), frame.top(), frame.width(), HEAD_H)
        rounded = QPainterPath()
        rounded.addRoundedRect(frame, FRAME_RADIUS, FRAME_RADIUS)
        painter.save()
        painter.setClipPath(rounded)               # 머리 띠가 둥근 틀 모서리를 따라가게
        _draw_bar(painter, head_rect, head, 21, head=True)
        painter.restore()
        painter.setPen(QPen(FRAME, 2.5))
        painter.drawRoundedRect(frame, FRAME_RADIUS, FRAME_RADIUS)
        mark(head_rect, page.head_ref, "head")
        y = frame.top() + HEAD_H + GAP
        if not cont:
            painter.setFont(_font(17, True))
            painter.setPen(INK)
            for note in page.notes:
                painter.drawText(QRectF(frame.left() + 12, y, frame.width() - 24, 26), Qt.AlignLeft | Qt.AlignVCenter, note)
                y += 28
        return y

    for page in pages:
        cells_of = [_cells(block, cache, needs) for block in page.blocks]
        titles = [block.title for block in page.blocks]
        f, plan = _orient(page, cells_of, titles)
        frame = f.frame
        for n, slots in enumerate(plan):
            y = new_page(page, n > 0, f)
            _allot(slots, cells_of, titles, f.inner_w, f.bottom - y)
            for slot in slots:
                block = page.blocks[slot.block]
                if block.title:
                    title = block.title if slot.start == 0 else [block.title[0] + " (계속)"] + block.title[1:]
                    bar = QRectF(frame.left() + 1, y, frame.width() - 2, TITLE_H)      # 틀 양끝에 붙인 띠
                    _draw_bar(painter, bar, title, 17)
                    mark(bar, block.title_ref, "bar")
                    y += TITLE_H + GAP
                if slot.count:
                    cells = cells_of[slot.block][slot.start:slot.start + slot.count]
                    _draw_grid(painter, QRectF(f.inner_left, y, f.inner_w, slot.room_h), cells, best_grid(cells, f.inner_w, slot.room_h), mark)
                    y += slot.room_h
                y += GAP
    if count == 0:
        target.begin(PAGE_SIZE)                    # 쪽이 하나도 없어도 PDF 는 닫는다
    target.end()
    return count
