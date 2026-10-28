"""AI 플랫폼 로그인 상태 — 앱 전체에 하나. 위쪽 바 단추 · 홈 띠 · 설정 · 회의록 생성이 모두 이것을 본다.

담당자 요청(2026-10-14): 로그인 단추를 회의록 화면에서 위쪽 바로 옮기고, 앱을 켜면 홈에서 바로 로그인 상태를 보고,
로그아웃돼 있으면 로그인할 수 있게. 그래서 확인은 화면마다 하지 않고 여기 한 곳에서 한다(claim_downloader/ai.py).

- 확인(ai.probe)은 외부 명령이라 몇 초 걸린다 — 뒤 스레드에서 돌리고 결과는 신호로 받는다(화면 스레드로 옮겨진다).
- 로그인 창을 연 뒤에는 로그인이 끝날 때까지 4초마다(최대 3분) 다시 확인한다 — 담당자가 [다시 확인] 을 누르지 않아도
  로그인을 마치면 위쪽 단추가 초록으로 바뀐다.
- 작업이 '로그인 풀림' 으로 멈추면 화면이 mark() 로 알려 위쪽 단추 · 홈 띠도 바로 바뀐다.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QWidget

from .. import ai, settings
from .widgets import ElideLabel, Pill

POLL_MS = 4000
POLL_TRIES = 45          # 4초 × 45 = 3분 — 브라우저에서 로그인을 마치기에 넉넉하다

_INSTANCE: "AiStatus | None" = None


def instance() -> "AiStatus":
    """앱에 하나뿐인 상태 객체. QApplication 이 만들어진 뒤에 부른다."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AiStatus()
    return _INSTANCE


class AiStatus(QObject):
    changed = Signal()
    _probed = Signal(object)          # 뒤 스레드 → 화면 스레드: ai.Status
    _finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._statuses: dict[str, ai.Status] = {}
        self._checking = False
        self._again = False
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_tick)
        self._poll_left = 0
        self._probed.connect(self._on_probed)
        self._finished.connect(self._on_finished)

    # ── 읽기 ───────────────────────────────────────────────────────────
    def status(self, key: str) -> ai.Status:
        return self._statuses.get(key) or ai.Status(key=key)

    def for_use(self, use: str) -> ai.Status:
        """그 업무(minutes · claim)에 쓰기로 정한 플랫폼의 상태."""
        return self.status(ai.chosen(use))

    def statuses(self) -> list[ai.Status]:
        return [self.status(key) for key in ai.used_keys()]

    def headline(self) -> ai.Status | None:
        """위쪽 바 · 홈 띠가 보여 줄 대표 — 손이 필요한 것이 먼저."""
        return ai.summary(self.statuses())

    @property
    def checking(self) -> bool:
        return self._checking

    # ── 확인 ───────────────────────────────────────────────────────────
    def check(self) -> None:
        """설정에서 쓰는 플랫폼들을 다시 확인한다. 확인 중에 또 부르면 끝난 뒤 한 번 더."""
        if self._checking:
            self._again = True
            return
        self._checking = True
        keys = ai.used_keys()
        for key in keys:
            if key not in self._statuses:
                self._statuses[key] = ai.Status(key=key)
        self.changed.emit()

        def run() -> None:
            try:
                for key in keys:
                    self._probed.emit(ai.probe(key))
            finally:
                self._finished.emit()

        threading.Thread(target=run, name="ai-check", daemon=True).start()

    def _on_probed(self, status: ai.Status) -> None:
        self._statuses[status.key] = status
        if self._poll.isActive() and all(s.state == ai.OK for s in self.statuses()):
            self._poll.stop()
        self.changed.emit()

    def _on_finished(self) -> None:
        self._checking = False
        self.changed.emit()
        if self._again:
            self._again = False
            self.check()

    def mark(self, key: str, state: str, note: str = "") -> None:
        """작업이 '로그인 풀림' 같은 이유로 멈췄을 때 — 확인을 기다리지 않고 바로 표시를 바꾼다."""
        self._statuses[key] = ai.Status(key=key, state=state, note=note)
        self.changed.emit()

    # ── 로그인 ─────────────────────────────────────────────────────────
    def login(self, parent: QWidget | None = None, key: str = "") -> bool:
        """로그인 창을 연다. 이메일은 로그인 화면에 미리 채우는 용도로만 설정에 남긴다 — 비밀번호는 어디에도 두지 않는다."""
        if not key:
            needs = [s.key for s in self.statuses() if s.state != ai.OK and ai.can_login(s.key)]
            key = needs[0] if needs else ai.used_keys()[0]
        label = ai.short_label(key)
        if not ai.can_login(key):
            QMessageBox.information(parent, "AI 로그인", f"{label} 은(는) 앱에서 로그인 창을 열 수 없습니다.")
            return False
        email = settings.load().claude_email.strip()
        if not email:
            email, ok = QInputDialog.getText(
                parent, f"{label} 로그인",
                "로그인에 쓸 이메일 주소를 입력하세요.\n로그인 화면에 미리 채워집니다. (이 PC 에만 저장되고, 비밀번호는 저장하지 않습니다)")
            if not ok:
                return False
            email = email.strip()
            if email:
                settings.update(claude_email=email)
        try:
            ai.open_login(key, email)
        except Exception as error:  # noqa: BLE001 — 사유를 그대로 보여 준다
            QMessageBox.warning(
                parent, f"{label} 로그인",
                f"로그인 창을 열지 못했습니다.\n\n{error}\n\n{label} 이(가) 설치되어 있는지 확인해 주세요. "
                "설치했는데도 이 메시지가 보이면 컴퓨터를 다시 시작해 보세요.")
            return False
        QMessageBox.information(
            parent, f"{label} 로그인",
            "로그인 창을 열었습니다.\n\n새로 열린 검은 창의 안내를 따라가면 브라우저가 열립니다.\n"
            "브라우저에서 로그인을 마치면 검은 창이 알아서 끝납니다. 그 사이 검은 창에는 아무것도 입력하지 마세요.\n\n"
            "로그인을 마치면 앱이 알아서 확인합니다 — 위쪽의 AI 단추가 초록 '로그인됨' 으로 바뀌면 됩니다.")
        self._poll_left = POLL_TRIES
        self._poll.start()
        return True

    def _poll_tick(self) -> None:
        if self._poll_left <= 0 or all(s.state == ai.OK for s in self.statuses()):
            self._poll.stop()
            return
        self._poll_left -= 1
        self.check()


class PlatformRow(QWidget):
    """회의록 생성 화면 위의 'AI 플랫폼' 한 줄 — 고르기 · 로그인은 여기서 하지 않는다.

    플랫폼은 설정에서 정하고 로그인은 위쪽 바 AI 단추에서 한다(담당자 요청 2026-10-14). 이 줄은 그 결과를 보여 주고
    [다시 확인] · [설정에서 바꾸기] 만 둔다. 화면은 changed 로 받은 상태를 보고 [작업 시작] 을 열고 닫는다.
    """

    changed = Signal(object)              # ai.Status — 그 업무에 쓰는 플랫폼의 지금 상태
    settings_requested = Signal()

    def __init__(self, use: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.use = use
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        label = QLabel("AI 플랫폼")
        label.setObjectName("fieldLabel")
        row.addWidget(label)
        self.name = QLabel("")
        self.name.setObjectName("body")
        row.addWidget(self.name)
        self.pill = Pill("확인 중", "neutral")
        row.addWidget(self.pill, 0, Qt.AlignVCenter)
        self.note = ElideLabel("")
        self.note.setObjectName("muted")
        row.addWidget(self.note, 1)
        self.recheck_button = QPushButton("다시 확인")
        self.recheck_button.setObjectName("ghost")
        self.recheck_button.clicked.connect(instance().check)
        row.addWidget(self.recheck_button)
        self.settings_button = QPushButton("설정에서 바꾸기")
        self.settings_button.setObjectName("ghost")
        self.settings_button.setToolTip("이 업무에 쓸 AI 플랫폼은 설정 → AI 플랫폼에서 정합니다")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        row.addWidget(self.settings_button)
        instance().changed.connect(self.refresh)
        self.refresh()

    def status(self) -> ai.Status:
        return instance().for_use(self.use)

    def refresh(self) -> None:
        status = self.status()
        self.name.setText(ai.short_label(status.key))
        self.name.setToolTip(status.label)
        checking = status.state == ai.CHECKING or (instance().checking and not status.checked_at)
        if checking:
            self.pill.set_status("확인 중", "neutral")
            self.note.setText("")
        else:
            self.pill.set_status(status.text, status.tone)
            if status.state == ai.NO_LOGIN and ai.can_login(status.key):
                self.note.setText("로그인이 필요합니다 — 위쪽의 AI 단추에서 [로그인] 을 누르세요")
            else:
                self.note.setText(status.note)
        self.note.setToolTip(status.note)
        self.changed.emit(status)

    def set_enabled_for_run(self, enabled: bool) -> None:
        """작업 중에는 다시 확인 · 설정 단추를 잠근다 — 도는 중에 플랫폼이 바뀌면 안 된다."""
        self.recheck_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)
