"""지출 서류 검토 데스크톱 앱.

왼쪽 사이드바로 네 화면을 오간다.

  검토            지출종류 선택 → 폴더 지정 → 대시보드 요약
  파일별 보완사항  어떤 파일을 무엇 때문에 고쳐야 하는지
  검토 기준        서류 종류별 기준 확인·수정
  설정            구글시트 연동 · 기능 갱신 확인·적용

검토는 별도 스레드에서 돌린다. PDF 수십 장을 읽는 동안 창이 멈추면
사용자는 앱이 죽은 줄 안다.
"""
from __future__ import annotations

import logging
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
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config, updater
from .backgrounds import paint_aurora
from .pages import FilesPage, ReviewPage, RulesPage, UpdatesPage
from .state import AppState
from .icons import paint_icon
from .theme import COLORS, stylesheet

NAV_ITEMS = [
    ("검토", "document-check", "서류를 읽고 기준에 맞춰 확인합니다"),
    ("파일별 보완사항", "folder", "파일마다 고칠 부분을 모아 봅니다"),
    ("검토 기준", "sliders", "기준을 확인하고 고칩니다"),
    ("설정", "gear", "구글시트 연동과 기능 갱신"),
]


class RootWidget(QWidget):
    """창 전체 배경. 민트 → 하늘색 → 연한 남보라로 아주 옅게 흐른다."""

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_aurora(painter, QRectF(self.rect()),
                     QColor(COLORS["grad_mint"]), QColor(COLORS["grad_cyan"]),
                     QColor(COLORS["grad_blue"]))


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
        self._icon_name = icon_name
        # 아이콘 자리를 왼쪽에 비워 둔다
        self.setStyleSheet(f"padding-left: {self.ICON + 22}px;")

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        color = QColor(COLORS["on_dark"] if self.isChecked() else COLORS["text_muted"])
        box = QRectF(24, (self.height() - self.ICON) / 2, self.ICON, self.ICON)
        paint_icon(painter, box, self._icon_name, color)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("지출 서류 검토")
        self.resize(1320, 860)
        self.setMinimumSize(1120, 720)

        self.state = AppState()

        central = RootWidget()
        central.setObjectName("root")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.review_page = ReviewPage(self.state)
        self.files_page = FilesPage(self.state)
        self.rules_page = RulesPage()
        self.updates_page = UpdatesPage()
        for page in (self.review_page, self.files_page, self.rules_page, self.updates_page):
            self.stack.addWidget(page)

        layout.addWidget(self._build_sidebar())
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.statusBar().showMessage("지출종류를 고르고 서류 폴더를 지정하세요.")
        self.state.busy_changed.connect(
            lambda busy, message: self.statusBar().showMessage(message)
        )
        self.state.results_changed.connect(self._on_results)

        # 시작 직후 창이 그려지고 나서 확인한다. 네트워크가 느려도 창은 바로 뜬다.
        QTimer.singleShot(1200, self.updates_page.check_quietly)
        QTimer.singleShot(2000, self.updates_page.refresh_sheet_quietly)
        self.updates_page.sheet_refreshed.connect(self._on_sheet_refreshed)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(216)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QLabel("지출 서류 검토")
        brand.setObjectName("brand")
        brand.setAlignment(Qt.AlignCenter)
        brand.setContentsMargins(0, 22, 0, 0)
        layout.addWidget(brand)
        subtitle = QLabel("근로장학금 · 혁신인재지원금 · 출장비")
        subtitle.setObjectName("brandSub")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (label, icon_name, tooltip) in enumerate(NAV_ITEMS):
            button = NavButton(label, icon_name)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked, i=index: self.stack.setCurrentIndex(i))
            self.nav_group.addButton(button, index)
            layout.addWidget(button)
        self.nav_group.button(0).setChecked(True)

        layout.addStretch(1)
        self.version_label = QLabel(f"버전 {updater.current_version()}")
        self.version_label.setObjectName("versionLabel")
        self.version_label.setWordWrap(True)
        layout.addWidget(self.version_label)
        self.updates_page.version_changed.connect(
            lambda version: self.version_label.setText(f"버전 {version}")
        )
        return sidebar

    def _on_results(self, results: list) -> None:
        """검토가 끝나면 파일별 화면으로 넘어갈 수 있음을 알린다."""
        if not results:
            return
        button = self.nav_group.button(1)
        button.setText(f"파일별 보완사항 ({self.state.document_count()})")

    def _on_sheet_refreshed(self, message: str) -> None:
        """시트 기준이 갱신되면 기준 화면을 다시 읽고 상태줄에 알린다."""
        self.rules_page._reload(self.rules_page.expense_type.currentText())
        self.statusBar().showMessage(message)

ICON_PATH = Path(__file__).parent / "assets" / "icon.png"


def main() -> int:
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    app = QApplication(sys.argv)
    app.setApplicationName("지출 서류 검토")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyleSheet(stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
