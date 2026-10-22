"""[로그 보내기] 화면 — 업무 화면 다섯의 머리에 단추가 있고, 오류 창에서도 보낼 수 있고, 보내면 채팅에 붙일 한 줄이 클립보드에 남는다.
구글은 부르지 않는다(log_send.send 를 바꿔 끼운다). 화면은 offscreen 으로 띄운다."""
from __future__ import annotations

import os
import time

import pytest

from claim_downloader import log_send, settings


def _qt_app():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _close(widget) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _wait(app, check, seconds: float = 5.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if check():
            return True
        time.sleep(0.02)
    return False


def test_every_work_page_has_the_button():
    app = _qt_app()
    from claim_downloader.ui.log_button import LogSendButton
    from claim_downloader.ui.pages.claim import ClaimPage
    from claim_downloader.ui.pages.download import DownloadPage
    from claim_downloader.ui.pages.minutes import MinutesPage
    from claim_downloader.ui.pages.parking import ParkingPage
    from claim_downloader.ui.pages.structure import StructurePage
    from claim_downloader.ui.worker import SessionWorker

    worker = SessionWorker()
    pages = [DownloadPage(worker=worker), MinutesPage(), ClaimPage(worker=worker), ParkingPage(worker=worker), StructurePage(worker=worker)]
    try:
        tasks = [[b.task for b in page.findChildren(LogSendButton)] for page in pages]
        assert tasks == [["증빙 다운로드"], ["회의록 생성"], ["일반청구"], ["주차등록"], ["화면 구조 저장"]]
    finally:
        for page in pages:
            _close(page)
        app.processEvents()


def test_button_sends_and_copies_the_line(monkeypatch):
    app = _qt_app()
    from claim_downloader.ui import log_button

    calls = []

    def fake_send(task, error="", names=(), version=""):
        calls.append((task, error))
        return log_send.Sent(ok=True, log_id="x1", url="https://script.google.com/macros/s/a/exec?key=k&id=x1",
                             line="로그 보냈어요 (주차등록 · 10-22 15:31) https://script.google.com/macros/s/a/exec?key=k&id=x1")

    shown = []
    monkeypatch.setattr(log_button.log_send, "send", fake_send)
    monkeypatch.setattr(log_button.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    button = log_button.LogSendButton("주차등록")
    try:
        button.click()
        assert not button.isEnabled()                           # 보내는 동안 꺼 둔다
        assert _wait(app, lambda: button.isEnabled())
        assert calls == [("주차등록", "")]
        assert app.clipboard().text().startswith("로그 보냈어요 (주차등록")
        assert shown and "Ctrl+V" in shown[0]
    finally:
        _close(button)


def test_without_connection_the_masked_log_is_copied_instead(monkeypatch):
    app = _qt_app()
    from claim_downloader.ui import log_button

    settings.log_path().write_text("10:00:01 소득자 자동 선택: 홍길동(202600001) — 학번 일치\n", encoding="utf-8")
    boxes = []
    monkeypatch.setattr(log_button, "_exec", lambda box: boxes.append(box.text()))
    button = log_button.LogSendButton("일반청구")
    try:
        button.click()
        assert _wait(app, lambda: button.isEnabled())
        assert boxes and "구글 시트가 연결돼 있지 않아" in boxes[0]
        copied = app.clipboard().text()
        assert "업무 일반청구" in copied and "홍길동" not in copied and "홍○○" in copied
    finally:
        _close(button)


def test_error_box_offers_to_send(monkeypatch):
    app = _qt_app()
    from PySide6.QtWidgets import QWidget

    from claim_downloader.ui import log_button

    sent = []
    monkeypatch.setattr(log_button, "send_log", lambda parent, task, error="", **k: sent.append((task, error)) or True)
    texts = []

    def press_send(box):
        texts.append(box.text())
        box.buttons()                                           # 단추가 만들어졌는지
        [send] = [b for b in box.buttons() if b.text() == "로그 보내기"]
        send.click()

    monkeypatch.setattr(log_button, "_exec", press_send)
    parent = QWidget()
    try:
        log_button.warn(parent, "문제가 생겼습니다", "첨부를 받지 못했습니다", "증빙 다운로드")
        assert sent == [("증빙 다운로드", "첨부를 받지 못했습니다")]
        assert "첨부를 받지 못했습니다" in texts[0] and log_button.HINT in texts[0]
        # 닫기만 누르면 보내지 않는다
        sent.clear()
        monkeypatch.setattr(log_button, "_exec", lambda box: None)
        log_button.warn(parent, "문제가 생겼습니다", "x", "증빙 다운로드")
        assert sent == []
    finally:
        _close(parent)
        app.processEvents()
