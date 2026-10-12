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
    s.browser = type("B", (), {"is_connected": lambda self: True})()
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
    assert (0, "retry", "다시 로그인 대기") in items


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
