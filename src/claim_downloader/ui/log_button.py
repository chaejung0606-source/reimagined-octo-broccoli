"""[로그 보내기] — 업무 화면 머리의 단추 · 오류 창의 단추 · 사용자 메뉴가 같이 쓴다(log_send.py, CLAUDE.md 24절).

보내기는 뒤 스레드에서 한다(구글 웹 앱은 몇 초 걸린다). 보내면 Claude 가 읽을 주소를 담은 한 줄을 클립보드에 둔다 — 담당자는 채팅에
붙여 넣기만 한다. 못 보내면(연결 전 · 옛 스크립트 · 인터넷) 전처럼 가린 기록 전체를 복사해 두고 까닭을 알린다.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from .. import log_send, updater

HINT = "[로그 보내기] 를 누르면 Claude 가 바로 읽을 수 있게 기록을 보냅니다."


def known_names(widget: QWidget | None) -> set[str]:
    """기록에서 가릴 이름 — 일반청구에 읽어 둔 명단 + 임시저장한 사람(share_log 가 규칙으로 찾는 이름 밖의 것)."""
    names: set[str] = set()
    window = widget.window() if widget is not None else None
    claim = (getattr(window, "_pages", None) or {}).get("claim")
    for job in getattr(claim, "_jobs", None) or []:
        if job is not None:
            names.update(p.name for p in job.people)
    try:
        from ..claims import record
        names.update(record.saved_names())
    except Exception:  # noqa: BLE001 — 기록 파일을 못 읽어도 규칙으로 찾는 이름은 가린다
        pass
    return names


class _Sender(QObject):
    """하나만 — 보내는 중에 또 누르면 겹쳐 보내지 않는다. 뒤 스레드의 결과는 신호로 화면 스레드에 넘긴다."""
    done = Signal(object, object)      # (log_send.Sent, 끝나면 부를 것)

    def __init__(self) -> None:
        super().__init__()
        self.busy = False
        self.done.connect(self._on_done)

    def _on_done(self, sent, finish) -> None:
        self.busy = False
        finish(sent)


_sender: _Sender | None = None


def _instance() -> _Sender:
    global _sender
    if _sender is None:
        _sender = _Sender()
    return _sender


def _status(widget: QWidget | None, text: str) -> None:
    window = widget.window() if widget is not None else None
    if window is not None and hasattr(window, "statusBar"):
        window.statusBar().showMessage(text, 6000)


def send_log(parent: QWidget, task: str, error: str = "", on_done: Callable[[object], None] | None = None,
             show: Callable[[QWidget, object], None] | None = None) -> bool:
    """보내기 시작 — 보내는 중이면 False. 끝나면 결과 창(show, 기본 show_result)을 띄우고 on_done 을 부른다."""
    sender = _instance()
    if sender.busy:
        _status(parent, "로그를 보내는 중입니다 — 잠시만 기다려 주세요")
        return False
    names = known_names(parent)          # 화면을 읽으니 화면 스레드에서
    sender.busy = True
    QApplication.setOverrideCursor(Qt.BusyCursor)
    _status(parent, "로그를 구글 시트로 보내는 중…")

    def work() -> None:
        try:
            sent = log_send.send(task, error, names, updater.current_version())
        except Exception as failure:  # noqa: BLE001 — 뒤 스레드가 죽으면 단추가 꺼진 채로 남는다
            sent = log_send.Sent(note="로그를 보내지 못했습니다 — " + (str(failure).splitlines() or [type(failure).__name__])[0][:200])
        sender.done.emit(sent, finish)

    def finish(sent) -> None:
        QApplication.restoreOverrideCursor()
        _status(parent, "로그를 보냈습니다 — 채팅에 붙여 넣으세요" if sent.ok else "로그를 보내지 못했습니다")
        (show or show_result)(parent, sent)
        if on_done is not None:
            on_done(sent)

    threading.Thread(target=work, daemon=True).start()
    return True


def show_result(parent: QWidget, sent) -> None:
    clipboard = QGuiApplication.clipboard()
    if sent.ok:
        clipboard.setText(sent.line)
        QMessageBox.information(
            parent, "로그 보내기",
            "개인정보를 가린 실행 기록을 구글 시트 '로그' 탭으로 보냈습니다.\n\n"
            "채팅에 붙여 넣을 한 줄을 복사해 두었습니다 — Claude 채팅 창에서 Ctrl+V 로 붙여 넣고 보내기만 하세요. "
            "Claude 가 그 주소로 기록을 읽습니다.\n\n"
            "(이름 · 계좌는 규칙으로 가립니다 · 시트에는 최근 30번만 남습니다)")
        return
    if not sent.text:
        QMessageBox.information(parent, "로그 보내기", sent.note)
        return
    clipboard.setText(sent.text)
    box = QMessageBox(QMessageBox.Warning, "로그 보내기",
                      f"{sent.note}\n\n대신 개인정보를 가린 기록 전체를 복사해 두었습니다 — 이번에는 채팅에 붙여 넣어 주세요.",
                      QMessageBox.Close, parent)
    settings_button = None
    window = parent.window() if parent is not None else None
    if getattr(window, "_pages", None) is not None:       # 앱 창(MainWindow.open) — 결과 표 창 같은 대화상자의 open() 은 다르다
        settings_button = box.addButton("설정 열기", QMessageBox.ActionRole)
    box.setDefaultButton(QMessageBox.Close)
    _exec(box)
    if settings_button is not None and box.clickedButton() is settings_button:
        window.open("settings")


def _exec(box: QMessageBox) -> None:
    """창을 띄우고 기다린다 — 시험은 이것을 바꿔 끼운다."""
    box.exec()


def warn(parent: QWidget, title: str, message: str, task: str, detail: str = "자세한 내용은 [진행 기록] 에 있습니다.") -> None:
    """오류 창 — [로그 보내기] 를 함께 둔다(담당자 2026-10-22 "오류 생겼거나 했을 때 … 버튼하나만 누르면")."""
    box = QMessageBox(QMessageBox.Warning, title, f"{message}\n\n{detail}\n{HINT}", QMessageBox.Close, parent)
    send = box.addButton("로그 보내기", QMessageBox.ActionRole)
    box.setDefaultButton(QMessageBox.Close)
    _exec(box)
    if box.clickedButton() is send:
        send_log(parent, task, error=message)


class LogSendButton(QPushButton):
    """업무 화면 머리 오른쪽의 [로그 보내기]."""

    def __init__(self, task: str, parent: QWidget | None = None):
        super().__init__("로그 보내기", parent)
        self.task = task
        self.setObjectName("ghost")
        self.setToolTip("개인정보를 가린 최근 실행 기록을 구글 시트로 보내고, 채팅에 붙여 넣을 한 줄을 복사합니다 — "
                        "Claude 가 그 기록을 바로 읽습니다")
        self.clicked.connect(self._send)

    def _send(self) -> None:
        self.setEnabled(False)
        if not send_log(self, self.task, on_done=lambda _sent: self.setEnabled(True)):
            self.setEnabled(True)
