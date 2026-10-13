"""브라우저 작업 스레드.

Playwright 동기 API 는 시작한 스레드에서만 쓸 수 있다. 그래서 스레드 하나를
앱이 살아 있는 동안 붙잡아 두고, 화면은 명령을 큐로 넘기기만 한다. 결과는
Qt 시그널로 돌아온다 — 다른 스레드에서 보낸 시그널은 Qt 가 화면 스레드로
옮겨 준다.

작업을 화면 스레드에서 돌리면 청구서 한 건(보고서 생성에 수십 초)마다 창이
얼어 사용자는 앱이 죽은 줄 안다.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback

from PySide6.QtCore import QObject, Signal

from ..session import BrowserClosed, ErpSession, ListNotFound, file_logger


class SessionWorker(QObject):
    log = Signal(str)
    busy = Signal(bool, str)            # 작업 중 여부, 상태 문구
    prepared = Signal(object)           # archive.ScanReport
    browser_opened = Signal()
    listed = Signal(object)             # targets.Selection
    list_failed = Signal(str)
    item = Signal(int, str, str)        # 번호, 상태, 설명
    finished = Signal(object)           # session.RunSummary
    relogin = Signal(str)               # 사람이 다시 로그인해야 함
    error = Signal(str)
    browser_state = Signal(bool)        # 명령을 마칠 때마다 브라우저가 살아 있는지
    structure_saved = Signal(str)       # 진단: 화면 구조를 저장한 파일 경로

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume_ok = False
        self._waiting_relogin = False
        self._thread = threading.Thread(target=self._loop, name="erp-browser", daemon=True)
        self._thread.start()

    # ── 화면 스레드에서 부르는 것 ──────────────────────────────────────────
    def open_browser(self) -> None:
        self._queue.put(("open", ()))

    def read_list(self) -> None:
        self._queue.put(("read_list", ()))

    def download(self, targets: list[dict]) -> None:
        self._stop.clear()
        self._queue.put(("download", (targets,)))

    def capture_structure(self) -> None:
        """진단 모드 — 지금 열린 화면의 구조를 파일로. 읽기만 한다."""
        self._queue.put(("capture", ()))

    def request_stop(self) -> None:
        """지금 받는 건을 마치고 멈춘다. 받는 도중 끊으면 반쪽짜리 파일이 남는다."""
        self._stop.set()
        if self._waiting_relogin:
            self.answer_relogin(False)

    def answer_relogin(self, ok: bool) -> None:
        self._resume_ok = ok
        self._resume.set()

    def shutdown(self, timeout: float = 8.0) -> None:
        self.request_stop()
        self._queue.put(None)
        self._thread.join(timeout)

    # ── 작업 스레드 ─────────────────────────────────────────────────────
    def _ask_relogin(self, message: str) -> bool:
        if self._stop.is_set():
            return False
        self._resume.clear()
        self._waiting_relogin = True
        self.relogin.emit(message)
        self._resume.wait()
        self._waiting_relogin = False
        return self._resume_ok and not self._stop.is_set()

    def _loop(self) -> None:
        log = file_logger(self.log.emit)
        log("════ %s 앱 실행 ════" % time.strftime("%Y-%m-%d"))
        session = ErpSession(log, self._ask_relogin, should_stop=self._stop.is_set)
        while True:
            command = self._queue.get()
            if command is None:
                session.close()
                return
            name, args = command
            try:
                getattr(self, "_do_" + name)(session, *args)
            except Exception as error:   # noqa: BLE001 — 스레드가 죽으면 앱 전체가 먹통이 된다
                log("오류: %s" % (str(error).splitlines()[0] if str(error) else type(error).__name__))
                log(traceback.format_exc())
                self.error.emit(str(error).splitlines()[0] if str(error) else type(error).__name__)
            finally:
                self.browser_state.emit(session.browser_open)
                self.busy.emit(False, "")

    def _do_open(self, session: ErpSession) -> None:
        self.busy.emit(True, "보관 폴더를 읽는 중…")
        self.prepared.emit(session.prepare())
        self.busy.emit(True, "브라우저를 여는 중…")
        session.open_browser()
        self.browser_opened.emit()

    def _do_capture(self, session: ErpSession) -> None:
        self.busy.emit(True, "화면 구조를 읽는 중…")
        self.structure_saved.emit(str(session.capture_structure()))

    def _do_read_list(self, session: ErpSession) -> None:
        self.busy.emit(True, "결의서 목록을 읽는 중…")
        try:
            selection = session.read_list()
        except (ListNotFound, BrowserClosed) as error:
            self.list_failed.emit(str(error))
            return
        self.listed.emit(selection)

    def _do_download(self, session: ErpSession, targets: list[dict]) -> None:
        self.busy.emit(True, "청구서를 받는 중…")
        summary = session.download(targets, on_item=self.item.emit)
        self.finished.emit(summary)
