"""폴더 여러 개 고르기 창 — 담당자 2026-11-11 "폴더 여러개 선택가능하도록".

운영체제(윈도우 탐색기) 폴더 창은 하나만 고를 수 있다(Qt 의 getExistingDirectory). 그래서 Qt 의 폴더 창을 쓰고 목록을 여러 줄 고르기로 바꾼다 —
Ctrl · Shift 로 여러 개, 아무것도 고르지 않고 [넣기] 하면 지금 보는 폴더 하나. 두 번 누르면 그 폴더 안으로 들어간다.
처음 여는 곳은 업무마다의 작업 폴더(work_folders — 카드는 '2. 카드', 출장증빙은 '3. 출장비 …').
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QTranslator, QUrl
from PySide6.QtWidgets import QAbstractItemView, QFileDialog, QFileSystemModel, QListView, QTreeView, QWidget

from .. import work_folders


def desktops() -> list[Path]:
    """바탕화면이 있을 만한 곳 — Qt 가 알려 준 곳(OneDrive 로 옮긴 것도) · 홈의 Desktop · '바탕 화면' · OneDrive 아래."""
    from .report_dialog import desktop_dir
    home = Path.home()
    found = [desktop_dir(), home / "Desktop", home / "바탕 화면", home / "OneDrive" / "Desktop", home / "OneDrive" / "바탕 화면"]
    return list(dict.fromkeys(found))


def work_root(word: str, saved: str = "") -> str:
    """작업 폴더(설정 값이 있으면 그것) — 못 찾으면 ''."""
    return work_folders.find(saved, desktops(), word)


def folder_dialog(parent: QWidget | None, title: str, start: str = "") -> QFileDialog:
    """여러 줄을 고를 수 있는 폴더 창(아직 띄우지 않음 — 시험이 고르기를 흉내 낼 수 있게 나눴다)."""
    dialog = QFileDialog(parent, title, start)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setViewMode(QFileDialog.ViewMode.Detail)
    dialog.setLabelText(QFileDialog.DialogLabel.LookIn, "위치")
    dialog.setLabelText(QFileDialog.DialogLabel.FileName, "고른 폴더")
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, "넣기")
    dialog.setLabelText(QFileDialog.DialogLabel.Reject, "취소")
    side = [p for p in (start, *map(str, desktops())) if p and Path(p).is_dir()]
    if side:
        dialog.setSidebarUrls([QUrl.fromLocalFile(p) for p in dict.fromkeys(side)])
    for view in dialog.findChildren(QListView) + dialog.findChildren(QTreeView):
        # 왼쪽 즐겨찾기 칸(QListView 이지만 폴더 목록이 아님)은 그대로 둔다
        if isinstance(view.model(), QFileSystemModel):
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        if isinstance(view, QTreeView) and isinstance(view.model(), QFileSystemModel):
            view.header().hideSection(1)          # 크기 · 종류 — 폴더만 보이므로 이름 · 수정한 날짜만
            view.header().hideSection(2)
            view.setColumnWidth(0, 420)
            view.setColumnWidth(3, 170)
    for name in ("fileTypeCombo", "fileTypeLabel"):  # '파일 형식: 폴더' 줄은 고를 것이 없다
        widget = dialog.findChild(QWidget, name)
        if widget is not None:
            widget.hide()
    dialog.resize(860, 540)
    return dialog


def _korean() -> QTranslator | None:
    """Qt 폴더 창의 기본 글자(열 이름 '이름' · '수정한 날짜' 등)를 한국어로 — 창을 띄운 동안만(앱의 다른 기본 글자는 그대로)."""
    app = QCoreApplication.instance()
    translator = QTranslator()
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if app is None or not translator.load("qtbase_ko", folder):
        return None
    app.installTranslator(translator)
    return translator


def chosen(dialog: QFileDialog) -> list[str]:
    """[넣기] 뒤 고른 폴더들(있는 폴더만, 고른 차례)."""
    out: list[str] = []
    for path in dialog.selectedFiles():
        if path and Path(path).is_dir() and path not in out:
            out.append(path)
    return out


def pick_folders(parent: QWidget | None, title: str, start: str = "") -> list[str]:
    """폴더를 여러 개 고르게 한다 — 취소면 []."""
    translator = _korean()
    try:
        dialog = folder_dialog(parent, title, start)
        if not dialog.exec():
            return []
        return chosen(dialog)
    finally:
        if translator is not None:
            QCoreApplication.instance().removeTranslator(translator)
