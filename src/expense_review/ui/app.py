"""지출 서류 검토 데스크톱 앱.

왼쪽 사이드바로 네 화면을 오간다.

  검토            지출종류 선택 → 폴더 지정 → 대시보드 요약
  파일별 보완사항  어떤 파일을 무엇 때문에 고쳐야 하는지
  검토 기준        서류 종류별 기준 확인·수정
  업데이트         기능 갱신 확인·적용

검토는 별도 스레드에서 돌린다. PDF 수십 장을 읽는 동안 창이 멈추면
사용자는 앱이 죽은 줄 안다.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
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
from .backgrounds import paint_gingham, paint_starfield
from .pages import FilesPage, ReviewPage, RulesPage, UpdatesPage
from .state import AppState
from .theme import COLORS, DEFAULT_THEME, is_cozy, is_galaxy, set_theme, stylesheet

NAV_ITEMS = [
    ("검토", "서류를 읽고 기준에 맞춰 확인합니다"),
    ("파일별 보완사항", "파일마다 고칠 부분을 모아 봅니다"),
    ("검토 기준", "기준을 확인하고 고칩니다"),
    ("설정", "화면 모양과 기능 갱신"),
]


class RootWidget(QWidget):
    """창 전체 배경. 갤럭시 테마는 별하늘, 포근한 테마는 깅엄 체크를 깐다."""

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        if is_galaxy():
            paint_starfield(painter, QRectF(self.rect()),
                            QColor(COLORS["bg"]), QColor(COLORS["gingham"]))
        elif is_cozy():
            paint_gingham(painter, QRectF(self.rect()),
                          QColor(COLORS["bg"]), QColor(COLORS["gingham"]))
        else:
            painter.fillRect(self.rect(), QColor(COLORS["bg"]))


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
        self.updates_page.theme_changed.connect(self.apply_theme)
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
        for index, (label, tooltip) in enumerate(NAV_ITEMS):
            button = QPushButton(label)
            button.setObjectName("navItem")
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.setCursor(Qt.PointingHandCursor)
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

    def apply_theme(self, name: str) -> None:
        """테마를 바꾸고 화면 전체를 다시 칠한다."""
        QApplication.instance().setStyleSheet(set_theme(name))
        for widget in self.findChildren(QWidget):
            widget.update()
        self.update()


def main() -> int:
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    app = QApplication(sys.argv)
    app.setApplicationName("지출 서류 검토")
    app.setStyleSheet(set_theme(config.load_settings().get("theme", DEFAULT_THEME)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
