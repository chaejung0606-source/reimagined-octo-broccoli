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
        self.pages: list[list[str]] | None = None   # 과제현황 쪽 나눔(#prevBtn · #nextBtn) — 쪽마다 보이는 과제번호
        self.page_index = 0
        self.numbered = False       # True — 쪽 번호 링크 · 지금 쪽 숫자(실측 2026-10-21 17:36: #prevBtn · <a id="1">1</a> · <strong>2</strong> · #nextBtn)
        self.filter = "전체과제"     # 과제현황 거르기(#SEARCH_GB). '진행과제' 면 all_pages 는 '전체과제' 로 바꿔야 보인다
        self.all_pages: list[list[str]] | None = None
        self.filter_reloads = True  # False — 보기를 골라도 [검색] 을 눌러야 목록이 바뀐다
        self.script_pages = True    # False — 화면 스크립트의 click() 으로는 쪽이 안 바뀐다(2026-10-21 실제 ERP 에서 겪은 모양)
        self.mouse_pages = True     # False — 마우스로 눌러도 안 됨(Playwright 오류)
        self.mouse: list[str] = []
        self.lists: dict[str, list[dict]] = {}      # 과제마다 결의서내역 행(있으면 list_rows 대신)
        self.sub = "claims"           # 과제정보의 하위 탭: claims(청구서 — 결의서 목록이 보임) · budget(예산)
        self.dom_is_page = False      # True — 실제 ERP 처럼 지금 거르기 · 지금 쪽의 줄만 화면에 있다(다른 쪽의 과제는 기간을 읽을 수 없다)
        self.budgets: dict[str, list[list[str]]] = {}   # 과제마다 예산 탭 예산내역의 [비목코드, 비목명] 차례

    def on_page(self, no: str) -> bool:
        return self.pages is None or no in self.pages[self.page_index]


class Frame:
    url = ""                                 # 진단 줄(erp.dump_context)이 읽는다

    def __init__(self, screen: Screen, kind: str):
        self.s, self.kind = screen, kind

    def evaluate(self, js, *args):
        s = self.s
        if js is navigate.BUDGET_JS:
            if self.kind != "budget" or s.active != "project" or s.sub != "budget" or s.toolbar_prj not in s.budgets:
                return None
            return {"prj": s.toolbar_prj, "shown": True, "items": [list(x) for x in s.budgets[s.toolbar_prj]]}
        if js is navigate.CLICK_BUDGET_TAB_JS:
            assert self.kind == "toolbar"
            s.clicks.append("예산")
            s.sub = "budget"
            return {"ok": True}
        if js is navigate.PROJECTS_JS:
            # 과제현황은 메인화면 탭이 앞일 때만 보인다. visible_projects=False 는 "고른 과제가 다음 쪽에 있음"
            rows = [r for r in ROWS if not s.dom_is_page or s.on_page(r["no"])]
            return ([dict(r, visible=s.active == "main" and s.on_page(r["no"])) for r in rows]
                    if self.kind == "dash" and s.dashboard else [])
        if js is navigate.CLICK_PROJECT_JS:
            # 과제현황은 메인화면 탭이 앞에 있을 때만 보인다
            if self.kind != "dash" or not s.dashboard or s.active != "main":
                return {"ok": False, "why": "과제현황에 이 과제가 보이지 않음"}
            if not s.visible or args[0] not in {r["no"] for r in ROWS} or not s.on_page(args[0]):
                return {"ok": False, "why": "과제현황에 이 과제가 보이지 않음"}
            s.clicks.append("project:" + args[0])
            s.toolbar_prj, s.grid_prj, s.active = args[0], "", "project"     # 과제정보 탭을 그 과제로 다시 연다
            return {"ok": True}
        if js is navigate.CLICK_PAGE_JS:
            if self.kind != "dash" or s.active != "main" or s.pages is None:
                return {"ok": False, "why": "쪽 단추가 없음"}
            if args[0].isdigit():
                index = int(args[0]) - 1
                if not s.numbered or not 0 <= index < len(s.pages) or index == s.page_index:
                    return {"ok": False, "why": "쪽 번호가 없음"}
                s.page_index = index
                s.clicks.append("page:" + args[0])
                return {"ok": True}
            step = 1 if args[0] == "nextBtn" else -1
            if not 0 <= s.page_index + step < len(s.pages):
                return {"ok": False, "why": "끝 쪽"}
            if s.script_pages:
                self._turn(args[0])
            return {"ok": True}
        if js is navigate.PAGE_STATE_JS:
            if self.kind != "dash" or s.active != "main" or s.pages is None:
                return "쪽 단추가 없음"
            step = 1 if args[0] == "nextBtn" else -1
            return "" if 0 <= s.page_index + step < len(s.pages) else "끝 쪽"
        if js is navigate.PAGER_JS:
            if self.kind != "dash" or not s.dashboard or s.active != "main":
                return None
            pages = s.pages or [[]]
            return {"next": "보임 24×24 (type 없음)", "prev": "보임 24×24 (type 없음)", "links": 2, "shown": 2,
                    "pages": "" if s.numbered or not s.pages else f"{s.page_index + 1} / {len(pages)}",
                    "nums": [str(i + 1) for i in range(len(pages)) if i != s.page_index] if s.numbered else [],
                    "now": str(s.page_index + 1) if s.numbered else "", "filter": s.filter, "query": False}
        if js is navigate.ALL_PROJECTS_JS:
            if self.kind != "dash" or s.active != "main":
                return {"ok": False, "why": "과제현황 거르기 칸(#SEARCH_GB)이 없음"}
            if args[0] == "search":
                s.clicks.append("검색")
                if s.filter == "전체과제" and s.all_pages is not None:
                    s.pages, s.page_index = s.all_pages, 0
                return {"ok": True}
            if s.filter == "전체과제":
                return {"ok": True, "done": True}
            if args[0] == "open":
                s.clicks.append("거르기")
                return {"ok": True}
            s.clicks.append("전체과제")
            s.filter = "전체과제"
            if s.filter_reloads and s.all_pages is not None:
                s.pages, s.page_index = s.all_pages, 0
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
            s.sub = "claims"
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
        if js in (form.FRAME_VISIBLE_JS, erp.GRID_SHOWN_JS):
            # 위쪽 탭 중 앞에 있는 것의 프레임만 크기가 있다 — 결의서 목록은 과제정보 탭, 작성 화면은 청구서(일반) 탭
            if js is erp.GRID_SHOWN_JS and self.kind != "grid":
                return False
            if self.kind == "grid" and s.sub != "claims":
                return False                     # 예산 하위 탭이 앞이면 결의서 목록은 숨는다
            return {"toolbar": "project", "grid": "project", "form": "sheet", "card": "sheet"}.get(self.kind, s.active) == s.active
        if js is erp._PARSE_ROWS_JS:
            rows = s.lists.get(s.grid_prj, s.list_rows)
            return [dict(r) for r in rows] if self.kind == "grid" and s.grid_prj else []
        if js in (erp._SCROLL_TOP_JS, erp._SCROLL_INFO_JS):
            return None                  # 한 화면에 다 보인다 — 내리지 않는다
        if js is form.STATE_JS:
            values = s.card if self.kind == "card" else s.form
            return {key: {"value": (values or {}).get(key, "")} for key in args[0]}
        if self.kind == "layout":
            return None
        raise AssertionError("모르는 JS: " + str(js)[:60])

    def _turn(self, which):
        self.s.page_index += 1 if which == "nextBtn" else -1
        self.s.clicks.append("page:" + which)

    def click(self, selector, timeout=None):
        """Playwright 의 frame.click — 마우스로 누르기. 쪽 단추 밖의 것이 오면 깨진다."""
        s = self.s
        assert selector in ("#nextBtn", "#prevBtn") and self.kind == "dash", selector
        s.mouse.append(selector)
        if not s.mouse_pages:
            raise TimeoutError("Timeout 3000ms exceeded. <div class=\"x\">손경호</div> intercepts pointer events")
        self._turn(selector[1:])


class Page:
    def __init__(self, screen: Screen):
        self.frames = [Frame(screen, k) for k in ("layout", "dash", "toolbar", "grid", "form", "card", "budget")]
        for frame in self.frames:
            frame.page = self                    # Playwright 의 frame.page 처럼

    def wait_for_timeout(self, ms):
        pass

    def bring_to_front(self):
        pass


class Context:
    def __init__(self, screen: Screen):
        self.pages = [Page(screen)]
        for page in self.pages:
            page.context = self              # Playwright 의 page.context 처럼 — 목록을 찾은 창을 작업 창으로 쓴다(session.read_list)


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

        def auto_logout_due(self):
            return ""

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
    # 임시저장 · 보완요청이면 첨부만 다시 올리는 길을 띠에 적는다(화면이 그 글로 셋째 단추를 보인다) — 승인된 것뿐이면 적지 않는다
    from claim_downloader.claims import reattach
    assert reattach.REATTACH_CHOICE in asked[0]
    screen.list_rows = [_row("300", SUMMARY, state="승인")]
    asked.clear()
    assert s._duplicate_check(SUMMARY, "202408470003", lambda m: asked.append(m) or False, False)
    assert "결의번호 300(승인" in asked[0] and reattach.REATTACH_CHOICE not in asked[0]
    screen.list_rows = [_row("324", SUMMARY, amt="5100000")]
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


def _approved(doc, cont):
    return {"r": doc, "no": doc, "seq": doc, "gubun": "일반청구", "cont": cont, "amt": "10000", "state": "승인",
            "docNo": "202408470003-20261001-" + doc, "expDt": "2026-10-01"}


def test_download_list_is_brought_in_front_of_a_sheet_before_reading(isolated_home, monkeypatch):
    """담당자 실제(2026-10-21): 일반청구 작성 탭이 앞인 채 [목록 읽기] → 숨은 목록은 스크롤이 안 돼 '수집 26행 · 대상 0건'.
    받기 화면에서 고른 과제의 목록을 '과제정보' 탭으로 앞에 띄운 뒤 읽는다."""
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    screen = Screen()
    s, logs = _session(screen)
    assert navigate.go_to_claims(s.page.context, "202408470003", logs.append, no_wait)[0]
    screen.list_rows = [_approved("1", "09_사무용품"), _approved("2", "03_등록비")]
    screen.active = "sheet"                                   # 일반청구 작성 탭이 앞 — 결의서 목록은 숨음
    assert erp.grid_rows_shown(s.page.context) == 0          # 숨은 목록은 목록 자동 읽기도 세지 않는다
    sel = s.read_list("202408470003")
    assert len(sel.targets) == 2 and screen.clicks[-1] == "과제정보" and screen.active == "project"
    # 과제를 고르지 않은 경로(콘솔)도 숨은 목록은 앞에 가져온다
    screen.active = "sheet"
    assert len(s.read_list().targets) == 2 and screen.clicks[-1] == "과제정보"


def test_download_list_goes_to_the_chosen_project(isolated_home, monkeypatch):
    """받기 화면의 과제 칸(담당자 요청 2026-10-21) — 다른 과제의 목록이 떠 있으면 고른 과제의 결의서내역으로 옮겨 읽는다."""
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    screen = Screen()
    s, logs = _session(screen)
    assert navigate.go_to_claims(s.page.context, "202408470003", logs.append, no_wait)[0]
    screen.list_rows = [_approved("7", "03_다른 과제")]
    s.read_list("202409710003")
    assert screen.grid_prj == "202409710003" and "project:202409710003" in screen.clicks


def test_hidden_list_that_cannot_be_shown_is_not_read_in_part(isolated_home, monkeypatch):
    """'과제정보' 탭을 누를 수 없으면 그려진 26행만 읽고 '대상 0건' 이라 하지 않는다 — 멈추고 까닭을 알린다."""
    from claim_downloader.session import ErpSession, ListNotFound
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    screen = Screen()
    s, logs = _session(screen)
    assert navigate.go_to_claims(s.page.context, "202408470003", logs.append, no_wait)[0]
    screen.list_rows = [_approved("1", "09_사무용품")]
    screen.active, screen.toolbar_prj = "sheet", ""          # 위쪽 '과제정보' 탭이 보이지 않는 화면
    for project in ("202408470003", ""):
        with pytest.raises(ListNotFound) as caught:
            s.read_list(project)
        assert "뒤에" in str(caught.value) and "과제정보" in str(caught.value)
    assert not any(line.startswith("대상 ") for line in logs)


def test_project_on_another_page_is_found_by_turning_pages():
    """과제 폴더별 받기(담당자 2026-10-21) — 끝난 과제는 과제현황 둘째 쪽에 있다. 쪽 넘김(#nextBtn)으로 찾아 열고,
    다음 과제는 앞 쪽(#prevBtn)으로 돌아가 찾는다. 쪽 단추 밖의 것은 누르지 않는다."""
    screen = Screen()
    screen.pages = [["202408470003", "202409710003"], ["202603130001", "202408470002"]]
    ok, message = navigate.go_to_claims(Context(screen), "202408470002", lambda m: None, no_wait)
    assert ok, message
    assert screen.clicks == ["page:nextBtn", "project:202408470002", "청구서"] and screen.grid_prj == "202408470002"
    ok, _ = navigate.go_to_claims(Context(screen), "202409710003", lambda m: None, no_wait)
    assert ok and screen.clicks[3:] == ["메인화면", "page:prevBtn", "project:202409710003", "청구서"]
    ok, message = navigate.go_to_claims(Context(screen), "209999999999", lambda m: None, no_wait)      # 어느 쪽에도 없음
    assert not ok and "찾지 못했습니다" in message and "쪽 2개를 다 봤지만" in message and screen.clicks[-1].startswith("page:")
    assert not screen.mouse                     # 화면 스크립트로 넘어가면 마우스는 쓰지 않는다


def test_page_button_is_pressed_with_the_mouse_when_the_script_click_does_nothing():
    """2026-10-21 실제 ERP — 과제현황 둘째 쪽의 세 과제를 못 찾았다(#nextBtn 을 화면 스크립트로 눌러도 쪽이 안 바뀐 것으로 본다).
    쪽이 안 바뀌면 같은 단추를 마우스로 한 번 더 누르고, 단추 모양 · 쪽 표시 · 넘긴 결과를 기록에 남긴다."""
    screen = Screen()
    screen.pages = [["202408470003", "202409710003"], ["202603130001", "202408470002"]]
    screen.script_pages = False
    logs = []
    ok, message = navigate.go_to_claims(Context(screen), "202408470002", logs.append, no_wait)
    assert ok, message
    assert screen.mouse == ["#nextBtn"] and screen.clicks == ["page:nextBtn", "project:202408470002", "청구서"]
    assert any("다음 쪽 단추 보임" in line and "쪽 표시 '1 / 2'" in line for line in logs)
    assert any("(#nextBtn, 마우스)" in line for line in logs)
    # 둘째 쪽('2 / 2')에서 첫 쪽 과제로 — 막히지 않은 [다음] 을 헛누르지 않고 [이전] 만
    ok, message = navigate.go_to_claims(Context(screen), "202409710003", logs.append, no_wait)
    assert ok, message
    assert screen.mouse == ["#nextBtn", "#prevBtn"] and screen.clicks[-3:] == ["page:prevBtn", "project:202409710003", "청구서"]

    # 마우스로도 안 되면 — 까닭을 남기고 멈춘다. Playwright 오류 글(화면 글자가 섞임)은 기록에 그대로 두지 않는다
    screen = Screen()
    screen.pages = [["202408470003", "202409710003"], ["202603130001", "202408470002"]]
    screen.script_pages = screen.mouse_pages = False
    logs = []
    ok, message = navigate.go_to_claims(Context(screen), "202408470002", logs.append, no_wait)
    assert not ok and "쪽을 넘기지 못했습니다" in message and "#nextBtn" in message
    assert screen.mouse == ["#nextBtn"] and screen.page_index == 0
    assert any("다른 것에 가려짐" in line for line in logs) and not any("손경호" in line for line in logs)


ENDED = "202603130001"        # 끝난 과제 — '진행과제' 에 없고 '전체과제' 둘째 쪽에 있다(가짜 행 중 하나를 그 자리에 둔다)


def _filtered_screen(**kw):
    """2026-10-21 17:36 실측 모양 — 과제현황 거르기 '진행과제' 는 한 쪽(지금 쪽 '1' 만), '전체과제' 는 두 쪽이고 쪽 번호 링크로 넘긴다."""
    screen = Screen()
    screen.numbered = True
    screen.filter = "진행과제"
    screen.pages = [["202408470003", "202409710003", "202408470002"]]
    screen.all_pages = [["202408470003", "202409710003"], ["202408470002", ENDED]]
    for key, value in kw.items():
        setattr(screen, key, value)
    return screen


def test_ended_project_is_found_by_showing_all_projects_and_page_two():
    """담당자 2026-10-21 "전체과제로 설정하고 2페이지를 눌러야함" — '진행과제' 에 없는 과제는 거르기를 '전체과제' 로 바꾸고 쪽 번호 2 를 누른다.
    한 쪽뿐인 '진행과제' 에서는 [다음] · [이전] 을 헛누르지 않는다(지금 쪽 숫자만 있고 번호 링크가 없으면 한 쪽)."""
    screen = _filtered_screen()
    logs = []
    ok, message = navigate.go_to_claims(Context(screen), ENDED, logs.append, no_wait)
    assert ok, message
    assert screen.clicks == ["거르기", "전체과제", "page:2", "project:" + ENDED, "청구서"] and not screen.mouse
    assert screen.filter == "전체과제"
    assert any("거르기 '진행과제' · 쪽 번호 없음 (지금 1)" in line for line in logs)
    assert any("'진행과제' 에서 '전체과제' 로 바꿉니다" in line for line in logs) and any("(쪽 2) → 보이는 과제" in line for line in logs)
    # 다음 과제가 첫 쪽에 있으면 — 거르기는 그대로 두고 쪽 번호 1 로
    ok, message = navigate.go_to_claims(Context(screen), "202409710003", logs.append, no_wait)
    assert ok, message
    assert screen.clicks[5:] == ["메인화면", "page:1", "project:202409710003", "청구서"]
    # '진행과제' 첫 쪽에 있는 과제는 거르기를 바꾸지 않는다
    screen = _filtered_screen()
    ok, _ = navigate.go_to_claims(Context(screen), "202408470002", logs.append, no_wait)
    assert ok and screen.clicks == ["project:202408470002", "청구서"] and screen.filter == "진행과제"


def test_show_all_presses_search_only_when_the_list_does_not_redraw():
    """보기 '전체과제' 를 골라도 목록이 그대로면 과제현황 [검색] 을 한 번 누른다. 어디에도 없으면 까닭에 '전체과제' 의 쪽 수를 적는다."""
    screen = _filtered_screen(filter_reloads=False)
    ok, message = navigate.go_to_claims(Context(screen), ENDED, lambda m: None, no_wait)
    assert ok, message
    assert screen.clicks[:4] == ["거르기", "전체과제", "검색", "page:2"]
    screen = _filtered_screen()
    ok, message = navigate.go_to_claims(Context(screen), "209999999999", lambda m: None, no_wait)
    assert not ok and "'전체과제' 의 쪽 2개를 다 봤지만 없습니다" in message
    assert screen.clicks == ["거르기", "전체과제", "page:2"]


def test_show_all_failure_is_reported_without_guessing():
    """거르기 칸이 없거나 바꾸지 못하면 누르지 않고 까닭을 알린다 — 사람이 브라우저에서 '전체과제' 로 바꾸면 된다."""
    screen = _filtered_screen()
    original = Frame.evaluate

    def no_filter(self, js, *args):
        if js is navigate.ALL_PROJECTS_JS:
            return {"ok": False, "why": "과제현황 거르기 칸(#SEARCH_GB)이 없음"}
        return original(self, js, *args)

    Frame.evaluate = no_filter
    try:
        ok, message = navigate.go_to_claims(Context(screen), ENDED, lambda m: None, no_wait)
    finally:
        Frame.evaluate = original
    assert not ok and "'전체과제' 로 바꾸지 못했습니다" in message and "#SEARCH_GB" in message and screen.clicks == []


def _folders(tmp_path, *names):
    for name in names:
        (tmp_path / name).mkdir()
    return str(tmp_path)


def _folder_session(screen, out_root):
    from claim_downloader.session import ErpSession

    logs, saved = [], []

    def process(page, row, root, name_date_first, wait_sec, log):
        saved.append((row["docNo"], root))
        return "09", __import__("pathlib").Path(root) / "x.pdf"

    s = ErpSession(logs.append, lambda m: True, process=process,
                   load_settings=lambda: settings.Settings(out_root=out_root, freeze_reload=False))
    s.page = Page(screen)
    s.page.context = Context(screen)
    s.claim_form_open = lambda: False
    return s, logs, saved


def test_read_lists_and_download_go_into_each_project_folder(isolated_home, monkeypatch, tmp_path):
    """담당자 2026-10-21: 저장 폴더를 '(과제번호)_…' 폴더로 나눴다 — 과제마다 결의서내역을 읽고, 그 과제 폴더에 받는다.
    폴더가 없는 과제는 받지 않는다("일단 지금 폴더 만든 과제만")."""
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    root = _folders(tmp_path, "(202408470003)_2026년도 사업비_4,438,000,000", "(202408470002)_2025년도 사업비(출연금)_4,462,000,000",
                    "e나라도움 부정징후 현장점검 자료(24년도)")
    screen = Screen()
    screen.pages = [["202408470003", "202409710003"], ["202603130001", "202408470002"]]
    screen.lists = {
        "202408470003": [_approved("1", "09_사무용품")],
        "202408470002": [dict(_approved("2", "03_등록비"), docNo="202408470002-20250901-2")],
        "202409710003": [dict(_approved("3", "03_대응"), docNo="202409710003-20261001-3")],
    }
    s, logs, saved = _folder_session(screen, root)
    sel = s.read_lists(["202408470003", "202408470002", "202409710003"])
    assert [t["project"] for t in sel.targets] == ["202408470003", "202408470002"]
    assert sel.blocked and sel.blocked[0][0] == "202409710003" and "폴더가 없어" in sel.blocked[0][1]
    summary = s.download(sel.targets)
    assert summary.ok == 2 and not summary.failed
    assert [(doc, __import__("os").path.basename(where)) for doc, where in saved] == [
        ("202408470003-20261001-1", "(202408470003)_2026년도 사업비_4,438,000,000"),
        ("202408470002-20250901-2", "(202408470002)_2025년도 사업비(출연금)_4,462,000,000")]
    assert screen.grid_prj == "202408470002"                      # 받을 때도 그 과제의 목록을 앞에 두었다


def test_download_refuses_a_row_of_another_project_or_without_folder(isolated_home, monkeypatch, tmp_path):
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    root = _folders(tmp_path, "(202408470003)_2026년도 사업비")
    screen = Screen()
    s, logs, saved = _folder_session(screen, root)
    wrong = dict(_approved("5", "03_다른"), docNo="202409710003-20261001-5", project="202408470003")
    nowhere = dict(_approved("6", "03_폴더 없음"), docNo="202603130001-20260501-6", project="202603130001")
    summary = s.download([wrong, nowhere])
    assert summary.ok == 0 and len(summary.failed) == 2 and saved == []
    assert any("다른 과제(202409710003)" in line for line in logs) and any("폴더가 없어" in line for line in logs)


BUDGET = [["A10110002", "장학금"], ["A10110012", "연구시설/장비비"]]       # 2026-10-21 담당자 그림(202409710003 예산 탭)의 차례


def test_matching_fund_project_numbers_bimok_by_its_budget_tab(isolated_home, monkeypatch, tmp_path):
    """담당자 2026-10-21: "대응자금은 사업비와 비목이 다릅니다" · "과제정보-예산에서 확인하고 순서대로 숫자를 붙여주세요".
    대응자금 과제는 목록을 읽은 뒤 예산 탭의 비목을 차례대로 읽어 받을 건에 붙이고, 받을 때 'NN. 비목명' 폴더에 둔다. 사업비 과제는 그대로."""
    from claim_downloader import naming
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    root = _folders(tmp_path, "(202408470003)_2026년도 사업비_4,438,000,000", "(202409710003)_2026년도 대응자금_254,907,000")
    screen = Screen()
    screen.budgets = {"202409710003": BUDGET}
    screen.lists = {
        "202408470003": [_approved("1", "02_2026년도 9월 (가)형 근로장학금")],
        "202409710003": [dict(_approved("3", "02_연구장비 구입"), docNo="202409710003-20261001-3"),
                         dict(_approved("4", "장학금 지급"), docNo="202409710003-20261001-4")],
    }
    s, logs, _saved = _folder_session(screen, root)
    placed = []

    def process(page, row, out, name_date_first, wait_sec, log):
        bimok = {"3": "연구시설/장비비", "4": "장학금"}.get(row["no"], "장학금")
        code, fname = naming.build_name(row, {"bimok": bimok, "owners": ["가나"]})
        dest = naming.destination(out, code, fname, row.get("budget"))
        placed.append(f"{__import__('os').path.basename(out)}/{dest.parent.name}/{dest.name[:3]}")
        return code, dest

    s._process = process
    sel = s.read_lists(["202408470003", "202409710003"])
    assert [t.get("budget") for t in sel.targets] == [None, BUDGET, BUDGET] and not sel.blocked
    assert screen.clicks.count("예산") == 1 and screen.sub == "claims"         # 읽은 뒤 청구서 탭으로 돌아왔다
    assert any("01 장학금 · 02 연구시설/장비비" in line for line in logs)
    s.read_lists(["202409710003"])
    assert screen.clicks.count("예산") == 1                                      # 한 번 읽은 차례는 다시 읽지 않는다
    assert s.download(sel.targets).ok == 3
    assert placed == ["(202408470003)_2026년도 사업비_4,438,000,000/02. 장학금/02_",
                      "(202409710003)_2026년도 대응자금_254,907,000/02. 연구시설장비비/02_",
                      "(202409710003)_2026년도 대응자금_254,907,000/01. 장학금/01_"]


def test_matching_fund_whose_budget_cannot_be_read_is_not_downloaded(isolated_home, monkeypatch, tmp_path):
    """예산 탭에서 비목을 못 읽으면 그 대응자금 과제는 받지 않는다 — 번호 없이 받으면 사업비 폴더 · 미분류에 섞인다.
    과제 폴더가 없는 옛 저장 폴더여도 ERP 과제명의 '대응자금' 으로 안다."""
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    navigate.save_projects([navigate.Project("202409710003", "가짜사업[대응자금-교내] / 3연차", "2026-03-01", "2027-02-28")])
    screen = Screen()
    screen.lists = {"202409710003": [dict(_approved("3", "02_연구장비 구입"), docNo="202409710003-20261001-3")]}
    s, logs, _saved = _folder_session(screen, _folders(tmp_path, "02. 장학금"))
    sel = s.read_list("202409710003")
    assert sel.targets == [] and sel.blocked and "대응자금" in sel.blocked[0][1] and "예산 탭" in sel.blocked[0][1]
    assert screen.sub == "claims"                         # 못 읽어도 결의서 목록을 앞에 되돌려 둔다
    screen.budgets = {"202409710003": BUDGET}             # 다음에 다시 읽으면(못 읽은 것은 기억하지 않는다) 받는다
    assert s.read_list("202409710003").targets[0]["budget"] == BUDGET


def test_show_list_presses_claim_tab_when_budget_tab_is_in_front(isolated_home):
    screen = Screen()
    context = Context(screen)
    assert navigate.go_to_claims(context, "202409710003", lambda _m: None, no_wait)[0]
    screen.sub = "budget"
    frame, why = navigate.show_list(context, "202409710003", lambda _m: None, no_wait)
    assert frame is not None and not why and screen.clicks[-1] == "청구서" and "과제정보" not in screen.clicks


def test_session_renames_already_downloaded_matching_fund_files(isolated_home, monkeypatch, tmp_path):
    """담당자 2026-10-21: 이미 다 받은 뒤 "예산비목명이랑 순서만 확인하고 다운받은 파일명만 수정" — 예산 탭을 읽어 계획하고, 고른 것만 옮긴다."""
    import test_rebudget as fake
    from claim_downloader import rebudget
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    root, fund, reader = fake.build(tmp_path)
    monkeypatch.setattr(rebudget, "pdf_text", reader)
    screen = Screen()
    screen.budgets = {"202409710003": BUDGET}
    s, logs, _saved = _folder_session(screen, str(root))
    plan = s.plan_rebudget()
    assert screen.clicks.count("예산") == 1 and screen.sub == "claims"
    assert len(plan.changes()) == 3 and all(m.source.exists() for m in plan.changes())     # 계획만 — 아직 옮기지 않음
    s.apply_rebudget(plan.changes())
    assert (fund / "01. 장학금" / "01_(261001) 9월 근로장학금_홍길동 등 3명_(900,000).pdf").exists()
    assert any("옮김 3 · 못 옮김 0" in line for line in logs)


def test_read_list_leaves_out_documents_on_the_skip_list(isolated_home, monkeypatch, tmp_path):
    """담당자 2026-10-21 "지금 받지 못하는 결의서는 받지 않아도 되는 결의서 목록에 추가" — 목록에 있으면 받을 것에서 뺀다(과제마다)."""
    from claim_downloader import skiplist
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    root = _folders(tmp_path, "(202408470003)_2026년도 사업비", "(202408470002)_2025년도 사업비")
    screen = Screen()
    screen.lists = {"202408470003": [_approved("1", "정산 완료 후 잔액조정"), _approved("2", "09_사무용품")],
                    "202408470002": [dict(_approved("1", "09_정수기"), docNo="202408470002-20250901-1")]}
    s, logs, _saved = _folder_session(screen, root)
    assert skiplist.add(dict(_approved("1", "정산 완료 후 잔액조정"), gubun="예산잔액조정신청"), "청구서출력 없음", "202408470003")[0]
    sel = s.read_lists(["202408470003", "202408470002"])
    assert [(t["project"], t["seq"]) for t in sel.targets] == [("202408470003", "2"), ("202408470002", "1")]   # 다른 과제의 결의번호 1 은 그대로
    assert sel.excluded == 1 and any("받지 않는 결의서 1건" in line for line in logs)


def test_read_list_leaves_out_every_document_of_a_kind_on_the_skip_list(isolated_home, monkeypatch, tmp_path):
    """담당자 2026-10-22 — 목록에 든 결의서구분은 통째로 뺀다: 다른 과제 · 새 결의번호여도. 청구 결의서는 그대로."""
    from claim_downloader import skiplist
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    root = _folders(tmp_path, "(202408470003)_2026년도 사업비", "(202408470002)_2025년도 사업비")
    screen = Screen()
    screen.lists = {"202408470003": [dict(_approved("5", "새 잔액조정"), gubun="예산잔액조정신청"), _approved("2", "09_사무용품")],
                    "202408470002": [dict(_approved("8", "정산 잔액조정"), gubun="예산잔액조정신청", docNo="202408470002-20250901-8"),
                                     dict(_approved("1", "09_정수기"), docNo="202408470002-20250901-1")]}
    s, logs, _saved = _folder_session(screen, root)
    assert skiplist.add(dict(_approved("1", "정산 완료 후 잔액조정"), gubun="예산잔액조정신청"), "청구서출력 없음", "202408470001")[0]
    sel = s.read_lists(["202408470003", "202408470002"])
    assert [(t["project"], t["seq"]) for t in sel.targets] == [("202408470003", "2"), ("202408470002", "1")]
    assert sel.excluded == 2 and any("결의서구분으로 뺀 것: '예산잔액조정신청' 1건" in line for line in logs)


def test_all_projects_are_collected_from_every_page_of_the_full_filter(isolated_home):
    """끝난 과제의 과제기간은 '진행과제' 에 없다 — 거르기를 '전체과제' 로 바꾸고 모든 쪽을 넘겨 모은다(담당자 2026-10-22
    "진행과제말고 전체과제로 설정하면 이전 과제도 다 보이는데"). 모은 것은 _과제목록.json 에 합쳐 남고, 다음에 '진행과제' 만 다시 읽어도 지워지지 않는다."""
    screen = _filtered_screen(dom_is_page=True)
    assert [p.no for p in navigate.read_projects(Context(screen))] == ["202408470003", "202409710003", "202408470002"]   # '진행과제' 한 쪽
    logs = []
    found, why = navigate.collect_all_projects(Context(screen), logs.append, no_wait)
    assert why == "" and screen.clicks == ["거르기", "전체과제", "page:2"] and not screen.mouse
    assert {p.no: (p.start, p.end) for p in found}[ENDED] == ("2026-03-01", "2026-06-30") and len(found) == 4
    assert any("'전체과제' 2쪽에서 과제 4개를 읽었습니다 (과제기간 있는 과제 4개)" in line for line in logs)
    navigate.save_projects(found)
    navigate.save_projects(navigate.read_projects(Context(_filtered_screen(dom_is_page=True))))   # 다음 로그인 — '진행과제' 3개만 읽힘
    assert {p.no for p in navigate.load_projects()[0]} == {r["no"] for r in ROWS}                 # 끝난 과제의 기간이 남아 있다
    # 다른 탭이 앞이면 '메인화면' 탭을 먼저 누른다 · 거르기가 이미 '전체과제' 면 바꾸지 않는다
    screen = _filtered_screen(dom_is_page=True, filter="전체과제")
    screen.pages, screen.active, screen.toolbar_prj = screen.all_pages, "project", "202408470003"
    found, why = navigate.collect_all_projects(Context(screen), logs.append, no_wait)
    assert why == "" and screen.clicks == ["메인화면", "page:2"] and len(found) == 4
    # 로그인 전이면 누르지 않고 까닭만
    found, why = navigate.collect_all_projects(Context(Screen(dashboard=False)), logs.append, no_wait)
    assert found == [] and "보이지 않습니다" in why


def test_read_purchases_collects_project_periods_before_giving_up(isolated_home, monkeypatch, tmp_path):
    """2026-10-22 실제: 구매요청(계약) 서류에서 끝난 과제 7개가 '과제기간을 몰라' 로 빠졌다 — 이제 '전체과제' 모든 쪽을 읽어 기간을 안다."""
    from claim_downloader import purchase
    from claim_downloader.session import ErpSession
    monkeypatch.setattr(ErpSession, "browser_open", property(lambda self: True))
    screen = _filtered_screen(dom_is_page=True)
    root = _folders(tmp_path, f"({ENDED})_2025년 이월금_1", "(202408470003)_2026년도 사업비_1")
    s, logs, _saved = _folder_session(screen, root)
    searched = []
    monkeypatch.setattr(purchase, "open_list", lambda ctx, log, wait: (object(), ""))
    monkeypatch.setattr(purchase, "search", lambda frame, start, end, log, wait, what="구매요청일자": (searched.append((start, end)), (True, ""))[1])
    monkeypatch.setattr(purchase, "read_rows", lambda frame: [])
    sel = s.read_purchases([ENDED, "202408470003"])
    assert sel.blocked == [] and screen.clicks[:3] == ["거르기", "전체과제", "page:2"]
    assert searched and searched[0][0] == "2026-03-01"                                    # 두 과제기간을 합친 범위로 조회
    assert any("과제기간을 몰라 메인화면 과제현황을 '전체과제' 로 바꿔" in line and ENDED in line for line in logs)
    assert ENDED in {p.no for p in navigate.load_projects()[0]}
    # 전체과제 어디에도 없는 과제만 받지 않는다 — 까닭에 그렇게 적는다
    sel = s.read_purchases(["209999999999"])
    assert len(sel.blocked) == 1 and "'전체과제' 의 모든 쪽에 과제 209999999999 이 없거나" in sel.blocked[0][1]
