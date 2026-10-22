"""공무확인증 관리대장(parking_ledger.py) — 담당자 2026-10-21 "사용자와 사용내용을 남겨두는게 좋을 것 같습니다 … 엑셀파일로 다운받을 수 있도록".

이름 · 차량번호는 모양만 같은 가짜다.
"""
from __future__ import annotations

import json

import pytest

from claim_downloader import parking_ledger as ledger
from claim_downloader import settings


def test_balance_runs_in_date_order(isolated_home):
    ledger.add(ledger.Entry(date="2026-10-02", given=1, content="자문위원 방문", user="가나다", car="12가3456", source="apply"))
    ledger.add(ledger.Entry(date="2026-10-01", bought=100, content="공무확인증 구입"))
    ledger.add(ledger.Entry(date="2026-10-02", given=5, content="워크숍", user="라마바", note="할인 링크 '워크숍'", source="link"))
    rows = ledger.with_balance(ledger.load())
    assert [(e.date, left) for e, left in rows] == [("2026-10-01", 100), ("2026-10-02", 99), ("2026-10-02", 94)]   # 같은 날은 적은 차례
    assert ledger.totals(ledger.load()) == (100, 6, 94)
    assert rows[1][0].remark() == "12가3456" and rows[2][0].remark() == "할인 링크 '워크숍'"


def test_update_and_remove(isolated_home):
    entry = ledger.Entry(date="2026-10-03", given=1, car="34나5678", source="site")
    ledger.add(entry)
    ledger.update(entry.id, user="가나다", content="회의 참석", given="2")
    (saved,) = ledger.load()
    assert (saved.user, saved.content, saved.given) == ("가나다", "회의 참석", 2)
    assert ledger.remove(entry.id) == [] and ledger.load() == []


def test_broken_file_is_kept_aside_not_overwritten(isolated_home):
    settings.parking_ledger_path().write_text("{깨진", encoding="utf-8")
    assert ledger.load() == []
    ledger.add(ledger.Entry(date="2026-10-01", bought=10))
    assert settings.parking_ledger_path().with_name("_공무확인증관리대장.json.읽지못함").read_text(encoding="utf-8") == "{깨진"
    assert json.loads(settings.parking_ledger_path().read_text(encoding="utf-8"))["entries"][0]["bought"] == 10


def test_left_of_and_site_count_read_held_tickets():
    assert ledger.left_of("교환공무확인증4시간 (잔량 85)") == 85            # 실측 ② — [새 링크] 창의 할인권 상품 보기
    assert ledger.left_of("공무확인증4시간 1,204매") == 1204
    assert ledger.left_of("공무확인증4시간 (12)") == 12
    assert ledger.left_of("공무확인증4시간") is None
    assert ledger.site_count(["선택", "교환공무확인증4시간 (잔량 85)"]) == 85
    assert ledger.site_count("교환공무확인증4시간 (잔량 85)\n공무확인증2시간 (잔량 5)\n정기권 (잔량 9)") == 90   # 공무확인증만 더한다
    assert ledger.site_count(["정기권 (잔량 9)"]) is None and ledger.site_count([]) is None


def test_fit_to_site_counts_back_the_starting_amount(isolated_home):
    """담당자 2026-10-22: 구입이 비어 잔여가 마이너스였다 — 사이트 보유 잔량에서 거꾸로 처음 수량을 셈하고 줄마다 잔여를 다시."""
    ledger.add(ledger.Entry(date="2026-10-02", given=1, car="12가3456", source="site"))
    ledger.add(ledger.Entry(date="2026-09-29", given=1, car="34나5678", source="site"))
    ledger.add(ledger.Entry(date="2026-10-05", bought=10, content="공무확인증 구입"))
    ledger.add(ledger.Entry(date="2026-10-06", given=3, content="워크숍", source="manual"))
    fit = ledger.fit_to_site(ledger.load(), 85, "10-22 09:00")
    assert fit.changed and fit.start == 85 + 5 - 10 and fit.short == 0
    ledger.save(fit.entries)
    rows = ledger.with_balance(ledger.load())
    assert rows[0][0].source == ledger.CARRY and rows[0][0].date == "2026-09-29"       # 대장의 첫 일자 맨 앞
    assert rows[0][0].content == "처음 수량" and "85" in rows[0][0].note
    assert [left for _, left in rows] == [80, 79, 78, 88, 85]                          # 마지막 잔여 = 사이트 잔량
    again = ledger.fit_to_site(ledger.load(), 85, "10-22 09:00")
    assert not again.changed and len([e for e in again.entries if e.source == ledger.CARRY]) == 1   # 처음 수량 줄은 하나
    ledger.add(ledger.Entry(date="2026-10-22", given=1, car="56다7890", source="apply"))
    later = ledger.fit_to_site(ledger.load(), 84, "10-22 10:00")
    assert later.start == 80 and ledger.with_balance(later.entries)[-1][1] == 84


def test_fit_to_site_reports_buys_it_cannot_explain(isolated_home):
    entries = [ledger.Entry(date="2026-10-01", bought=100), ledger.Entry(date="2026-10-02", given=10)]
    fit = ledger.fit_to_site(entries, 50, "10-22 09:00")
    assert fit.start == 0 and fit.short == 40          # 대장에 없는 사용이 있거나 구입 줄이 틀렸다


def test_site_history_rows_are_matched_by_car_and_day():
    """같은 차가 같은 날 두 번이면 대장에도 두 줄이어야 맞다 — 대장 줄 하나는 사이트 줄 하나에만."""
    entries = [ledger.Entry(date="2026-10-21", given=1, car="12가 3456"), ledger.Entry(date="2026-10-20", given=1, car="99하9999")]
    headers = ["적용일시", "차량번호", "상품"]
    rows = [["2026-10-21 10:03", "12가3456", "교환공무확인증4시간"],
            ["2026.10.21 15:00", "12가3456", "교환공무확인증4시간"],
            ["2026-10-21 11:00", "34나5678", "교환공무확인증4시간"]]
    match = ledger.match_site(entries, headers, rows)
    assert match.ok and match.matched == [0] and match.missing == [1, 2]
    new = ledger.from_site(headers, rows, match.missing, match)
    assert [(e.date, e.given, e.car, e.note, e.source, e.user, e.content) for e in new] == [
        ("2026-10-21", 1, "12가3456", "교환공무확인증4시간 · 15:00 할인", "site", "", ""),
        ("2026-10-21", 1, "34나5678", "교환공무확인증4시간 · 11:00 할인", "site", "", "")]


def test_real_history_columns():
    """담당자 PC 에서 읽힌 할인 내역 열(2026-10-22) — 정렬 그림 글자가 붙은 '할인일시', 일시로 착각하기 쉬운 '입차시각' · '할인시간'(240분).
    공무확인증이 아닌 할인은 대장과 상관없고, 링크 · QR 로 쓴 줄(적용방식이 수동이 아님)도 바로 넣는다(담당자 2026-10-22) — 비고에 적용방식."""
    headers = ["할인일시arrow_downward", "차량번호", "입차시각", "할인명", "바코드", "할인유형", "적용방식", "입주사", "구분", "할인시간"]
    rows = [["2026-10-20 17:37:04", "09주5782", "2026-10-20 14:07:16", "공무확인증4시간", "", "할인권", "수동", "사업단", "무료", "240분"],
            ["2026-10-19 11:33:29", "38어3853", "2026-10-19 11:31:34", "공무확인증4시간", "", "할인권", "QR", "사업단", "무료", "240분"],
            ["2026-10-18 09:00:00", "11가1111", "2026-10-18 08:00:00", "정기권 할인", "", "할인권", "수동", "사업단", "무료", "60분"]]
    assert ledger.clean_header(headers[0]) == "할인일시"
    match = ledger.match_site([], headers, rows)
    assert (match.date_col, match.car_col, match.product_col, match.method_col) == (0, 1, 3, 6)
    assert match.missing == [0, 1] and match.others == [2]
    manual, qr = ledger.from_site(headers, rows, match.missing, match)
    assert (manual.date, manual.given, manual.car, manual.note, manual.user, manual.content) == (
        "2026-10-20", 1, "09주5782", "공무확인증4시간 · 17:37 할인", "", "")
    assert (qr.date, qr.car, qr.note) == ("2026-10-19", "38어3853", "공무확인증4시간 · 11:33 할인 · QR")


def test_unknown_history_columns_are_not_guessed():
    match = ledger.match_site([], ["칸 1", "칸 2"], [["a", "b"]])
    assert not match.ok and "알아보지 못해" in match.note and match.missing == []


def test_export_has_the_old_ledger_shape(isolated_home, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    ledger.add(ledger.Entry(date="2026-10-01", bought=100, content="공무확인증 구입"))
    ledger.add(ledger.Entry(date="2026-10-02", given=1, content="자문위원 방문", user="가나다", car="12가3456"))
    path = ledger.export_xlsx(ledger.load(), tmp_path / "대장.xlsx")
    sheet = openpyxl.load_workbook(path).active
    assert sheet["A1"].value == "공무확인증 관리대장"
    assert [sheet[f"{c}3"].value for c in "AEFG"] == ["일자", "내용", "사용자", "비고(차량번호 등)"]
    assert sheet["B3"].value == "수량" and [sheet[f"{c}4"].value for c in "BCD"] == ["구입", "배부", "잔여"]
    assert [sheet[f"{c}5"].value for c in "ABCD"] == ["2026-10-01", 100, None, 100]
    assert [sheet[f"{c}6"].value for c in "ACDEFG"] == ["2026-10-02", 1, 99, "자문위원 방문", "가나다", "12가3456"]
    assert [sheet[f"{c}7"].value for c in "ABCD"] == ["합계", 100, 1, 99]
