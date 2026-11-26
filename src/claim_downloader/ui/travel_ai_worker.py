"""출장증빙 AI 읽기 스레드 — 그림 · 스캔 영수증을 Claude Code 로 읽는 동안 창이 얼지 않게(travel/ai_read.py).

카드청구의 ui/card_ai_worker.py 와 같은 모양이다(큐로 명령, Qt 시그널로 결과). 몇 개씩 묶어 읽고, 한 묶음이 끝날 때마다 화면이
그 파일들의 빈 칸을 채운다. 읽은 것은 ai_read.remember 로 캐시에 남긴다 — 같은 파일은 다시 읽지 않는다.
"""
from __future__ import annotations

import queue
import threading
import traceback

from PySide6.QtCore import QObject, Signal

from ..minutes import logbook
from ..minutes.errors import BackendError, fatal_kind
from ..travel import ai_read

FATAL_TEXT = {"login": "Claude 로그인이 풀림", "limit": "Claude 사용 한도에 걸림", "balance": "Claude 잔액 부족"}


class TravelAiWorker(QObject):
    log = Signal(str)
    started = Signal(int, int)              # 몇 번째 파일부터, 모두 — 한 번 맡긴 묶음 안에서
    done = Signal(object)                   # {경로: 읽은 것} — 한 묶음
    finished = Signal(str)                  # 멈춘 까닭 종류('' · 'login' · 'limit' · 'balance' · 그 밖의 실패 글)

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="travel-ai", daemon=True)
        self._thread.start()

    def run(self, files: list[tuple[str, str]]) -> None:
        """files = [(경로, 항목)] — 몇 개씩 묶어 차례로 읽는다."""
        self._stop.clear()
        self._queue.put(("run", (list(files),)))

    def request_stop(self) -> None:
        self._stop.set()

    def shutdown(self, timeout: float = 2.0) -> None:
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
            except Exception:  # noqa: BLE001 — 스레드가 죽으면 화면이 '읽는 중' 에 멈춘다
                logbook.log("출장 AI 읽기 오류\n" + traceback.format_exc())
                self.finished.emit("오류")

    def _do_run(self, files: list[tuple[str, str]]) -> None:
        total = len(files)
        logbook.log(f"출장증빙: 그림 · 스캔 영수증을 AI(Claude Code)로 읽습니다 — 파일 {total}개")
        stopped = ""
        done = 0
        for batch in ai_read.batches(files):
            if self._stop.is_set():
                stopped = stopped or "멈춤"
                break
            self.started.emit(done + 1, total)
            try:
                results = ai_read.read(batch)
            except BackendError as error:
                kind = fatal_kind(error)
                logbook.log(f"출장 AI 읽기 실패({done + 1}~{done + len(batch)}/{total}): {error}")
                if kind:
                    stopped = kind
                    break
                stopped = str(error)[:80]
                done += len(batch)
                continue
            try:
                ai_read.remember(results)
            except OSError as error:
                logbook.log(f"출장 AI 읽은 것을 남기지 못함(다음에 다시 읽음): {error}")
            done += len(batch)
            logbook.log(f"출장 AI 읽기 {done}/{total}: {ai_read.found_text(results, batch)}")
            self.done.emit(results)
        if stopped in FATAL_TEXT:
            logbook.log(f"출장 AI 읽기 멈춤 — {FATAL_TEXT[stopped]}")
        self.finished.emit(stopped)
