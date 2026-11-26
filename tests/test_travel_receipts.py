"""출장증빙 — 한 파일에 든 영수증 여러 장을 일자별로(담당자 2026-11-23, CLAUDE.md 28절).

KTX 영수증 둘(10월 28일 · 29일)이 나란히 든 파일 하나가 '2026년 11월 2일'(맨 아래 발행일시) 한 칸으로 묶여 '출장기간 밖' 이었다 —
"교통비나 체류 증빙 영수증을 일자별로 구분해주세요. 제가 일자별로 영수증을 구분해서 알려주지 않아도 일자별로 구분해서 검토해주세요".
값(역 · 금액 · 번호)은 모두 지어낸 것이다.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from claim_downloader.travel import model

TWO_TICKETS = """영수증(고객용) KORAIL
NO 00000-1021-00000-36
2026년 10월 28일(수) KTX-산천 519 일반실
가나 14:08 → 다라엑스포 17:20
어른 1매, 어린이 0매 할인 : 0
계좌이체 결제
승인일시 20261021
승인번호 11112222333
결제금액 44,500원
발행일시 2026년 11월 02일 14:50:46
영수증(고객용) KORAIL
NO 00000-1022-00000-62
2026년 10월 29일(목) KTX-산천 668 일반실
다라엑스포 18:39 → 마바 21:44
승인일시 20261022
승인번호 44445555666
결제금액 36,900원
발행일시 2026년 11월 02일 14:50:46
"""
ONE_TICKET = TWO_TICKETS.split("영수증(고객용) KORAIL\nNO 00000-1022")[0]


def test_receipt_days_skip_the_issue_date_and_the_booking_date():
    """발행일시(11월 2일)는 이용일이 아니고, 승차권의 승인일시(10월 21일)도 아니다 — 승차일만."""
    assert model.receipt_days(TWO_TICKETS, route=True) == [date(2026, 10, 28), date(2026, 10, 29)]
    assert model.receipt_days(ONE_TICKET, route=True) == [date(2026, 10, 28)]
    assert model.receipt_days("발행일시 2026년 11월 02일 14:50", route=True) == []
    # 카드 영수증(체류)은 승인일이 쓴 날
    assert model.receipt_days("거래 승인일시 2026-10-28 12:30\n인쇄일 2026-11-02") == [date(2026, 10, 28)]
    # 승차권에 승인일만 보이면 그것(택시 카드 영수증)
    assert model.receipt_days("택시 승인일시 2026-10-28 23:10", route=True) == [date(2026, 10, 28)]


def test_guess_leaves_a_file_with_two_tickets_for_the_ai_to_split(monkeypatch):
    texts = {"두 장.pdf": TWO_TICKETS, "한 장.pdf": ONE_TICKET,
             "숙박.pdf": "입실 2026-10-28 퇴실 2026-10-29\n결제금액 150,000원\n발행일 2026-11-02",
             "발행만.pdf": "발행일시 2026년 11월 02일\n결제금액 8,400원"}
    monkeypatch.setattr(model, "pdf_text", lambda path, pages=2: texts[path.name])
    two = model.guess(Path("x/두 장.pdf"), 2026, route=True)
    # 하나를 고르지 않는다 — 전에는 일자 11월 2일 · 금액 44,500(두 장 중 큰 것)이 들어갔다
    assert (two.day, two.amount, two.origin, two.receipt_key, two.several) == (None, None, "", "", True)
    one = model.guess(Path("x/한 장.pdf"), 2026, route=True)
    assert (one.day, one.amount, one.several) == (date(2026, 10, 28), 44500, False)
    stay = model.guess(Path("x/두 장.pdf"), 2026, stay=True)
    assert stay.several and stay.day is None
    # 숙박은 여러 날이 한 영수증(입실 · 퇴실) — 입실일 · 금액 그대로
    lodging = model.guess(Path("x/숙박.pdf"), 2026)
    assert (lodging.day, lodging.amount, lodging.several) == (date(2026, 10, 28), 150000, False)
    assert model.guess(Path("x/발행만.pdf"), 2026, route=True).day is None      # 발행일을 이용일로 넣지 않는다


def test_parts_of_one_file_are_named_and_not_taken_for_duplicates():
    path = Path("x/홍길동_체류 증빙.png")
    Evidence = model.Evidence
    trip = model.Trip(name="홍길동", start=date(2026, 10, 28), end=date(2026, 10, 29), destination="가나시",
                      stay=[Evidence(path=path, day=date(2026, 10, 28), part=0, pieces=2, receipt_key="111111"),
                            Evidence(path=path, day=date(2026, 10, 28), part=1, pieces=2, receipt_key="222222")])
    # 한 파일의 두 영수증은 '같은 날 두 번 넣음' 이 아니다
    assert not any("같은 날" in note for note in model.review(trip))
    assert model.receipt_name(trip.stay[1]) == "홍길동_체류 증빙.png (2번째 영수증)"
    # 같은 영수증이 따로 든 파일이 있으면 그 파일을 남긴다(그 영수증만 보인다)
    alone = Evidence(path=Path("x/홍길동_체류 증빙1.pdf"), day=date(2026, 10, 28), receipt_key="111111")
    trip.stay.append(alone)
    model.dedupe(trip)
    assert [e.part for e in trip.stay] == [1, None] and trip.dropped[0][1].part == 0


# ── 그림 나누기 ─────────────────────────────────────────────────────────
@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:      # 화면 라이브러리가 없는 곳
        pytest.skip(str(exc))
    return QApplication.instance() or QApplication([])


def _cards(path: Path, cards: list[list[str]], side: bool = True, footer: str = "", marks: tuple = (),
           bg: str = "white", border: str = "#cfcfcf") -> Path:
    """승차권 영수증을 본뜬 그림 — 옅은 회색 테두리의 카드(위 · 아래 테두리는 없음)를 나란히(또는 위아래로), 아래에 두 장에 걸친 안내 글 한 줄.
    marks 의 카드에는 빨간 네모(어느 조각인지 보려고)."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
    cw, ch, gap = 300, 420, 30
    w = 40 + (cw * len(cards) + gap * (len(cards) - 1) if side else cw)
    h = 40 + (ch if side else ch * len(cards) + gap * (len(cards) - 1)) + (60 if footer else 0)
    image = QImage(w, h, QImage.Format_RGB32)
    image.fill(QColor(bg))
    p = QPainter(image)
    p.setFont(QFont("Sans", 11))
    for i, lines in enumerate(cards):
        x, y = (20 + i * (cw + gap), 20) if side else (20, 20 + i * (ch + gap))
        p.setPen(QPen(QColor(border), 2))
        p.drawLine(x, y, x, y + ch)                      # 옆 테두리만
        p.drawLine(x + cw, y, x + cw, y + ch)
        p.setPen(QPen(QColor("#222222"), 1))
        for j, line in enumerate(lines):
            p.drawText(x + 18, y + 40 + j * 34, line)
            if j % 3 == 2:
                p.setPen(QPen(QColor("#888888"), 1))
                for k in range(x + 18, x + cw - 18, 6):  # 점선
                    p.drawPoint(k, y + 52 + j * 34)
                p.setPen(QPen(QColor("#222222"), 1))
        if i in marks:
            p.fillRect(QRect(x + cw - 60, y + ch - 60, 30, 30), QColor("red"))
    if footer:
        p.setPen(QPen(QColor("#222222"), 1))
        p.drawText(30, h - 30, footer)
    p.end()
    image.save(str(path))
    return path


CARD_A = ["영수증(고객용)", "2026년 10월 28일(수) KTX 519", "가나 14:08 → 다라 17:20", "어른 1매", "결제금액 44,500원", "발행일시 2026년 11월 02일"]
CARD_B = ["영수증(고객용)", "2026년 10월 29일(목) KTX 668", "다라 18:39 → 마바 21:44", "어른 1매", "결제금액 36,900원", "발행일시 2026년 11월 02일"]
FOOTER = "* 본 영수증은 세금계산서로 사용하실 수 없으며, 고속철도는 부가가치세가 포함되어 있습니다."


def _reds(image) -> int:
    from PySide6.QtGui import QColor
    small = image.scaledToWidth(min(200, image.width()))
    return sum(1 for y in range(small.height()) for x in range(small.width())
               if (lambda c: c.red() > 200 and c.green() < 80 and c.blue() < 80)(QColor(small.pixel(x, y))))


def test_two_receipts_side_by_side_are_cut_apart(qapp, tmp_path):
    """나란히 놓인 두 장 — 아래에 두 장에 걸친 안내 글이 있어도 영수증 사이의 빈 띠로 나눈다(왼쪽부터 — AI 가 읽는 차례)."""
    from claim_downloader.travel import render
    path = _cards(tmp_path / "두 장.png", [CARD_A, CARD_B], footer=FOOTER, marks=(1,))
    pieces = render.receipt_pieces(path, 2)
    assert len(pieces) == 2
    full = render._load(path)[0]
    assert all(piece.width() < 0.6 * full.width() for piece in pieces)
    assert _reds(pieces[0]) == 0 and _reds(pieces[1]) > 0              # 빨간 네모는 오른쪽(둘째) 카드에만
    assert all(piece.height() < full.height() - 50 for piece in pieces)     # 두 장에 걸친 아래 안내 글(60점 띠)은 빼고
    assert render.receipt_pieces(path, 3) == []                         # 셋으로는 못 나눈다 — 칸에는 파일 전체
    # 한 장뿐인 영수증을 둘로 자르지 않는다(줄 사이로 자르지 않게)
    one = _cards(tmp_path / "한 장.png", [CARD_A], footer=FOOTER)
    assert render.receipt_pieces(one, 2) == []


def test_faint_cards_on_a_tinted_background_with_a_footer_are_cut_apart(qapp, tmp_path):
    """옅은 바탕에 바탕과 거의 같은 색의 카드 테두리(담당자 그림 2026-11-23 — 테두리가 내용으로 안 잡혀 줄마다 따로 덩어리) + 두 장에 걸친 안내 글.
    영수증 사이의 칸은 거의 모든 줄에서 비어 있다 — 그 칸으로 자르고, 아래 안내 글은 조각에 넣지 않는다."""
    from claim_downloader.travel import render
    path = _cards(tmp_path / "옅은.png", [CARD_A, CARD_B], footer=FOOTER, marks=(1,), bg="#e8e3d8", border="#dad5ca")
    pieces = render.receipt_pieces(path, 2)
    assert len(pieces) == 2 and _reds(pieces[0]) == 0 and _reds(pieces[1]) > 0
    full = render._load(path)[0]
    assert all(piece.height() < full.height() - 50 for piece in pieces)       # 아래 안내 글(60점 띠)은 빠졌다


def test_two_receipts_stacked_are_cut_top_to_bottom(qapp, tmp_path):
    from claim_downloader.travel import render
    path = _cards(tmp_path / "위아래.png", [CARD_A, CARD_B], side=False, marks=(0,))
    pieces = render.receipt_pieces(path, 2)
    assert len(pieces) == 2 and _reds(pieces[0]) > 0 and _reds(pieces[1]) == 0
    full = render._load(path)[0]
    assert all(piece.height() < 0.6 * full.height() for piece in pieces)


def _ticket_pdf(path: Path, pages: list[list[str]]) -> Path:
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QFont, QPageSize, QPainter, QPdfWriter
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(150)
    p = QPainter(writer)
    p.setFont(QFont("Sans", 10))
    for i, lines in enumerate(pages):
        if i:
            writer.newPage()
        p.drawRect(QRectF(100, 100, 700, 600))
        for j, line in enumerate(lines):
            p.drawText(QRectF(130, 130 + j * 60, 640, 50), line)
    p.end()
    return path


def test_a_pdf_with_one_ticket_per_page_is_split_by_page_without_ai(qapp, tmp_path):
    """쪽마다 승차권 하나인 PDF — 글자로 쪽마다 줄을 만든다(AI 없이). 그림은 쪽마다."""
    pytest.importorskip("pypdf")
    from claim_downloader.travel import render
    from claim_downloader.ui.pages import travel as travel_page
    path = _ticket_pdf(tmp_path / "홍길동_대중교통 증빙 KTX.pdf", [
        ["2026년 10월 28일 KTX", "가나 → 다라", "결제금액 44,500원", "발행일시 2026년 11월 02일"],
        ["2026년 10월 29일 KTX", "다라 → 마바", "결제금액 36,900원", "발행일시 2026년 11월 02일"]])
    rows = model.page_receipts(path, route=True)
    assert [(e.day, e.amount, e.origin, e.goal, e.part, e.pieces) for e in rows] == [
        (date(2026, 10, 28), 44500, "가나", "다라", 0, 2), (date(2026, 10, 29), 36900, "다라", "마바", 1, 2)]
    table = travel_page.EvidenceTable(model.PUBLIC)
    table.add_files([path], 2026)
    assert table.parts == [0, 1] and [table.item(r, 1).text() for r in range(2)] == ["2026-10-28", "2026-10-29"]
    assert table.item(0, 3).text() == "열차" and table.ai_wanted() == []
    assert len(render.receipt_pieces(path, 2)) == 2
    # 같은 날 · 승인번호 모름인 두 쪽은 한 영수증일 수 있다 — 나누지 않는다
    same = _ticket_pdf(tmp_path / "같은 날.pdf", [["2026년 10월 28일 KTX", "결제금액 44,500원"], ["2026년 10월 28일 약관"]])
    assert model.page_receipts(same, route=True) == []


def _read(*receipts) -> dict:
    keys = ("date", "amount", "mode", "origin", "goal", "address", "approvalNo")
    return {"receipts": [dict(zip(keys, r)) | {"nights": None} for r in receipts]}


def test_public_file_with_two_tickets_is_split_per_date_after_ai(qapp, tmp_path, monkeypatch):
    """AI 가 두 장을 읽으면 영수증마다 한 줄 — 일자 · 금액 · 이동편 · 출발지 · 목적지도 영수증마다, 쪽에서는 일자마다 묶음, 그림은 그 영수증만."""
    from claim_downloader.travel import ai_read, render
    from claim_downloader.ui.pages import travel as travel_page
    path = _cards(tmp_path / "홍길동_대중교통 증빙.png", [CARD_A, CARD_B], footer=FOOTER, marks=(1,))
    table = travel_page.EvidenceTable(model.PUBLIC)
    table.add_files([path], 2026)
    assert table.ai_wanted() == [path]
    found = ai_read.summary(model.PUBLIC, _read(("2026-10-28", 44500, "열차", "가나", "다라", "", "11112222333"),
                                                ("2026-10-29", 36900, "열차", "다라", "마바", "", "44445555666")))
    assert table.apply_ai(path, found) == 10
    rows = [[table.item(r, c).text() for c in range(6)] for r in range(table.rowCount())]
    assert [row[1:] for row in rows] == [["2026-10-28", "44,500", "열차", "가나", "다라"], ["2026-10-29", "36,900", "열차", "다라", "마바"]]
    assert rows[1][0].endswith("(2번째 영수증)") and table.pieces == [2, 2] and table.ai_wanted() == []
    trip = model.Trip(name="홍길동", start=date(2026, 10, 28), end=date(2026, 10, 29), public=table.evidence(2026))
    assert not any(model.unclear(trip, model.PUBLIC, e) for e in trip.public)
    page = model.public_pages(trip)[0]
    assert [b.title for b in page.blocks[:2]] == [["2026년 10월 28일 수요일", "증빙 1건", "일자 합계 44,500원"],
                                                  ["2026년 10월 29일 목요일", "증빙 1건", "일자 합계 36,900원"]]
    assert page.head == ["* 교통비 증빙 (대중교통)", "실비 합계 81,400원"]
    first, second = (render._cells(b, {}, {}) for b in page.blocks[:2])
    assert len(first) == len(second) == 1
    assert _reds(first[0].image) == 0 and _reds(second[0].image) > 0      # 일자마다 그 영수증만
    # 같은 파일을 다시 읽어도(캐시) 같게 나눈다
    table.clear_all()
    table.add_files([path], 2026)
    assert table.apply_ai(path, found) == 10 and table.rowCount() == 2


def test_stay_file_with_two_receipts_is_split_with_their_shop_regions(qapp, tmp_path):
    from claim_downloader.travel import ai_read
    from claim_downloader.ui.pages import travel as travel_page
    path = _cards(tmp_path / "홍길동_체류 증빙.png", [CARD_A, CARD_B])
    table = travel_page.EvidenceTable(model.STAY)
    table.add_files([path], 2026)
    found = ai_read.summary(model.STAY, _read(("2026-10-28", 9000, "", "", "", "강원 원주시 가나로 1", "1234567"),
                                              ("2026-10-29", 12000, "", "", "", "강원 원주시 다라로 2", "7654321")))
    assert table.apply_ai(path, found) == 4
    assert [(table.item(r, 1).text(), table.item(r, travel_page.SHOP_COL).text()) for r in range(2)] == [
        ("2026-10-28", "원주"), ("2026-10-29", "원주")]
    trip = model.Trip(name="홍길동", start=date(2026, 10, 28), end=date(2026, 10, 29), destination="원주시청", stay=table.evidence(2026))
    block = model.stay_pages(trip)[0].blocks[0]
    assert block.parts == [0, 1] and block.pieces == [2, 2]
    assert block.captions == ["2026년 10월 28일 수요일", "2026년 10월 29일 목요일"]


def _slips(path: Path, slips: list[list[tuple[str, str]]], marks: tuple = ()) -> Path:
    """카드 매출전표를 본뜬 그림(담당자 2026-11-24 우리카드 매출전표 둘) — 위에 두 장에 걸친 로고 · 출력 시각 줄과 밑줄, 장마다 제목 ·
    칸마다 테두리 친 표(이름 칸은 옅은 파랑) · 양옆에 동그라미(연속 용지 구멍). 값은 지어낸 것."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
    cw, gap, top, row = 330, 70, 90, 30
    w = 40 + cw * len(slips) + gap * (len(slips) - 1)
    h = top + 60 + row * max(len(s) for s in slips) + 30
    image = QImage(w, h, QImage.Format_RGB32)
    image.fill(QColor("white"))
    p = QPainter(image)
    p.setFont(QFont("Sans", 13, QFont.Bold))
    p.setPen(QColor("#1d4f9a"))
    p.drawText(30, 40, "가나카드")
    p.setFont(QFont("Sans", 10))
    p.setPen(QColor("#333333"))
    p.drawText(w - 200, 40, "2026.11.11 20:00:43")
    p.setPen(QPen(QColor("#999999"), 1))
    p.drawLine(20, 55, w - 20, 55)
    for i, lines in enumerate(slips):
        x = 20 + i * (cw + gap)
        p.setPen(QPen(QColor("#dddddd"), 1))
        for y in range(top - 20, h - 20, 18):                 # 양옆 구멍
            p.drawEllipse(x - 12, y, 9, 9)
            p.drawEllipse(x + cw + 3, y, 9, 9)
        p.setPen(QColor("#1d4f9a"))
        p.setFont(QFont("Sans", 11, QFont.Bold))
        p.drawText(x + 90, top, "가나카드 매출전표")
        p.setFont(QFont("Sans", 9))
        for j, (label, value) in enumerate(lines):
            y = top + 20 + j * row
            p.fillRect(QRect(x + 20, y, 80, row), QColor("#eef2fa"))
            p.setPen(QPen(QColor("#b8c4dd"), 1))
            p.drawRect(x + 20, y, 80, row)
            p.drawRect(x + 100, y, cw - 120, row)
            p.setPen(QColor("#222222"))
            p.drawText(x + 26, y + 20, label)
            p.drawText(x + 106, y + 20, value)
        if i in marks:
            p.fillRect(QRect(x + cw - 70, top + 20 + 4 * row + 5, 20, 20), QColor("red"))
    p.end()
    image.save(str(path))
    return path


SLIP_A = [("카드종류", ""), ("카드번호", "1234-****-****-5678"), ("거래일시", "2026/11/04 12:32:52"), ("결제방법", "체크계좌"),
          ("거래금액", "19,000 원"), ("부 가 세", "1,727 원"), ("봉 사 료", "0 원"), ("승인번호", "11112222"), ("가맹점명", "가나식당"),
          ("가맹점주소", "서울 가나구 가나로 1"), ("가맹점번호", "123456789"), ("사업자번호", "123-45-67890"), ("연 락 처", "02 000 0000")]
SLIP_B = [(a, b.replace("2026/11/04 12:32:52", "2026/11/03 12:37:14").replace("19,000", "24,000").replace("11112222", "33334444")
           .replace("가나식당", "다라식당")) for a, b in SLIP_A]


def test_card_slips_in_tables_are_cut_per_slip_not_per_table_cell(qapp, tmp_path):
    """담당자 2026-11-24: 매출전표 둘(11월 4일 · 3일)이 나란히 든 그림 — 표의 칸마다 테두리가 있어 하이패스 영수증 상자(frames)로 값 칸 몇 개만
    오려 냈다(승인번호 ~ 가맹점번호). 상자 안에 글이 적으면 영수증 상자가 아니다 — 영수증 사이의 빈 띠로 장마다 오린다."""
    from claim_downloader.travel import render
    path = _slips(tmp_path / "매출전표 둘.png", [SLIP_A, SLIP_B], marks=(1,))
    image = render._load(path)[0]
    assert render.frames(image) and render.receipt_frames(image) == []
    pieces = render.receipt_pieces(path, 2)
    assert len(pieces) == 2 and _reds(pieces[0]) == 0 and _reds(pieces[1]) > 0
    assert all(0.35 * image.width() < piece.width() < 0.6 * image.width() and piece.height() > 0.75 * image.height() for piece in pieces)


def test_hipass_print_boxes_are_still_receipt_frames(qapp, tmp_path):
    """하이패스 인쇄(상자 밖은 인쇄 시각 · '총 N 건' · 주소 몇 줄)는 그대로 상자마다 — 한 장 · 두 장."""
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

    from claim_downloader.travel import render
    for n in (1, 2):
        image = QImage(1240, 1754, QImage.Format_RGB32)
        image.fill(QColor("white"))
        p = QPainter(image)
        p.setFont(QFont("Sans", 12))
        p.drawText(60, 60, "2026. 10. 30. 오후 3:12   하이패스 영수증 출력")
        p.setPen(QPen(QColor("black"), 2))
        for i in range(n):
            x = 60 + i * 270
            p.drawRect(x, 200, 270, 360)
            for j, line in enumerate(["하이패스는", "영수증", "가나도로공사 가나영업소", "2026년10월30일 14시57분", "입구영업소 : 다라", "1 종  12,800원(카드)"]):
                p.drawText(x + 20, 240 + j * 40, line)
        p.drawText(60, 640, f"총 {n} 건 / 12,800 원")
        p.drawText(60, 690, "가나도 가나시 가나로 123 가나도로공사")
        p.end()
        assert len(render.receipt_frames(image)) == n


def test_picture_with_filled_cells_is_still_read_and_split(qapp, tmp_path, isolated_home, monkeypatch):
    """파일 이름의 차례 번호(일자) · 지역(가맹점 지역)으로 칸이 다 찬 그림도 AI 가 한 번 본다 — 한 장에 두 날의 매출전표가 있으면 날마다 줄.
    전에는 빈 칸이 없어 AI 에 맡기지 않아 두 장이 첫날 한 칸으로 들어갔다(담당자 2026-11-24 '체류 증빙이 없는 날: 11월 4일')."""
    import time

    from claim_downloader.travel import ai_read
    from claim_downloader.ui.pages import travel as travel_page
    from test_travel_people import FakeWorker
    folder = tmp_path / "출장비 지급(26.11.03-04. 서울)"
    folder.mkdir()
    (folder / "국내 출장신청서.txt").write_text(
        "출장자 연구원 홍길동\n출장기간 2026. 11. 3.(화) ~ 2026. 11. 4.(수)\n출장지 서울 가나협회\n", encoding="utf-8")
    path = _slips(folder / "홍길동_서울 체류 증빙1.png", [SLIP_A, SLIP_B], marks=(1,))
    assert model.guess(path, 2026, stay=True).scanned and not model.guess(path, 2026).several
    read = _read(("2026-11-04", 19000, "", "", "", "서울 가나구 가나로 1", "11112222"),
                 ("2026-11-03", 24000, "", "", "", "서울 가나구 가나로 1", "33334444"))
    calls = []
    qapp.processEvents()

    def fake_read(files):
        files = [(p, k) for p, k in files if Path(p).is_relative_to(folder)]
        calls.extend(Path(p).name for p, _ in files)
        return {p: read for p, _ in files}
    monkeypatch.setattr(ai_read, "find_claude", lambda: "claude")
    monkeypatch.setattr(ai_read, "read", fake_read)
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.show()
    page.load_folder(str(folder))
    page._go("files")
    stay = page.tables[model.STAY]
    for _ in range(200):
        qapp.processEvents()
        if calls and not page._ai_running:
            break
        time.sleep(0.02)
    qapp.processEvents()
    assert calls == ["홍길동_서울 체류 증빙1.png"]
    assert [(stay.item(r, 1).text(), stay.parts[r]) for r in range(stay.rowCount())] == [("2026-11-04", 0), ("2026-11-03", 1)]
    trip = page.trips()[0]
    assert not any("체류 증빙이 없는 날" in n for n in model.review(trip))
    block = model.stay_pages(trip)[0].blocks[0]
    assert block.captions == ["2026년 11월 3일 화요일", "2026년 11월 4일 수요일"]
    from claim_downloader.travel import render
    cells = render._cells(block, {}, {})
    assert len(cells) == 2 and _reds(cells[0].image) > 0 and _reds(cells[1].image) == 0     # 11월 3일 칸에는 오른쪽(둘째) 전표만
    # 다시 열면 캐시로 — 다시 읽지 않는다
    page._reload(str(folder))
    for _ in range(5):
        qapp.processEvents()
    assert calls == ["홍길동_서울 체류 증빙1.png"] and stay.rowCount() == 2


def test_single_read_of_a_two_slip_picture_by_an_older_version_is_read_again_once(qapp, tmp_path, isolated_home, monkeypatch):
    """전 판의 AI 가 한 장으로 읽어 둔(캐시) 그림이 영수증 둘로 오려지면 한 번 다시 읽는다 — 새 판으로 읽은 것은 다시 읽지 않는다."""
    import json

    from claim_downloader.travel import ai_read
    from claim_downloader.ui.pages import travel as travel_page
    two = _slips(tmp_path / "홍길동_체류 증빙.png", [SLIP_A, SLIP_B])
    one = _slips(tmp_path / "홍길동_체류 증빙2.png", [SLIP_A])
    single = _read(("2026-11-03", 24000, "", "", "", "서울 가나구 가나로 1", "33334444"))
    ai_read.remember({str(two): single, str(one): single})
    data = json.loads(ai_read.cache_path().read_text(encoding="utf-8"))
    for entry in data["items"].values():
        entry["v"] = 2
    ai_read.cache_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    table = travel_page.EvidenceTable(model.STAY)
    table.add_files([two, one], 2026)
    assert table.one_of_two(two, single) and not table.one_of_two(one, single)
    ai_read.remember({str(two): single})                        # 새 판으로 다시 읽었는데도 한 장이면 그대로
    assert not table.one_of_two(two, single)
    assert "나란히(또는 위아래로) 여러 장" in ai_read.build_prompt([(str(two), model.STAY)], "x.json")


def test_a_slip_whose_date_the_ai_could_not_read_gets_its_own_row(qapp, tmp_path):
    """AI 가 두 장 중 하나의 일자를 못 읽어도 줄은 나눈다 — 그 줄은 일자 칸이 비어 '확인 필요'(파일 이름 끝의 번호는 일자가 아니다).
    전에는 한 줄로 두고 읽은 날 하나만 적어 다른 날의 영수증이 숨었다."""
    from claim_downloader.travel import ai_read
    from claim_downloader.ui.pages import travel as travel_page
    path = _slips(tmp_path / "홍길동_체류 증빙1.png", [SLIP_A, SLIP_B])
    table = travel_page.EvidenceTable(model.STAY)
    table.period_of = lambda person: (date(2026, 11, 3), date(2026, 11, 4))
    table.add_files([path], 2026)
    assert table.apply_dates() == 0 and table.item(0, 1).text() == ""               # 이름 끝 번호 1 은 첫날이 아니다
    notes = []
    table.note = notes.append
    found = ai_read.summary(model.STAY, _read(("", 19000, "", "", "", "서울 가나구 가나로 1", "11112222"),
                                              ("2026-11-03", 24000, "", "", "", "서울 가나구 가나로 1", "33334444")))
    table.apply_ai(path, found)
    table.apply_dates()
    assert [(table.item(r, 1).text(), table.parts[r]) for r in range(2)] == [("", 0), ("2026-11-03", 1)]
    assert notes and "2줄로 나눴습니다" in notes[0] and "일자를 못 읽은 영수증 1장" in notes[0] and "11112222" not in notes[0]
    trip = model.Trip(name="홍길동", start=date(2026, 11, 3), end=date(2026, 11, 4), destination="서울 가나협회", stay=table.evidence(2026))
    assert model.unclear(trip, model.STAY, trip.stay[0])


def test_a_typed_date_equal_to_the_ai_dates_still_splits(qapp, tmp_path):
    """사람이 AI 보다 먼저 같은 일자 · 합계를 적어 둔 하이패스 두 장도 나눈다 — 나눠도 사람이 적은 값이 바뀌지 않는다(2026-11-25 담당자 기록:
    '일자를 직접 적은 줄이라 나누지 않았습니다'). 다른 일자 · 다른 합계를 적었으면 전처럼 두고."""
    from claim_downloader.travel import ai_read
    from claim_downloader.ui.pages import travel as travel_page
    path = _cards(tmp_path / "홍길동_하이패스 증빙.png", [CARD_A, CARD_A])
    found = ai_read.summary(model.TOLL, _read(("2026-10-29", 4100, "", "", "", "", ""), ("2026-10-29", 4100, "", "", "", "", "")))
    for typed, amount, rows in (("2026-10-29", "8,200", 2), ("20261029", "", 2), ("2026-10-29", "9,000", 1), ("2026-10-30", "8,200", 1)):
        table = travel_page.EvidenceTable(model.TOLL)
        table.add_files([path], 2026)
        table.item(0, 1).setText(typed)
        table.item(0, 2).setText(amount)
        notes = []
        table.note = notes.append
        table.apply_ai(path, found)
        assert table.rowCount() == rows, (typed, amount, notes)
        if rows == 2:
            assert [table.item(r, 2).text() for r in range(2)] == ["4,100", "4,100"]
        else:
            assert "직접 적은" in notes[0]
