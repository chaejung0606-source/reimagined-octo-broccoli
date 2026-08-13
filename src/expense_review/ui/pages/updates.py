"""업데이트 페이지.

Claude 가 저장소에 기능을 올리면 여기서 받아 온다. 확인과 적용을 나눠 두었다 —
사용자가 무엇이 바뀌는지 보고 나서 누르게 하려는 것이다.
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
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ... import config, updater
from ..theme import COLORS
from ..widgets import Card, muted_label


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

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self._thread: QThread | None = None
        self._status: updater.UpdateStatus | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("업데이트")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addWidget(muted_label(
            "기능이 갱신되면 여기서 받아 옵니다. 앱에서 고친 검토 기준은 "
            "별도 폴더에 저장되어 업데이트해도 유지됩니다."
        ))
        layout.addLayout(header)

        status_card = Card("설치 상태")
        self.version_label = QLabel(updater.current_version())
        self.version_label.setObjectName("statValue")
        status_card.add(self.version_label)
        self.status_label = QLabel("업데이트를 확인하지 않았습니다.")
        self.status_label.setObjectName("cardHint")
        self.status_label.setWordWrap(True)
        status_card.add(self.status_label)

        buttons = QHBoxLayout()
        self.check_button = QPushButton("업데이트 확인")
        self.check_button.setObjectName("ghost")
        self.check_button.clicked.connect(lambda: self._start("check"))
        self.apply_button = QPushButton("업데이트 적용")
        self.apply_button.setObjectName("primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._confirm_apply)
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.apply_button)
        buttons.addStretch(1)
        status_card.add_layout(buttons)
        layout.addWidget(status_card)

        options_card = Card("자동 확인")
        settings = config.load_settings()
        self.auto_check = QCheckBox("앱을 시작할 때 새 업데이트가 있는지 확인")
        self.auto_check.setChecked(settings.get("auto_update_check", True))
        self.auto_check.toggled.connect(
            lambda checked: config.update_setting("auto_update_check", checked)
        )
        options_card.add(self.auto_check)
        options_card.add(muted_label(
            "적용은 항상 직접 누르셔야 합니다. 확인만 자동으로 하고, 무엇이 바뀌는지 "
            "보여 준 뒤에 적용합니다."
        ))
        options_card.add(muted_label(f"설정 저장 위치: {config.config_dir()}"))
        layout.addWidget(options_card)

        log_card = Card("변경 내역", "적용하면 반영되는 내용")
        self.log = QTextBrowser()
        self.log.setFrameShape(QFrame.NoFrame)
        log_card.add(self.log, 1)
        layout.addWidget(log_card, 1)

    # ── 실행 ─────────────────────────────────────────────────────────────
    def check_quietly(self) -> None:
        """시작 시 자동 확인. 결과가 없으면 조용히 지나간다."""
        if config.load_settings().get("auto_update_check", True):
            self._start("check")

    def _start(self, action: str) -> None:
        if self._thread is not None:
            return
        self.check_button.setEnabled(False)
        self.apply_button.setEnabled(False)
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
        self.status_label.setText(status.describe())
        self.apply_button.setEnabled(status.can_apply)
        self.version_label.setText(updater.current_version())

        if status.messages:
            items = "".join(f"<li>{message}</li>" for message in status.messages)
            self.log.setHtml(
                f"<p style='color:{COLORS['text_muted']};font-size:11px;'>"
                f"새 변경 {status.behind}건</p><ul>{items}</ul>"
            )
        elif status.error:
            self.log.setHtml(f"<p style='color:{COLORS['error']};'>{status.error}</p>")
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
        self.version_label.setText(updater.current_version())
        self.version_changed.emit(updater.current_version())
        self.apply_button.setEnabled(False)
        if ok:
            QMessageBox.information(self, "업데이트", message)
        else:
            QMessageBox.warning(self, "업데이트", message)

    def _on_failed(self, message: str) -> None:
        self._stop()
        self.status_label.setText("업데이트 처리 중 오류가 발생했습니다.")
        self.log.setHtml(f"<pre style='font-size:11px;'>{message}</pre>")
