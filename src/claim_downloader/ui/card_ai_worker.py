"""카드청구 AI 읽기 스레드 — 영수증 사진 · 회의록 PDF 를 Claude Code 로 읽는 동안 창이 얼지 않게(claims/card_ai.py).

결제 건 하나에 수십 초가 걸린다. ui/minutes_worker.py 와 같은 모양이다(큐로 명령, Qt 시그널로 결과). 브라우저 스레드(worker.py)와
섞지 않는다 — ERP 와 상관없는 일이고, 넣는 중에도 다른 폴더를 읽을 수 있게. 읽은 것은 card_ai.remember 로 캐시에 남기고,
화면은 결제 건 하나가 끝날 때마다 그 폴더를 다시 읽는다(card.load_job 이 캐시를 쓴다).
"""
from __future__ import annotations

import queue
import threading
import traceback

from PySide6.QtCore import QObject, Signal

from ..claims import card_ai
from ..minutes import logbook
from ..minutes.errors import BackendError, fatal_kind

FATAL_TEXT = {"login": "Claude 로그인이 풀림", "limit": "Claude 사용 한도에 걸림", "balance": "Claude 잔액 부족"}


class CardAiWorker(QObject):
    log = Signal(str)
    started = Signal(str, int, int)         # 결제 건 폴더, 몇 번째, 모두 — 한 번 맡긴 묶음 안에서
    done = Signal(str, object)              # 결제 건 폴더, dict(읽은 것) 또는 str(못 읽은 까닭)
    finished = Signal(str)                  # 멈춘 까닭 종류('' · 'login' · 'limit' · 'balance')

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="card-ai", daemon=True)
        self._thread.start()

    # ── 화면 스레드에서 부르는 것 ──────────────────────────────────────────
    def run(self, jobs: list[tuple[str, list[str]]]) -> None:
        """jobs = [(결제 건 폴더, 그 폴더의 파일들)] — 차례로 읽는다. 앞 묶음이 돌고 있으면 그 뒤에."""
        self._stop.clear()
        self._queue.put(("run", (list(jobs),)))

    def request_stop(self) -> None:
        """지금 읽는 결제 건은 마치고 남은 것은 하지 않는다 — CLI 를 끊으면 반쪽 결과가 남는다."""
        self._stop.set()

    def shutdown(self, timeout: float = 2.0) -> None:
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
            except Exception:  # noqa: BLE001 — 스레드가 죽으면 화면이 '읽는 중' 에 멈춘다
                logbook.log("카드 AI 읽기 오류\n" + traceback.format_exc())
                self.finished.emit("")

    def _do_run(self, jobs: list[tuple[str, list[str]]]) -> None:
        total = len(jobs)
        logbook.log(f"카드: 영수증 그림 · 회의록을 AI(Claude Code)로 읽습니다 — 결제 {total}건")
        fatal = ""
        for number, (folder, files) in enumerate(jobs, 1):
            if fatal or self._stop.is_set():
                self.done.emit(folder, FATAL_TEXT.get(fatal, "멈춤") + " — 읽지 않음")
                continue
            self.started.emit(folder, number, total)
            try:
                data = card_ai.read(folder, files)
            except BackendError as error:
                fatal = fatal_kind(error)
                logbook.log(f"카드 AI 읽기 {number}/{total} 실패: {error}")
                self.done.emit(folder, str(error))
                continue
            try:
                card_ai.remember(folder, files, data)
            except OSError as error:
                logbook.log(f"카드 AI 읽은 것을 남기지 못함(다음에 다시 읽음): {error}")
            logbook.log(f"카드 AI 읽기 {number}/{total}: {card_ai.found_text(data)}")
            self.done.emit(folder, data)
        if fatal:
            logbook.log(f"카드 AI 읽기 멈춤 — {FATAL_TEXT.get(fatal, fatal)}")
        self.finished.emit(fatal)
