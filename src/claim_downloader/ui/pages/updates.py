"""업데이트 화면.

업데이트는 확인과 적용을 나눠 두었다. 사용자가 무엇이 바뀌는지 보고 나서
누르게 하려는 것이다.
"""
from __future__ import annotations

import html

import traceback

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ... import settings, updater
from ..theme import COLORS
from ..widgets import Card, PageHeader, Pill, muted_label


class UpdateWorker(QObject):
    checked = Signal(object)
    applied = Signal(bool, str)
    failed = Signal(str)

    def __init__(self, action: str):
        super().__init__()
        self.action = action

    def run(self) -> None:
        try:
            if self.action == "check":
                self.checked.emit(updater.check())
            else:
                ok, message = updater.apply()
                self.applied.emit(ok, message)
        except Exception:
            self.failed.emit(traceback.format_exc())


class UpdatesPage(QWidget):
    version_changed = Signal(str)
    status_checked = Signal(object)   # updater.UpdateStatus — 홈의 업데이트 띠가 본다
    applied = Signal(bool)            # 적용이 끝남 — 홈 띠가 [새로고침] 으로 바뀐다
    restart_requested = Signal()      # [새로고침] — 앱이 새로 떠서 받은 것을 반영
    idle = Signal()                   # 확인·적용 스레드가 끝남 — 그동안 창을 닫으려 했으면 그때 닫는다(app.closeEvent)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self._thread: QThread | None = None
        self._status: updater.UpdateStatus | None = None
        self._then_restart = False        # F5 — 확인 · 적용이 끝나면 묻지 않고 새로고침까지
        self._applied = False             # 적용하고 아직 새로고침하지 않음 — F5 는 바로 새로고침

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("pageBody")
        scroll.setWidget(content)
        outer.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 34)
        layout.setSpacing(16)
        layout.addWidget(PageHeader(
            "관리  ›  업데이트", "업데이트",
            "새 기능이나 고친 내용이 올라오면 여기서 받습니다. 설정과 받은 기록은 "
            "앱 폴더 밖에 있어 업데이트해도 유지됩니다."))

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(16)
        holder = QWidget()
        holder.setMaximumWidth(920)
        holder.setLayout(column)
        layout.addWidget(holder, 1)

        status_card = Card("설치 상태", "설치된 버전")
        self.version_label = QLabel(updater.current_version())
        self.version_label.setObjectName("kpiValue")
        status_card.add(self.version_label)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_pill = Pill("확인 전", "neutral")
        status_row.addWidget(self.status_pill, 0, Qt.AlignTop)
        self.status_label = QLabel("업데이트를 확인하지 않았습니다.")
        self.status_label.setObjectName("body")
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, 1)
        status_card.add_layout(status_row)

        buttons = QHBoxLayout()
        self.check_button = QPushButton("업데이트 확인")
        self.check_button.clicked.connect(lambda: self._start("check"))
        self.apply_button = QPushButton("업데이트 적용")
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._confirm_apply)
        # 적용이 끝나면 보인다. 껐다 켤 필요 없이 새 앱이 뜨고 이 창은 닫힌다(담당자 요청 2026-10-13)
        self.restart_button = QPushButton("새로고침")
        self.restart_button.setObjectName("primary")
        self.restart_button.setToolTip("창이 닫혔다가 새 버전으로 다시 열립니다 (2~3초)")
        self.restart_button.clicked.connect(self.restart_requested.emit)
        self.restart_button.hide()
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.restart_button)
        buttons.addStretch(1)
        status_card.add_layout(buttons)
        column.addWidget(status_card)

        options_card = Card("자동 확인")
        self.auto_check = QCheckBox("앱을 시작할 때 새 업데이트가 있는지 확인")
        self.auto_check.setChecked(settings.load().auto_update_check)
        self.auto_check.toggled.connect(
            lambda checked: settings.update(auto_update_check=checked)
        )
        options_card.add(self.auto_check)
        options_card.add(muted_label(
            "적용은 항상 직접 누르셔야 합니다. 확인만 자동으로 하고, 무엇이 바뀌는지 "
            "보여 준 뒤에 적용합니다."
        ))
        column.addWidget(options_card)

        log_card = Card("변경 내역", "적용하면 반영되는 내용")
        self.log = QTextBrowser()
        self.log.setFrameShape(QFrame.NoFrame)
        self.log.setMinimumHeight(140)
        log_card.add(self.log, 1)
        column.addWidget(log_card, 1)

    # ── 실행 ─────────────────────────────────────────────────────────────
    def check_quietly(self) -> None:
        """시작 시 자동 확인. 결과가 없으면 조용히 지나간다."""
        if settings.load().auto_update_check:
            self._start("check")

    def update_and_restart(self) -> None:
        """F5 · 사용자 메뉴 '앱 새로고침' — 업데이트를 확인해 있으면 적용하고 새로고침, 없으면 그대로 새로고침.

        담당자 2026-10-22 "f5를 누르면 새로고침되게" — [새로고침] 만 누르면 앱을 다시 띄울 뿐이라 새 기능이 들어오지 않았다
        (업데이트 화면에서 [업데이트 확인] → [업데이트 적용] 을 먼저 눌러야 했다). 확인 · 적용 중이면 그것이 끝난 뒤 이어서 한다.
        적용 전에는 무엇이 바뀌는지 보이고 한 번 묻는다(이 화면의 원칙 — 확인만 자동, 적용은 사람이 누른다).
        """
        self._then_restart = True
        if self._thread is not None:
            return
        if self._applied:
            self._then_restart = False
            self.restart_requested.emit()
            return
        self._say("업데이트를 확인하고 있습니다… 끝나면 새로고침합니다 (F5)")
        self._start("check")

    def _say(self, text: str) -> None:
        """창 아래 상태 줄 — F5 를 누른 사람이 이 화면을 보고 있지 않아도 지금 무엇을 하는지 알게."""
        window = self.window()
        if hasattr(window, "statusBar"):
            if text:
                window.statusBar().showMessage(text)
            else:
                window.statusBar().clearMessage()

    def _after_check(self, status) -> None:
        """F5 로 확인했을 때 — 있으면 묻고 적용, 없으면 새로고침, 못 하면 까닭."""
        self._then_restart = False
        self._say("")
        if status.error or (status.available and not status.can_apply):
            answer = QMessageBox.question(
                self, "새로고침",
                f"{status.describe()}\n\n업데이트 없이 앱만 새로고침할까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                self.restart_requested.emit()
            return
        if not status.available:
            self._say("최신 버전입니다. 새로고침합니다…")
            self.restart_requested.emit()
            return
        changes = "\n".join(f"· {message}" for message in status.messages[:6])
        if len(status.messages) > 6:
            changes += f"\n· … 외 {len(status.messages) - 6}건"
        answer = QMessageBox.question(
            self, "새로고침",
            f"새 업데이트 {status.behind}건이 있습니다.\n\n{changes}\n\n"
            "적용하고 새로고침할까요? 창이 닫혔다가 새 버전으로 다시 열립니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self._then_restart = True
            self._say("업데이트를 적용하고 있습니다… 끝나면 새로고침합니다 (F5)")
            self._start("apply")

    def _start(self, action: str) -> None:
        if self._thread is not None:
            return
        self.check_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.status_pill.set_status("확인 중" if action == "check" else "적용 중", "info")
        self.status_label.setText("확인 중입니다…" if action == "check" else "적용 중입니다…")

        self._thread = QThread()
        self._worker = UpdateWorker(action)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.checked.connect(self._on_checked, Qt.QueuedConnection)
        self._worker.applied.connect(self._on_applied, Qt.QueuedConnection)
        self._worker.failed.connect(self._on_failed, Qt.QueuedConnection)
        self._thread.start()

    def _stop(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
        self.check_button.setEnabled(True)
        self.idle.emit()

    def busy(self) -> bool:
        """git 이 도는 중인지 — 이때 창을 닫으면 스레드가 살아 있는 채로 지워져 앱이 강제 종료됐다(2026-10-14 점검)."""
        return self._thread is not None

    def _on_checked(self, status) -> None:
        self._stop()
        self._status = status
        self.status_checked.emit(status)
        self.status_label.setText(status.describe())
        if status.error:
            self.status_pill.set_status("확인 실패", "danger")
        elif status.available:
            self.status_pill.set_status(f"새 업데이트 {status.behind}건", "info")
        else:
            self.status_pill.set_status("최신", "success")
        self.apply_button.setEnabled(status.can_apply)
        self.version_label.setText(updater.current_version())

        if status.messages:
            items = "".join(f"<li>{html.escape(message)}</li>" for message in status.messages)
            self.log.setHtml(
                f"<p style='color:{COLORS['text_muted']};font-size:12px;'>"
                f"새 변경 {status.behind}건</p><ul>{items}</ul>"
            )
        elif status.error:
            self.log.setHtml(f"<p style='color:{COLORS['danger']};'>{html.escape(status.error)}</p>")
        else:
            self.log.setHtml(
                f"<p style='color:{COLORS['text_muted']};'>받아 올 변경이 없습니다.</p>"
            )
        if self._then_restart:
            # 이 처리기(확인 일꾼의 신호) 밖에서 잇는다 — 사람이 [업데이트 적용] 을 누르는 것과 같은 때. 처리기 안에서 적용 스레드를 띄우면
            # 신호를 보낸 일꾼을 그 신호를 처리하는 중에 갈아 끼우게 된다.
            QTimer.singleShot(0, lambda: self._after_check(status))

    def _confirm_apply(self) -> None:
        if self._status is None or not self._status.can_apply:
            return
        answer = QMessageBox.question(
            self, "업데이트 적용",
            f"변경 {self._status.behind}건을 적용합니다.\n"
            "앱 파일이 갱신되고, 그다음 [새로고침] 을 누르면 바로 반영됩니다.\n\n계속할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._start("apply")

    def _on_applied(self, ok: bool, message: str) -> None:
        self._stop()
        self.status_label.setText(message)
        self.status_pill.set_status("적용됨" if ok else "적용 실패", "success" if ok else "danger")
        self.version_label.setText(updater.current_version())
        self.version_changed.emit(updater.current_version())
        self.apply_button.setEnabled(False)
        self.restart_button.setVisible(ok)
        self._applied = self._applied or ok
        self.applied.emit(ok)
        then_restart, self._then_restart = self._then_restart, False
        self._say("")
        if not ok:
            QMessageBox.warning(self, "업데이트", message)
            return
        if then_restart:
            self.restart_requested.emit()       # F5 — 적용하기 전에 이미 물었다
            return
        answer = QMessageBox.question(
            self, "업데이트",
            f"{message}\n\n지금 새로고침해서 반영할까요? 창이 닫혔다가 새 버전으로 다시 열립니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self.restart_requested.emit()

    def _on_failed(self, message: str) -> None:
        """예상 못 한 예외. 마지막 줄이라도 화면에 띄워야 원인을 알 수 있다."""
        self._stop()
        if self._then_restart:
            self._then_restart = False
            self._say("업데이트 처리 중 오류가 나서 새로고침하지 않았습니다 — 업데이트 화면을 보세요.")
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        reason = lines[-1] if lines else "알 수 없는 오류"
        self.status_label.setText(f"업데이트 처리 중 오류가 발생했습니다 — {reason}")
        self.status_pill.set_status("오류", "danger")
        self.log.setHtml(f"<pre style='font-size:12px;'>{html.escape(message)}</pre>")
