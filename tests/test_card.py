"""카드청구 폴더 읽기(claims/card.py) — 기간 · 결제 건 이름 · 영수증 글자 · 회의록 · 물품 표 · 청구구분 · ERP 목록에서 고르기.

담당자 설명(2026-10-20): MMDD 는 사용일, '26-09' 는 2026년 9월. 결제 건은 영수증 PDF · 회의록 · 카드 뒷자리 · 공문으로 맞춘다.
실명 · 카드번호 · 실제 가맹점은 없다. 영수증 PDF 글자는 read_text 를 바꿔 끼워 흉내 낸다.
"""
from __future__ import annotations

import datetime as dt

import openpyxl

from claim_downloader.claims import card, kinds
from claim_downloader.minutes.docx import build_docx
from claim_downloader.minutes.hwpx import build_hwpx

D = dt.date

RECEIPT = """카드매출전표
가맹점명 가나다식당   사업자번호 000-00-00000
카드번호 9410-12**-****-4321
거래일시 2026-09-15 12:31:02
승인번호 30012345
공급가액 40,909
부가세 4,091
합계 45,000원"""


def minutes_data(**over) -> dict:
    data = {"filenameBase": "2026-09-15 월 운영회의", "agenda": "사업단 운영회의", "date": "2026. 9. 15. (월) 11:00 ~ 12:00",
            "place": "사업단 회의실", "expensePlace": "가나다식당", "amount": "45,000원", "attendeeCount": 2,
            "attendees": [{"org": "강원대학교", "name": "참석자1"}, {"org": "강원대학교", "name": "참석자2"}],
            "content": ["운영 현황을 논의하였음."], "supplement": "보완사항 없음"}
    data.update(over)
    return data


def make_goods(path, rows=(("A4 용지", "80g", 2, 25000, 50000), ("볼펜", "흑색", 10, 1200, 12000)), sheets=("생협",)):
    """구매의뢰 엑셀 모양(14절 '사무용품'): A1 담당자 · 8행 머리글 '연번 품명 규격 수량 단가 금액 비고', 합계 줄."""
    wb = openpyxl.Workbook()
    for n, name in enumerate(sheets):
        ws = wb.active if n == 0 else wb.create_sheet()
        ws.title = name
        ws["A1"] = "담당자: 사업단"
        for col, text in zip("ABCDEFG", ("연번", "품명", "규격", "수량", "단가", "금액", "비고(링크)")):
            ws[f"{col}8"] = text
        r = 9
        for i, row in enumerate(rows, 1):
            for col, value in zip("ABCDEF", (i, *row)):
                ws[f"{col}{r}"] = value
            r += 1
        ws[f"A{r}"] = "합계"
        ws[f"F{r}"] = sum(x[-1] for x in rows)
    wb.save(path)
    return path


def reader(texts: dict):
    """파일 이름 → PDF 글자. 없는 이름은 '' (스캔 PDF)."""
    return lambda path: texts.get(path.replace("\\", "/").rsplit("/", 1)[-1], "")


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake")
    return path


# ── 기간 · 이름 ──────────────────────────────────────────────────────
def test_period_names_the_staff_uses_and_the_short_ones():
    assert card.parse_period("26-09(09.09. ~ 10.08.)") == (D(2026, 9, 9), D(2026, 10, 8))
    assert card.parse_period("26.09.09. ~10.08.") == (D(2026, 9, 9), D(2026, 10, 8))      # 담당자가 물어본 꼴
    assert card.parse_period("26.09.09.~26.10.08.") == (D(2026, 9, 9), D(2026, 10, 8))
    assert card.parse_period("2026.09.09 ~ 2026.10.08") == (D(2026, 9, 9), D(2026, 10, 8))
    assert card.parse_period("25-12(12.09. ~ 01.08.)") == (D(2025, 12, 9), D(2026, 1, 8))  # 해를 넘김
    assert card.parse_period("26-09") == (D(2026, 9, 9), D(2026, 10, 8))                   # 9일 ~ 다음 달 8일
    assert card.parse_period("26-12") == (D(2026, 12, 9), D(2027, 1, 8))
    for name in ("2026-09-15 월 운영회의", "기타운영경비 0915 회의", "카드", "26-13"):
        assert card.parse_period(name) is None


def test_main_summary_matches_past_claim_titles():
    """실제 청구서 제목(ERP 대시보드 알림 실측) `03_[교육연구프로그램개발운영비] 카드 결제 건(26.…` · `09_[그밖의사업운영경비] 카드 결제 건(26.10.0…`
    — 괄호 안은 ERP 보기('기타운영경비')가 아니라 보관 폴더식 이름."""
    start, end = D(2026, 10, 9), D(2026, 11, 8)
    assert card.main_summary("09", start, end) == "09_[그밖의사업운영경비] 카드 결제 건(26.10.09.~26.11.08.)"
    assert card.main_summary("03", start, end) == "03_[교육연구프로그램개발운영비] 카드 결제 건(26.10.09.~26.11.08.)"
    assert card.main_summary("", start, end) == ""
    for code, short in (("04", "교육연구환경개선비"), ("05", "실험실습장비및기자재구입운영비"), ("07", "기업지원협력활동비"), ("08", "성과활용확산지원비")):
        assert card.category_short(code) == short


def test_item_folder_name_parts():
    period = (D(2026, 9, 9), D(2026, 10, 8))
    got = card.parse_item_name("기타운영경비 0915 사업단 운영회의", period)
    assert (got.code, got.used, got.title, got.amount, got.req_div) == ("09", D(2026, 9, 15), "사업단 운영회의", None, "")
    got = card.parse_item_name("교육연구프로그램개발운영비 1002 특강 다과 60,000원 [소모품]", period)
    assert (got.code, got.used, got.title, got.amount, got.req_div) == ("03", D(2026, 10, 2), "특강 다과", 60000, "85")
    got = card.parse_item_name("09_그 밖의 사업운영 경비 9.20 클로드 계정 구독 (기타)", period)
    assert (got.code, got.used, got.title, got.req_div) == ("09", D(2026, 9, 20), "클로드 계정 구독", "90")
    # 해를 넘긴 기간 — 01월은 다음 해
    got = card.parse_item_name("기타운영경비 0105 회의", (D(2025, 12, 9), D(2026, 1, 8)))
    assert got.used == D(2026, 1, 5)
    # 비목 자리를 못 읽음 · 번호와 이름이 다름
    assert card.parse_item_name("사업단 0915 회의", period).code == ""
    assert card.parse_item_name("03_기타운영경비 0915 회의", period).code == ""
    # 금액 뒤의 '원' 은 사용일이 아니다
    got = card.parse_item_name("기타운영경비 1500원 0915 회의", period)
    assert (got.used, got.amount) == (D(2026, 9, 15), 1500)


def test_category_folder_is_strict():
    assert card.is_category_folder("기타운영경비")
    assert card.is_category_folder("09_기타운영경비")
    assert card.is_category_folder("교육·연구프로그램 개발·운영비")
    assert not card.is_category_folder("기타운영경비 사업단 회의")
    assert not card.is_category_folder("기타운영경비 0915 회의")


# ── 서류 ─────────────────────────────────────────────────────────────
def test_receipt_text():
    got = card.read_receipt(RECEIPT)
    assert (got.amount, got.card_last, got.approval, got.merchant, got.used) == (45000, "4321", "30012345", "가나다식당", D(2026, 9, 15))
    # 값이 다음 줄로 떨어진 PDF · 카드번호 뒷자리가 가려진 전표
    got = card.read_receipt("결제금액\n29,000\n카드번호 ****-****-****-****\n이용일 2026.09.20")
    assert (got.amount, got.card_last, got.used) == (29000, "", D(2026, 9, 20))


def test_minutes_hwpx_and_docx_amount_and_place(tmp_path):
    for builder, suffix in ((build_hwpx, ".hwpx"), (build_docx, ".docx")):
        path = tmp_path / f"2026-09-15 월 운영회의{suffix}"
        builder(minutes_data(), str(path))
        got = card.read_minutes(str(path))
        assert (got.amount, got.merchant, got.used) == (45000, "가나다식당", D(2026, 9, 15)), suffix
    # 사용처가 빈 회의록 — 다음 라벨을 값으로 읽지 않는다
    path = tmp_path / "빈칸.hwpx"
    build_hwpx(minutes_data(expensePlace=""), str(path))
    assert card.read_minutes(str(path)).merchant == ""


def test_goods_table(tmp_path):
    got = card.read_goods(str(make_goods(tmp_path / "사무용품 구매의뢰0920.xlsx")))
    assert got.total == 62000 and [r["name"] for r in got.rows] == ["A4 용지", "볼펜"]
    assert got.rows[0] == {"name": "A4 용지", "spec": "80g", "qty": 2, "price": 25000, "amount": 50000}
    two = card.read_goods(str(make_goods(tmp_path / "구매의뢰 둘.xlsx", sheets=("생협", "오피스디포"))))
    assert two.sheet == "생협" and any("시트가 여럿" in n for n in two.notes)


# ── 폴더 전체 ────────────────────────────────────────────────────────
def build_period(tmp_path):
    base = tmp_path / "26-09(09.09. ~ 10.08.)"
    meeting = base / "기타운영경비 0915 사업단 운영회의"
    touch(meeting / "0915 영수증.pdf")
    touch(meeting / "서명부.pdf")
    build_hwpx(minutes_data(), str(meeting / "2026-09-15 월 운영회의.hwpx"))
    goods = base / "기타운영경비 0920 사무용품 구입"
    touch(goods / "0920 영수증.pdf")                                   # 스캔 — 글자 없음
    make_goods(goods / "사무용품 구매의뢰0920.xlsx")
    sub = base / "기타운영경비 0925 클로드 계정 구독"
    touch(sub / "0925 영수증.pdf")
    snack = base / "교육연구프로그램개발운영비" / "1002 특강 다과 60,000원"   # 비목 폴더 아래
    touch(snack / "1002 영수증.jpg")
    (base / "메모.txt").write_text("x", encoding="utf-8")
    (base / "정리 중").mkdir()
    texts = {"0915 영수증.pdf": RECEIPT,
             "0925 영수증.pdf": "Anthropic Receipt\n결제금액 29,000원\n카드번호 9410-12**-****-4321\n승인번호 30099999\n가맹점 ANTHROPIC"}
    return base, reader(texts)


def test_period_folder_splits_by_category_and_reads_each_payment(tmp_path):
    base, read = build_period(tmp_path)
    job = card.load_job(str(base), read_text=read)
    assert (job.start, job.end) == (D(2026, 9, 9), D(2026, 10, 8))
    assert [s.code for s in job.sheets] == ["03", "09"]
    other, etc = job.sheets
    assert etc.main_summary == "09_[그밖의사업운영경비] 카드 결제 건(26.09.09.~26.10.08.)"
    meeting, goods, sub = etc.items                                      # 사용일 차례
    assert (meeting.req_div, meeting.amount, meeting.amount_from, meeting.merchant, meeting.card_last, meeting.approval) == \
        ("17", 45000, "영수증", "가나다식당", "4321", "30012345")
    assert meeting.minutes.endswith(".hwpx") and meeting.summary == "09_사업단 운영회의"
    assert (goods.req_div, goods.amount, goods.amount_from) == ("85", 62000, "물품 표")
    assert any("글자를 못 읽는 영수증" in n for n in goods.notes)
    assert (sub.req_div, sub.amount, sub.merchant) == ("90", 29000, "ANTHROPIC")
    snack = other.items[0]
    assert (snack.code, snack.used, snack.amount, snack.amount_from, snack.req_div) == ("03", D(2026, 10, 2), 60000, "폴더 이름", "90")
    assert any("1002 영수증.jpg" in n for n in snack.notes)
    assert etc.total == 45000 + 62000 + 29000 and job.total == etc.total + 60000
    assert job.problems() == []
    assert any("메모.txt" in s for s in job.skipped) and any("정리 중" in s for s in job.skipped)
    assert job.summary_lines()[0].startswith("기간 26.09.09.~26.10.08. · 청구서 2개 · 결제 4건")
    assert "회의비 1 · 소모성물품 1 · 기타 1" in job.summary_lines()[2]


def test_amount_conflicts_and_missing_values_are_reported(tmp_path):
    base = tmp_path / "26-09"
    item = base / "기타운영경비 0915 운영회의 50,000원"
    touch(item / "0915 영수증.pdf")
    build_hwpx(minutes_data(), str(item / "2026-09-15 월 운영회의.hwpx"))
    nothing = base / "사업단 0916 뭔가"
    nothing.mkdir(parents=True)
    job = card.load_job(str(base), read_text=reader({"0915 영수증.pdf": RECEIPT.replace("2026-09-15", "2026-09-14")}))
    first = next(i for i in job.items if i.code == "09")
    assert first.amount == 50000 and first.amount_from == "폴더 이름"        # 사람이 적은 것이 먼저
    assert any("금액이 서로 다름" in n and "영수증 45,000" in n for n in first.notes)
    assert any("사용일이 다름" in n for n in first.notes)
    problems = job.problems()
    assert any("사업단 0916 뭔가" in p and "비목을 모름" in p and "금액을 모름" in p for p in problems)


def test_unknown_period_is_a_problem_but_items_still_show(tmp_path):
    base = tmp_path / "카드 정리"
    touch(base / "기타운영경비 0915 회의 45,000원" / "a.pdf")
    job = card.load_job(str(base), read_text=reader({}))
    assert len(job.items) == 1 and job.items[0].used is None
    assert any("결제 기간을 읽지 못함" in p for p in job.problems())


def test_card_period_folder_shape(tmp_path):
    base, _read = build_period(tmp_path)
    assert card.looks_like_card_folder(str(base))
    assert kinds.resolve(kinds.CARD, str(base)) == kinds.CARD
    plain = tmp_path / "26-10(10.09. ~ 11.08.)"
    plain.mkdir()
    assert not card.looks_like_card_folder(str(plain))                  # 결제 건 폴더가 없으면 아님


# ── ERP 목록에서 결제 건 고르기 ──────────────────────────────────────
def payments(*rows):
    return [card.payment_from_cells(i, dict(zip(("k_USED_DATE", "k_SHOP_NAME", "k_USED_COST", "k_BAL_AMT", "k_CARD_NO", "k_APPRNO"), r)))
            for i, r in enumerate(rows)]


def item(**over) -> card.CardItem:
    base = {"folder": "x", "name": "기타운영경비 0915 회의", "code": "09", "used": D(2026, 9, 15), "amount": 45000}
    base.update(over)
    return card.CardItem(**base)


def test_payment_cells_from_the_grid():
    got = payments(("20260915", "(주)가나다식당", "45000", "45,000", "9410-12**-****-4321", "30012345"))[0]
    assert (got.used, got.amount, got.balance, got.card_last, got.approval) == (D(2026, 9, 15), 45000, 45000, "4321", "30012345")
    assert card.shop_match("가나다식당", got.shop) and not card.shop_match("라마", got.shop)


def test_payment_cells_in_the_measured_shape():
    """실측(2026-10-20): 그리드 값은 숫자만 — 날짜 20261012 · 금액 콤마 없음 · 카드번호도 숫자. 남은 금액 k_BAL_AMT."""
    cells = {"k_USED_DATE": "20261012", "k_USED_TIME": "124553", "k_SHOP_NAME": "가나다식당", "k_APPRNO": "06123456",
             "k_USED_COST": "180000", "k_SUP_AMT": "163637", "k_TAX_AMT": "16363", "k_REQ_AMT": "0", "k_BAL_AMT": "180000",
             "k_CARD_NO": "9410120000004321", "k_USER_NM": "사용자"}
    got = card.payment_from_cells(0, cells)
    assert (got.used, got.amount, got.balance, got.card_last, got.approval) == (D(2026, 10, 12), 180000, 180000, "4321", "06123456")
    found = card.CardItem(folder="x", code="03", used=D(2026, 10, 12), amount=180000)
    assert card.pick(found, [got])[0] == 0


def test_pick_by_date_and_amount_then_narrow():
    rows = payments(("2026-09-15", "가나다식당", "45000", "45000", "****4321", "1"),
                    ("2026-09-15", "편의점", "3000", "3000", "****4321", "2"),
                    ("2026-09-16", "가나다식당", "45000", "45000", "****4321", "3"))
    assert card.pick(item(), rows)[0] == 0
    assert card.pick(item(used=D(2026, 9, 17)), rows) == (None, "09-17 에 쓴 미청구 결제 건이 목록에 없음")
    index, why = card.pick(item(amount=46000), rows)
    assert index is None and "그날" in why and "편의점" in why
    # 금액을 모르면 고르지 않는다 — 가맹점까지 맞으면 고른다
    assert card.pick(item(amount=None), rows)[0] is None
    assert card.pick(item(amount=None, merchant="가나다식당"), rows)[0] == 0
    # 승인번호가 같으면 그 줄
    assert card.pick(item(used=None, approval="3"), rows)[0] == 2


def test_pick_same_day_same_amount_needs_more_and_skips_claimed():
    rows = payments(("20260915", "가나다식당", "45000", "45000", "****1111", ""),
                    ("20260915", "라마바카페", "45000", "45000", "****4321", ""),
                    ("20260915", "가나다식당", "45000", "0", "****4321", ""))        # 이미 청구됨(남은 금액 0)
    index, why = card.pick(item(), rows)
    assert index is None and "2개" in why
    assert card.pick(item(card_last="4321"), rows)[0] == 1
    assert card.pick(item(merchant="가나다식당"), rows)[0] == 0
    only = payments(("20260915", "가나다식당", "45000", "45000", "****1111", ""))
    index, why = card.pick(item(card_last="4321"), only)               # 하나뿐이어도 영수증 카드와 다르면 고르지 않는다
    assert index is None and "카드 뒷자리가 다름" in why


def test_assign_spreads_same_day_payments_and_flags_collisions():
    rows = payments(("20260915", "가나다식당", "45000", "45000", "", "30011111"),
                    ("20260915", "가나다식당", "45000", "45000", "", "30022222"))
    # 승인번호로 정해진 줄을 빼면 남은 폴더도 하나로 정해진다
    assert [r[0] for r in card.assign([item(name="a", approval="30011111"), item(name="b")], rows)] == [0, 1]
    same = card.assign([item(name="a", merchant="가나다식당"), item(name="b", merchant="가나다식당")],
                       payments(("20260915", "가나다식당", "45000", "45000", "", "")))
    assert [r[0] for r in same] == [None, None] and all("같은 줄" in r[1] for r in same)


# ── 회의비: 회의 장소와 가맹점 주소의 도 · 시 ──────────────────────────
def test_regions_from_addresses_and_places():
    """담당자 규칙(2026-10-20): 영수증이 없으면 카드매출전표로 갈음하는데, 회의비 공문의 장소(춘천시 정도)와 가맹점 주소(도 · 시)가 달라서는 안 된다."""
    assert card.address_region("강원 춘천시 강원대학길 1 (효자동)") == "춘천"
    assert card.address_region("강원특별자치도 원주시 흥업면") == "원주"
    assert card.address_region("서울특별시 강남구 테헤란로 1") == "서울"
    assert card.address_region("") == ""
    assert card.regions_in("강원대학교 춘천캠퍼스 미래도서관") == ["춘천"]
    assert card.regions_in("고성능 장비 · 동해안 · 정선된 · 세종대왕") == []      # 이름 뒤에 글자가 붙은 낱말은 지역이 아니다
    assert card.regions_in("춘천에서 개최, 원주로 이동") == ["춘천", "원주"]
    assert card.meeting_region("사업단 회의실") == (card.HOME_REGION, "장소에 시 · 군이 없어 사업단 소재지로 봄")
    assert card.meeting_region("원주시 OO 회의실") == ("원주", "회의록 회의장소")
    assert card.meeting_region("사업단 회의실", "1. 일시: 10.15.\n2. 장소: 강릉시 OO호텔 세미나실\n3. 참석: 춘천 소재 기업") == ("강릉", "공문 장소")
    assert card.region_conflict("춘천", "강원 춘천시 공지로 1") == ""
    assert "지역이 다름" in card.region_conflict("춘천", "서울특별시 중구 세종대로 1")
    assert card.region_conflict("춘천", "") == ""                                  # 주소를 모르면 ERP 에서 넣을 때 본다


def test_meeting_payment_flags_a_shop_outside_the_meeting_region(tmp_path):
    base = tmp_path / "26-10(10.09. ~ 11.08.)"
    far = base / "기타운영경비 1015 사업단 운영회의"
    touch(far / "1015 영수증.pdf")
    touch(far / "운영회의 개최 계획 공문.pdf")
    build_hwpx(minutes_data(place="사업단 회의실", date="2026. 10. 15. (목) 11:00 ~ 12:00"), str(far / "2026-10-15 목 운영회의.hwpx"))
    near = base / "기타운영경비 1016 기획회의"
    touch(near / "1016 영수증.pdf")
    build_hwpx(minutes_data(date="2026. 10. 16. (금) 11:00 ~ 12:00"), str(near / "2026-10-16 금 기획회의.hwpx"))
    texts = {"1015 영수증.pdf": RECEIPT.replace("2026-09-15", "2026-10-15") + "\n가맹점 주소: 서울특별시 중구 세종대로 1",
             "운영회의 개최 계획 공문.pdf": "수신 내부결재\n제목 사업단 운영회의 개최 계획\n1. 장소: 강원대학교 춘천캠퍼스 사업단 회의실\n붙임 1부. 끝.",
             "1016 영수증.pdf": RECEIPT.replace("2026-09-15", "2026-10-16") + "\n주소 강원 춘천시 공지로 1"}
    job = card.load_job(str(base), read_text=reader(texts))
    first, second = job.items
    assert (first.meeting_region, first.meeting_region_from) == ("춘천", "공문 장소")
    assert first.notice.endswith("공문.pdf") and first.shop_address.startswith("서울특별시")
    assert any("지역이 다름" in n and "서울" in n for n in first.notes)
    assert second.meeting_region == "춘천" and second.shop_address.startswith("강원 춘천시")
    assert not any("지역이 다름" in n for n in second.notes)
