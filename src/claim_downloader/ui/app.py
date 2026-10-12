"""ERP 청구서 다운로더 데스크톱 앱.

왼쪽 사이드바로 세 화면을 오간다.

  청구서 받기  브라우저 열기 → 로그인(사람) → 목록 읽기 → 확인(사람) → 받기
  설정        저장 폴더 · 파일 이름 형식 · 누락 검토 엑셀
  업데이트    기능 갱신 확인·적용

브라우저 작업은 별도 스레드에서 돈다(ui/worker.py). 청구서 한 건에 수십 초가
걸리는데, 그동안 창이 멈추면 사용자는 앱이 죽은 줄 안다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import updater
from .art import Art
from .icons import paint_icon
from .pages import DownloadPage, SettingsPage, UpdatesPage
from .theme import COLORS, stylesheet

APP_NAME = "ERP 청구서 다운로더"
WORKSPACE = "강원대 산학협력단 ERP"

# 업무 흐름대로 묶는다. (묶음, [(메뉴, 아이콘, 설명)])
NAV_GROUPS = [
    ("업무", [("청구서 받기", "download", "승인된 청구서 PDF 를 받아 비목 폴더에 넣습니다")]),
    ("관리", [("설정", "sliders", "저장 폴더 · 파일 이름 형식"),
             ("업데이트", "gear", "기능 갱신 확인·적용")]),
]


class NavButton(QPushButton):
    """사이드바 항목. 라인 아이콘 + 글자.

    아이콘을 QSS 로 넣으려면 파일이 있어야 한다. 코드로 그리면 파일이 없고,
    선택 여부에 따라 색이 저절로 따라온다.
    """

    ICON = 18

    def __init__(self, label: str, icon_name: str, parent: QWidget | None = None):
        super().__init__(label, parent)
        self.setObjectName("navItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(label)
        self._icon_name = icon_name
        # 아이콘 자리를 왼쪽에 비워 둔다
        self.setStyleSheet(f"padding-left: {self.ICON + 22}px;")

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        color = QColor(COLORS["primary_hover"] if self.isChecked() else COLORS["text_muted"])
        box = QRectF(12, (self.height() - self.ICON) / 2, self.ICON, self.ICON)
        paint_icon(painter, box, self._icon_name, color)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 860)
        self.setMinimumSize(1120, 720)

        central = QWidget()
        central.setObjectName("root")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.download_page = DownloadPage()
        self.settings_page = SettingsPage()
        self.updates_page = UpdatesPage()
        for page in (self.download_page, self.settings_page, self.updates_page):
            self.stack.addWidget(page)

        layout.addWidget(self._build_sidebar())
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.download_page.need_settings.connect(lambda: self._go(1))
        self.settings_page.changed.connect(self.download_page.refresh_counts)

        # 시작 직후 창이 그려지고 나서 확인한다. 네트워크가 느려도 창은 바로 뜬다.
        QTimer.singleShot(1200, self.updates_page.check_quietly)

    def _go(self, index: int) -> None:
        self.nav_group.button(index).setChecked(True)
        self.stack.setCurrentIndex(index)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 20, 12, 16)
        layout.setSpacing(2)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 0, 4)
        brand_row.setSpacing(10)
        brand_row.addWidget(Art("register", 40))
        names = QVBoxLayout()
        names.setSpacing(0)
        brand = QLabel("청구서 다운로더")
        brand.setObjectName("brand")
        names.addWidget(brand)
        workspace = QLabel(WORKSPACE)
        workspace.setObjectName("workspace")
        names.addWidget(workspace)
        brand_row.addLayout(names, 1)
        layout.addLayout(brand_row)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        index = 0
        for group, items in NAV_GROUPS:
            head = QLabel(group)
            head.setObjectName("navGroup")
            layout.addWidget(head)
            for label, icon_name, tooltip in items:
                button = NavButton(label, icon_name)
                button.setToolTip(tooltip)
                button.clicked.connect(lambda _checked, i=index: self.stack.setCurrentIndex(i))
                self.nav_group.addButton(button, index)
                layout.addWidget(button)
                index += 1
        self.nav_group.button(0).setChecked(True)

        layout.addStretch(1)
        self.version_label = QLabel(f"버전 {updater.current_version()}")
        self.version_label.setObjectName("versionLabel")
        self.version_label.setContentsMargins(12, 0, 0, 0)
        self.version_label.setWordWrap(True)
        layout.addWidget(self.version_label)
        self.updates_page.version_changed.connect(
            lambda version: self.version_label.setText(f"버전 {version}")
        )
        return sidebar

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.download_page.stop_button.isEnabled():
            answer = QMessageBox.question(
                self, APP_NAME,
                "아직 청구서를 받는 중입니다. 지금 닫으면 받던 건이 끝나지 않습니다.\n그래도 닫을까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.download_page.shutdown()
        super().closeEvent(event)


ICON_PATH = Path(__file__).parent / "assets" / "icon.png"


def main() -> int:
    import logging

    # 깨진 보관 PDF 를 읽을 때 pypdf 가 경고를 쏟아낸다. 스캔은 그런 파일을 건너뛴다.
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyleSheet(stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
