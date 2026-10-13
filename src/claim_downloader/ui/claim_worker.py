"""일반청구 추출 스레드 — 지출 폴더를 AI 로 읽는 동안 창이 얼지 않게.

ui/minutes_worker.py 와 같은 모양이다(큐로 명령, Qt 시그널로 결과). ERP 에 채우는 쪽은 브라우저
스레드(ui/worker.py)가 맡는다 — Playwright 는 그 스레드에서만 쓸 수 있다.
"""
from __future__ import annotations

import queue
import threading
import traceback

from PySide6.QtCore import QObject, Signal

from ..claims import extract, process
from ..minutes import logbook


class ClaimExtractWorker(QObject):
    log = Signal(str)
    checked = Signal(str, bool, str, str)   # 백엔드 key, 쓸 수 있는지, 안내, 상태
    started = Signal(int)
    done = Signal(int, object)              # 번호, claims.ExtractResult
    skipped = Signal(int, str)
    stopped = Signal(int)
    finished = Signal(str, int, int)        # 치명 종류, 성공 수, 실패 수
    busy = Signal(bool, str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="claims", daemon=True)
        self._thread.start()

    def check(self, key: str) -> None:
        self._queue.put(("check", (key,)))

    def run(self, folders: list[str], key: str) -> None:
        self._stop.clear()
        self._queue.put(("run", (list(folders), key)))

    def request_stop(self) -> None:
        self._stop.set()

    def shutdown(self, timeout: float = 3.0) -> None:
        self.request_stop()
        self._queue.put(None)
        self._thread.join(timeout)

    def _loop(self) -> None:
        logbook.set_echo(self.log.emit)
        while True:
            command = self._queue.get()
            if command is None:
                return
            name, args = command
            try:
                getattr(self, "_do_" + name)(*args)
            except Exception as error:  # noqa: BLE001
                logbook.log("일반청구 읽기 오류\n" + traceback.format_exc())
                self.error.emit(str(error).splitlines()[0] if str(error) else type(error).__name__)
            finally:
                self.busy.emit(False, "")

    def _do_check(self, key: str) -> None:
        self.busy.emit(True, "AI 플랫폼을 확인하는 중…")
        backend = extract.get(key)
        ok, note = backend.available()
        self.checked.emit(backend.key, ok, note, getattr(backend, "last_state", ""))

    def _do_run(self, folders: list[str], key: str) -> None:
        backend = extract.get(key)
        self.busy.emit(True, "지출 자료를 읽는 중…")
        logbook.log("일반청구 읽기 시작: %d건 · %s" % (len(folders), backend.label))
        stop, ok_count, fail_count = "", 0, 0
        for index, event, payload in process.run(folders, backend, should_stop=self._stop.is_set):
            if event == "start":
                self.started.emit(index)
            elif event == "done":
                if payload.ok:
                    ok_count += 1
                else:
                    fail_count += 1
                    stop = payload.kind or stop
                self.done.emit(index, payload)
            elif event == "skip":
                self.skipped.emit(index, payload)
            elif event == "stopped":
                self.stopped.emit(index)
        logbook.log("일반청구 읽기 끝: 성공 %d · 실패 %d%s" % (ok_count, fail_count, (" · 중단 " + stop) if stop else ""))
        self.finished.emit(stop, ok_count, fail_count)
