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
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen, QTransform

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

INK = QColor("#111111")
LINE = QColor("#222222")
SOFT = QColor("#F2F2F2")
MUTED = QColor("#555555")


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
    image = QImage(str(path))
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


def _cells(block: Block, cache: dict, needs: dict) -> list[_Cell]:
    """묶음의 칸들 — 증빙 파일 하나가 PDF 여러 쪽이면 칸도 여럿(설명 글은 첫 칸에만)."""
    out = []
    for i, path in enumerate(block.images):
        caption = block.captions[i] if i < len(block.captions) else ""
        images = cache.setdefault(path, load_images(path))
        part = block.parts[i] if i < len(block.parts) else None
        if part is not None and part < len(images):
            images = [images[part]]
        if not images:
            out.append(_Cell(None, caption or path.name, 1.0, 600, 260))
        for j, image in enumerate(images):
            if id(image) not in needs:
                needs[id(image)] = legible_scale(image)
            out.append(_Cell(image, caption if j == 0 else "", needs[id(image)], image.width(), image.height()))
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


def _draw_bar(p: QPainter, rect: QRectF, cells: list[str], px: int, fill: QColor | None = None) -> None:
    """칸 나뉜 한 줄 — 첫 칸이 남는 폭을 받고 나머지 칸은 글자만큼. 칸이 많아(출장지 여러 곳의 이동경로) 넘치면 글자를 줄인다.
    칸이 하나뿐인 줄(출장지 줄 '삼척 출장 증빙')은 가운데."""
    first_need = QFontMetrics(_font(px, True)).horizontalAdvance(cells[0]) + 28
    while px > 11:
        fm = QFontMetrics(_font(px, True))
        widths = [fm.horizontalAdvance(c) + 28 for c in cells[1:]]
        if sum(widths) + min(first_need, rect.width() * 0.25) <= rect.width():
            break
        px -= 1
        first_need = fm.horizontalAdvance(cells[0]) + 28
    fm = QFontMetrics(_font(px, True))
    widths = [fm.horizontalAdvance(c) + 28 for c in cells[1:]]
    first = max(rect.width() - sum(widths), min(first_need, rect.width() * 0.25))
    p.setFont(_font(px, True))
    x = rect.left()
    for i, text in enumerate(cells):
        w = first if i == 0 else widths[i - 1]
        cell = QRectF(x, rect.top(), w, rect.height())
        if fill is not None:
            p.fillRect(cell, fill)
        p.setPen(QPen(LINE, 2))
        p.drawRect(cell)
        p.setPen(INK)
        align = (Qt.AlignLeft if i == 0 and len(cells) > 1 else Qt.AlignCenter) | Qt.AlignVCenter
        p.drawText(cell.adjusted(10, 0, -10, 0), align, fm.elidedText(text, Qt.ElideRight, int(cell.width() - 20)))
        x += w


def _draw_cell(p: QPainter, rect: QRectF, cell: _Cell, cap_h: float) -> None:
    if cap_h:
        if cell.caption:
            cap = QRectF(rect.left(), rect.top(), rect.width(), cap_h)
            p.fillRect(cap, SOFT)
            p.setPen(QPen(LINE, 1))
            p.drawRect(cap)
            px = 17          # 긴 설명(대중교통 '열차 · 춘천 → 서울 · 8,000원')은 칸 폭에 맞게 글자를 줄인다
            while px > 11 and QFontMetrics(_font(px, True)).horizontalAdvance(cell.caption) > cap.width() - 12:
                px -= 1
            p.setFont(_font(px, True))
            p.setPen(INK)
            p.drawText(cap, Qt.AlignCenter, QFontMetrics(_font(px, True)).elidedText(cell.caption, Qt.ElideRight, int(cap.width() - 12)))
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


def _draw_grid(p: QPainter, rect: QRectF, cells: list[_Cell], grid: _Grid) -> None:
    """줄마다 실제 높이로 위에서부터 — 설명 글 바로 아래에 증빙. 줄 안에서는 가운데."""
    col_w = rect.width() / grid.cols
    cap_h = _caption_h(cells)
    heights = _row_heights(cells, rect.width(), rect.height(), grid)
    y = rect.top()
    for r, row_h in enumerate(heights):
        row = cells[r * grid.cols:(r + 1) * grid.cols]
        # 마지막 줄이 덜 차면 그 줄을 가운데로
        left = rect.left() + (grid.cols - len(row)) * col_w / 2
        for c, cell in enumerate(row):
            _draw_cell(p, QRectF(left + c * col_w, y, col_w, row_h), cell, cap_h)
        y += row_h


def render(pages: list[Page], out: Path) -> int:
    """쪽들을 out 에 쓰고 실제 쪽 수를 돌려준다. 쪽 짜임 하나가 증빙이 잘 보이게 한 쪽에 안 들어가면 같은 머리 줄 '(계속)' 으로 다음 쪽에 이어 그린다."""
    writer = QPdfWriter(str(out))
    writer.setResolution(DPI)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    writer.setTitle(out.stem)
    painter = QPainter(writer)
    size = QSizeF(writer.width(), writer.height())
    frame = QRectF(MARGIN, MARGIN, size.width() - 2 * MARGIN, size.height() - 2 * MARGIN)
    cache: dict = {}
    needs: dict = {}
    count = 0

    def new_page(page: Page, cont: bool) -> float:
        nonlocal count
        if count:
            writer.newPage()
        count += 1
        painter.setPen(QPen(LINE, 3))
        painter.drawRect(frame)
        head = list(page.head)
        if cont:
            head[0] += " (계속)"
        _draw_bar(painter, QRectF(frame.left(), frame.top(), frame.width(), HEAD_H), head, 21)
        y = frame.top() + HEAD_H + GAP
        if not cont:
            painter.setFont(_font(17, True))
            painter.setPen(INK)
            for note in page.notes:
                painter.drawText(QRectF(frame.left() + 12, y, frame.width() - 24, 26), Qt.AlignLeft | Qt.AlignVCenter, note)
                y += 28
        return y

    inner_left, inner_w = frame.left() + 16, frame.width() - 32
    bottom = frame.bottom() - 12
    full_room = bottom - (frame.top() + HEAD_H + GAP)
    for page in pages:
        cells_of = [_cells(block, cache, needs) for block in page.blocks]
        titles = [block.title for block in page.blocks]
        y = new_page(page, False)
        plan = _plan(cells_of, titles, inner_w, bottom - y, full_room)
        for n, slots in enumerate(plan):
            if n:
                y = new_page(page, True)
            _allot(slots, cells_of, titles, inner_w, bottom - y)
            for slot in slots:
                block = page.blocks[slot.block]
                if block.title:
                    title = block.title if slot.start == 0 else [block.title[0] + " (계속)"] + block.title[1:]
                    _draw_bar(painter, QRectF(inner_left, y, inner_w, TITLE_H), title, 17, SOFT)
                    y += TITLE_H + GAP
                if slot.count:
                    cells = cells_of[slot.block][slot.start:slot.start + slot.count]
                    _draw_grid(painter, QRectF(inner_left, y, inner_w, slot.room_h), cells, best_grid(cells, inner_w, slot.room_h))
                    y += slot.room_h
                y += GAP
    painter.end()
    return count
