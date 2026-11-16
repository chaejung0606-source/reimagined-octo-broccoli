"""마지막 단계의 [새로 시작] — 업무 화면 여섯 모두 마지막 단계에 같은 단추가 있고, 누르면 ① 부터(담당자 2026-11-16 "업무카드별로 마지막 단계에
이 업무카드를 새로 시작할 수 있는 버튼"). 아직 끝내지 않은 것이 화면에서 사라질 때만 한 번 묻는다. 화면은 offscreen 으로 띄운다."""
from __future__ import annotations

from test_log_button import _close, _qt_app, _wait
from test_project_folders import make
from test_scholarship import make_ga  # noqa: F401 — 가짜 명단


def _states(page) -> dict:
    return {key: step.state for key, step in page.steps.items()}


def _ask(monkeypatch, answer: bool | None):
    """[새로 시작] 의 물음 — answer 가 None 이면 묻지 않아야 한다(물으면 실패)."""
    from claim_downloader.ui import flow

    asked: list[str] = []

    def question(_parent, _title, text, *_a, **_k):
        if answer is None:
            raise AssertionError("묻지 않아야 한다: " + text)
        asked.append(text)
        return flow.QMessageBox.Yes if answer else flow.QMessageBox.No
    monkeypatch.setattr(flow.QMessageBox, "question", question)
    return asked


def test_every_work_page_has_restart_in_its_last_step(tmp_path):
    _qt_app()
    from claim_downloader.ui.flow import RESTART_TEXT, RestartButton
    from claim_downloader.ui.pages.claim import ClaimPage
    from claim_downloader.ui.pages.download import DownloadPage
    from claim_downloader.ui.pages.minutes import MinutesPage
    from claim_downloader.ui.pages.parking import ParkingPage
    from claim_downloader.ui.pages.structure import StructurePage
    from claim_downloader.ui.pages.travel import TravelPage
    from claim_downloader.ui.worker import SessionWorker

    worker = SessionWorker()
    pages = [DownloadPage(worker=worker), MinutesPage(), ClaimPage(worker=worker), ParkingPage(worker=worker),
             StructurePage(worker=worker), TravelPage()]
    download, minutes, claim, parking, structure, travel = pages
    try:
        last = {download: download.step_list, minutes: minutes.step_result, claim: claim.step_put,
                parking: parking.step_result, structure: structure.step_send, travel: travel.step_make}
        for page, step in last.items():
            buttons = step.findChildren(RestartButton)
            assert len(buttons) == 1 and buttons[0].text() == RESTART_TEXT, type(page).__name__
            # 다른 단계에는 없다(주차등록의 ② 는 '관리대장' 이 마지막 단계라 하나 더)
            others = [s for s in page.steps.values() if s is not step] if hasattr(page, "steps") else []
            extra = sum(len(s.findChildren(RestartButton)) for s in others)
            assert extra == (1 if page is parking else 0), type(page).__name__
        assert len(travel.findChildren(RestartButton)) == 1
    finally:
        for page in pages:
            _close(page)


def test_download_restart_goes_back_to_docs(tmp_path, monkeypatch):
    app = _qt_app()
    from claim_downloader import settings
    from claim_downloader.targets import Selection
    from claim_downloader.ui.flow import CURRENT, HIDDEN
    from claim_downloader.ui.pages.download import DownloadPage

    root = make(tmp_path)
    settings.update(out_root=str(root))
    page = DownloadPage()
    try:
        page.doc_contract.setChecked(True)
        page._browser_open = True
        target = {"no": "3", "project": "202408470003", "cont": "02_장학금", "amt": "1000", "expDt": "2026-10-01",
                  "docNo": "202408470003-20261001-3"}
        page._on_listed(Selection(targets=[target, dict(target, no="4", docNo="202408470003-20261001-4")]))
        assert _states(page)["list"] == CURRENT and page.table.rowCount() == 2
        assert page.restart_button.isVisibleTo(page) and page.restart_button.isEnabled()
        # 받는 중에는 누를 수 없다
        page._busy = True
        page._sync_buttons()
        assert not page.restart_button.isEnabled()
        page._busy = False
        page._sync_buttons()
        # 아직 안 받은 건이 있으면 묻고 — [아니요] 면 그대로
        asked = _ask(monkeypatch, False)
        page.restart_button.click()
        assert asked and "2건" in asked[0] and page.table.rowCount() == 2 and _states(page)["list"] == CURRENT
        asked = _ask(monkeypatch, True)
        page.restart_button.click()
        assert asked and page.table.rowCount() == 0 and not page._listed and not page._targets
        assert _states(page) == {"docs": CURRENT, "project": HIDDEN, "login": HIDDEN, "list": HIDDEN}
        assert page.resumable() == (False, "") and page.state_pill.text() == "준비"
        # 받을 서류 체크 · 브라우저는 그대로 — ① [다음] 이면 이어서 할 수 있다
        assert page.doc_claim.isChecked() and page.doc_contract.isChecked() and page._browser_open
        page.docs_button.click()
        assert _states(page)["project"] == CURRENT
        # 다 받았으면 묻지 않는다
        page._on_listed(Selection(targets=[target]))
        page._status = ["done"]
        _ask(monkeypatch, None)
        page.restart_button.click()
        assert _states(page)["docs"] == CURRENT
        app.processEvents()
    finally:
        _close(page)


def test_minutes_restart_clears_meetings(tmp_path, monkeypatch):
    _qt_app()
    from claim_downloader.ui.flow import CURRENT, HIDDEN
    from claim_downloader.ui.pages.minutes import MinutesPage

    page = MinutesPage()
    try:
        for name in ("2026-10-01 회의", "2026-10-08 회의"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "자료.txt").write_text("회의 자료", encoding="utf-8")
            assert page.add_meeting_dir(str(tmp_path / name))
        page._finished = True
        page._status = ["done", "failed"]
        page._sync_buttons()
        assert _states(page)["result"] == CURRENT and page.restart_button.isVisibleTo(page)
        page._running = True
        page._sync_buttons()
        assert not page.restart_button.isEnabled()
        page.start_over()
        assert len(page._dirs) == 2                             # 만드는 중에는 비우지 않는다
        page._running = False
        page._sync_buttons()
        asked = _ask(monkeypatch, True)
        page.restart_button.click()
        assert asked and "1건" in asked[0]                       # 만들지 못한 회의가 빠진다고 묻는다
        assert page._dirs == [] and page.table.rowCount() == 0 and not page._finished
        assert _states(page) == {"folders": CURRENT, "make": HIDDEN, "result": HIDDEN}
        # 다 만들었으면 묻지 않는다
        assert page.add_meeting_dir(str(tmp_path / "2026-10-01 회의"))
        page._finished, page._status = True, ["done"]
        page._sync_buttons()
        _ask(monkeypatch, None)
        page.restart_button.click()
        assert page._dirs == [] and _states(page)["folders"] == CURRENT
    finally:
        _close(page)


def test_claim_restart_goes_back_to_kind(tmp_path, monkeypatch):
    app = _qt_app()
    from claim_downloader.claims import kinds
    from claim_downloader.ui.flow import CURRENT, HIDDEN
    from claim_downloader.ui.pages import claim as claim_page
    from claim_downloader.ui.worker import SessionWorker

    folder = tmp_path / "7월"
    folder.mkdir()
    make_ga(folder / "2026학년도 (가)형 근로장학금 지급내역.xlsx")
    page = claim_page.ClaimPage(worker=SessionWorker())
    try:
        page._choose_kind(kinds.SCHOLARSHIP)
        assert page.add_folder(str(folder))
        assert _wait(app, lambda: page._jobs and page._jobs[0] is not None, 10)
        page._sync_buttons()
        assert _states(page)["put"] == CURRENT and page.restart_button.isVisibleTo(page)
        # ERP 에 넣는 중에는 누를 수 없다
        page._erp_running = True
        page._sync_buttons()
        assert not page.restart_button.isEnabled()
        page.start_over()
        assert page._dirs
        page._erp_running = False
        page._sync_buttons()
        asked = _ask(monkeypatch, True)
        page.restart_button.click()
        assert asked and "1개" in asked[0]                       # 아직 임시저장하지 않은 폴더가 빠진다고 묻는다
        assert page._dirs == [] and page.table.rowCount() == 0 and not page._kind_picked
        assert _states(page) == {"kind": CURRENT, "add": HIDDEN, "check": HIDDEN, "put": HIDDEN}
        assert not any(card.objectName() == "cardCurrent" for card in page.kind_cards.values())
        # 카드 AI 가 뒤에서 아직 읽는 중이어도 ① 에서 종류를 고를 수 있다(넣는 중일 때만 막는다)
        page._ai_reading = {"결제 건"}
        page._choose_kind(kinds.CARD)
        assert page._kind_picked and _states(page)["add"] == CURRENT
        page._ai_reading = set()
        # 다 임시저장했으면 묻지 않는다
        assert page.add_folder(str(folder), kinds.SCHOLARSHIP)
        assert _wait(app, lambda: page._jobs and page._jobs[0] is not None, 10)
        page._set_status(0, "saved")
        _ask(monkeypatch, None)
        page._sync_buttons()
        page.restart_button.click()
        assert page._dirs == [] and _states(page)["kind"] == CURRENT
    finally:
        _close(page)


def test_parking_restart_from_result_and_ledger(tmp_path, monkeypatch):
    _qt_app()
    from claim_downloader.ui.flow import CURRENT, HIDDEN
    from claim_downloader.ui.pages import parking as parking_page
    from claim_downloader.ui.worker import SessionWorker

    page = parking_page.ParkingPage(worker=SessionWorker())
    monkeypatch.setattr(page.worker, "read_parking_history", lambda: None)       # 관리대장을 고르면 사이트를 읽으려 한다 — 부르지 않는다
    _ask(monkeypatch, None)                                                       # 주차등록은 묻지 않는다(관리대장은 그대로)
    try:
        page._choose(parking_page.APPLY)
        page.car_edit.setText("12가3456")
        page._done_cars = ["✓ 12가3456"]
        page._show_result("적용됨", "success", "✓ 12가3456")
        assert _states(page) == {"what": "done", "work": "open", "result": CURRENT}
        assert page.restart_button.isVisibleTo(page) and not page.work_restart_button.isVisibleTo(page)
        page._on_busy(True, "")
        assert not page.restart_button.isEnabled()
        page._on_busy(False, "")
        page.restart_button.click()
        assert _states(page) == {"what": CURRENT, "work": HIDDEN, "result": HIDDEN}
        assert page.car_edit.text() == "" and page._done_cars == [] and page.result.text() == ""
        assert not any(o.objectName() == "cardCurrent" for o in page.options.values())
        # '관리대장' 은 ② 가 마지막 단계 — 그 자리의 단추로
        page._choose(parking_page.HISTORY)
        assert _states(page)["work"] == CURRENT and page.work_restart_button.isVisibleTo(page)
        page.work_restart_button.click()
        assert _states(page)["what"] == CURRENT and not page._picked
        page._choose(parking_page.LINK)
        assert not page.work_restart_button.isVisibleTo(page)
    finally:
        _close(page)


def test_structure_restart_goes_back_to_site(monkeypatch):
    _qt_app()
    from claim_downloader.ui.flow import CURRENT, HIDDEN
    from claim_downloader.ui.pages.structure import StructurePage
    from claim_downloader.ui.worker import SessionWorker

    worker = SessionWorker()
    page = StructurePage(worker=worker)
    _ask(monkeypatch, None)
    try:
        worker.sites = dict(worker.sites, erp=True, erp_login=True)
        page._choose("erp")
        page._saved = True
        page.last.setText("ERP 화면을 저장했습니다")
        page._sync()
        assert _states(page)["send"] == CURRENT and page.restart_button.isVisibleTo(page)
        page.restart_button.click()
        assert _states(page) == {"site": CURRENT, "open": HIDDEN, "save": HIDDEN, "send": HIDDEN}
        assert page._site == "" and not page._saved and page.last.text() == ""
    finally:
        _close(page)


def test_travel_restart_clears_folders(tmp_path, monkeypatch):
    _qt_app()
    from claim_downloader.ui.flow import CURRENT, HIDDEN, OPEN
    from claim_downloader.ui.pages import travel as travel_page
    from test_travel_people import FakeWorker, _image

    folders = []
    for name in ("출장비 지급(26.11.10. 원주)", "출장비 지급(26.11.12. 강릉)"):
        folder = tmp_path / name
        folder.mkdir()
        _image(folder / "홍길동_체류증빙 1110.png")
        folders.append(folder)
    page = travel_page.TravelPage(worker=FakeWorker(tmp_path))
    page.show()
    try:
        page._add_folders(folders)
        page.load_folder(str(folders[0]))
        page.name_edit.setText("홍길동")
        page._go("files")
        assert page.step_make.state == OPEN and page.restart_button.isVisibleTo(page)
        asked = _ask(monkeypatch, False)
        page.restart_button.click()
        assert asked and "2개" in asked[0] and page.folder_list.count() == 2       # [아니요] — 그대로
        asked = _ask(monkeypatch, True)
        page.restart_button.click()
        assert asked and page.folder_list.count() == 0 and page.folder_edit.text() == ""
        assert page._stage == "folder" and page.step_folder.state == CURRENT
        assert page.step_info.state == HIDDEN and page.step_make.state == HIDDEN and page.step_files.state == HIDDEN
        assert page.name_edit.text() == "" and page._done_folders == set() and page._groups == []
        assert all(not table.paths for table in page.tables.values())
        # 뒤에서 끝난 AI 읽기가 비운 화면에 앞 폴더 소식을 띄우지 않는다
        page._ai_running = 1
        page._on_ai_finished("")
        assert page.ai_note.isHidden()
        # 다 만든 폴더뿐이면 묻지 않는다
        page._add_folders([folders[0]])
        page._done_folders.add(str(folders[0]))
        _ask(monkeypatch, None)
        page.start_over()
        assert page.folder_list.count() == 0
    finally:
        _close(page)


def test_restart_button_only_asks_when_told(monkeypatch):
    _qt_app()
    from claim_downloader.ui.flow import RestartButton

    calls = []
    button = RestartButton(lambda: calls.append("restart"))
    _ask(monkeypatch, None)
    button.click()
    assert calls == ["restart"]
    asked = _ask(monkeypatch, False)
    button = RestartButton(lambda: calls.append("again"), lambda: "남은 것이 사라집니다")
    button.click()
    assert asked == ["남은 것이 사라집니다"] and calls == ["restart"]
    _close(button)
