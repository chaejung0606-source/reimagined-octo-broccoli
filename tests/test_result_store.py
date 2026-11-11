"""일반청구 결과 창 다시 보기(ui/result_store.py) — 담당자 2026-11-11 "일반청구 결과내용이 새창에 뜨는데 이걸 한번 닫으면
다시 내용을 확인할 수 없습니다". 폴더마다 최근 결과를 사용자 폴더에 남기고 ④ 의 [결과 다시 보기] 가 다시 띄운다. 이름은 가짜다."""
from __future__ import annotations

import datetime as dt
import json
import os

import pytest

from claim_downloader.ui import result_store


def test_results_are_kept_per_folder_newest_first_and_survive_a_restart(tmp_path):
    folder = str(tmp_path / "07_[기업지원협력활동비] WE-Meet 회의비")
    for n in range(7):
        assert result_store.save(folder, "카드청구", f"임시저장 결제 {n}건", {"heading": f"h{n}"},
                                 when=dt.datetime(2026, 11, 11, 16, n)) == ""
    got = result_store.entries(folder)
    assert [e["heading"] for e in got] == ["임시저장 결제 6건", "임시저장 결제 5건", "임시저장 결제 4건", "임시저장 결제 3건", "임시저장 결제 2건"]
    assert got[0]["when"] == "2026-11-11 16:06" and got[0]["report"] == {"heading": "h6"}
    result_store.forget_cache()                                     # 앱을 다시 켠 것처럼 — 파일에서 읽는다
    assert len(result_store.entries(os.path.join(folder, ".", ""))) == 5     # 같은 폴더는 같은 열쇠
    assert result_store.entries(str(tmp_path / "다른 폴더")) == [] and result_store.entries("") == []
    assert json.loads(result_store.path().read_text(encoding="utf-8"))           # 사용자 폴더의 _청구결과.json
    assert result_store.path().name == "_청구결과.json"


def _qt_app():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_report_round_trip_keeps_rows_and_structured_checks():
    _qt_app()
    from claim_downloader.claims import checks
    from claim_downloader.ui.report_dialog import ReportRow, report_from_data, report_to_data
    note = checks.Note("21행 가나다: 금액이 없음", level=checks.FIX, what="가나다 — 금액이 비어 있음", where="명단 엑셀 21행",
                       todo="금액을 적으세요", person=3)
    kwargs = {"title": "카드청구", "heading": "임시저장 결제 11건", "tone": "warning", "summary": ["대표적요: 07_…"],
              "columns": [("상태", 90), ("건명", None)], "rows": [ReportRow("저장", "success", ["1012", "회의"], tips={1: "긴 글"},
                                                                         right=(0,), html="<b>x</b>", key=3)],
              "notes": [note, "그냥 알림"], "notes_title": "신청 전 확인할 것", "side_detail": True, "accept_text": "ERP 에 넣기"}
    data = json.loads(json.dumps(report_to_data(kwargs), ensure_ascii=False))     # 파일에 썼다 읽은 것처럼
    back = report_from_data(data)
    assert "accept_text" not in back and back["columns"] == [("상태", 90), ("건명", None)] and back["side_detail"] is True
    row = back["rows"][0]
    assert (row.status, row.cells, row.tips, row.right, row.html, row.key) == ("저장", ["1012", "회의"], {1: "긴 글"}, (0,), "<b>x</b>", 3)
    got = back["notes"][0]
    assert isinstance(got, checks.Note) and got == str(note) and (got.level, got.what, got.where, got.todo, got.person) == \
        (checks.FIX, "가나다 — 금액이 비어 있음", "명단 엑셀 21행", "금액을 적으세요", 3)
    assert back["notes"][1] == "그냥 알림" and not isinstance(back["notes"][1], checks.Note)


def test_claim_page_reopens_the_result_after_it_was_closed(tmp_path, monkeypatch):
    app = _qt_app()
    from test_log_button import _close
    from claim_downloader.claims import kinds
    from claim_downloader.ui.pages import claim as claim_page
    from claim_downloader.ui.report_dialog import ReportRow
    from claim_downloader.ui.worker import SessionWorker
    from test_scholarship import make_ga

    folder = tmp_path / "7월"
    folder.mkdir()
    make_ga(folder / "2026학년도 (가)형 근로장학금 지급내역.xlsx")
    page = claim_page.ClaimPage(worker=SessionWorker())
    shown: list[dict] = []
    monkeypatch.setattr(claim_page, "show_report", lambda parent, **kw: shown.append(kw) or True)
    try:
        assert page.add_folder(str(folder), kinds.SCHOLARSHIP)
        page._current = 0
        page._sync_buttons()
        assert not page.result_button.isVisibleTo(page)               # 넣은 적 없는 폴더 — 다시 볼 결과가 없다
        page._show_result(0, title="장학금 청구", heading="임시저장 2명 · 신청 전 확인할 것 1건", tone="warning",
                          columns=[("상태", 90), ("이름", None)], rows=[ReportRow("저장", "success", ["1", "가나다"])],
                          notes=["가나다: 소득구분이 '기타소득'"], footer="ERP 에서 검토하세요." + claim_page.NEXT_FOLDER_NOTE)
        assert len(shown) == 1 and page.result_button.isVisibleTo(page) and page.result_button.text() == "결과 다시 보기"
        page._reopen_result()                                         # 창을 닫은 뒤 다시
        again = shown[-1]
        assert len(shown) == 2 and again["heading"] == "임시저장 2명 · 신청 전 확인할 것 1건" and again["title"] == "장학금 청구 — 다시 보기"
        assert "에 넣은 결과입니다" in again["summary"][0] and again["notes"] == ["가나다: 소득구분이 '기타소득'"]
        assert again["rows"][0].cells == ["1", "가나다"] and claim_page.NEXT_FOLDER_NOTE not in again["footer"]
        # 앱을 다시 켜도(새 화면 · 파일에서) 남아 있다
        page2 = claim_page.ClaimPage(worker=SessionWorker())
        try:
            assert page2.add_folder(str(folder), kinds.SCHOLARSHIP)
            page2._current = 0
            page2._sync_buttons()
            assert page2.result_button.isVisibleTo(page2)
        finally:
            _close(page2)
    finally:
        _close(page)
        app.processEvents()
