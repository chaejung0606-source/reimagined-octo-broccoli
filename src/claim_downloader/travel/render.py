"""출장증빙 쪽 짜임(model.Page) → A4 PDF. PySide6(QPdfWriter · QPainter · QPdfDocument) — 새 의존성 없이 앱에 있는 것으로 그린다.

모양은 담당자가 만들던 것(2026-10-27 그림): 쪽 둘레 테두리 · 머리 줄(왼쪽 '* … 증빙', 오른쪽 일자 · 금액 칸, 굵게) · 아래에 영수증 그림.
PDF 영수증은 쪽마다 그림으로 바꿔 넣는다. 영수증은 둘레의 빈 여백을 잘라 내고 칸에 꽉 차게 키워 가운데에 둔다
(담당자 2026-10-27 "증빙내용이 잘보이도록 확대 및 여백부분 자르기, 가운데 정렬" — A4 PDF 영수증은 내용이 쪽 위 한 귀퉁이뿐이라 작게 보였다).
QGuiApplication 이 떠 있어야 한다(앱 안에서 부른다).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen, QTransform

from .model import Block, Page, grid_cols, rows_for

DPI = 150
MARGIN = 40          # 쪽 바깥 여백(점)
HEAD_H = 46          # 머리 줄 높이
TITLE_H = 36         # 묶음 머리 줄 높이
CAPTION_H = 30       # 칸 위 일자 글
GAP = 10
ROW_MAX = 520        # 흘려 담는 묶음(자차 하이패스)의 한 줄 최대 높이
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


class _Cells:
    """그림 묶음 — 증빙 파일 하나가 PDF 여러 쪽이면 칸도 여럿(설명 글은 첫 칸에만)."""

    def __init__(self, block: Block, cache: dict):
        self.items: list[tuple[QImage | None, str]] = []
        for i, path in enumerate(block.images):
            caption = block.captions[i] if i < len(block.captions) else ""
            images = cache.setdefault(path, load_images(path))
            part = block.parts[i] if i < len(block.parts) else None
            if part is not None and part < len(images):
                images = [images[part]]
            if not images:
                self.items.append((None, caption or path.name))
            for j, image in enumerate(images):
                self.items.append((image, caption if j == 0 else ""))
        # 칸 수는 실제 그림 수로 — PDF 영수증이 여러 쪽이면 늘어난다. 하이패스도 그날 영수증이 적으면 칸을 넓혀 크게(담당자 2026-10-27 "하이패스 내역도 동일하게")
        self.cols = grid_cols(len(self.items)) if self.items else block.cols


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


def _draw_cell(p: QPainter, rect: QRectF, image: QImage | None, caption: str) -> None:
    if caption:
        cap = QRectF(rect.left(), rect.top(), rect.width(), CAPTION_H)
        p.fillRect(cap, SOFT)
        p.setPen(QPen(LINE, 1))
        p.drawRect(cap)
        p.setFont(_font(17, True))
        p.setPen(INK)
        p.drawText(cap, Qt.AlignCenter, caption)
        rect = rect.adjusted(0, CAPTION_H, 0, 0)
    box = rect.adjusted(6, 6, -6, -6)
    if image is None:
        p.setFont(_font(15))
        p.setPen(MUTED)
        p.drawText(box, Qt.AlignCenter | Qt.TextWordWrap, "그림을 읽지 못한 파일")
        return
    if box.width() <= 0 or box.height() <= 0:
        return
    scale = min(box.width() / image.width(), box.height() / image.height())
    w, h = image.width() * scale, image.height() * scale
    target = QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h)      # 가운데(담당자 2026-10-27)
    p.drawImage(target, image)


def _grid_height(cells: _Cells, width: float, row_h: float) -> float:
    return rows_for(len(cells.items), cells.cols) * row_h


def _draw_grid(p: QPainter, rect: QRectF, cells: _Cells, start: int, count: int, row_h: float) -> None:
    col_w = rect.width() / cells.cols
    for k in range(count):
        image, caption = cells.items[start + k]
        r, c = divmod(k, cells.cols)
        # 마지막 줄이 덜 차면 그 줄을 가운데로
        in_row = min(cells.cols, count - r * cells.cols)
        left = rect.left() + (cells.cols - in_row) * col_w / 2
        _draw_cell(p, QRectF(left + c * col_w, rect.top() + r * row_h, col_w, row_h), image, caption)


def render(pages: list[Page], out: Path) -> int:
    """쪽들을 out 에 쓰고 실제 쪽 수를 돌려준다. 흘려 담는 묶음이 한 쪽에 안 들어가면 같은 머리 줄로 다음 쪽에 이어 그린다."""
    writer = QPdfWriter(str(out))
    writer.setResolution(DPI)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    writer.setTitle(out.stem)
    painter = QPainter(writer)
    size = QSizeF(writer.width(), writer.height())
    frame = QRectF(MARGIN, MARGIN, size.width() - 2 * MARGIN, size.height() - 2 * MARGIN)
    cache: dict = {}
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
    for page in pages:
        y = new_page(page, False)
        all_cells = [_Cells(block, cache) for block in page.blocks]
        for index, block in enumerate(page.blocks):
            cells = all_cells[index]
            title_h = TITLE_H + GAP if block.title else 0
            if block.fill:
                # 남은 높이를 이 묶음과 뒤의 남은 높이 묶음(출장지 여러 곳의 체류)이 줄 수만큼 나눠 쓴다 — 너무 좁으면 새 쪽에서
                rest = [i for i in range(index, len(page.blocks)) if page.blocks[i].fill]
                titles = sum(TITLE_H + GAP for i in rest if page.blocks[i].title)
                weights = [rows_for(len(all_cells[i].items), all_cells[i].cols) if all_cells[i].items else 0 for i in rest]
                if (bottom - y - titles) / max(1, sum(1 for w in weights if w)) < 220:
                    y = new_page(page, True)
                share = (bottom - y - titles - GAP * (len(rest) - 1)) * (weights[0] / sum(weights)) if sum(weights) else 0
                if block.title:
                    _draw_bar(painter, QRectF(inner_left, y, inner_w, TITLE_H), block.title, 17, SOFT)
                    y += title_h
                if cells.items:
                    rows = rows_for(len(cells.items), cells.cols)
                    _draw_grid(painter, QRectF(inner_left, y, inner_w, share), cells, 0, len(cells.items), share / rows)
                y += share + (GAP if len(rest) > 1 else 0)
                continue
            row_h = min(ROW_MAX, inner_w / cells.cols * 1.35)
            start = 0
            first = True
            while first or start < len(cells.items):
                room_rows = int((bottom - y - (title_h if first else 0)) // row_h)
                if room_rows < 1:
                    y = new_page(page, True)
                    continue
                if block.title:
                    _draw_bar(painter, QRectF(inner_left, y, inner_w, TITLE_H), block.title if first else [block.title[0] + " (계속)"] + block.title[1:], 17, SOFT)
                    y += title_h
                first = False
                take = min(len(cells.items) - start, room_rows * cells.cols)
                _draw_grid(painter, QRectF(inner_left, y, inner_w, row_h * rows_for(take, cells.cols)), cells, start, take, row_h)
                y += row_h * rows_for(take, cells.cols) + GAP
                start += take
    painter.end()
    return count
