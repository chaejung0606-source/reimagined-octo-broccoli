"""설정 페이지 — 화면 모양과 업데이트.

업데이트는 확인과 적용을 나눠 두었다. 사용자가 무엇이 바뀌는지 보고 나서
누르게 하려는 것이다.
"""
from __future__ import annotations

import shutil
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
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

from ... import config, updater
from ..mascot import IMAGE_SUFFIXES, MascotWidget, StickerStrip
from ..theme import COLORS, PALETTES, current_theme
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
    theme_changed = Signal(str)
    mascot_changed = Signal()

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
        content.setObjectName("page")
        scroll.setWidget(content)
        outer.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("설정")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addWidget(muted_label(
            "화면 모양과 기능 갱신을 다룹니다. 앱에서 고친 검토 기준은 "
            "별도 폴더에 저장되어 업데이트해도 유지됩니다."
        ))
        layout.addLayout(header)

        layout.addWidget(self._build_theme_card())
        layout.addWidget(self._build_mascot_card())

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
        self.log.setMinimumHeight(140)
        log_card.add(self.log, 1)
        layout.addWidget(log_card, 1)

    # ── 화면 모양 ────────────────────────────────────────────────────────
    def _build_theme_card(self) -> QWidget:
        card = Card("화면 모양")
        row = QHBoxLayout()
        row.setSpacing(16)

        preview = MascotWidget(76)
        row.addWidget(preview)

        picker = QVBoxLayout()
        picker.setSpacing(6)
        self.theme_buttons: dict[str, QPushButton] = {}
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        active = current_theme()
        for name, palette in PALETTES.items():
            button = QPushButton(palette["label"])
            button.setCheckable(True)
            button.setChecked(name == active)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _c, key=name: self._choose_theme(key))
            self.theme_buttons[name] = button
            buttons.addWidget(button)
        buttons.addStretch(1)
        picker.addLayout(buttons)
        picker.addWidget(muted_label(
            "'포근한 체크' 는 크림색 깅엄 바탕에 마스코트가 함께 나옵니다. "
            "'차분한 대시보드' 는 색을 줄인 업무용 화면입니다."
        ))
        row.addLayout(picker, 1)
        card.add_layout(row)
        card.add(StickerStrip(height=28))
        return card

    def _build_mascot_card(self) -> QWidget:
        card = Card("나만의 마스코트")
        card.add(muted_label(
            "가지고 있는 그림을 넣으면 기본 마스코트 대신 그 이미지가 나옵니다. "
            "배경이 투명한 PNG(누끼 딴 이미지)를 권합니다. 이미지는 이 컴퓨터의 "
            "설정 폴더에만 저장되고, 앱은 파일을 그대로 표시만 합니다."
        ))

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for label, mood in (("웃는 표정(기본)", "happy"),
                            ("걱정 표정", "worried"),
                            ("졸린 표정", "sleepy")):
            button = QPushButton(label)
            button.clicked.connect(lambda _c, m=mood: self._pick_mascot_image(m))
            buttons.addWidget(button)
        sticker_button = QPushButton("스티커 이미지 추가")
        sticker_button.clicked.connect(self._add_sticker_images)
        buttons.addWidget(sticker_button)
        buttons.addStretch(1)
        card.add_layout(buttons)

        tail = QHBoxLayout()
        tail.setSpacing(8)
        open_button = QPushButton("이미지 폴더 열기")
        open_button.setObjectName("ghost")
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(config.config_dir()))))
        reset_button = QPushButton("기본 그림으로 되돌리기")
        reset_button.setObjectName("ghost")
        reset_button.clicked.connect(self._reset_mascot_images)
        tail.addWidget(open_button)
        tail.addWidget(reset_button)
        tail.addStretch(1)
        card.add_layout(tail)
        return card

    def _pick_mascot_image(self, mood: str) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "이미지 선택", filter="이미지 (*.png *.webp *.jpg *.jpeg *.gif)"
        )
        if not chosen:
            return
        source = Path(chosen)
        target_dir = config.mascot_dir()
        # 같은 표정의 다른 확장자 파일이 남아 있으면 그쪽이 먼저 잡힐 수 있다.
        for suffix in IMAGE_SUFFIXES:
            (target_dir / f"{mood}{suffix}").unlink(missing_ok=True)
        shutil.copyfile(source, target_dir / f"{mood}{source.suffix.lower()}")
        self.mascot_changed.emit()

    def _add_sticker_images(self) -> None:
        chosen, _ = QFileDialog.getOpenFileNames(
            self, "스티커 이미지 선택", filter="이미지 (*.png *.webp *.jpg *.jpeg *.gif)"
        )
        for item in chosen:
            source = Path(item)
            shutil.copyfile(source, config.stickers_dir() / source.name)
        if chosen:
            self.mascot_changed.emit()

    def _reset_mascot_images(self) -> None:
        removed = 0
        for directory in (config.mascot_dir(), config.stickers_dir()):
            for path in directory.iterdir():
                if path.is_file():
                    path.unlink()
                    removed += 1
        if removed:
            self.mascot_changed.emit()
        QMessageBox.information(self, "되돌림", "기본 그림으로 되돌렸습니다.")

    def _choose_theme(self, name: str) -> None:
        for key, button in self.theme_buttons.items():
            button.setChecked(key == name)
        config.update_setting("theme", name)
        self.theme_changed.emit(name)

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
