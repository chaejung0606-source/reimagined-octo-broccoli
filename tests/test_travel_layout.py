"""출장증빙 — 증빙이 잘 보이게 배치(render.py, 담당자 2026-11-10 "모든 증빙서류에서 원본 증빙서류가 잘보이게 배치하기 …
다음페이지로 넘어가서 만드는게 좋다고 판단되면 최대한 증빙이 잘보이는 방향으로"). CLAUDE.md 28절.

영수증 대신 '글자 줄'(검은 막대)을 그린 가짜 그림을 코드로 만든다 — 막대 높이가 글자 높이다.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from claim_downloader.travel import model


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        pytest.skip(str(exc))
    return QApplication.instance() or QApplication([])


def _receipt(path: Path, w: int, h: int, line: int, boxed: bool = False) -> Path:
    """글자 줄 높이가 line 점인 가짜 영수증 — 줄마다 폭을 달리한 막대, boxed 면 둘레 테두리(하이패스 상자처럼)."""
    from PySide6.QtGui import QColor, QImage, QPainter
    image = QImage(w, h, QImage.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    if boxed:
        for rect in ((0, 0, w, 4), (0, h - 4, w, 4), (0, 0, 4, h), (w - 4, 0, 4, h)):
            painter.fillRect(*rect, QColor("black"))
    y, i = int(h * 0.08), 0
    while y + line < h * 0.92:
        painter.fillRect(int(w * 0.1), y, int(w * (0.3 + 0.3 * (i % 2))), line, QColor("#222222"))
        y += line * 2
        i += 1
    painter.end()
    image.save(str(path))
    return path


def _pages_text(out: Path) -> list[str]:
    from pypdf import PdfReader
    return ["".join(page.extract_text().split()) for page in PdfReader(str(out)).pages]       # 띄어쓰기 · 줄바꿈 없이


def test_text_height_reads_line_height_and_ignores_borders(qapp, tmp_path):
    from PySide6.QtGui import QColor, QImage

    from claim_downloader.travel import render
    assert render.text_height(QImage(str(_receipt(tmp_path / "a.png", 1080, 2000, 30)))) == pytest.approx(30, abs=1)
    assert render.text_height(QImage(str(_receipt(tmp_path / "b.png", 420, 520, 12, boxed=True)))) == pytest.approx(12, abs=1)
    blank = QImage(600, 800, QImage.Format_RGB32)
    blank.fill(QColor("white"))
    assert render.text_height(blank) is None
    assert render.legible_scale(blank) == pytest.approx(render.MIN_TEXT / (600 / render.FALLBACK_CHARS))   # 못 재면 한 줄 40자 영수증으로


def test_small_text_stay_moves_to_next_pages_evenly(qapp, tmp_path):
    """글자가 작은 체류 영수증 7장 — 한 쪽에 7칸이면 안 읽히므로 잘 보이는 만큼씩(3 · 2 · 2) 다음 쪽으로."""
    from claim_downloader.travel import render
    days = [date(2026, 5, d) for d in range(1, 8)]
    trip = model.Trip(name="가", start=days[0], end=days[-1], destination="삼척",
                      stay=[model.Evidence(_receipt(tmp_path / f"s{d.day}.png", 1080, 2000, 30), d) for d in days])
    out = tmp_path / "small.pdf"
    assert render.render(model.pages(trip), out) == 3
    texts = _pages_text(out)
    # 칸마다 그날 일자 이름표(요일까지) — 묶음 줄의 기간 칩('5월 1일 ~ 5월 7일')은 세지 않는다
    assert [sum(f"5월{d.day}일{model.WEEKDAYS[d.weekday()]}요일" in t for d in days) for t in texts] == [3, 2, 2]
    assert "(계속)" in texts[1] and "삼척출장증빙(계속)" in texts[2]


def test_big_text_stay_stays_on_one_page(qapp, tmp_path):
    from claim_downloader.travel import render
    days = [date(2026, 5, d) for d in range(1, 8)]
    trip = model.Trip(name="가", start=days[0], end=days[-1],
                      stay=[model.Evidence(_receipt(tmp_path / f"b{d.day}.png", 1080, 2000, 60), d) for d in days])
    assert render.render(model.pages(trip), tmp_path / "big.pdf") == 1


def test_every_cell_is_legible_when_it_can_be(qapp, tmp_path):
    """한 쪽에 놓은 칸은 모두 글자가 MIN_TEXT 점 이상 — 짜임(_plan)과 높이 나누기(_allot)로 본다."""
    from claim_downloader.travel import render
    cache, needs = {}, {}
    block = model.Block([_receipt(tmp_path / f"c{i}.png", 1080, 1500, 34) for i in range(5)], ["일자"] * 5)
    cells = render._cells(block, cache, needs)
    width, room = 1100, 900
    plan = render._plan([cells], [["제목"]], width, room, room)
    assert sum(s.count for page in plan for s in page) == 5 and len(plan) > 1
    for page in plan:
        render._allot(page, [cells], [["제목"]], width, room)
        for slot in page:
            sub = cells[slot.start:slot.start + slot.count]
            assert render.best_grid(sub, width, slot.room_h).ratio >= 0.99


def test_map_keeps_page_width_and_goes_to_next_page(qapp, tmp_path):
    """지도 그림은 쪽 폭을 다 써도 글자가 작다 — 하이패스 아래에 줄여 넣지 않고 다음 쪽에 쪽 폭으로."""
    from claim_downloader.travel import render
    tolls = [model.Evidence(_receipt(tmp_path / f"h{i}.png", 420, 520, 14, boxed=True), date(2026, 5, 1 + i // 2), 2000) for i in range(4)]
    trip = model.Trip(name="가", start=date(2026, 5, 1), end=date(2026, 5, 2), tolls=tolls, legs=[76], fuel="휘발유",
                      route_map=_receipt(tmp_path / "map.png", 1400, 900, 13))
    out = tmp_path / "car.pdf"
    assert render.render(model.car_pages(trip), out) == 2
    texts = _pages_text(out)
    assert "하이패스4,000원" in texts[0] and "이동경로" not in texts[0]
    assert "(자차-이동경로)" in texts[1] and "총이동경로152km" in texts[1] and "연료휘발유" in texts[1]
    assert "연료" not in texts[0] and "2026년5월1일금요일,5월2일토요일" in texts[1]        # 하이패스 쪽엔 연료 없음 · 이동일자 = 하이패스 이용일자


def test_public_page_draws_route_captions_and_totals(qapp, tmp_path):
    from claim_downloader.travel import render
    tickets = [model.Evidence(_receipt(tmp_path / f"p{i}.png", 900, 600, 40), date(2026, 5, 1 + i // 2), 8000, "열차",
                              origin="춘천", goal="용산" if i % 2 == 0 else "") for i in range(3)]
    out = tmp_path / "public.pdf"
    assert render.render(model.public_pages(model.Trip(public=tickets)), out) == 1
    text = _pages_text(out)[0]
    for words in ("실비 합계 24,000원", "일자 합계 16,000원", "열차 · 춘천 → 용산 · 8,000원", "열차 · 춘천 → ? · 8,000원", "2일 · 증빙 3건"):
        assert "".join(words.split()) in text


def test_phone_photo_is_drawn_upright(qapp, tmp_path):
    """휴대폰을 옆으로 들고 찍은 영수증은 눕힌 채 저장되고 EXIF 회전 표시(6 = 90° 돌려 보라)만 붙는다 —
    QImage(경로) 는 그 표시를 무시해 출장증빙에 옆으로 누운 영수증이 들어갔다. 바로 세워 읽는지 본다."""
    pil = pytest.importorskip("PIL.Image")
    from claim_downloader.travel import render
    photo = pil.new("RGB", (400, 200), "white")
    photo.paste((30, 30, 30), (40, 40, 360, 160))    # 여백 자르기가 지우지 않게 가운데에 내용
    exif = pil.Exif()
    exif[0x0112] = 6
    path = tmp_path / "홍길동_체류증빙.jpg"
    photo.save(path, exif=exif.tobytes())
    images = render.load_images(path)
    assert len(images) == 1
    assert images[0].height() > images[0].width()
