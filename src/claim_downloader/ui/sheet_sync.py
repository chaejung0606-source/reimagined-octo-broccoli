"""관리대장 구글 시트 맞추기 — 뒤 스레드(parking_sheet.py 는 구글까지 몇 초 걸린다). 화면은 기다리지 않는다.

하나만 둔다(instance) — 설정 카드의 [연결 확인] 과 관리대장 화면이 같은 것을 쓴다. 맞추는 중에 또 부르면 끝난 뒤 한 번 더 한다(고친 것이 빠지지 않게).
브라우저 스레드(worker.py)와 섞지 않는다 — 주차 사이트 일과 상관없이 돈다.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .. import parking_sheet


class SheetSync(QObject):
    synced = Signal(object)        # parking_sheet.Result — 관리대장을 맞춘 뒤
    checked = Signal(object)       # parking_sheet.Result — [연결 확인]
    history_saved = Signal(object)  # parking_sheet.Result — 할인내역 탭에 쌓은 뒤

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.busy = False
        self._again = False
        self.last: parking_sheet.Result | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.run_now)
        self.synced.connect(self._finished)

    @staticmethod
    def connected() -> bool:
        return parking_sheet.load_config().connected

    def request(self, delay_ms: int = 1500) -> None:
        """대장을 고친 뒤 — 잇달아 고쳐도 한 번에 맞추게 조금 기다린다."""
        if self.connected():
            self._timer.start(delay_ms)

    def run_now(self) -> None:
        if not self.connected():
            return
        if self.busy:
            self._again = True
            return
        self.busy = True
        threading.Thread(target=lambda: self.synced.emit(self._safe(parking_sheet.sync_ledger)), daemon=True).start()

    def check(self) -> None:
        threading.Thread(target=lambda: self.checked.emit(self._safe(parking_sheet.check)), daemon=True).start()

    def save_history(self, headers: list[str], rows: list[list[str]]) -> None:
        if self.connected() and rows:
            threading.Thread(target=lambda: self.history_saved.emit(self._safe(lambda: parking_sheet.push_history(headers, rows))),
                             daemon=True).start()

    @staticmethod
    def _safe(work) -> parking_sheet.Result:
        try:
            return work()
        except Exception as error:  # noqa: BLE001 — 뒤 스레드가 죽으면 화면이 '맞추는 중' 에 멈춘다
            return parking_sheet.Result(note="구글 시트와 맞추지 못했습니다: " + (str(error).splitlines()[0][:120] or type(error).__name__))

    def _finished(self, result) -> None:
        self.busy = False
        self.last = result
        if self._again:
            self._again = False
            self.run_now()


_instance: SheetSync | None = None


def instance() -> SheetSync:
    global _instance
    if _instance is None:
        _instance = SheetSync()
    return _instance
