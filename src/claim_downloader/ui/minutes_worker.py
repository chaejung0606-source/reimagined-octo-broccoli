"""회의록 작업 스레드.

회의 1건에 수십 초~수 분(Claude Code 가 20~35턴)이 걸린다. 화면 스레드에서 돌리면 창이 얼어
담당자는 앱이 죽은 줄 안다. ui/worker.py 와 같은 방식이다 — 명령은 큐로 넘기고 결과는 Qt
시그널로 돌아온다. 다만 브라우저 스레드(worker.py)와 섞지 않는다: 회의록은 브라우저와 무관하고,
Playwright 동기 API 는 시작한 스레드에서만 쓸 수 있다.

백엔드는 minutes/backends 에서 key 로 고른다. 이 파일은 규약(base.py)만 안다 — 백엔드가 늘어도
고치지 않는다.
"""
from __future__ import annotations

import queue
import threading
import traceback

from PySide6.QtCore import QObject, Signal

from ..minutes import backends, logbook, process


class MinutesWorker(QObject):
    log = Signal(str)
    started = Signal(int)                   # 회의 번호 — 작성 시작
    done = Signal(int, object)              # 회의 번호, minutes.MeetingResult
    skipped = Signal(int, str)              # 회의 번호, 건너뛴 이유(login · limit · balance)
    stopped = Signal(int)                   # 회의 번호 — 사람이 멈춰 하지 않음
    finished = Signal(str, int, int)        # 치명 종류("" 이면 정상), 성공 수, 실패 수
    busy = Signal(bool, str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="minutes", daemon=True)
        self._thread.start()

    # ── 화면 스레드에서 부르는 것 ──────────────────────────────────────────
    def run(self, meeting_dirs: list[str], key: str) -> None:
        self._stop.clear()
        self._queue.put(("run", (list(meeting_dirs), key)))

    def request_stop(self) -> None:
        """지금 쓰는 회의를 마치고 멈춘다. 돌고 있는 CLI 를 끊으면 반쪽짜리 결과가 남는다."""
        self._stop.set()

    def shutdown(self, timeout: float = 3.0) -> None:
        self.request_stop()
        self._queue.put(None)
        self._thread.join(timeout)

    # ── 작업 스레드 ─────────────────────────────────────────────────────
    def _loop(self) -> None:
        logbook.set_echo(self.log.emit)
        while True:
            command = self._queue.get()
            if command is None:
                return
            name, args = command
            try:
                getattr(self, "_do_" + name)(*args)
            except Exception as error:  # noqa: BLE001 — 스레드가 죽으면 화면이 '작업 중' 에 멈춘다
                logbook.log("회의록 작업 오류\n" + traceback.format_exc())
                self.error.emit(str(error).splitlines()[0] if str(error) else type(error).__name__)
            finally:
                self.busy.emit(False, "")

    def _do_run(self, meeting_dirs: list[str], key: str) -> None:
        backend = backends.get(key)
        self.busy.emit(True, "회의록을 만드는 중…")
        logbook.log("회의록 작업 시작: %d건 · %s" % (len(meeting_dirs), backend.label))
        stop, ok_count, fail_count = "", 0, 0
        for index, event, payload in process.run(meeting_dirs, backend, should_stop=self._stop.is_set):
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
        logbook.log("회의록 작업 끝: 성공 %d · 실패 %d%s" % (ok_count, fail_count, (" · 중단 " + stop) if stop else ""))
        self.finished.emit(stop, ok_count, fail_count)
