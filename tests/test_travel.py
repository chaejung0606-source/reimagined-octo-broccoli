"""출장증빙자료 만들기(travel/) — 쪽 짜임 · 숙박 상한 · 폴더 나누기 · PDF 그리기. CLAUDE.md 28절.

가짜 그림 · 가짜 PDF 를 코드로 만든다(실제 영수증은 저장소에 두지 않는다 — 10절).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from claim_downloader.travel import model
from claim_downloader.travel.model import Evidence, Trip


def ev(name, day=None, amount=None, mode="", nights=1, place=""):
    return Evidence(Path(name), day, amount, mode, nights, place)


def test_page_order_is_stay_transport_lodging():
    trip = Trip(name="가", start=date(2026, 5, 28), end=date(2026, 5, 29),
                stay=[ev("s.png", date(2026, 5, 28))], public=[ev("t.png", date(2026, 5, 28), 8000, "열차")],
                tolls=[ev("h.png", date(2026, 5, 28), 2170)], lodging=[ev("l.png", date(2026, 5, 28), 90000)], legs=[142])
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
    pages = model.stay_pages(trip)
    assert len(pages) == 8 and pages[0].blocks[0].captions == ["2026년 5월 1일 금요일"]


def test_stay_head_has_no_amount_and_place_bar():
    """담당자 2026-10-27 그림 — 체류 증빙 머리 줄 오른쪽 칸은 비우고, 아래에 '삼척 출장 증빙' 줄."""
    trip = Trip(destination="삼척", start=date(2026, 5, 28), end=date(2026, 5, 29),
                stay=[ev("a.png", date(2026, 5, 28)), ev("b.png", date(2026, 5, 29))])
    page = model.stay_pages(trip)[0]
    assert page.head == ["* 체류 증빙", ""]
    assert [b.title for b in page.blocks] == [["삼척 출장 증빙"]]


def test_several_destinations():
    """담당자 2026-10-27 "출장지가 한군데가 아닌 경우도 있습니다" — 체류는 출장지마다 줄, 이동경로는 구간마다, 숙박 상한은 그 출장지로."""
    assert model.split_places("삼척, 강릉 → 부산광역시") == ["삼척", "강릉", "부산광역시"]
    places = ["강원 삼척시", "강원 강릉시"]
    assert model.match_place("체류/삼척/0528.png", places) == "강원 삼척시"
    assert model.match_place("체류/강원/0528.png", places) == ""          # 두 곳에 다 든 낱말로는 못 가린다
    trip = Trip(destination="삼척, 부산", start=date(2026, 5, 28), end=date(2026, 5, 30),
                stay=[ev("a.png", date(2026, 5, 28), place="삼척"), ev("c.png", date(2026, 5, 30), place="부산"),
                      ev("b.png", date(2026, 5, 29), place="삼척")],
                lodging=[ev("h1.png", date(2026, 5, 28), 90000, place="삼척"), ev("h2.png", date(2026, 5, 29), 90000, place="부산")],
                tolls=[ev("t.png", date(2026, 5, 28), 2000)], legs=[120, 300, 330])
    page = model.stay_pages(trip)[0]
    assert [(b.title, [p.name for p in b.images]) for b in page.blocks] == [(["삼척 출장 증빙"], ["a.png", "b.png"]),
                                                                          (["부산 출장 증빙"], ["c.png"])]
    route = model.car_pages(trip)[0].blocks[-1].title
    assert route == ["* 이동경로", "출발지→삼척 120km", "삼척→부산 300km", "부산→출발지 330km", "총 이동경로 750km"]
    assert [p.head[2] for p in model.lodging_pages(trip)] == ["지원금액 70,000원", "지원금액 80,000원"]   # 그 밖의 지역 · 광역시
    trip.stay.append(ev("d.png", date(2026, 5, 30)))
    assert any("어느 출장지인지" in p for p in model.problems(trip))


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
                route_map=Path("map.png"), legs=[142])
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


def test_output_path_has_trip_date_and_never_overwrites(tmp_path):
    """담당자 2026-10-27 — 파일명은 '이름 출장증빙_yy.mm.dd'(출장 시작일)."""
    first = model.output_path(tmp_path, "홍길동", date(2026, 5, 28))
    assert first.name == "홍길동 출장증빙_26.05.28.pdf"
    first.write_bytes(b"x")
    assert model.output_path(tmp_path, "홍길동", date(2026, 5, 28)).name == "홍길동 출장증빙_26.05.28_2.pdf"


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
                tolls=tolls, route_map=_image(tmp_path / "map.png", 1600, 900), legs=[142],
                lodging=[ev(str(_pdf(tmp_path / "hotel.pdf", 2)), date(2026, 5, 28), 150000, nights=2)])
    out = model.output_path(tmp_path, trip.name, trip.start)
    count = render.render(model.pages(trip), out)
    assert count == len(PdfReader(str(out)).pages)
    assert count > len(model.pages(trip))          # 하이패스 14장은 한 쪽에 안 들어가 이어진다
    text = "".join(page.extract_text() for page in PdfReader(str(out)).pages)
    for words in ("체류 증빙", "교통비 증빙 (자차)", "(계속)", "총 이동경로 284", "지원금액 140,000원"):
        assert words in text.replace("\n", " ")


def test_page_fills_origin_with_the_campus(qapp):
    """담당자 2026-10-27 — 출발지는 늘 강원대학교 춘천캠퍼스로 채워져 있다(설정 travel_origin)."""
    from claim_downloader import settings
    from claim_downloader.ui.pages.travel import TravelPage
    assert settings.Settings().travel_origin == "강원대학교 춘천캠퍼스"
    assert TravelPage().origin_edit.text() == "강원대학교 춘천캠퍼스"


def test_lodging_is_optional(qapp, tmp_path):
    """담당자 2026-10-27 — 숙박은 있을 수도 없을 수도 있다. 숙박 없이 만들 수 있고, 숙박 상한 칸은 숙박 영수증을 넣었을 때만 보인다."""
    from claim_downloader.ui.pages.travel import TravelPage
    trip = Trip(name="가", start=date(2026, 5, 28), end=date(2026, 5, 28), stay=[ev("s.png", date(2026, 5, 28))])
    assert model.blocking(trip) == [] and model.problems(trip) == []
    assert [p.head[0] for p in model.pages(trip)] == ["* 체류 증빙"]
    page = TravelPage()
    page.show()
    assert page.lodging_box.isHidden()
    receipt = _image(tmp_path / "hotel.png", 300, 400)
    page.tables["lodging"].add_files([receipt], 2026)
    assert not page.lodging_box.isHidden()
    page.tables["lodging"].clear_all()
    assert page.lodging_box.isHidden()


def test_trim_cuts_white_margins(qapp):
    """담당자 2026-10-27 — 증빙이 잘 보이게 여백을 잘라 키운다(가운데 정렬은 render._draw_cell)."""
    from PySide6.QtGui import QColor, QImage, QPainter

    from claim_downloader.travel import render
    image = QImage(1240, 1754, QImage.Format_RGB32)       # A4 쪽 위 귀퉁이에만 영수증이 있는 모양
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.fillRect(100, 120, 400, 600, QColor("#333333"))
    painter.end()
    cut = render.trim(image)
    assert 400 <= cut.width() < 500 and 600 <= cut.height() < 700
    blank = QImage(300, 300, QImage.Format_RGB32)
    blank.fill(QColor("white"))
    assert render.trim(blank).size() == blank.size()        # 내용이 없으면 그대로


def test_page_shows_place_column_and_legs_for_several_destinations(qapp, tmp_path):
    from claim_downloader.ui.pages.travel import TravelPage
    page = TravelPage()
    page.show()
    stay = page.tables["stay"]
    assert stay.isColumnHidden(2) and len(page.leg_spins) == 2
    page.dest_edit.setText("삼척, 강릉")
    assert not stay.isColumnHidden(2) and len(page.leg_spins) == 3
    (tmp_path / "삼척").mkdir()
    stay.add_files([_image(tmp_path / "삼척" / "0528.png", 300, 400)], 2026)
    assert page.trip().stay[0].place == "삼척"
    page.leg_spins[0].setValue(100)
    page.leg_spins[1].setValue(50)
    page.leg_spins[2].setValue(120)
    assert page.total_label.text() == "총 이동경로 270km"
