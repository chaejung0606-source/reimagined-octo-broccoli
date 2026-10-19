"""로그인 뒤 청구서 화면까지(navigate.py) — 가짜 프레임으로 과제 목록 읽기 · 과제 고르기 칸 · 이동 · 새 청구서를 본다.

실측(2026-10-19 [화면 구조 저장] 1~6번)의 모양을 흉내 낸다. 과제번호는 실측의 것, 과제명은 모양만 같은 가짜.
"""
from __future__ import annotations

import datetime as dt

import pytest

from claim_downloader import erp, navigate, settings
from claim_downloader.claims import form

TODAY = dt.date(2026, 10, 19)
ROWS = [
    {"no": "202408470003", "name": "가짜사업(데이터)", "start": "2026-03-01", "end": "2027-02-28", "visible": True},
    {"no": "202409710003", "name": "가짜사업[대응자금]", "start": "2026-03-01", "end": "2027-02-28", "visible": True},
    {"no": "202603130001", "name": "가짜사업_이월금", "start": "2026-03-01", "end": "2026-06-30", "visible": True},
    {"no": "202408470002", "name": "가짜사업(데이터)", "start": "2025-03-01", "end": "2026-02-28", "visible": True},
]


class Screen:
    """ERP 한 창 — 대시보드 · 과제정보 · 결의서 목록 · 작성 화면 프레임의 상태를 함께 들고 있다."""

    def __init__(self, dashboard=True, visible_projects=True):
        self.dashboard = dashboard
        self.visible = visible_projects
        self.toolbar_prj = ""          # 열린 과제정보의 과제번호
        self.grid = False              # 결의서 목록이 떴는지
        self.form = None               # 작성 화면 값 {REQ_CNT, APPR_DIV_CD, REQ_SEQ_NO, REQ_AMT, REQ_PTCL, RCV_NM}
        self.clicks: list[str] = []
        self.sheets = 0


class Frame:
    def __init__(self, screen: Screen, kind: str):
        self.s, self.kind = screen, kind

    def evaluate(self, js, *args):
        s = self.s
        if js is navigate.PROJECTS_JS:
            return [dict(r, visible=s.visible) for r in ROWS] if self.kind == "dash" and s.dashboard else []
        if js is navigate.CLICK_PROJECT_JS:
            if self.kind != "dash" or not s.dashboard:
                return {"ok": False, "why": "과제현황에 이 과제가 보이지 않음"}
            if not s.visible or args[0] not in {r["no"] for r in ROWS}:
                return {"ok": False, "why": "과제현황에 이 과제가 보이지 않음"}
            s.clicks.append("project:" + args[0])
            s.toolbar_prj = args[0]
            return {"ok": True}
        if js is navigate.TOOLBAR_JS:
            return {"prj": s.toolbar_prj, "shown": True} if self.kind == "toolbar" and s.toolbar_prj else None
        if js is navigate.CLICK_CLAIM_TAB_JS:
            s.clicks.append("청구서")
            s.grid = True
            return {"ok": True}
        if js is navigate.CLICK_NEW_SHEET_JS:
            s.clicks.append("P10")
            s.sheets += 1
            s.form = {"REQ_CNT": "", "APPR_DIV_CD": "", "REQ_SEQ_NO": f"TMP_REQ_{s.sheets}", "REQ_AMT": "0", "REQ_PTCL": "", "RCV_NM": ""}
            return {"ok": True}
        if js is erp._GRID_PROBE:
            return self.kind == "grid" and s.grid
        if js is erp.GRID_ROWS_JS:
            return 26 if self.kind == "grid" and s.grid else 0
        if js is form.PROBE_JS:
            return self.kind == "form" and s.form is not None
        if js is form.FRAME_VISIBLE_JS:
            return True
        if js is form.STATE_JS:
            return {key: {"value": (s.form or {}).get(key, "")} for key in args[0]}
        raise AssertionError("모르는 JS: " + str(js)[:60])


class Page:
    def __init__(self, screen: Screen):
        self.frames = [Frame(screen, k) for k in ("dash", "toolbar", "grid", "form")]

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
    screen.toolbar_prj = "202408470003"
    ok, _ = navigate.go_to_claims(Context(screen), "202408470003", lambda m: None, no_wait)
    assert ok and screen.clicks == ["청구서"]


def test_go_to_claims_leaves_it_to_a_person_when_the_project_is_not_shown():
    screen = Screen(visible_projects=False)
    ok, message = navigate.go_to_claims(Context(screen), "202408470003", lambda m: None, no_wait)
    assert not ok and "보이지 않습니다" in message and screen.clicks == []


def test_new_sheet_is_opened_from_the_list_only_over_a_saved_empty_sheet():
    screen = Screen()
    screen.grid = True
    ctx = Context(screen)
    # 작성 화면이 없으면 띄운다
    ok, _note, frame = navigate.open_new_sheet(ctx, lambda m: None, no_wait)
    assert ok and frame is not None and screen.clicks == ["P10"]
    # 저장 전(결의번호 없음) 화면이면 이미 새 청구서 — 누르지 않는다
    ok, note, _ = navigate.open_new_sheet(ctx, lambda m: None, no_wait)
    assert not ok and "저장 전" in note and screen.clicks == ["P10"]
    # 저장된 청구서인데 입력이 남아 있으면 날아가므로 누르지 않는다
    screen.form.update(REQ_CNT="327", APPR_DIV_CD="40", REQ_PTCL="03_적요_가나다")
    ok, note, _ = navigate.open_new_sheet(ctx, lambda m: None, no_wait)
    assert not ok and "저장하지 않은 입력(적요)" in note and screen.clicks == ["P10"]
    # 저장된 청구서이고 칸이 비었으면(저장 뒤 실측 ⑤) 새로 띄운다
    screen.form.update(REQ_PTCL="")
    ok, _note, frame = navigate.open_new_sheet(ctx, lambda m: None, no_wait)
    assert ok and screen.clicks == ["P10", "P10"] and screen.form["REQ_SEQ_NO"] == "TMP_REQ_2"


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
