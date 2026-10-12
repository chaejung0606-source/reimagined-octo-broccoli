"""업데이트 화면.

업데이트는 확인과 적용을 나눠 두었다. 사용자가 무엇이 바뀌는지 보고 나서
누르게 하려는 것이다.
"""
from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, Qt, QThread, Signal
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

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self._thread: QThread | None = None
        self._status: updater.UpdateStatus | None = None

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
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.apply_button)
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
            items = "".join(f"<li>{message}</li>" for message in status.messages)
            self.log.setHtml(
                f"<p style='color:{COLORS['text_muted']};font-size:12px;'>"
                f"새 변경 {status.behind}건</p><ul>{items}</ul>"
            )
        elif status.error:
            self.log.setHtml(f"<p style='color:{COLORS['danger']};'>{status.error}</p>")
        else:
            self.log.setHtml(
                f"<p style='color:{COLORS['text_muted']};'>받아 올 변경이 없습니다.</p>"
            )

    def _confirm_apply(self) -> None:
        if self._status is None or not self._status.can_apply:
            return
        answer = QMessageBox.question(
            self, "업데이트 적용",
            f"변경 {self._status.behind}건을 적용합니다.\n"
            "앱 파일이 갱신되며, 반영하려면 앱을 다시 시작해야 합니다.\n\n계속할까요?",
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
        if ok:
            QMessageBox.information(self, "업데이트", message)
        else:
            QMessageBox.warning(self, "업데이트", message)

    def _on_failed(self, message: str) -> None:
        """예상 못 한 예외. 마지막 줄이라도 화면에 띄워야 원인을 알 수 있다."""
        self._stop()
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        reason = lines[-1] if lines else "알 수 없는 오류"
        self.status_label.setText(f"업데이트 처리 중 오류가 발생했습니다 — {reason}")
        self.status_pill.set_status("오류", "danger")
        self.log.setHtml(f"<pre style='font-size:12px;'>{message}</pre>")
