"""공무확인증 관리대장(parking_ledger.py) — 담당자 2026-10-21 "사용자와 사용내용을 남겨두는게 좋을 것 같습니다 … 엑셀파일로 다운받을 수 있도록".

이름 · 차량번호는 모양만 같은 가짜다.
"""
from __future__ import annotations

import datetime as dt
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


SITE_HEAD = ["할인일시arrow_downward", "차량번호", "입차시각", "할인명", "적용방식", "할인시간", "할인금액", "적용금액", "절사금액", "결제금액"]


def _site(when, car, applied, method="수동"):
    return [when, car, when, "공무확인증4시간", method, "240분", "", applied, "0", "0"]


def test_applied_amount_goes_into_the_note_and_matched_rows_get_it_too(isolated_home):
    """담당자 2026-10-22 "적용금액이 있는 건만 공무확인증이 차감되는건지도 확인" — 줄마다 적용금액을 비고에 남긴다."""
    old = ledger.Entry(date="2026-10-20", given=1, car="12가3456", source="apply")
    rows = [_site("2026-10-20 17:37:04", "12가3456", "6,700"), _site("2026-10-21 09:00:00", "34나5678", "0", "QR")]
    match = ledger.match_site([old], SITE_HEAD, rows)
    assert match.applied_col == 7 and match.pairs == [(0, old)] and match.missing == [1]
    assert ledger.note_applied(rows, match) == 1 and old.note == "적용금액 6,700"
    assert ledger.note_applied(rows, match) == 0                                  # 두 번 붙이지 않는다
    (free,) = ledger.from_site(SITE_HEAD, rows, match.missing, match)
    assert free.given == 1 and free.note == "공무확인증4시간 · 09:00 할인 · QR · 적용금액 0" and ledger.is_free(free.note)
    (not_drawn,) = ledger.from_site(SITE_HEAD, rows, match.missing, match, free_drawn=False)
    assert not_drawn.given == 0 and not_drawn.note.endswith("적용금액 0 · 차감 안 됨")
    again = ledger.match_site([old, not_drawn], SITE_HEAD, rows)                  # 배부 0 으로 둔 줄도 그 사이트 줄의 짝
    assert again.missing == [] and len(again.pairs) == 2


def test_free_rule_switches_given_both_ways():
    entries = [ledger.Entry(date="2026-10-21", given=1, car="34나5678", note="공무확인증4시간 · 적용금액 0", source="site"),
               ledger.Entry(date="2026-10-21", given=1, car="56다7890", note="공무확인증4시간 · 적용금액 1,000", source="site")]
    assert ledger.apply_free_rule(entries) == 1 and [e.given for e in entries] == [0, 1] and "차감 안 됨" in entries[0].note
    assert ledger.restore_free(entries) == 1 and [e.given for e in entries] == [1, 1] and "차감 안 됨" not in entries[0].note


def test_check_drain_tells_whether_free_uses_are_drawn():
    """두 번 읽은 잔량 사이에 줄어든 수 = 모든 사용이면 'all', = 적용금액 있는 사용만이면 'paid'. 그 사이 적용금액 0 사용이 없으면 판정하지 않는다."""
    rows = [_site("2026-10-22 10:20:00", "11가1111", "3,700"), _site("2026-10-22 10:15:00", "22나2222", "0"),
            _site("2026-10-22 09:59:00", "33다3333", "0")]                       # 앞서 읽은 때(10:00) 전 — 세지 않는다
    match = ledger.match_site([], SITE_HEAD, rows)
    drain = ledger.check_drain(85, "2026-10-22 10:00:00", 83, rows, match)
    assert (drain.used, drain.paid, drain.free, drain.verdict) == (2, 1, 1, "all") and "차감됩니다" in drain.text()
    assert ledger.check_drain(85, "2026-10-22 10:00:00", 84, rows, match).verdict == "paid"
    assert ledger.check_drain(85, "2026-10-22 10:00:00", 80, rows, match).verdict == ""     # 그 사이 구입 · 시각 차이 — 모름
    only_paid = ledger.check_drain(85, "2026-10-22 10:16:00", 84, rows, match)
    assert only_paid.verdict == "" and "맞습니다" in only_paid.text()
    assert ledger.check_drain(-1, "", 84, rows, match) is None


def test_history_since_and_stamps():
    entries = [ledger.Entry(date="2025-11-03", given=1), ledger.Entry(date="2025-01-01", bought=9, source=ledger.CARRY)]
    assert ledger.history_since(entries, dt.date(2026, 10, 22)) == "2025-11-03"
    assert ledger.history_since([], dt.date(2026, 10, 22)) == "2026-01-01"
    assert ledger.stamp_of("2026-10-20 17:37:04") == "2026-10-20 17:37:04" and ledger.stamp_of("2026.9.5 9:03") == "2026-09-05 09:03:00"
    assert (ledger.amount_of("6,700"), ledger.amount_of("0"), ledger.amount_of(""), ledger.amount_of("-")) == (6700, 0, None, None)
