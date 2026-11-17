"""증빙 다운로드 — 구매요청(계약) 서류만 고르면 화면 글이 청구서 · 결의서내역을 말하지 않는다(2026-11-16 검수 남은 것).
그때는 '새로 받을 청구서가 없습니다' · '결의서내역 목록을 읽는 중' · '받은 파일은 비목 폴더 바로 아래' 가 떴다. 화면은 offscreen."""
from __future__ import annotations

from test_log_button import _close, _qt_app
from test_project_folders import make


def _page(tmp_path, claims: bool, purchases: bool):
    from claim_downloader import settings
    from claim_downloader.ui.pages.download import DownloadPage

    settings.update(out_root=str(make(tmp_path)))
    page = DownloadPage()
    page.doc_claim.setChecked(claims)
    page.doc_contract.setChecked(purchases)
    page._docs_picked = page._picked = True
    return page


def _purchase_target(no="3"):
    from claim_downloader import purchase
    return {"kind": purchase.KIND, "req_no": "202606170005", "project": "202408470003", "no": no, "expDt": "2026-06-17",
            "cont": "실습 재료 구입", "amt": "49500", "gubun": "구매요청(물품) · 지급완료", "existing": 0}


def test_purchase_only_screen_does_not_talk_about_claims(tmp_path, monkeypatch):
    _qt_app()
    from claim_downloader.session import RunSummary
    from claim_downloader.targets import Selection
    from claim_downloader.ui.pages import download as download_page

    page = _page(tmp_path, claims=False, purchases=True)
    try:
        assert "구매·자산 → 구매진행관리" in page._guide_login() and "청구서" not in page._guide_login()
        assert "결의서" not in page._guide_browser()
        page._reading = True
        page._sync_buttons()
        page._sync_empty()
        assert page.counts.text() == "구매진행관리(구매·자산) 목록을 읽는 중입니다…"
        reading = " ".join(label.text() for label in page.empty.findChildren(download_page.QLabel))
        assert "받을 구매요청(계약) 서류가 여기에" in reading and "결의서" not in reading
        # 받을 것이 없으면 — 끝까지 받은 구매 건과 다시 받는 길
        page._on_listed(Selection(purchase_done=3))
        texts = " ".join(label.text() for label in page.empty.findChildren(download_page.QLabel))
        assert "새로 받을 구매요청(계약) 서류가 없습니다" in texts and "끝까지 받은 건 3건" in texts
        assert "청구서" not in texts and "결의서" not in texts
        # 받을 것이 있으면 — 건수 줄 · 표 머리글
        page._on_listed(Selection(targets=[_purchase_target()], purchase_done=3))
        assert page.counts.text() == "받을 구매요청(계약) 서류 1건 · 끝까지 받은 구매 건 3건 제외"
        heads = [page.table.horizontalHeaderItem(c).text() for c in range(page.table.columnCount())]
        assert heads[3] == "요청일자" and heads[6] == "구분"
        # 보관 폴더(청구서 PDF) 스캔이 실패했어도 구매 건만 받을 때는 그 경고를 띄우지 않는다
        page._archive_ok = False
        monkeypatch.setattr(download_page.QMessageBox, "warning", lambda *a, **k: (_ for _ in ()).throw(AssertionError("경고 창")))
        monkeypatch.setattr(download_page.QMessageBox, "question", lambda *a, **k: download_page.QMessageBox.No)
        page._download(limit=0)
        assert page._run_claims is False
        page._on_finished(RunSummary(ok=1))
        assert "비목 폴더" not in page._guide and "청구서" not in page._guide
        assert all("청구서" not in hint for hint in page._blocked_hints())
    finally:
        _close(page)


def test_claims_only_and_mixed_wording_stay_clear(tmp_path):
    _qt_app()
    from claim_downloader.targets import Selection
    from claim_downloader.ui.pages import download as download_page

    page = _page(tmp_path, claims=True, purchases=False)
    try:
        assert page._guide_login() == download_page.GUIDE_LOGIN and page._noun() == "청구서"
        claim = {"no": "4", "project": "202408470003", "cont": "02_장학금", "amt": "1000", "expDt": "2026-10-01", "docNo": "x"}
        page._on_listed(Selection(targets=[claim], skipped=2))
        assert page.counts.text() == "받을 청구서 1건 · 이미 받아 둔 2건 제외"
        assert page.table.horizontalHeaderItem(3).text() == "지출예정일" and page.table.horizontalHeaderItem(6).text() == "결의서구분"
        page.doc_contract.setChecked(True)
        page._on_listed(Selection(targets=[claim, _purchase_target()], skipped=2, purchase_done=1))
        assert page.counts.text() == "받을 서류 2건(청구서 1 · 구매요청(계약) 1) · 이미 받아 둔 청구서 2건 · 끝까지 받은 구매 건 1건 제외"
        assert page.table.horizontalHeaderItem(3).text() == "일자"
        assert "결의서내역과 구매·자산" in page._guide_login() and len(page._blocked_hints()) == 2
    finally:
        _close(page)
