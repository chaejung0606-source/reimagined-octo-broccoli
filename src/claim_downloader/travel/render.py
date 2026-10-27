"""출장증빙 쪽 짜임(model.Page) → A4 PDF. PySide6(QPdfWriter · QPainter · QPdfDocument) — 새 의존성 없이 앱에 있는 것으로 그린다.

모양은 담당자가 만들던 것(2026-10-27 그림): 쪽 둘레 테두리 · 머리 줄(왼쪽 '* … 증빙', 오른쪽 일자 · 금액 칸, 굵게) · 아래에 영수증 그림.
PDF 영수증은 쪽마다 그림으로 바꿔 넣는다. QGuiApplication 이 떠 있어야 한다(앱 안에서 부른다).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from .model import Block, Page, grid_cols, rows_for

DPI = 150
MARGIN = 40          # 쪽 바깥 여백(점)
HEAD_H = 46          # 머리 줄 높이
TITLE_H = 36         # 묶음 머리 줄 높이
CAPTION_H = 30       # 칸 위 일자 글
GAP = 10
ROW_MAX = 520        # 흘려 담는 묶음(자차 하이패스)의 한 줄 최대 높이
PDF_WIDTH = 1400     # PDF 영수증을 그림으로 바꿀 폭(점)

INK = QColor("#111111")
LINE = QColor("#222222")
SOFT = QColor("#F2F2F2")
MUTED = QColor("#555555")


def _font(px: int, bold: bool = False) -> QFont:
    font = QFont("Pretendard")
    font.setPixelSize(px)
    font.setBold(bold)
    return font


def load_images(path: Path) -> list[QImage]:
    """그림 파일은 그대로, PDF 는 쪽마다 그림 하나."""
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
            if not images:
                self.items.append((None, caption or path.name))
            for j, image in enumerate(images):
                self.items.append((image, caption if j == 0 else ""))
        # PDF 영수증이 여러 쪽이면 칸 수가 늘어난다 — 한 쪽을 다 쓰는 묶음은 늘어난 칸 수로 다시 나눈다
        self.cols = grid_cols(len(self.items)) if block.fill else block.cols


def _draw_bar(p: QPainter, rect: QRectF, cells: list[str], px: int, fill: QColor | None = None) -> None:
    """칸 나뉜 한 줄 — 첫 칸이 남는 폭을 받고 나머지 칸은 글자만큼."""
    fm = QFontMetrics(_font(px, True))
    widths = [fm.horizontalAdvance(c) + 28 for c in cells[1:]]
    first = max(rect.width() - sum(widths), rect.width() * 0.25)
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
        align = (Qt.AlignLeft if i == 0 else Qt.AlignCenter) | Qt.AlignVCenter
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
    target = QRectF(box.center().x() - w / 2, box.top(), w, h)      # 위에 붙인다 — 칸 위 일자 글 바로 아래에 영수증이 오게
    p.drawImage(target, image)


def _grid_height(cells: _Cells, width: float, row_h: float) -> float:
    return rows_for(len(cells.items), cells.cols) * row_h


def _draw_grid(p: QPainter, rect: QRectF, cells: _Cells, start: int, count: int, row_h: float) -> None:
    col_w = rect.width() / cells.cols
    for k in range(count):
        image, caption = cells.items[start + k]
        r, c = divmod(k, cells.cols)
        _draw_cell(p, QRectF(rect.left() + c * col_w, rect.top() + r * row_h, col_w, row_h), image, caption)


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
        for block in page.blocks:
            cells = _Cells(block, cache)
            title_h = TITLE_H + GAP if block.title else 0
            if block.fill:
                # 남은 높이를 다 쓴다 — 너무 좁으면(위 묶음이 많이 차지) 새 쪽에서
                if bottom - y - title_h < 260:
                    y = new_page(page, True)
                if block.title:
                    _draw_bar(painter, QRectF(inner_left, y, inner_w, TITLE_H), block.title, 17, SOFT)
                    y += title_h
                if cells.items:
                    rows = rows_for(len(cells.items), cells.cols)
                    _draw_grid(painter, QRectF(inner_left, y, inner_w, bottom - y), cells, 0, len(cells.items), (bottom - y) / rows)
                y = bottom
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
