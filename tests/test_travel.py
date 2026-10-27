"""출장증빙자료 만들기(travel/) — 쪽 짜임 · 숙박 상한 · 폴더 나누기 · PDF 그리기. CLAUDE.md 28절.

가짜 그림 · 가짜 PDF 를 코드로 만든다(실제 영수증은 저장소에 두지 않는다 — 10절).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from claim_downloader.travel import model
from claim_downloader.travel.model import Evidence, Trip


def ev(name, day=None, amount=None, mode="", nights=1):
    return Evidence(Path(name), day, amount, mode, nights)


def test_page_order_is_stay_transport_lodging():
    trip = Trip(name="가", start=date(2026, 5, 28), end=date(2026, 5, 29),
                stay=[ev("s.png", date(2026, 5, 28))], public=[ev("t.png", date(2026, 5, 28), 8000, "열차")],
                tolls=[ev("h.png", date(2026, 5, 28), 2170)], lodging=[ev("l.png", date(2026, 5, 28), 90000)], km_go=142)
    heads = [p.head[0] for p in model.pages(trip)]
    assert heads == ["* 체류 증빙", "* 교통비 증빙 (열차)", "* 교통비 증빙 (자차)", "* 숙박비 증빙"]


def test_stay_one_page_up_to_seven_days_then_page_per_day():
    days = [date(2026, 5, d) for d in range(1, 8)]
    trip = Trip(start=days[0], end=days[-1], stay=[ev(f"{d.day}.png", d) for d in days])
    pages = model.stay_pages(trip)
    assert len(pages) == 1 and len(pages[0].blocks[0].images) == 7 and pages[0].blocks[0].fill
    assert pages[0].blocks[0].captions[0] == "2026년 5월 1일 금요일"
    trip.end = date(2026, 5, 8)
    trip.stay.append(ev("8.png", date(2026, 5, 8)))
    assert len(model.stay_pages(trip)) == 8


def test_public_splits_by_day_and_mode_in_travel_order():
    d = date(2026, 5, 28)
    trip = Trip(public=[ev("a.png", d, 8000, "열차"), ev("b.png", d, 5000, "고속버스"), ev("c.png", d, 1000, "열차"),
                        ev("d.png", date(2026, 5, 29), 5000, "고속버스")])
    pages = model.public_pages(trip)
    assert [(p.head[0], p.head[2]) for p in pages] == [("* 교통비 증빙 (열차)", "9,000원"), ("* 교통비 증빙 (고속버스)", "5,000원"),
                                                      ("* 교통비 증빙 (고속버스)", "5,000원")]
    assert pages[0].head[1] == "2026년 5월 28일 목요일"


def test_toll_amounts_by_use_date_and_route():
    trip = Trip(tolls=[ev("1.png", date(2026, 5, 28), 2170), ev("2.png", date(2026, 5, 28), 2800), ev("3.png", date(2026, 5, 29), 1820)],
                route_map=Path("map.png"), km_go=142)
    page = model.car_pages(trip)[0]
    assert page.head == ["* 교통비 증빙 (자차)", "6,790원"]
    assert [b.title for b in page.blocks] == [["2026년 5월 28일 목요일", "하이패스 4,970원"], ["2026년 5월 29일 금요일", "하이패스 1,820원"],
                                              ["* 이동경로", "출발지→도착지 142km", "도착지→출발지 142km", "총 이동경로 284km"]]


def test_lodging_cap_by_region_nights_and_people():
    assert model.lodging_region("서울 중구") == "서울특별시"
    assert model.lodging_region("부산광역시 해운대구") == "광역시"
    assert model.lodging_region("강원 평창군") == "그 밖의 지역"
    trip = Trip(destination="강원 평창군", lodging=[ev("h.pdf", date(2026, 5, 28), 150000, nights=2)])
    page = model.lodging_pages(trip)[0]
    assert page.head == ["* 숙박비 증빙", "숙박기간 2026년 5월 28일 ~ 5월 30일(2박)", "지원금액 140,000원"]
    assert "상한금액으로 지원" in page.notes[0]
    trip.people = 2                                # 공동숙박 — 상한 × 인원
    assert model.lodging_pages(trip)[0].head[2] == "지원금액 150,000원" and not model.lodging_pages(trip)[0].notes
    trip.people, trip.lodging_cap = 1, 100_000     # 화면에서 고친 1박 상한
    assert model.lodging_pages(trip)[0].head[2] == "지원금액 150,000원"


def test_guess_from_file_name():
    got = model.guess(Path("0528 KTX 8,000원.png"), 2026)
    assert (got.day, got.amount) == (date(2026, 5, 28), 8000)
    assert model.guess(Path("2026-05-29 영수증.jpg"), 2025).day == date(2026, 5, 29)
    assert model.guess(Path("영수증.jpg"), 2026).day is None
    assert model.mode_of("KTX 승차권") == "열차" and model.mode_of("고속버스표") == "고속버스"


def test_problems_block_only_name_and_empty():
    trip = Trip(public=[ev("a.png")])
    assert model.blocking(trip) == ["출장자 이름을 넣어 주세요."]
    probs = model.problems(trip)
    assert any("일자가 없습니다" in p for p in probs) and any("이동편" in p for p in probs)
    assert model.blocking(Trip(name="가")) == ["증빙 파일이 하나도 없습니다."]


def test_scan_folder_sorts_by_item_and_skips_others(tmp_path):
    for rel in ("체류/0528.png", "교통비/하이패스/0528.png", "교통비/KTX 0528.pdf", "숙박/호텔.pdf", "경로 지도.png",
                "국내 출장신청서(0528).pdf", "홍길동 출장증빙.pdf", "기타.png"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    scan = model.scan_folder(tmp_path)
    names = {k: [p.name for p in v] for k, v in scan.files.items()}
    assert names == {"stay": ["0528.png"], "public": ["KTX 0528.pdf"], "toll": ["0528.png"], "lodging": ["호텔.pdf"]}
    assert scan.route_map.name == "경로 지도.png"
    assert [p.name for p in scan.unsorted] == ["기타.png"]


def test_output_path_never_overwrites(tmp_path):
    first = model.output_path(tmp_path, "홍길동")
    assert first.name == "홍길동 출장증빙.pdf"
    first.write_bytes(b"x")
    assert model.output_path(tmp_path, "홍길동").name == "홍길동 출장증빙_2.pdf"


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:      # 화면 라이브러리가 없는 곳
        pytest.skip(str(exc))
    return QApplication.instance() or QApplication([])


def _image(path: Path, w: int, h: int) -> Path:
    from PySide6.QtGui import QColor, QImage
    image = QImage(w, h, QImage.Format_RGB32)
    image.fill(QColor("white"))
    image.save(str(path))
    return path


def _pdf(path: Path, pages: int) -> Path:
    from PySide6.QtGui import QPainter, QPdfWriter
    writer = QPdfWriter(str(path))
    painter = QPainter(writer)
    for i in range(pages):
        if i:
            writer.newPage()
        painter.drawText(100, 100, f"page {i}")
    painter.end()
    return path


def test_render_makes_pdf_and_continues_long_toll_pages(qapp, tmp_path):
    from pypdf import PdfReader

    from claim_downloader.travel import render
    tolls = [ev(str(_image(tmp_path / f"h{i}.png", 400, 520)), date(2026, 5, 28 + i % 3), 2000) for i in range(14)]
    trip = Trip(name="홍길동", start=date(2026, 5, 28), end=date(2026, 5, 30),
                stay=[ev(str(_image(tmp_path / f"s{i}.png", 600, 900)), date(2026, 5, 28 + i)) for i in range(3)],
                tolls=tolls, route_map=_image(tmp_path / "map.png", 1600, 900), km_go=142,
                lodging=[ev(str(_pdf(tmp_path / "hotel.pdf", 2)), date(2026, 5, 28), 150000, nights=2)])
    out = model.output_path(tmp_path, trip.name)
    count = render.render(model.pages(trip), out)
    assert count == len(PdfReader(str(out)).pages)
    assert count > len(model.pages(trip))          # 하이패스 14장은 한 쪽에 안 들어가 이어진다
    text = "".join(page.extract_text() for page in PdfReader(str(out)).pages)
    for words in ("체류 증빙", "교통비 증빙 (자차)", "(계속)", "총 이동경로 284", "지원금액 140,000원"):
        assert words in text.replace("\n", " ")
