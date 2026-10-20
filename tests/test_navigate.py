"""로그인 뒤 청구서 화면까지(navigate.py) — 가짜 프레임으로 과제 목록 읽기 · 과제 고르기 칸 · 이동 · 새 청구서를 본다.

실측(2026-10-19 [화면 구조 저장] 1~6번)의 모양을 흉내 낸다. 과제번호는 실측의 것, 과제명은 모양만 같은 가짜.
"""
from __future__ import annotations

import datetime as dt

import pytest

from claim_downloader import erp, navigate, settings
from claim_downloader.claims import card_erp, form

TODAY = dt.date(2026, 10, 19)
ROWS = [
    {"no": "202408470003", "name": "가짜사업(데이터)", "start": "2026-03-01", "end": "2027-02-28", "visible": True},
    {"no": "202409710003", "name": "가짜사업[대응자금]", "start": "2026-03-01", "end": "2027-02-28", "visible": True},
    {"no": "202603130001", "name": "가짜사업_이월금", "start": "2026-03-01", "end": "2026-06-30", "visible": True},
    {"no": "202408470002", "name": "가짜사업(데이터)", "start": "2025-03-01", "end": "2026-02-28", "visible": True},
]


class Screen:
    """ERP 한 창 — 위쪽 탭(메인화면 · 과제정보 · 청구서(일반)) 중 하나만 앞에 보인다(실측 2026-10-19).
    과제정보 · 결의서 목록 · 작성 화면 프레임은 숨은 #PRJ_NO 에 과제번호를 든다."""

    def __init__(self, dashboard=True, visible_projects=True):
        self.dashboard = dashboard     # 로그인됨
        self.visible = visible_projects
        self.active = "main"           # 앞에 있는 위쪽 탭: main · project · sheet
        self.toolbar_prj = ""          # 열린 과제정보의 과제번호
        self.grid_prj = ""             # 결의서 목록의 과제번호(청구서 탭을 누른 과제)
        self.form = None               # 작성 화면 값 {PRJ_NO, REQ_CNT, APPR_DIV_CD, REQ_SEQ_NO, REQ_AMT, REQ_PTCL, RCV_NM}
        self.card = None               # 카드청구 작성 화면 값 — 일반청구 화면과 위쪽 탭 한 자리를 같이 쓴다(14절)
        self.clicks: list[str] = []
        self.sheets = 0
        self.list_rows: list[dict] = []  # 결의서내역 그리드의 행 (erp._PARSE_ROWS_JS 모양)


class Frame:
    def __init__(self, screen: Screen, kind: str):
        self.s, self.kind = screen, kind

    def evaluate(self, js, *args):
        s = self.s
        if js is navigate.PROJECTS_JS:
            # 과제현황은 메인화면 탭이 앞일 때만 보인다. visible_projects=False 는 "고른 과제가 다음 쪽에 있음"
            return [dict(r, visible=s.active == "main") for r in ROWS] if self.kind == "dash" and s.dashboard else []
        if js is navigate.CLICK_PROJECT_JS:
            # 과제현황은 메인화면 탭이 앞에 있을 때만 보인다
            if self.kind != "dash" or not s.dashboard or s.active != "main":
                return {"ok": False, "why": "과제현황에 이 과제가 보이지 않음"}
            if not s.visible or args[0] not in {r["no"] for r in ROWS}:
                return {"ok": False, "why": "과제현황에 이 과제가 보이지 않음"}
            s.clicks.append("project:" + args[0])
            s.toolbar_prj, s.grid_prj, s.active = args[0], "", "project"     # 과제정보 탭을 그 과제로 다시 연다
            return {"ok": True}
        if js is navigate.CLICK_PROJECT_TAB_JS:
            if self.kind != "layout" or not s.toolbar_prj:
                return {"ok": False, "why": "위쪽 '과제정보' 탭이 보이지 않음"}
            s.clicks.append("과제정보")
            s.active = "project"
            return {"ok": True}
        if js is navigate.CLICK_MAIN_TAB_JS:
            if self.kind != "layout" or not s.dashboard:
                return {"ok": False, "why": "위쪽 '메인화면' 탭이 보이지 않음"}
            s.clicks.append("메인화면")
            s.active = "main"
            return {"ok": True}
        if js is navigate.TOOLBAR_JS:
            return {"prj": s.toolbar_prj, "shown": s.active == "project"} if self.kind == "toolbar" and s.toolbar_prj else None
        if js is navigate.CLICK_CLAIM_TAB_JS:
            s.clicks.append("청구서")
            s.grid_prj = s.toolbar_prj
            return {"ok": True}
        if js is navigate.CLICK_NEW_SHEET_JS:
            s.clicks.append("P10:" + s.grid_prj)
            s.sheets += 1
            s.active = "sheet"
            s.card = None
            s.form = {"PRJ_NO": s.grid_prj, "REQ_CNT": "", "APPR_DIV_CD": "", "REQ_SEQ_NO": f"TMP_REQ_{s.sheets}",
                      "REQ_AMT": "0", "REQ_PTCL": "", "RCV_NM": ""}
            return {"ok": True}
        if js is navigate.CLICK_CARD_SHEET_JS:
            s.clicks.append("P11:" + s.grid_prj)
            s.sheets += 1
            s.active = "sheet"
            s.form = None                  # 일반청구 탭 자리가 '청구서(카드)' 로 바뀐다
            s.card = {"PRJ_NO": s.grid_prj, "REQ_CNT": "", "APPR_DIV_CD": "", "REQ_SEQ_NO": f"TMP_REQ_{s.sheets}",
                      "REQ_AMT": "", "REQ_PTCL": "", "RCV_NM": "카드청구"}
            return {"ok": True}
        if js is card_erp.PROBE_JS:
            return self.kind == "card" and s.card is not None
        if js is navigate.PRJ_JS:
            return {"toolbar": s.toolbar_prj or None, "grid": s.grid_prj or None,
                    "form": (s.form or {}).get("PRJ_NO"), "card": (s.card or {}).get("PRJ_NO")}.get(self.kind)
        if js is erp._GRID_PROBE:
            return self.kind == "grid" and bool(s.grid_prj)
        if js is erp.GRID_ROWS_JS:
            return 26 if self.kind == "grid" and s.grid_prj else 0
        if js is form.PROBE_JS:
            return self.kind == "form" and s.form is not None
        if js is form.FRAME_VISIBLE_JS:
            # 위쪽 탭 중 앞에 있는 것의 프레임만 크기가 있다 — 결의서 목록은 과제정보 탭, 작성 화면은 청구서(일반) 탭
            return {"toolbar": "project", "grid": "project", "form": "sheet", "card": "sheet"}.get(self.kind, s.active) == s.active
        if js is erp._PARSE_ROWS_JS:
            return [dict(r) for r in s.list_rows] if self.kind == "grid" and s.grid_prj else []
        if js in (erp._SCROLL_TOP_JS, erp._SCROLL_INFO_JS):
            return None                  # 한 화면에 다 보인다 — 내리지 않는다
        if js is form.STATE_JS:
            values = s.card if self.kind == "card" else s.form
            return {key: {"value": (values or {}).get(key, "")} for key in args[0]}
        if self.kind == "layout":
            return None
        raise AssertionError("모르는 JS: " + str(js)[:60])


class Page:
    def __init__(self, screen: Screen):
        self.frames = [Frame(screen, k) for k in ("layout", "dash", "toolbar", "grid", "form", "card")]

    def wait_for_timeout(self, ms):
        pass

    def bring_to_front(self):
        pass


class Context:
    def __init__(self, screen: Screen):
        self.pages = [Page(screen)]


def no_wait(_seconds):
    pass


def test_projects_are_read_and_only_running_ones_are_choices(isolated_home):
    projects = navigate.read_projects(Context(Screen()))
    assert [p.no for p in projects] == [r["no"] for r in ROWS]
    assert [p.no for p in navigate.running(projects, TODAY)] == ["202408470003", "202409710003"]
    assert navigate.read_projects(Context(Screen(dashboard=False))) == []         # 로그인 전 · 다른 화면

    # 읽기 전에는 기본 과제번호 하나(담당자 지정)
    assert navigate.choices(settings.DEFAULT_PROJECT_NO, TODAY) == [("202408470003", "202408470003")]
    navigate.save_projects(projects)
    loaded, when = navigate.load_projects()
    assert [p.no for p in loaded] == [p.no for p in projects] and when
    choices = navigate.choices("202408470003", TODAY)
    assert [no for no, _ in choices] == ["202408470003", "202409710003"]           # 과제기간에 오늘이 든 과제만
    assert "2026-03-01 ~ 2027-02-28" in choices[0][1]
    # 끝난 과제를 고른 채였으면 칸에서 사라지지 않게 끝에 남기되 기간이 아니라고 적는다
    old = navigate.choices("202603130001", TODAY)
    assert old[-1][0] == "202603130001" and "과제기간 아님" in old[-1][1]


def test_settings_default_project_is_the_one_the_manager_named(isolated_home):
    cfg = settings.load()
    assert cfg.project_no == "202408470003" and cfg.auto_open_project and cfg.auto_new_sheet


def test_go_to_claims_opens_project_then_claim_tab():
    screen = Screen()
    logs = []
    ok, message = navigate.go_to_claims(Context(screen), "202408470003", logs.append, no_wait)
    assert ok, message
    assert screen.clicks == ["project:202408470003", "청구서"]
    # 이미 목록이 떠 있으면 아무것도 누르지 않는다
    ok, _ = navigate.go_to_claims(Context(screen), "202408470003", logs.append, no_wait)
    assert ok and screen.clicks == ["project:202408470003", "청구서"]


def test_go_to_claims_uses_an_open_project_page_without_touching_the_dashboard():
    screen = Screen()
    screen.toolbar_prj, screen.active = "202408470003", "project"
    ok, _ = navigate.go_to_claims(Context(screen), "202408470003", lambda m: None, no_wait)
    assert ok and screen.clicks == ["청구서"]


def test_go_to_claims_leaves_it_to_a_person_when_the_project_is_not_shown():
    screen = Screen(visible_projects=False)
    ok, message = navigate.go_to_claims(Context(screen), "202408470003", lambda m: None, no_wait)
    assert not ok and "보이지 않습니다" in message and screen.clicks == []


def test_new_sheet_is_opened_from_the_list_only_over_a_saved_empty_sheet():
    screen = Screen()
    screen.toolbar_prj = screen.grid_prj = "202408470003"
    ctx = Context(screen)
    # 작성 화면이 없으면 띄운다
    ok, _note, frame = navigate.open_new_sheet(ctx, lambda m: None, no_wait)
    assert ok and frame is not None and screen.clicks == ["P10:202408470003"]
    # 저장 전(결의번호 없음) 화면이면 이미 새 청구서 — 누르지 않는다
    ok, note, _ = navigate.open_new_sheet(ctx, lambda m: None, no_wait)
    assert not ok and "저장 전" in note and screen.clicks == ["P10:202408470003"]
    # 저장된 청구서인데 입력이 남아 있으면 날아가므로 누르지 않는다
    screen.form.update(REQ_CNT="327", APPR_DIV_CD="40", REQ_PTCL="03_적요_가나다")
    ok, note, _ = navigate.open_new_sheet(ctx, lambda m: None, no_wait)
    assert not ok and "저장하지 않은 입력(적요)" in note and screen.clicks == ["P10:202408470003"]
    # 저장된 청구서이고 칸이 비었으면(저장 뒤 실측 ⑤) 새로 띄운다
    screen.form.update(REQ_PTCL="")
    ok, _note, frame = navigate.open_new_sheet(ctx, lambda m: None, no_wait)
    assert ok and screen.clicks == ["P10:202408470003"] * 2 and screen.form["REQ_SEQ_NO"] == "TMP_REQ_2"


def test_card_sheet_is_opened_from_the_list_unless_something_unsaved_is_on_screen():
    """결의서 목록의 [카드청구](#P11, 담당자 허락 2026-10-20). 일반청구 · 카드 작성 화면은 한 탭 자리라 저장하지 않은 입력이 있으면 누르지 않는다."""
    screen = Screen()
    screen.toolbar_prj = screen.grid_prj = "202408470003"
    ctx = Context(screen)
    # 일반청구 화면에 적다 만 입력이 있으면 그 탭이 카드로 바뀌며 날아간다 — 누르지 않는다
    screen.form = {"PRJ_NO": "202408470003", "REQ_CNT": "", "REQ_PTCL": "09_적다 만 적요", "REQ_AMT": "0", "RCV_NM": ""}
    ok, note, _ = navigate.open_card_sheet(ctx, lambda m: None, no_wait, "202408470003")
    assert not ok and "일반청구 작성 화면에 저장하지 않은 입력(적요)" in note and screen.clicks == []
    # 저장된 일반청구 화면(칸이 빔)이면 띄운다
    screen.form.update(REQ_CNT="330", APPR_DIV_CD="40", REQ_PTCL="")
    ok, _note, frame = navigate.open_card_sheet(ctx, lambda m: None, no_wait, "202408470003")
    assert ok and frame is not None and screen.clicks == ["P11:202408470003"] and screen.form is None
    assert card_erp.find_card_form(ctx)[1] is frame
    # 이미 새 카드 화면이면 누르지 않는다 — 결의서내역을 읽느라 뒤로 갔으면(replace_empty) 다시 띄워 앞으로
    ok, note, _ = navigate.open_card_sheet(ctx, lambda m: None, no_wait, "202408470003")
    assert not ok and "저장 전" in note and screen.clicks == ["P11:202408470003"]
    ok, _note, _ = navigate.open_card_sheet(ctx, lambda m: None, no_wait, "202408470003", replace_empty=True)
    assert ok and screen.clicks == ["P11:202408470003"] * 2
    # 결제 건을 골라 청구액이 들어온 화면은 날리지 않는다(숨은 입금처 '카드청구' 는 입력으로 보지 않는다)
    screen.card.update(REQ_AMT="45,000")
    ok, note, _ = navigate.open_card_sheet(ctx, lambda m: None, no_wait, "202408470003", replace_empty=True)
    assert not ok and "저장하지 않은 입력(청구액)" in note and len(screen.clicks) == 2
    # 저장된 카드 청구서(칸이 빔)면 다음 청구서를 띄운다
    screen.card.update(REQ_AMT="", REQ_CNT="335", APPR_DIV_CD="40")
    ok, _note, _ = navigate.open_card_sheet(ctx, lambda m: None, no_wait, "202408470003")
    assert ok and len(screen.clicks) == 3 and screen.card["REQ_CNT"] == ""


def test_new_sheet_needs_the_list():
    screen = Screen()
    ok, note, frame = navigate.open_new_sheet(Context(screen), lambda m: None, no_wait)
    assert not ok and frame is None and "결의서 목록" in note and screen.clicks == []


def test_watcher_reads_projects_and_goes_to_claims_after_login(isolated_home, monkeypatch):
    """브라우저를 연 뒤 지켜보다가 로그인(대시보드)이 보이면 과제 목록을 남기고 청구서 탭까지 간다 — 한 번만."""
    pytest.importorskip("PySide6")
    from claim_downloader.ui import worker as worker_mod

    screen = Screen(dashboard=False)
    ticks = {"n": 0}

    class FakeSession:
        browser_open = True

        def __init__(self):
            self.page = Page(screen)
            self.page.context = Context(screen)
            self.logs = []
            self.went = []

        def log(self, message):
            self.logs.append(message)

        def read_projects(self):
            ticks["n"] += 1
            if ticks["n"] >= 2:
                screen.dashboard = True                  # 두 번째로 볼 때 사람이 로그인을 마쳤다
            return navigate.read_projects(self.page.context)

        def go_to_claims(self, no):
            self.went.append(no)
            return navigate.go_to_claims(self.page.context, no, self.log, no_wait)

    w = worker_mod.SessionWorker.__new__(worker_mod.SessionWorker)
    worker_mod.QObject.__init__(w)
    import queue
    w._queue = queue.Queue()
    ready, read = [], []
    w.list_ready.connect(lambda: ready.append(1))
    w.projects_read.connect(lambda: read.append(1))
    session = FakeSession()
    w._watch_for_list(session, ready=True, project_no="202408470003")
    assert session.went == ["202408470003"] and screen.clicks == ["project:202408470003", "청구서"]
    assert read == [1] and ready == [1]
    assert [p.no for p in navigate.load_projects()[0]][:2] == ["202408470003", "202409710003"]


def test_folder_project_switches_from_another_projects_screen():
    """폴더마다 과제가 다르다(담당자 2026-10-19) — 다른 과제의 작성 화면이 앞에 있으면 메인화면 탭 → 그 과제 → 청구서 → [일반청구]."""
    screen = Screen()
    ctx = Context(screen)
    ok, _ = navigate.go_to_claims(ctx, "202408470003", lambda m: None, no_wait)
    ok, _note, _ = navigate.open_new_sheet(ctx, lambda m: None, no_wait, "202408470003")
    assert ok and screen.active == "sheet"
    screen.form.update(REQ_CNT="327", APPR_DIV_CD="40")            # 앞 폴더를 저장했다
    # 이번 폴더는 다른 과제 — 그 과제의 목록이 없으니 메인화면으로 돌아가 연다
    assert navigate.list_frame(ctx, "202409710003") is None
    ok, message = navigate.go_to_claims(ctx, "202409710003", lambda m: None, no_wait)
    assert ok, message
    ok, _note, frame = navigate.open_new_sheet(ctx, lambda m: None, no_wait, "202409710003")
    assert ok and navigate.frame_project(frame) == "202409710003"
    assert screen.clicks == ["project:202408470003", "청구서", "P10:202408470003",
                             "메인화면", "project:202409710003", "청구서", "P10:202409710003"]


def test_unsaved_empty_sheet_of_another_project_is_replaced_but_typed_one_is_not():
    screen = Screen()
    ctx = Context(screen)
    navigate.go_to_claims(ctx, "202408470003", lambda m: None, no_wait)
    navigate.open_new_sheet(ctx, lambda m: None, no_wait, "202408470003")
    navigate.go_to_claims(ctx, "202409710003", lambda m: None, no_wait)
    # 저장 전이어도 다른 과제의 빈 작성 화면이면 바꾼다
    ok, _note, frame = navigate.open_new_sheet(ctx, lambda m: None, no_wait, "202409710003")
    assert ok and navigate.frame_project(frame) == "202409710003"
    # 입력이 남은 화면이면 과제가 달라도 누르지 않는다
    screen.form.update(REQ_PTCL="03_적요")
    ok, note, _ = navigate.open_new_sheet(ctx, lambda m: None, no_wait, "202408470003")
    assert not ok and "저장하지 않은 입력" in note


def _row(seq, cont, state="임시저장", amt="300000"):
    return {"r": seq, "no": seq, "seq": seq, "gubun": "일반청구", "cont": cont, "amt": amt, "state": state,
            "docNo": "", "expDt": ""}


SUMMARY = "02_2026년도 9월 (가)형 근로장학금"


def test_existing_claims_reads_the_project_list_and_matches_whole_summary():
    """넣기 전 ERP 결의서내역 확인(담당자 요청 2026-10-19) — 작성 화면이 앞에 있으면 '과제정보' 탭으로 목록을 앞에 두고 읽기만 한다.
    대표적요가 통째로 같은 줄만(공백 무시) — [시험] 청구서 · 다른 달은 같은 것이 아니다."""
    screen = Screen()
    ctx = Context(screen)
    navigate.go_to_claims(ctx, "202408470003", lambda m: None, no_wait)
    navigate.open_new_sheet(ctx, lambda m: None, no_wait, "202408470003")
    screen.list_rows = [_row("324", SUMMARY.replace(" ", "  ")), _row("325", "[시험] " + SUMMARY),
                        _row("310", "02_2026년도 8월 (가)형 근로장학금", state="승인")]
    clicks = list(screen.clicks)
    rows, total, why = navigate.existing_claims(ctx, "202408470003", SUMMARY, lambda m: None, no_wait)
    assert [r["seq"] for r in rows] == ["324"] and total == 3 and why == ""
    assert screen.clicks == clicks + ["과제정보"]                       # 읽으려고 탭만 옮겼다 — 목록에서 아무것도 누르지 않는다
    # 시험 청구서는 [시험] 이 붙은 대표적요로만 같다
    rows, _total, _why = navigate.existing_claims(ctx, "202408470003", "[시험] " + SUMMARY, lambda m: None, no_wait)
    assert [r["seq"] for r in rows] == ["325"]


def test_existing_claims_without_moving_reads_only_a_list_in_front():
    screen = Screen()
    ctx = Context(screen)
    navigate.go_to_claims(ctx, "202408470003", lambda m: None, no_wait)
    navigate.open_new_sheet(ctx, lambda m: None, no_wait, "202408470003")
    rows, _total, why = navigate.existing_claims(ctx, "202408470003", SUMMARY, lambda m: None, no_wait, move=False)
    assert rows is None and "앞에 없음" in why and screen.active == "sheet"       # 사람이 띄운 작성 화면을 가리지 않는다


def test_existing_claims_opens_the_project_from_the_dashboard():
    screen = Screen()
    screen.list_rows = [_row("324", SUMMARY)]
    rows, total, _why = navigate.existing_claims(Context(screen), "202408470003", SUMMARY, lambda m: None, no_wait)
    assert [r["seq"] for r in rows] == ["324"] and total == 1
    assert screen.clicks == ["project:202408470003", "청구서"]
    # 과제가 과제현황에 안 보이면 읽지 못한 것(None) — 앱 기록으로 넘어간다
    rows, _total, why = navigate.existing_claims(Context(Screen(visible_projects=False)), "202408470003", SUMMARY,
                                                 lambda m: None, no_wait)
    assert rows is None and why


def _session(screen, auto_new_sheet=True):
    from claim_downloader.session import ErpSession

    logs = []
    s = ErpSession(logs.append, lambda m: True,
                   load_settings=lambda: settings.Settings(auto_new_sheet=auto_new_sheet))
    s.page = Page(screen)
    s.page.context = Context(screen)
    return s, logs


def test_duplicate_check_asks_when_erp_has_the_same_summary(isolated_home):
    screen = Screen()
    screen.list_rows = [_row("324", SUMMARY, amt="5100000")]
    s, logs = _session(screen)
    asked = []
    stop = s._duplicate_check(SUMMARY, "202408470003", lambda m: asked.append(m) or False, False)
    assert stop and "같은 청구서" in stop
    assert "결의번호 324(임시저장 · 5,100,000원)" in asked[0] and "[시험]" in asked[0]
    # [계속] 하면 이어 간다
    assert s._duplicate_check(SUMMARY, "202408470003", lambda m: True, False) == ""
    # 같은 것이 없으면 묻지 않는다 — 앱 기록에 넣은 이력이 있어도(ERP 에서 지웠으면 다시 넣는다)
    screen.list_rows = [_row("324", "[시험] " + SUMMARY)]
    asked.clear()
    assert s._duplicate_check(SUMMARY, "202408470003", lambda m: asked.append(m) or False, False,
                              lambda: "이 폴더를 넣은 이력") == ""
    assert asked == [] and any("같은 청구서 없음" in line for line in logs)


def test_duplicate_check_falls_back_to_app_record_only_when_the_list_cannot_be_read(isolated_home):
    s, logs = _session(Screen(visible_projects=False))
    asked = []
    stop = s._duplicate_check(SUMMARY, "202408470003", lambda m: asked.append(m) or False, False,
                              lambda: "이 폴더를 넣은 이력: 10-14")
    assert stop and "앱 기록" in asked[0] and "이 폴더를 넣은 이력" in asked[0]
    asked.clear()
    assert s._duplicate_check(SUMMARY, "202408470003", lambda m: asked.append(m) or False, False, lambda: "") == ""
    assert asked == []


def test_test_mode_skips_the_erp_check(isolated_home):
    screen = Screen()
    screen.list_rows = [_row("324", SUMMARY)]
    s, logs = _session(screen)
    assert s._duplicate_check(SUMMARY, "202408470003", lambda m: False, True) == ""
    assert screen.clicks == [] and any("시험" in line for line in logs)
