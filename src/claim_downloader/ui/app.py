"""업무 도구함 데스크톱 앱 — 홈 + 하단 독 + 상단 작업 탭.

    상단 바     로고 · 이름 | 검색 · 설정(설정·업데이트) · 사용자
    작업 탭     열려 있는 작업만. 홈 탭은 늘 있고 닫히지 않는다
    본문        홈(업무 도구함) 또는 열린 업무 화면
    하단 독     홈 · 청구서 받기 · 회의록 생성 · 일반청구 · 카드청구

업무 화면은 처음 열 때 한 번 만들고 그 뒤로는 숨겼다 보이기만 한다. 그래서 탭을
오가도 입력값·스크롤·진행 중인 받기가 그대로다. 청구서 받기는 별도 스레드에서
돌므로(ui/worker.py) 다른 탭으로 가도 멈추지 않는다.
"""
from __future__ import annotations

import getpass
import importlib
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import updater
from .pages.home import HomePage
from .shell import Dock, DockArea, TopBar, WorkTabs
from .tasks import HOME_ID, TASKS, UTILITIES, Task, find
from .theme import stylesheet

APP_NAME = "업무 도구함"
WORKSPACE = "강원대 산학협력단 ERP"

# 창이 이보다 낮으면 독과 여백을 줄인다
COMPACT_BELOW = 800


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 860)
        self.setMinimumSize(1120, 720)
        self._pages: dict[str, QWidget] = {}

        central = QWidget()
        central.setObjectName("root")
        column = QVBoxLayout(central)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self.topbar = TopBar(APP_NAME, WORKSPACE, _user_name())
        self.topbar.open_utility.connect(self.open)
        self.topbar.search_submitted.connect(self._search)
        column.addWidget(self.topbar)

        self.tabs = WorkTabs()
        self.tabs.activated.connect(self.show_task)
        self.tabs.close_requested.connect(self.close_task)
        column.addWidget(self.tabs)

        self.stack = QStackedWidget()
        column.addWidget(self.stack, 1)

        self.dock = Dock()
        self.dock.activated.connect(self.open)
        self.dock_area = DockArea(self.dock)
        column.addWidget(self.dock_area)
        self.setCentralWidget(central)

        self.home = HomePage()
        self.home.open_task.connect(self.open)
        self._pages[HOME_ID] = self.home
        self.stack.addWidget(self.home)
        self.tabs.add(HOME_ID, "홈", closable=False)
        self.show_task(HOME_ID)

        self.statusBar().showMessage("")
        self._sync_user_menu()
        # 시작 직후 창이 그려지고 나서 확인한다. 네트워크가 느려도 창은 바로 뜬다.
        QTimer.singleShot(1200, lambda: self.page("updates").check_quietly())

    # ── 화면 만들기 · 열기 ────────────────────────────────────────────
    def page(self, task_id: str) -> QWidget:
        """업무 화면을 처음 한 번만 만든다. 만든 뒤에는 같은 것을 돌려준다."""
        if task_id in self._pages:
            return self._pages[task_id]
        task = find(task_id)
        module_name, class_name = task.page.split(":")
        module = importlib.import_module(f".pages.{module_name}", __package__)
        cls = getattr(module, class_name)
        page = cls(task) if module_name == "pending" else cls()
        self._wire(task, page)
        self._pages[task_id] = page
        self.stack.addWidget(page)
        return page

    def _wire(self, task: Task, page: QWidget) -> None:
        if task.id == "download":
            page.need_settings.connect(lambda: self.open("settings"))
            page.busy_changed.connect(lambda busy: self._on_busy(task.id, busy))
            page.counts_changed.connect(self.home.refresh_recent)
        elif task.id == "settings":
            page.changed.connect(self._on_settings_changed)
        elif task.id == "updates":
            page.version_changed.connect(lambda _v: self._sync_user_menu())

    def open(self, task_id: str) -> None:
        """독·홈 카드·메뉴에서 부른다. 이미 열려 있으면 그 탭으로 간다."""
        if task_id == HOME_ID:
            self.show_task(HOME_ID)
            return
        task = find(task_id)
        self.page(task_id)
        if not self.tabs.has(task_id):
            self.tabs.add(task_id, task.name)
        self.show_task(task_id)

    def show_task(self, task_id: str) -> None:
        page = self._pages.get(task_id)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self.tabs.set_current(task_id)
        self.dock.set_current(task_id if task_id in {t.id for t in TASKS} or task_id == HOME_ID else "")
        if task_id == HOME_ID:
            self.home.refresh_recent()
            self._sync_continue()

    def close_task(self, task_id: str) -> None:
        page = self._pages.get(task_id)
        if page is None or task_id == HOME_ID:
            return
        if task_id == "download" and page.is_running():
            answer = QMessageBox.question(
                self, APP_NAME,
                "청구서를 받는 중입니다. 탭을 닫아도 받기는 이어지지만 진행 상황을 볼 수 없습니다.\n"
                "그래도 닫을까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self.tabs.remove(task_id)
        # 화면은 없애지 않는다 — 입력값과 진행 상태가 남아 있어야 다시 열었을 때 이어진다
        if self.stack.currentWidget() is page:
            self.show_task(HOME_ID)
        else:
            self._sync_continue()

    # ── 상태 ────────────────────────────────────────────────────────
    def _on_busy(self, task_id: str, busy: bool) -> None:
        self.tabs.set_busy(task_id, busy)
        self._sync_continue()

    def _on_settings_changed(self) -> None:
        if "download" in self._pages:
            self._pages["download"].refresh_counts()
        self.home.refresh_recent()

    def _sync_continue(self) -> None:
        opened = []
        for task_id in self.tabs.ids():
            if task_id == HOME_ID:
                continue
            task = find(task_id)
            page = self._pages[task_id]
            status = page.status_text() if hasattr(page, "status_text") else ("준비 중" if not task.ready else "")
            opened.append((task, status))
        self.home.set_open_tasks(opened)

    def _sync_user_menu(self) -> None:
        menu = self.topbar.user_menu
        menu.clear()
        menu.addAction(f"버전 {updater.current_version()}").setEnabled(False)
        menu.addSeparator()
        for task in UTILITIES:
            menu.addAction(task.name, lambda t=task.id: self.open(t))

    def _search(self, text: str) -> None:
        """업무 이름으로 찾아 연다. 못 찾으면 상태줄에 알린다."""
        if not text:
            return
        for task in TASKS + UTILITIES:
            if text in task.name or text in task.description:
                self.open(task.id)
                self.topbar.search.clear()
                return
        self.statusBar().showMessage(f"'{text}' 에 맞는 업무가 없습니다.", 4000)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.dock_area.set_compact(self.height() < COMPACT_BELOW)

    def closeEvent(self, event) -> None:  # noqa: N802
        download = self._pages.get("download")
        if download is not None and download.is_running():
            answer = QMessageBox.question(
                self, APP_NAME,
                "아직 청구서를 받는 중입니다. 지금 닫으면 받던 건이 끝나지 않습니다.\n그래도 닫을까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        if download is not None:
            download.shutdown()
        super().closeEvent(event)


def _user_name() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "사용자"


ICON_PATH = Path(__file__).parent / "assets" / "icon.png"
ICON_DIR = Path(__file__).parent / "assets" / "icons"


def _app_icon() -> QIcon:
    """크기별 그림을 모두 넣는다. 작은 크기는 입체 그림 대신 평면 그림이다(tools/make_icon.py)."""
    icon = QIcon()
    for path in sorted(ICON_DIR.glob("icon-*.png")):
        icon.addFile(str(path))
    if icon.isNull() and ICON_PATH.exists():
        icon.addFile(str(ICON_PATH))
    return icon


def main() -> int:
    import logging

    # 깨진 보관 PDF 를 읽을 때 pypdf 가 경고를 쏟아낸다. 스캔은 그런 파일을 건너뛴다.
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(_app_icon())
    app.setStyleSheet(stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
