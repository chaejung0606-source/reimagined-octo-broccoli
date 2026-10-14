"""COSS 업무데스크 데스크톱 앱 — 홈 + 하단 독 + 탐색기형 작업 탭.

    상단 바     로고 · 이름 | 검색 · 설정(설정·업데이트) · 사용자
    작업 탭     열려 있는 화면만. 홈 탭은 늘 있고 닫히지 않는다. [+] 로 새 업무
    작업 표면   흰 면 — 선택한 탭과 이어진다. 아래 가운데에 독이 떠 있다
    독          평소엔 짧은 둥근 선, 마우스를 대면 펼쳐진다 (홈 · 청구서 받기 · 회의록 생성 · 일반청구 · 카드청구)

높이는 위에서부터 상단 바(고정) · 탭 줄(고정) · 작업 표면(남는 높이 전부). 독은 따로 띠를
갖지 않고 작업 표면 안에 겹쳐 뜬다(담당자 요청). 접힌 선은 페이지의 아래 여백 안에 들어간다.

업무 화면은 처음 열 때 한 번 만들고 그 뒤로는 숨겼다 보이기만 한다. 그래서 탭을
오가거나 닫았다 열어도 입력값·스크롤·진행 중인 받기가 그대로다. 청구서 받기(ui/worker.py)와
회의록 생성(ui/minutes_worker.py)은 각자 별도 스레드에서 돌므로 다른 탭으로 가도 멈추지 않는다.
"""
from __future__ import annotations

import getpass
import importlib
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import ai, settings, shortcuts, updater
from . import ai_status
from .pages.home import HomePage
from .shell import Dock, DockOverlay, TopBar, WorkTabs
from .tasks import HOME_ICON, HOME_ID, TASKS, UTILITIES, Task, find
from .theme import stylesheet

APP_NAME = "COSS 업무데스크"
WORKSPACE = ""     # 이름 아래 기관 문구는 두지 않는다(담당자 요청)

# 창이 이보다 낮으면 독과 여백을 줄인다
COMPACT_BELOW = 800

# 별도 스레드에서 오래 도는 업무 — 탭·앱을 닫기 전에 묻고, 홈의 '이어서 작업하기' 에 보인다
RUNNING_WORDS = {"download": "청구서를 받는", "meeting": "회의록을 만드는", "claim": "일반청구 작업을 하는"}

ASSETS = Path(__file__).parent / "assets"
log = logging.getLogger(__name__)


class WorkSurface(QStackedWidget):
    """흰 작업 표면. 크기가 바뀌면 알린다 — 위에 떠 있는 독이 자리를 다시 잡는다."""

    resized = Signal()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 860)
        self.setMinimumSize(1120, 720)
        self._pages: dict[str, QWidget] = {}
        self._session_worker = None       # 브라우저 스레드 — 청구서 받기와 일반청구가 함께 쓴다

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
        self.tabs.new_task_requested.connect(self.open)
        column.addWidget(self.tabs)

        # 작업 표면 — 탭 줄 바탕 위에 흰 면. 좌우 10px 띄워 탭 줄과 같은 테두리 안에 놓인다
        surface_wrap = QWidget()
        surface_wrap.setObjectName("root")
        wrap_layout = QVBoxLayout(surface_wrap)
        wrap_layout.setContentsMargins(10, 0, 10, 0)
        self.stack = WorkSurface()
        self.stack.setObjectName("work")
        wrap_layout.addWidget(self.stack)
        column.addWidget(surface_wrap, 1)
        self.setCentralWidget(central)

        # 독은 작업 표면 안에 떠 있다 — 평소엔 아래 가운데의 짧은 선, 마우스를 대면 펼쳐진다
        self.dock = Dock()
        self.dock.activated.connect(self.open)
        self.dock_overlay = DockOverlay(self.dock, self.stack)
        self.stack.resized.connect(self.dock_overlay.relayout)
        # QStackedWidget 은 화면을 바꿀 때마다 새 화면을 맨 위로 올린다(QStackedLayout::setCurrentIndex 의
        # raise). 그러면 독이 화면 아래에 깔려 — 바탕이 투명해 선은 보이는데 — 마우스가 닿지 않는다.
        # 홈에서는 되고 설정·회의록 탭에 들어가면 안 되던 것이 이것이다(2026-10-13). 바꿀 때마다 다시 올린다.
        self.stack.currentChanged.connect(lambda _index: self.dock_overlay.raise_())

        self.home = HomePage()
        self.home.open_task.connect(self.open)
        self.home.apply_update.connect(self._apply_update)
        self.home.restart_requested.connect(self.restart)
        # AI 플랫폼 로그인 상태 — 위쪽 바 단추와 홈 띠가 같은 것을 본다(ui/ai_status.py)
        self.ai = ai_status.instance()
        self.ai.changed.connect(self._sync_ai)
        self.topbar.ai_login.connect(lambda: self.ai.login(self))
        self.topbar.ai_check.connect(self.ai.check)
        self.topbar.ai_settings.connect(self.open_ai_settings)
        self.home.ai_login.connect(lambda: self.ai.login(self))
        self.home.ai_check.connect(self.ai.check)
        self._closing_for_restart = False
        self._pages[HOME_ID] = self.home
        self.stack.addWidget(self.home)
        self.dock_overlay.raise_()
        self.tabs.add(HOME_ID, "홈", HOME_ICON, closable=False)
        self.show_task(HOME_ID)

        self.statusBar().showMessage("")
        self._sync_user_menu()
        # 시작 직후 창이 그려지고 나서 확인한다. 네트워크가 느려도 창은 바로 뜬다.
        QTimer.singleShot(1200, lambda: self.page("updates").check_quietly())
        # 앱을 켜면 AI 로그인 상태부터 본다 — 홈에서 바로 알 수 있게(담당자 요청 2026-10-14)
        self._sync_ai()
        QTimer.singleShot(600, self.ai.check)

    # ── 화면 만들기 · 열기 ────────────────────────────────────────────
    def page(self, task_id: str) -> QWidget:
        """업무 화면을 처음 한 번만 만든다. 만든 뒤에는 같은 것을 돌려준다."""
        if task_id in self._pages:
            return self._pages[task_id]
        task = find(task_id)
        module_name, class_name = task.page.split(":")
        module = importlib.import_module(f".pages.{module_name}", __package__)
        cls = getattr(module, class_name)
        if task_id in ("download", "claim"):
            page = cls(worker=self.session_worker())
        else:
            page = cls()
        self._wire(task, page)
        self._pages[task_id] = page
        self.stack.addWidget(page)
        self.dock_overlay.raise_()      # 새 화면이 독 위로 올라오지 않게
        return page

    def session_worker(self):
        """브라우저 작업 스레드 하나 — ERP 로그인은 한 번이면 되므로 받기와 일반청구가 같은 창을 쓴다."""
        if self._session_worker is None:
            from .worker import SessionWorker
            self._session_worker = SessionWorker()
        return self._session_worker

    def _wire(self, task: Task, page: QWidget) -> None:
        if task.id == "download":
            page.need_settings.connect(lambda: self.open("settings"))
            page.busy_changed.connect(lambda busy: self._on_busy(task.id, busy))
            page.counts_changed.connect(self._sync_home)
        elif task.id in ("meeting", "claim"):
            page.busy_changed.connect(lambda busy: self._on_busy(task.id, busy))
            page.need_settings.connect(self.open_ai_settings)
        elif task.id == "settings":
            page.changed.connect(self._on_settings_changed)
        elif task.id == "updates":
            page.version_changed.connect(lambda _v: self._sync_user_menu())
            page.status_checked.connect(self._on_update_status)
            page.applied.connect(self._on_update_applied)
            page.restart_requested.connect(self.restart)

    def open_ai_settings(self) -> None:
        """설정을 열고 AI 플랫폼 칸으로 — 위쪽 AI 단추 메뉴와 업무 화면의 [설정에서 바꾸기]."""
        self.open("settings")
        self.page("settings").focus_ai()

    def open(self, task_id: str) -> None:
        """독·홈 카드·[+]·메뉴에서 부른다. 이미 열려 있으면 그 탭으로 간다."""
        if task_id == HOME_ID:
            self.show_task(HOME_ID)
            return
        task = find(task_id)
        self.page(task_id)
        if not self.tabs.has(task_id):
            self.tabs.add(task_id, task.name, task.icon)
        self.show_task(task_id)

    def show_task(self, task_id: str) -> None:
        page = self._pages.get(task_id)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        self.tabs.set_current(task_id)
        self.dock.set_current(task_id if task_id in {t.id for t in TASKS} or task_id == HOME_ID else "")
        if task_id == HOME_ID:
            self._sync_home()

    def close_task(self, task_id: str) -> None:
        page = self._pages.get(task_id)
        if page is None or task_id == HOME_ID:
            return
        if task_id in RUNNING_WORDS and page.is_running():
            answer = QMessageBox.question(
                self, APP_NAME,
                f"{RUNNING_WORDS[task_id]} 중입니다. 탭을 닫아도 작업은 이어지지만 진행 상황을 볼 수 없습니다.\n그래도 닫을까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        was_current = self.stack.currentWidget() is page
        target = self.tabs.neighbour(task_id)
        self.tabs.remove(task_id)
        # 화면은 없애지 않는다 — 입력값과 진행 상태가 남아 있어야 다시 열었을 때 이어진다
        if was_current:
            self.show_task(target)
        else:
            self._sync_home()

    # ── 상태 ────────────────────────────────────────────────────────
    def _on_busy(self, task_id: str, busy: bool) -> None:
        self.tabs.set_busy(task_id, busy)
        self._sync_home()

    def _on_settings_changed(self) -> None:
        if "download" in self._pages:
            self._pages["download"].refresh_counts()
        self._sync_home()
        # 설정에서 AI 플랫폼을 바꿨을 수 있다 — 새로 쓰는 플랫폼의 로그인 상태를 본다
        if set(ai.used_keys()) != {s.key for s in self.ai.statuses() if s.checked_at}:
            self.ai.check()
        else:
            self._sync_ai()

    def _sync_ai(self) -> None:
        """위쪽 AI 단추와 홈 띠를 지금 상태로."""
        head = self.ai.headline()
        checking = self.ai.checking
        if head is None:
            return
        name = ai.short_label(head.key)
        lines = [f"{title}: {ai.short_label(ai.chosen(use))} · {self.ai.for_use(use).text}"
                 for use, (title, _f) in ai.USES.items()]
        if head.note:
            lines.append(head.note)
        if head.state == ai.CHECKING or (checking and head.state == ai.OK and not head.checked_at):
            text, tone = "AI 확인 중", "neutral"
        else:
            text, tone = f"{name} · {head.text}", head.tone
        # 로그인돼 있어도 메뉴에 남긴다 — 계정을 바꿀 때 쓴다
        login_label = "" if not ai.can_login(head.key) else f"{name} 다시 로그인" if head.state == ai.OK else f"{name} 로그인"
        self.topbar.set_ai(text, tone, "\n".join(lines), login_label)
        self.home.show_ai(head, checking)

    def _sync_home(self) -> None:
        """홈의 '이어서 작업하기'(실제 재개 가능한 일만)와 최근 기록을 새로 읽는다."""
        items = []
        for task_id in RUNNING_WORDS:
            page = self._pages.get(task_id)
            if page is None:
                continue
            ok, text = page.resumable()
            if ok:
                task = find(task_id)
                items.append((task.id, task.art, task.name, text))
        self.home.set_resumable(items)
        self.home.refresh_recent()

    def _on_update_status(self, status) -> None:
        self.home.show_update(status.behind if status.can_apply else 0, status.messages)

    def _apply_update(self) -> None:
        self.open("updates")
        self.page("updates")._confirm_apply()

    def _on_update_applied(self, ok: bool) -> None:
        if ok:
            self.home.show_restart()

    # ── 새로고침 ─────────────────────────────────────────────────────
    def _running_work(self) -> tuple[list, list[str]]:
        """별도 스레드에서 도는 화면들과, 그중 지금 작업 중인 것의 이름."""
        workers = [(tid, self._pages[tid]) for tid in RUNNING_WORDS if tid in self._pages]
        running = [RUNNING_WORDS[tid] for _tid, page in workers if page.is_running()]
        return workers, running

    def _confirm_leave(self, running: list[str], what: str) -> bool:
        answer = QMessageBox.question(
            self, APP_NAME,
            f"아직 {' · '.join(running)} 중입니다. 지금 {what} 하던 건이 끝나지 않습니다.\n그래도 할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def restart(self) -> None:
        """[새로고침] — 새 앱을 띄우고 이 창을 닫는다. 업데이트를 받은 뒤 껐다 켤 필요가 없다(담당자 요청)."""
        _workers, running = self._running_work()
        if running and not self._confirm_leave(running, "새로고침하면"):
            return
        try:
            updater.relaunch()
        except OSError as error:
            QMessageBox.warning(self, APP_NAME, f"앱을 새로 띄우지 못했습니다.\n{error}\n\n앱을 직접 닫고 다시 여세요.")
            return
        self._closing_for_restart = True      # closeEvent 가 한 번 더 묻지 않게
        self.close()

    def _sync_user_menu(self) -> None:
        menu = self.topbar.user_menu
        menu.clear()
        menu.addAction(f"버전 {updater.current_version()}").setEnabled(False)
        menu.addSeparator()
        for task in UTILITIES:
            menu.addAction(task.name, lambda t=task.id: self.open(t))
        menu.addSeparator()
        menu.addAction("앱 새로고침", self.restart)

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
        self.dock_overlay.set_compact(self.height() < COMPACT_BELOW)

    def closeEvent(self, event) -> None:  # noqa: N802
        workers, running = self._running_work()
        if running and not self._closing_for_restart and not self._confirm_leave(running, "닫으면"):
            event.ignore()
            return
        for _tid, page in workers:
            page.shutdown()
        if self._session_worker is not None:
            self._session_worker.shutdown()
        super().closeEvent(event)


def _user_name() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "사용자"


def load_fonts() -> str:
    """앱에 묶어 둔 Pretendard 를 등록하고 실제로 쓰이는 글꼴 이름을 돌려준다.

    설치된 글꼴에 기대지 않는다 — 동료 PC 에 Pretendard 가 없으면 맑은 고딕으로 바뀌어
    같은 화면이 다르게 보인다. 등록에 실패하면 대체 목록(tokens.FONT_FAMILY)이 쓰인다.
    """
    loaded = []
    for path in sorted((ASSETS / "fonts").glob("Pretendard-*.otf")):
        index = QFontDatabase.addApplicationFont(str(path))
        if index >= 0:
            loaded.extend(QFontDatabase.applicationFontFamilies(index))
    family = "Pretendard" if "Pretendard" in loaded else ""
    if not family:
        log.warning("Pretendard 를 등록하지 못해 대체 글꼴을 씁니다")
    return family


def _claim_taskbar_identity() -> None:
    """작업 표시줄에서 파이썬이 아니라 이 앱의 아이콘이 보이게 한다. 창을 만들기 전에 불러야 한다.

    이름이 없으면 창이 'pythonw.exe' 의 것으로 묶여 파이썬 아이콘이 뜬다. 바로가기에도 같은 이름을 적어야
    (create_shortcut.py) 고정한 단추와 실행 중인 창이 하나로 합쳐진다.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(settings.APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001 — 안 되면 아이콘만 파이썬으로 보일 뿐 앱은 돈다
        log.warning("작업 표시줄 이름을 정하지 못했습니다")


def _app_icon() -> QIcon:
    """크기별 그림을 모두 넣는다(tools/make_icon.py). 윈도우 작업 표시줄은 .ico 를 가장 잘 쓴다."""
    icon = QIcon()
    ico = ASSETS / "icon.ico"
    if ico.exists():
        icon.addFile(str(ico))
    for path in sorted((ASSETS / "icons").glob("icon-*.png")):
        icon.addFile(str(path))
    fallback = ASSETS / "icon.png"
    if icon.isNull() and fallback.exists():
        icon.addFile(str(fallback))
    return icon


def main() -> int:
    # 깨진 보관 PDF 를 읽을 때 pypdf 가 경고를 쏟아낸다. 스캔은 그런 파일을 건너뛴다.
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    _claim_taskbar_identity()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(_app_icon())
    family = load_fonts()
    if family:
        base = QFont(family)
        base.setPixelSize(14)
        app.setFont(base)
    app.setStyleSheet(stylesheet())
    window = MainWindow()
    window.show()
    shortcuts.remember_made()      # 바로가기는 만들지 않는다 — 업데이트 때마다 바탕화면에 다시 생기지 않게(shortcuts.py)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
