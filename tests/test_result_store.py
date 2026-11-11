"""일반청구 결과 창 다시 보기(ui/result_store.py) — 담당자 2026-11-11 "일반청구 결과내용이 새창에 뜨는데 이걸 한번 닫으면
다시 내용을 확인할 수 없습니다". 폴더마다 최근 결과를 사용자 폴더에 남기고 ④ 의 [결과 다시 보기] 가 다시 띄운다. 이름은 가짜다."""
from __future__ import annotations

import datetime as dt
import json
import os

import pytest

from claim_downloader.ui import result_store


def test_only_the_ten_newest_results_are_kept_across_folders_and_survive_a_restart(tmp_path):
    """담당자 2026-11-11 "최근 10건만 저장" — 모든 폴더를 합쳐 새것부터 열 건. 폴더마다 보기는 그중 그 폴더의 것."""
    a = str(tmp_path / "07_[기업지원협력활동비] WE-Meet 회의비")
    b = str(tmp_path / "7월")
    for n in range(12):
        assert result_store.save(a if n % 2 else b, "카드청구", f"임시저장 결제 {n}건", {"heading": f"h{n}", "tone": "success"},
                                 when=dt.datetime(2026, 11, 11, 16, n)) == ""
    got = result_store.recent()
    assert len(got) == result_store.KEEP == 10 and [e["heading"] for e in got][:3] == ["임시저장 결제 11건", "임시저장 결제 10건", "임시저장 결제 9건"]
    assert got[-1]["heading"] == "임시저장 결제 2건"                # 0 · 1 은 지워졌다
    assert [e["heading"] for e in result_store.entries(a)] == [f"임시저장 결제 {n}건" for n in (11, 9, 7, 5, 3)]
    assert got[0]["when"] == "2026-11-11 16:11" and got[0]["report"] == {"heading": "h11", "tone": "success"}
    assert result_store.find(got[3]["id"]) == got[3] and result_store.find("없음") is None
    assert len({e["id"] for e in got}) == 10
    result_store.forget_cache()                                     # 앱을 다시 켠 것처럼 — 파일에서 읽는다
    assert len(result_store.recent()) == 10 and len(result_store.entries(os.path.join(a, ".", ""))) == 5     # 같은 폴더는 같은 열쇠
    assert result_store.entries(str(tmp_path / "다른 폴더")) == [] and result_store.entries("") == []
    assert json.loads(result_store.path().read_text(encoding="utf-8"))["v"] == 2   # 사용자 폴더의 _청구결과.json
    assert result_store.path().name == "_청구결과.json"


def test_the_old_per_folder_file_is_read_as_one_newest_first_list(tmp_path):
    """같은 날 낮의 판은 폴더마다 다섯 {폴더: [결과…]} 이었다 — 합쳐 새것부터 열 건으로 읽는다."""
    old = {os.path.normcase(str(tmp_path / f"f{f}")): [{"when": f"2026-11-11 1{f}:{m:02d}", "folder": str(tmp_path / f"f{f}"), "title": "카드청구",
                                                     "heading": f"{f}-{m}", "report": {"heading": "x"}} for m in range(5)] for f in range(3)}
    result_store.path().parent.mkdir(parents=True, exist_ok=True)
    result_store.path().write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    result_store.forget_cache()
    got = result_store.recent()
    assert len(got) == 10 and got[0]["heading"] == "2-4" and got[-1]["heading"] == "1-0" and all(e.get("id") for e in got)
    assert result_store.find(got[0]["id"])["heading"] == "2-4"


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


def test_home_lists_the_results_and_opens_one_in_a_new_tab(tmp_path):
    """담당자 2026-11-11 "홈화면에 결과확인을 이어서 작업하기 오른쪽에 목록을 넣고 목록중 한건을 클릭하면 새탭에서 결과내용 확인하기"."""
    app = _qt_app()
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from claim_downloader.claims import checks
    from claim_downloader.ui import app as app_module
    from claim_downloader.ui.report_dialog import ReportRow, report_to_data

    folder = tmp_path / "07_[기업지원협력활동비] WE-Meet 회의비"
    folder.mkdir()
    report = report_to_data({"title": "카드청구", "heading": "임시저장 결제 11건 · 신청 전 확인할 것 2건", "tone": "warning",
                             "columns": [("상태", 90), ("건명", None)], "rows": [ReportRow("저장", "success", ["1012", "회의"], html="<b>회의</b>")],
                             "notes": [checks.Note("참석자 확인", level=checks.CHECK, what="참석자", where="회의록등록", todo="고치세요")],
                             "notes_title": "신청 전 확인할 것", "side_detail": True})
    assert result_store.save(str(folder), "카드청구", "임시저장 결제 11건 · 신청 전 확인할 것 2건", report,
                             when=dt.datetime(2026, 11, 11, 20, 20)) == ""
    window = app_module.MainWindow()
    try:
        home = window.home
        home.refresh_results()
        assert not home._results_empty.isVisibleTo(home) and home._result_rows.count() == 1
        row = home._result_rows.itemAt(0).widget()
        QTest.mouseClick(row, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))      # 줄을 누르면 새 탭
        entry = result_store.recent()[0]
        tab_id = app_module.RESULT_PREFIX + entry["id"]
        assert window.tabs.has(tab_id) and window.stack.currentWidget() is window._pages[tab_id]
        page = window._pages[tab_id]
        assert page.report.windowFlags() & Qt.Window != Qt.Window                 # 창이 아니라 탭 안
        assert page.report.table.rowCount() == 1 and "참석자" in page.report.notes.toPlainText()
        from claim_downloader.ui.pages.result import tab_name
        assert page.property("tab_name") == tab_name(entry) and tab_name(entry, dt.date(2026, 11, 11)) == "결과 20:20"
        assert tab_name(entry, dt.date(2026, 11, 12)) == "결과 11-11 20:20"
        window.open_result(entry["id"])                                            # 같은 것을 다시 — 탭은 하나
        assert [t for t in window._pages if t.startswith(app_module.RESULT_PREFIX)] == [tab_id]
        QTest.keyClick(page.report, Qt.Key_Escape)                                 # Esc 로 탭 안의 내용이 숨지 않는다
        assert page.report.isVisibleTo(page)
        page.report.close_requested.emit()                                         # [탭 닫기]
        app.processEvents()
        assert not window.tabs.has(tab_id) and tab_id not in window._pages
        window.open_result("없는 결과")                                             # 지워진 결과 — 탭을 만들지 않는다
        assert not any(t.startswith(app_module.RESULT_PREFIX) for t in window._pages)
    finally:
        window._closing_for_restart = True
        window.hide()
        _close_window(window)
        app.processEvents()


def _close_window(window) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
