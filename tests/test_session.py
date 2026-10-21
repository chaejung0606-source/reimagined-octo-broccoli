"""받기 흐름 — 멈춤 재시도 · 기록 저장 · 중단.

ERP 화면 조작(process)은 가짜로 바꿔 끼운다. 브라우저 없이 흐름만 시험한다.
"""
from __future__ import annotations

from pathlib import Path

from claim_downloader import archive, session as session_mod, settings
from claim_downloader.session import ErpSession
from conftest import make_row


class FakePage:
    def __init__(self):
        self.gotos = 0
        self.context = self

    @property
    def pages(self):
        return []

    def goto(self, *args, **kwargs):
        self.gotos += 1


def _session(process, answers=None, stop=lambda: False, monkeypatch=None):
    logs: list[str] = []
    asked: list[str] = []

    def ask(message):
        asked.append(message)
        return answers.pop(0) if answers else True

    s = ErpSession(logs.append, ask, should_stop=stop, process=process)
    s.page = FakePage()
    open_page = type("P", (), {"is_closed": lambda self: False})()
    s.browser = type("B", (), {"is_connected": lambda self: True,
                               "contexts": [type("C", (), {"pages": [open_page]})()]})()
    monkeypatch.setattr(session_mod.erp, "wait_for_grid", lambda ctx: (None, None))
    return s, logs, asked


def _ok(page, row, out_root, name_date_first, wait_sec, log):
    return "09", Path(out_root or ".") / f"{row['docNo']}.pdf"


def test_success_is_recorded_right_away(monkeypatch):
    s, _, _ = _session(_ok, monkeypatch=monkeypatch)
    summary = s.download([make_row(docNo="A"), make_row(docNo="B")])
    assert summary.ok == 2
    # 건마다 바로 저장해야 중간에 꺼져도 이어받는다
    assert archive.load_done(settings.done_path()) == {"A", "B"}


def test_freeze_retries_same_item_after_relogin(monkeypatch):
    calls = []

    def flaky(page, row, *rest):
        calls.append(row["docNo"])
        if len(calls) == 1:
            raise TimeoutError("상세화면(청구서출력)이 안 뜸")
        return _ok(page, row, *rest)

    s, _, asked = _session(flaky, monkeypatch=monkeypatch)
    items = []
    summary = s.download([make_row(docNo="A")], on_item=lambda *a: items.append(a))
    assert calls == ["A", "A"]
    assert len(asked) == 1 and s.page.gotos == 1
    assert summary.ok == 1 and not summary.failed
    assert (0, "retry", "ERP 를 새로 여는 중") in items


def test_document_without_print_button_is_skipped_without_relogin(monkeypatch):
    """2026-10-21 실제 — 끝난 과제의 '정산 완료 후 잔액조정' 처럼 상세화면에 청구서출력이 없는 결의서를 멈춤으로 보고 60초 기다린 뒤 ERP 를
    새로 열어 다시 로그인을 물었다. 이제 건너뛰고(묻지 않고 · ERP 를 새로 열지 않고) 다음 건을 받는다. 기록에 결의서구분을 남긴다."""
    def no_print(page, row, *rest):
        if row["docNo"] == "A":
            raise session_mod.erp.NoPrintScreen("상세화면에 '청구서출력' 이 없음 — 화면 rexpe_0099_01.act · 출력 단추 결의서출력")
        return _ok(page, row, *rest)

    s, logs, asked = _session(no_print, monkeypatch=monkeypatch)
    items = []
    summary = s.download([make_row(docNo="A", gubun="예산잔액조정"), make_row(docNo="B")], on_item=lambda *a: items.append(a))
    assert asked == [] and s.page.gotos == 0
    assert summary.ok == 1 and [r["docNo"] for r in summary.failed] == ["A"]
    assert any(state == "failed" and text.startswith("건너뜀:") for _i, state, text in items)
    assert any("↷ 건너뜀" in line and "예산잔액조정" in line for line in logs)
    assert any("(결의 " in line and "· 예산잔액조정)" in line for line in logs)
    assert archive.load_done(settings.done_path()) == {"B"}


def test_freeze_resumes_by_itself_when_still_logged_in(monkeypatch, tmp_path):
    """상세화면이 멈춰 ERP 를 새로 열었는데 로그인이 그대로면(쿠키가 이 브라우저에 남아 있다) 사람을 부르지 않고 그 과제의 목록을 다시 띄워 잇는다."""
    calls = []

    def flaky(page, row, *rest):
        calls.append(row["docNo"])
        if len(calls) == 1:
            raise TimeoutError("상세화면(청구서출력)이 안 뜸")
        return _ok(page, row, *rest)

    s, logs, asked = _session(flaky, monkeypatch=monkeypatch)
    (tmp_path / "(202408470001)_2024년도 사업비").mkdir()
    settings.update(out_root=str(tmp_path))
    shown = []
    monkeypatch.setattr(s, "_still_logged_in", lambda: True)
    monkeypatch.setattr(session_mod.navigate, "show_list", lambda ctx, project, log, wait: shown.append(project) or (object(), ""))
    monkeypatch.setattr(session_mod.erp, "grid_shown", lambda frame: True)
    summary = s.download([make_row(docNo="202408470001-20250201-1", project="202408470001")])
    assert asked == [] and s.page.gotos == 1 and calls == ["202408470001-20250201-1"] * 2
    assert summary.ok == 1 and shown == ["202408470001", "202408470001"]
    assert any("로그인이 그대로라" in line for line in logs)


def test_freeze_retry_is_capped(monkeypatch):
    def always(page, row, *rest):
        raise TimeoutError("Timeout 60000ms exceeded")

    s, _, asked = _session(always, monkeypatch=monkeypatch)
    summary = s.download([make_row(docNo="A"), make_row(docNo="B")])
    assert len(asked) == 2 * session_mod.MAX_RETRY
    assert [r["docNo"] for r in summary.failed] == ["A", "B"]


def test_other_errors_are_not_retried(monkeypatch):
    def broken(page, row, *rest):
        raise RuntimeError("PDF 저장 실패")

    s, _, asked = _session(broken, monkeypatch=monkeypatch)
    summary = s.download([make_row(docNo="A")])
    assert asked == [] and len(summary.failed) == 1


def test_refusing_relogin_stops_run(monkeypatch):
    def freeze(page, row, *rest):
        raise TimeoutError("상세화면(청구서출력)이 안 뜸")

    s, _, _ = _session(freeze, answers=[False], monkeypatch=monkeypatch)
    summary = s.download([make_row(docNo="A"), make_row(docNo="B")])
    assert summary.stopped and [r["docNo"] for r in summary.failed] == ["A"]


def test_freeze_reload_can_be_turned_off(monkeypatch):
    settings.update(freeze_reload=False)

    def freeze(page, row, *rest):
        raise TimeoutError("상세화면(청구서출력)이 안 뜸")

    s, _, asked = _session(freeze, monkeypatch=monkeypatch)
    s.download([make_row(docNo="A")])
    assert asked == []


def test_stop_request_ends_between_items(monkeypatch):
    stop = {"now": False}

    def once(page, row, *rest):
        stop["now"] = True
        return _ok(page, row, *rest)

    s, _, _ = _session(once, stop=lambda: stop["now"], monkeypatch=monkeypatch)
    summary = s.download([make_row(docNo="A"), make_row(docNo="B")])
    assert summary.ok == 1 and summary.stopped


def test_closed_browser_stops_run(monkeypatch):
    def closed(page, row, *rest):
        raise RuntimeError("Target page, context or browser has been closed")

    s, _, _ = _session(closed, monkeypatch=monkeypatch)
    s.browser = type("B", (), {"is_connected": lambda self: False})()
    summary = s.download([make_row(docNo="A"), make_row(docNo="B")])
    assert summary.stopped and len(summary.failed) == 1


def test_prepare_reports_missing_folder(isolated_home):
    settings.update(out_root=str(isolated_home / "없는폴더"))
    logs: list[str] = []
    report = ErpSession(logs.append, lambda m: True).prepare()
    assert not report.ok
    assert any("⚠⚠" in line for line in logs)


def test_file_logger_writes_log_file():
    log = session_mod.file_logger(lambda line: None)
    log("첫 줄\n둘째 줄")
    text = settings.log_path().read_text(encoding="utf-8")
    assert "첫 줄" in text and "둘째 줄" in text


def test_download_skips_rows_already_in_done(monkeypatch):
    """목록을 읽은 뒤 보관 폴더를 다시 훑어 이미 받은 것으로 확인된 건 — 표가 옛것이어도 다시 받지 않는다(2026-10-14 점검)."""
    calls = []

    def record(page, row, *rest):
        calls.append(row["docNo"])
        return _ok(page, row, *rest)

    s, logs, _ = _session(record, monkeypatch=monkeypatch)
    s.done = {"A"}
    items = []
    summary = s.download([make_row(docNo="A"), make_row(docNo="B")], on_item=lambda *a: items.append(a))
    assert calls == ["B"] and summary.ok == 1
    assert (0, "done", "이미 받음") in items
    assert any("이미 받은 문서번호라 건너뜀" in line for line in logs)


def test_download_asks_to_close_claim_form_first(monkeypatch):
    """일반청구 작성 화면이 열려 있으면 받기 전에 닫게 한다(7절 8번) — 멈추기를 고르면 아무것도 받지 않는다."""
    calls = []
    s, _, asked = _session(lambda page, row, *rest: calls.append(row) or _ok(page, row, *rest),
                           answers=[False], monkeypatch=monkeypatch)
    monkeypatch.setattr(s, "claim_form_open", lambda: True)
    summary = s.download([make_row(docNo="A")])
    assert summary.stopped and calls == [] and "일반청구 작성 화면" in asked[0]


def test_poll_alive_notices_a_closed_browser_window():
    """쉬는 동안 사람이 브라우저 창을 닫으면 알아챈다 — 전에는 명령을 하나 더 보내야 알아채 [브라우저 열기] 가 숨은 채였다(2026-10-20)."""
    class Page:
        def __init__(self):
            self.closed = False
            self.calls = 0

        def is_closed(self):
            return self.closed

        def wait_for_timeout(self, ms):
            self.calls += 1
            if self.closed:
                raise RuntimeError("Target closed")

    page = Page()
    context = type("C", (), {"pages": [page]})()
    s = ErpSession(lambda m: None, lambda m: True)
    assert s.poll_alive() is False                       # 브라우저를 연 적이 없다
    s.browser = type("B", (), {"is_connected": lambda self: True, "contexts": [context]})()
    assert s.poll_alive() is True and page.calls == 1    # 열린 창에 가볍게 한 번 물어 닫힘 소식을 받는다
    page.closed = True
    assert s.poll_alive() is False


class FakeDialog:
    def __init__(self, type_="confirm", message="저장하시겠습니까?", page=None, fail=False):
        self.type, self.message, self.page, self.fail = type_, message, page, fail
        self.done = ""

    def accept(self, *_a):
        if self.fail:
            raise RuntimeError("Cannot accept dialog which is already handled!")
        self.done = "accept"

    def dismiss(self):
        if self.fail:
            raise RuntimeError("already handled")
        self.done = "dismiss"


def _page_with_handlers(count):
    impl = type("Impl", (), {"listeners": lambda self, event: ["h"] * count if event == "dialog" else []})()
    return type("P", (), {"_impl_obj": impl})()


def test_dialog_is_left_for_the_person_while_they_use_the_browser():
    """Playwright 는 받는 곳이 없으면 확인 창을 보이지 않고 '취소' 한다 — 사람이 앱 브라우저에서 누른 저장이 조용히 취소됐다
    (2026-10-20 카드청구 회의록등록). 사람이 쓰는 동안에는 처리하지 않고 두어 브라우저에 보이게 한다."""
    logs = []
    s = ErpSession(logs.append, lambda m: True)
    assert s.hands_on is False             # 기본은 전처럼 앱이 닫는다 — 앱의 브라우저 스레드만 쉬는 동안 True 로 둔다(ui/worker.py)
    s.hands_on = True
    dialog = FakeDialog(page=_page_with_handlers(0))
    s._on_dialog(dialog)
    assert dialog.done == "" and "직접 누르세요" in logs[-1]


def test_dialog_closed_by_the_app_only_while_it_fills_and_has_no_handler():
    logs = []
    s = ErpSession(logs.append, lambda m: True)
    s.hands_on = False
    dialog = FakeDialog(page=_page_with_handlers(0))
    s._on_dialog(dialog)
    assert dialog.done == "dismiss" and "앱이 닫음" in logs[-1]          # 전처럼(Playwright 기본) — 자동화가 멈추지 않게
    leave = FakeDialog(type_="beforeunload", page=None)
    s._on_dialog(leave)
    assert leave.done == "accept"
    # 앱의 저장 · 팝업 처리기가 붙은 창은 그 처리기가 받는다 — 겹쳐 누르면 'already handled' 오류
    owned = FakeDialog(page=_page_with_handlers(1))
    s._on_dialog(owned)
    assert owned.done == ""
    s.hands_on = True
    owned_human = FakeDialog(page=_page_with_handlers(1))
    s._on_dialog(owned_human)
    assert owned_human.done == ""
    # 사람이 먼저 눌렀으면(이미 닫힘) 오류 없이 넘어간다
    s.hands_on = False
    s._on_dialog(FakeDialog(page=None, fail=True))

