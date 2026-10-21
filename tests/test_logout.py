"""ERP 자동 로그아웃(logout.py · session) — 30분 활동 없음 · 창 닫음 · 앱 끔(담당자 요청 2026-10-21).

브라우저 없이 가짜 창으로 본다. 실제 Chromium 으로는 모의 ERP(쿠키 로그인 · [로그아웃] 확인 창)에서 따로 확인했다(CLAUDE.md 21절).
"""
from __future__ import annotations

import json

from claim_downloader import logout, session as session_mod, settings
from claim_downloader.session import ErpSession

ERP = settings.ERP_URL


class FakeFrame:
    def __init__(self, page):
        self.page = page

    @property
    def url(self):
        return self.page.url

    def evaluate(self, js, *args):
        if js == logout.CLICK_LOGOUT_JS:
            self.page.clicks += 1
            if not self.page.logged_in:
                return "none"
            if self.page.button_text != logout.LOGOUT_TEXT:
                return "text"
            if self.page.dialog_handlers:                       # ERP 의 확인 창 — 앱의 처리기가 [확인]
                for handler in list(self.page.dialog_handlers):
                    handler(FakeDialog(self.page))
            if self.page.confirm_ok and self.page.works:
                self.page.logged_in = False
                self.page.url = ERP.replace("rderp_layoutMain.act", "login.act?x=1")
                for handler in list(self.page.nav_handlers):
                    handler(self)
            return "clicked"
        if js == logout.STATE_JS:
            return "in" if self.page.logged_in else "out"
        raise AssertionError(js)


class FakeDialog:
    message = "로그아웃 하시겠습니까?"
    type = "confirm"

    def __init__(self, page):
        self.page = page

    def accept(self):
        self.page.confirm_ok = True

    def dismiss(self):
        self.page.confirm_ok = False


class FakePage:
    def __init__(self, url=ERP, opener=None, logged_in=True):
        self.url = url
        self._opener = opener
        self.logged_in = logged_in
        self.button_text = logout.LOGOUT_TEXT
        self.works = True
        self.closed = False
        self.clicks = 0
        self.confirm_ok = False
        self.dialog_handlers = []
        self.nav_handlers = []
        self.main_frame = FakeFrame(self)
        self.frames = [self.main_frame]
        self.context = None

    def opener(self):
        return self._opener

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True

    def on(self, name, handler):
        (self.dialog_handlers if name == "dialog" else self.nav_handlers).append(handler)

    def remove_listener(self, name, handler):
        (self.dialog_handlers if name == "dialog" else self.nav_handlers).remove(handler)

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, wait_until=None):
        self.url = url


class FakeContext:
    def __init__(self, pages, server_logged_in=True):
        self.pages = pages
        self.server_logged_in = server_logged_in
        for page in pages:
            page.context = self

    def new_page(self):
        page = FakePage(url="about:blank", logged_in=self.server_logged_in)
        page.context = self
        self.pages.append(page)
        return page

    def new_cdp_session(self, page):
        raise RuntimeError("cdp 없음")                     # 작게 줄이기는 되면 하고 안 되면 그대로


class FakeBrowser:
    def __init__(self, context, connected=True):
        self.contexts = [context]
        self.connected = connected

    def is_connected(self):
        return self.connected


def make_session(tmp_path, monkeypatch, pages, **cfg):
    monkeypatch.setenv("CLAIM_DOWNLOADER_HOME", str(tmp_path))
    if cfg:
        settings.config_path().write_text(json.dumps(cfg), encoding="utf-8")
    logs = []
    s = ErpSession(logs.append, lambda message: False)
    context = FakeContext(pages)
    s.browser = FakeBrowser(context)
    s._context = context
    s.page = pages[0] if pages else None
    s.erp_logged_in = True
    return s, logs, context


def test_script_only_reports_and_presses_nothing():
    script = logout.activity_script("knu-icf.kangwon.ac.kr")
    assert '"knu-icf.kangwon.ac.kr"' in script and logout.BINDING in script
    for word in (".click(", ".value =", "dispatchEvent", "submit(", "fetch(", "XMLHttpRequest", "localStorage", "cookie"):
        assert word not in script, word
    assert logout.parse_signal("active:in") == ("active", "in")
    assert logout.parse_signal("load:out") == ("load", "out")
    assert logout.parse_signal("bogus") == ("", "?")
    assert logout.CLICK_LOGOUT_JS.count(".click()") == 1
    assert "getElementById('layoutMain_btn_logout')" in logout.CLICK_LOGOUT_JS and "!== '로그아웃'" in logout.CLICK_LOGOUT_JS


def test_signals_track_activity_and_login(tmp_path, monkeypatch):
    main = FakePage()
    popup = FakePage(url=ERP.replace("rderp_layoutMain.act", "rexpe_0084_rcv_pop.act"), opener=main)
    s, _logs, _ = make_session(tmp_path, monkeypatch, [main, popup])
    s.erp_logged_in = False
    s.last_active -= 3600
    s._on_erp_signal({"page": popup}, "active:out")              # 팝업에서 움직임 — 활동이지만 로그인 상태는 안 바꾼다
    assert s.idle_seconds() < 5 and s.erp_logged_in is False
    s._on_erp_signal({"page": main}, "load:in")
    assert s.erp_logged_in is True
    s._on_erp_signal({"page": main}, "load:?")                   # 읽는 중 — 그대로
    assert s.erp_logged_in is True
    parking = FakePage(url="https://traffic.kangwon.ac.kr/discount-links")
    s._on_erp_signal({"page": parking}, "load:out")              # 다른 사이트 — 그대로
    assert s.erp_logged_in is True
    s._on_erp_signal({"page": main}, "load:out")                 # 로그인 화면
    assert s.erp_logged_in is False


def test_due_after_idle_minutes_or_closed_window(tmp_path, monkeypatch):
    main = FakePage()
    s, _logs, _ = make_session(tmp_path, monkeypatch, [main])
    assert s.auto_logout_due() == ""
    s.last_active -= 29 * 60
    assert s.auto_logout_due() == ""
    s.last_active -= 2 * 60
    assert s.auto_logout_due() == "idle"
    s.touch()
    main.closed = True                                           # 사람이 ERP 창을 닫음
    assert s.auto_logout_due() == "closed"
    s.erp_logged_in = False                                      # 로그인 전이면 할 일 없음
    assert s.auto_logout_due() == ""


def test_settings_turn_it_off_or_change_minutes(tmp_path, monkeypatch):
    main = FakePage()
    s, _logs, _ = make_session(tmp_path, monkeypatch, [main], auto_logout=False)
    s.last_active -= 3 * 3600
    assert s.auto_logout_due() == "" and s.auto_logout("app") is False and main.clicks == 0
    settings.config_path().write_text(json.dumps({"auto_logout_minutes": 10.0}), encoding="utf-8")
    assert settings.load().auto_logout_minutes == 10
    assert s.auto_logout_due() == "idle"
    settings.config_path().write_text(json.dumps({"auto_logout_minutes": 0}), encoding="utf-8")
    assert s.auto_logout_due() == ""                             # 0 — '쓰지 않음' 만 끔. 창 닫기는 그대로
    main.closed = True
    assert s.auto_logout_due() == "closed"


def test_idle_logout_presses_logout_and_accepts_confirm(tmp_path, monkeypatch):
    main = FakePage()
    popup = FakePage(url=ERP.replace("rderp_layoutMain.act", "rexpe_0084_rcv_pop.act"), opener=main)
    s, logs, _ = make_session(tmp_path, monkeypatch, [main, popup])
    assert s.logout("idle", 30) is True
    assert main.clicks == 1 and main.confirm_ok and not main.logged_in
    assert s.erp_logged_in is False
    assert popup.closed and not main.closed                     # 지난 팝업은 닫고 ERP 창은 로그인 화면으로 둔다
    assert not main.dialog_handlers and not main.nav_handlers    # 처리기는 그때만
    text = "\n".join(logs)
    assert "30분 동안 ERP 를 쓰지 않아 ERP 에서 로그아웃했습니다" in text
    assert "로그아웃 확인 창: 로그아웃 하시겠습니까?" in text
    assert "로그아웃 뒤 주소" in text and "x=1" not in text           # 주소의 물음표 뒤는 남기지 않는다


def test_closed_window_is_reopened_small_logged_out_and_closed(tmp_path, monkeypatch):
    main = FakePage()
    s, logs, context = make_session(tmp_path, monkeypatch, [main])
    main.closed = True
    assert s.auto_logout_due() == "closed"
    assert s.auto_logout("closed") is True
    reopened = context.pages[-1]
    assert reopened is not main and reopened.url.endswith("login.act?x=1") and reopened.clicks == 1
    assert reopened.closed                                       # 다시 연 창은 닫는다
    assert "ERP 창을 로그아웃 없이 닫아 ERP 에서 로그아웃했습니다" in "\n".join(logs)


def test_reopened_window_already_logged_out(tmp_path, monkeypatch):
    main = FakePage()
    s, logs, context = make_session(tmp_path, monkeypatch, [main])
    main.closed = True
    context.server_logged_in = False                             # ERP 가 이미 끝낸 접속
    assert s.auto_logout("closed") is False
    assert s.erp_logged_in is False and context.pages[-1].closed
    assert "이미 로그아웃됨" in "\n".join(logs) and "⚠" not in "\n".join(logs)


def test_failure_is_reported_once_and_not_retried(tmp_path, monkeypatch):
    main = FakePage()
    main.works = False                                           # 눌러도 화면이 안 바뀜
    s, logs, _ = make_session(tmp_path, monkeypatch, [main])
    s.last_active -= 31 * 60
    assert s.logout("idle", 30, timeout=0.3) is False
    assert s.erp_logged_in is False and s.auto_logout_due() == ""  # 2초마다 다시 누르지 않는다
    assert "직접 눌러 주세요" in "\n".join(logs)
    main2 = FakePage()
    main2.button_text = "로그 아웃"                               # 글자가 다르면 누르지 않는다
    s2, logs2, _ = make_session(tmp_path, monkeypatch, [main2])
    assert s2.logout("idle") is False and not main2.dialog_handlers and main2.logged_in
    assert "글자가 다름" in "\n".join(logs2)


def test_browser_gone_is_reported(tmp_path, monkeypatch):
    main = FakePage()
    s, logs, _ = make_session(tmp_path, monkeypatch, [main])
    s.browser.connected = False
    assert s.logout("closed") is False and s.erp_logged_in is False
    assert "쿠키를 저장하지 않음" in "\n".join(logs)


def test_left_dialogs_are_closed_before_logout(tmp_path, monkeypatch):
    main = FakePage()
    s, _logs, _ = make_session(tmp_path, monkeypatch, [main])
    s.hands_on = True

    class Left:
        message = "저장하시겠습니까?"
        type = "confirm"
        page = main
        dismissed = False

        def dismiss(self):
            Left.dismissed = True

    s._on_dialog(Left())
    assert s._left_dialogs
    s.logout("idle")
    assert Left.dismissed and not s._left_dialogs


def test_close_and_reopen_forget_login(tmp_path, monkeypatch):
    s, _logs, _ = make_session(tmp_path, monkeypatch, [FakePage()])
    monkeypatch.setattr(session_mod.ErpSession, "logout", lambda self, *a, **k: True)
    s.close()
    assert s.erp_logged_in is False and s._context is None


def _worker():
    import pytest
    worker_mod = pytest.importorskip("claim_downloader.ui.worker")
    import queue
    import threading
    w = worker_mod.SessionWorker.__new__(worker_mod.SessionWorker)
    worker_mod.QObject.__init__(w)
    w._queue = queue.Queue()
    w._stop = threading.Event()
    w._resume = threading.Event()
    w._resume_ok = True
    w._capture_now = threading.Event()
    w._idle_stopped = False
    return w


class LoopSession:
    def __init__(self, due):
        self.due = due
        self.hands_on = True
        self.done = []
        self.erp_logged_in = True
        self.logs = []

    def poll_alive(self):
        return True

    def auto_logout_due(self):
        return self.due

    def auto_logout(self, reason):
        self.done.append((reason, self.hands_on))       # 로그아웃하는 동안은 앱이 확인 창을 받는다(hands_on False)
        return True

    def log(self, message):
        self.logs.append(message)


def test_idle_loop_logs_out_when_due():
    w = _worker()
    s = LoopSession("idle")
    w._auto_logout(s)
    assert s.done == [("idle", False)] and s.hands_on is True
    s2 = LoopSession("")
    w._auto_logout(s2)
    assert s2.done == []


def test_band_left_too_long_stops_the_run():
    """노란 띠 · 재로그인 띠를 띄운 채 오래 비우면 하던 일을 멈추고(멈추기와 같다) 쉬는 고리에서 로그아웃한다."""
    w = _worker()
    s = LoopSession("idle")
    w._session = s
    w._wait_resume()
    assert w._stop.is_set() and w._idle_stopped and w._resume_ok is False
    assert "곧 자동 로그아웃" in "\n".join(s.logs)
