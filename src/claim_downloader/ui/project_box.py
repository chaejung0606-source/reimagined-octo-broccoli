"""ERP 과제 고르기 칸 — 일반청구 · 청구서 받기가 함께 쓴다(담당자 2026-10-21: "일반청구와 동일하게 옵션 선택을 넣으면 될 것 같습니다. 기본값도 동일").

보기는 로그인 뒤 메인화면 과제현황에서 읽은 과제 중 과제기간에 오늘이 든 것(navigate.choices), 기본은 마지막으로 고른 과제 → 담당자가 정한
기본 과제(settings.DEFAULT_PROJECT_NO). 고르면 settings.project_no 에 남겨 다음 로그인 뒤 그 과제의 청구서 화면으로 간다.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyleOptionComboBox,
    QVBoxLayout,
    QWidget,
)

from .. import navigate, project_folders, settings


class ProjectBox(QComboBox):
    """과제 칸 — 고른 과제명만큼 넓어지고, 펼친 목록은 가장 긴 과제명까지 보인다.

    담당자 2026-10-21: "과제명이 잘 안보이네요. 과제명에 따라서 길이가 수정되도록 설정"(+ "하드코딩 하지 말아주세요").
    전에는 13글자 폭으로 고정하고 과제명을 16자에서 잘라 '202408470003 첨단분' 처럼 보였다. 폭은 글자 길이로만 정한다 —
    줄이 좁으면 과제번호까지는 보이게 줄어들고(minimumSizeHint), 나머지는 말풍선."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.currentIndexChanged.connect(lambda _i: self.updateGeometry())

    def _hint_for(self, text: str) -> QSize:
        """이 글을 담는 칸의 크기 — 테두리 · 여백 · 펼침 단추는 스타일이 더한다(Qt 가 자기 크기를 셈하는 방식 그대로)."""
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        metrics = self.fontMetrics()
        content = QSize(metrics.horizontalAdvance(text), metrics.height())
        return self.style().sizeFromContents(QStyle.CT_ComboBox, option, content, self)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._hint_for(self.currentText())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self._hint_for(self.currentText().split(" ")[0])        # 좁은 줄에서도 과제번호까지는

    def showPopup(self) -> None:  # noqa: N802
        # 펼친 목록은 가장 긴 보기만큼 — 칸보다 좁게 잘리지 않게
        view = self.view()
        metrics = view.fontMetrics()
        longest = max((metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        pad = metrics.horizontalAdvance("    ") + view.verticalScrollBar().sizeHint().width() + 2 * view.frameWidth()
        view.setMinimumWidth(longest + pad)
        super().showPopup()


def project_box() -> QComboBox:
    """과제 고르기 칸 — 과제번호 + 과제명(자르지 않음). 기간은 말풍선."""
    return ProjectBox()


def last_project() -> str:
    return str(getattr(settings.load(), "project_no", "") or settings.DEFAULT_PROJECT_NO)


def fill_project_box(box: QComboBox, selected: str) -> None:
    box.blockSignals(True)
    box.clear()
    for no, text in navigate.choices(selected, short=True):
        box.addItem(text, no)
        box.setItemData(box.count() - 1, navigate.label_of(no), Qt.ToolTipRole)
    index = box.findData(selected)
    box.setCurrentIndex(index if index >= 0 else 0)
    box.setToolTip("ERP 과제: " + navigate.label_of(str(box.currentData() or selected))
                   + "\n보기는 로그인 뒤 메인화면 과제현황에서 읽은 과제 중 과제기간에 오늘이 든 것입니다.")
    box.blockSignals(False)
    box.updateGeometry()          # 신호를 막고 채웠으니 고른 과제명 폭을 여기서 다시 잰다


def remember(no: str) -> None:
    """마지막으로 고른 과제 — 로그인 뒤 그 과제의 청구서 화면으로 간다."""
    if no and no != last_project():
        settings.update(project_no=no)


def folder_projects() -> list[project_folders.ProjectFolder]:
    """저장 폴더 아래 과제 폴더 — 과제번호마다 하나(같은 번호 폴더가 둘이면 앞의 것만 보이고, 받을 때 save_root 가 막는다)."""
    seen, out = set(), []
    for folder in project_folders.folders(settings.load().out_root):
        if folder.no not in seen:
            seen.add(folder.no)
            out.append(folder)
    return out


def chosen_projects() -> list[str]:
    """'고른 과제 여럿' 에 담긴 과제 — 지금 폴더가 있는 것만, 폴더 차례대로."""
    return project_folders.pick([f.no for f in folder_projects()], settings.load().download_projects)


def fill_download_box(box: QComboBox, selected: str) -> None:
    """청구서 받기의 과제 칸(담당자 2026-10-21: "과제번호로 과제 구분해서" · "지금 폴더 만든 과제만" · "여러개 과제를 선택해서 연속적으로") —
    저장 폴더 아래에 `(과제번호)_…` 폴더가 있으면 맨 위 '폴더 만든 과제 모두' · '고른 과제 N개'(여러 과제 고르기 창) · 과제 폴더 하나씩.
    과제 폴더가 없는 옛 저장 폴더면 일반청구와 같은 보기."""
    found = folder_projects()
    if not found:
        fill_project_box(box, selected if selected not in (project_folders.ALL, project_folders.SOME) else last_project())
        return
    chosen = chosen_projects()
    names = {f.no: f.path.name for f in found}
    box.blockSignals(True)
    box.clear()
    box.addItem(f"폴더 만든 과제 모두 ({len(found)}개)", project_folders.ALL)
    box.setItemData(0, "저장 폴더 아래 과제 폴더가 있는 과제를 차례로 읽고 받습니다:\n" + "\n".join(f.path.name for f in found), Qt.ToolTipRole)
    box.addItem(f"고른 과제 {len(chosen)}개 (다시 고르려면 여기를 누르세요)" if chosen else "여러 과제 고르기…", project_folders.SOME)
    box.setItemData(1, ("고른 과제를 차례로 읽고 받습니다:\n" + "\n".join(names[no] for no in chosen)) if chosen
                    else "받을 과제를 여러 개 골라 차례로 받습니다", Qt.ToolTipRole)
    for folder in found:
        box.addItem(folder.short(), folder.no)
        known = navigate.label_of(folder.no)
        box.setItemData(box.count() - 1, folder.path.name + ("" if known == folder.no else "\nERP: " + known), Qt.ToolTipRole)
    index = box.findData(selected)
    box.setCurrentIndex(index if index >= 0 else 0)
    box.setToolTip("받을 과제 — 청구서는 그 과제의 폴더(저장 폴더 아래 '(과제번호)_…') 안 비목 폴더에 둡니다.\n"
                   "폴더가 없는 과제는 받지 않습니다.")
    box.blockSignals(False)
    box.updateGeometry()


class ProjectPickDialog(QDialog):
    """받을 과제를 여러 개 고르는 창 — 과제 폴더마다 체크 상자. 고른 과제는 위에서부터 차례로 읽고 받는다."""

    def __init__(self, parent: QWidget | None, folders: list[project_folders.ProjectFolder], chosen: list[str]):
        super().__init__(parent)
        self.setObjectName("reportDialog")
        self.setWindowTitle("받을 과제 고르기")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)
        heading = QLabel("받을 과제를 고르세요")
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        hint = QLabel("고른 과제를 위에서부터 차례로 열어 결의서내역을 읽고, 받을 청구서를 한 번에 보여 준 뒤 묻고 받습니다.\n"
                      "청구서는 그 과제의 폴더 안 비목 폴더에 들어갑니다.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        holder = QWidget()
        holder.setObjectName("pageBody")              # 바탕 없이 — 창의 흰 면이 그대로 보이게(theme)
        rows = QVBoxLayout(holder)
        rows.setContentsMargins(0, 4, 0, 4)
        rows.setSpacing(8)
        self.checks: list[tuple[str, QCheckBox]] = []
        for folder in folders:
            check = QCheckBox(folder.short())
            check.setToolTip(folder.path.name)
            check.setChecked(folder.no in chosen)
            check.toggled.connect(self._sync)
            rows.addWidget(check)
            self.checks.append((folder.no, check))
        rows.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setWidget(holder)
        area.viewport().setAutoFillBackground(False)
        area.setMinimumHeight(min(36 * len(folders) + 12, 340))
        layout.addWidget(area, 1)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        every = QPushButton("모두 고르기")
        every.setObjectName("ghost")
        every.clicked.connect(lambda: self._set_all(True))
        tools.addWidget(every)
        none = QPushButton("모두 풀기")
        none.setObjectName("ghost")
        none.clicked.connect(lambda: self._set_all(False))
        tools.addWidget(none)
        tools.addStretch(1)
        self.count = QLabel("")
        self.count.setObjectName("muted")
        tools.addWidget(self.count)
        layout.addLayout(tools)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok = QPushButton("이 과제들로")
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        buttons.addWidget(self.ok)
        layout.addLayout(buttons)
        self.resize(460, self.sizeHint().height())
        self._sync()

    def _set_all(self, on: bool) -> None:
        for _no, check in self.checks:
            check.setChecked(on)

    def _sync(self) -> None:
        n = len(self.chosen())
        self.count.setText(f"{n}개 고름" if n else "하나 이상 고르세요")
        self.ok.setEnabled(n > 0)

    def chosen(self) -> list[str]:
        return [no for no, check in self.checks if check.isChecked()]


def pick_projects(parent: QWidget | None) -> bool:
    """여러 과제 고르기 창을 띄우고, 고르면 설정(download_projects)에 남긴다. 골랐으면 True."""
    folders = folder_projects()
    dialog = ProjectPickDialog(parent, folders, chosen_projects())
    if dialog.exec() != QDialog.Accepted or not dialog.chosen():
        return False
    settings.update(download_projects=",".join(dialog.chosen()), download_scope="some")
    return True
