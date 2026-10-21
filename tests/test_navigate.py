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
        self.script_pages = True    # False — 화면 스크립트의 click() 으로는 쪽이 안 바뀐다(2026-10-21 실제 ERP 에서 겪은 모양)
        self.mouse_pages = True     # False — 마우스로 눌러도 안 됨(Playwright 오류)
        self.mouse: list[str] = []
        self.lists: dict[str, list[dict]] = {}      # 과제마다 결의서내역 행(있으면 list_rows 대신)

    def on_page(self, no: str) -> bool:
        return self.pages is None or no in self.pages[self.page_index]


class Frame:
    url = ""                                 # 진단 줄(erp.dump_context)이 읽는다

    def __init__(self, screen: Screen, kind: str):
        self.s, self.kind = screen, kind

    def evaluate(self, js, *args):
        s = self.s
        if js is navigate.PROJECTS_JS:
            # 과제현황은 메인화면 탭이 앞일 때만 보인다. visible_projects=False 는 "고른 과제가 다음 쪽에 있음"
            return ([dict(r, visible=s.active == "main" and s.on_page(r["no"])) for r in ROWS]
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
            return ({"next": "보임 24×24 (type 없음)", "prev": "보임 24×24 (type 없음)", "links": 2, "shown": 2,
                     "pages": f"{s.page_index + 1} / {len(s.pages)}"} if self.kind == "dash" and s.pages else None)
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
        if js in (form.FRAME_VISIBLE_JS, erp.GRID_SHOWN_JS):
            # 위쪽 탭 중 앞에 있는 것의 프레임만 크기가 있다 — 결의서 목록은 과제정보 탭, 작성 화면은 청구서(일반) 탭
            if js is erp.GRID_SHOWN_JS and self.kind != "grid":
                return False
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
        self.frames = [Frame(screen, k) for k in ("layout", "dash", "toolbar", "grid", "form", "card")]
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
