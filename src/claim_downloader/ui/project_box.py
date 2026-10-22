"""ERP 과제 고르기 칸 — 일반청구 · 청구서 받기가 함께 쓴다(담당자 2026-10-21: "일반청구와 동일하게 옵션 선택을 넣으면 될 것 같습니다. 기본값도 동일").
증빙 다운로드는 저장 폴더가 과제 폴더로 나뉘어 있으면 이 칸 대신 과제 폴더마다 체크하는 목록(ProjectChecklist, 2026-10-22)을 쓴다.

보기는 로그인 뒤 메인화면 과제현황에서 읽은 과제 중 과제기간에 오늘이 든 것(navigate.choices), 기본은 마지막으로 고른 과제 → 담당자가 정한
기본 과제(settings.DEFAULT_PROJECT_NO). 고르면 settings.project_no 에 남겨 다음 로그인 뒤 그 과제의 청구서 화면으로 간다.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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


def start_choice(found: list[str]) -> list[str]:
    """증빙 다운로드 ② 를 처음 채울 때 체크해 둘 과제 — 지난번 고른 그대로(project_folders.initial_choice)."""
    current = settings.load()
    return project_folders.initial_choice(found, current.download_scope, current.download_projects, last_project())


def remember_choice(chosen: list[str], found: list[str]) -> None:
    """체크한 과제를 설정에 — 다음에 앱을 켜도 그대로. 하나면 마지막 과제(project_no)로도 남겨 로그인 뒤 그 과제로 간다."""
    if not chosen:
        return                     # 다 풀어 둔 것은 남기지 않는다 — 다음에 켜면 지난번 고른 것으로
    settings.update(download_scope=project_folders.scope_of(chosen, found), download_projects=",".join(chosen))
    if len(chosen) == 1:
        remember(chosen[0])


class _ListArea(QScrollArea):
    """과제 줄을 담는 칸 — 높이는 줄 수만큼(많으면 VISIBLE_ROWS 줄까지 보이고 나머지는 스크롤). 찾기로 줄이 줄어도 높이를 그대로 두어
    아래 [다음] 단추가 오르내리지 않게 한다. 창이 낮으면 레이아웃이 이보다 줄인다(최소 높이를 박지 않는다)."""

    def __init__(self):
        super().__init__()
        self.rows_height = 0

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), self.rows_height + 2 * self.frameWidth())


class ProjectChecklist(QWidget):
    """증빙 다운로드 ② 의 과제 칸 — 과제 폴더마다 체크 상자. 하나만 체크하면 그 과제만, 여럿이면 위에서부터 차례로 받는다.

    담당자 2026-10-22: "과제 체크체크해서 단일이나 복수 선택할 수 있도록" · "그리고 검색 기능도". 전에는 펼침 칸에서 '폴더 만든 과제 모두' ·
    '여러 과제 고르기…'(따로 뜨는 체크 창) · 과제 하나 중에 골랐다 — 과제 폴더가 13개로 늘어(연구지원비 다섯) 펼친 목록이 길었고, 둘 이상은
    창을 한 번 더 열어야 했다. 찾기 칸은 줄을 숨기기만 하고 체크는 그대로 둔다(숨은 과제도 체크돼 있으면 받는다 — 고른 수에 함께 센다).
    """

    VISIBLE_ROWS = 8          # 이보다 많으면 칸 안에서 스크롤 — 창이 낮아도 아래 [다음] 이 보이게

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("과제 찾기 — 과제번호나 이름 일부(예: 연구지원비, 0003)")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("넣은 글이 과제번호 · 폴더 이름 · ERP 과제명에 든 과제만 보입니다. 띄어 쓰면 낱말마다 찾습니다.\n"
                               "찾기는 보이는 줄만 줄이고 체크는 그대로 둡니다.")
        self.search.textChanged.connect(self._filter)
        tools.addWidget(self.search, 1)
        # 찾는 중에만 — 찾은 과제만 체크하고 나머지는 푼다(모두 체크된 채 '연구지원비' 만 받고 싶을 때 한 번에)
        self.only = QPushButton("찾은 과제만 고르기")
        self.only.setObjectName("ghost")
        self.only.setToolTip("찾은 과제만 체크하고 나머지 과제는 체크를 풉니다")
        self.only.clicked.connect(self._only_shown)
        self.only.hide()
        tools.addWidget(self.only)
        self.every = QPushButton("모두 고르기")
        self.every.setObjectName("ghost")
        self.every.clicked.connect(lambda: self._set_shown(True))
        tools.addWidget(self.every)
        self.none = QPushButton("모두 풀기")
        self.none.setObjectName("ghost")
        self.none.clicked.connect(lambda: self._set_shown(False))
        tools.addWidget(self.none)
        layout.addLayout(tools)
        frame = QFrame()
        frame.setObjectName("card")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(1, 1, 1, 1)
        self.area = _ListArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QScrollArea.NoFrame)
        holder = QWidget()
        holder.setObjectName("pageBody")              # 바탕 없이 — 카드의 흰 면이 그대로 보이게(theme)
        self.rows = QVBoxLayout(holder)
        self.rows.setContentsMargins(14, 8, 14, 8)
        self.rows.setSpacing(6)
        self.empty = QLabel("찾는 과제가 없습니다 — 찾기 칸의 글을 지우거나 바꾸세요.")
        self.empty.setObjectName("muted")
        self.empty.hide()
        self.rows.addWidget(self.empty)
        self.rows.addStretch(1)
        self.area.setWidget(holder)
        self.area.viewport().setAutoFillBackground(False)
        inner.addWidget(self.area)
        layout.addWidget(frame)
        self.count = QLabel("")
        self.count.setObjectName("muted")
        layout.addWidget(self.count)
        self.checks: list[tuple[project_folders.ProjectFolder, QCheckBox]] = []
        self._texts: dict[str, tuple[str, ...]] = {}

    # ── 채우기 ───────────────────────────────────────────────────────
    def fill(self, folders: list[project_folders.ProjectFolder], chosen: list[str]) -> None:
        """과제 폴더마다 체크 상자 — chosen 에 든 과제는 체크. 찾기 칸의 글은 그대로 두고 다시 거른다."""
        for _folder, check in self.checks:
            self.rows.removeWidget(check)
            check.deleteLater()
        self.checks, self._texts = [], {}
        for i, folder in enumerate(folders):
            known = navigate.label_of(folder.no)
            check = QCheckBox(folder.short())
            check.setToolTip(folder.path.name + ("" if known == folder.no else "\nERP: " + known))
            check.setChecked(folder.no in chosen)
            check.toggled.connect(self._changed)
            self.rows.insertWidget(i, check)
            self.checks.append((folder, check))
            self._texts[folder.no] = (folder.no, folder.path.name, "" if known == folder.no else known)
        self._fit_height()
        self._filter(self.search.text())

    def _fit_height(self) -> None:
        """줄 VISIBLE_ROWS 개(그보다 적으면 그만큼)의 높이 — 글자 크기에서 셈한다(숫자로 박지 않는다)."""
        shown = min(len(self.checks), self.VISIBLE_ROWS) or 1
        row = max((check.sizeHint().height() for _f, check in self.checks), default=self.empty.sizeHint().height())
        margins = self.rows.contentsMargins()
        self.area.rows_height = shown * row + (shown - 1) * self.rows.spacing() + margins.top() + margins.bottom()
        self.area.updateGeometry()

    # ── 고르기 · 찾기 ────────────────────────────────────────────────
    def chosen(self) -> list[str]:
        """체크한 과제 — 폴더 차례대로(받는 차례)."""
        return [folder.no for folder, check in self.checks if check.isChecked()]

    def found(self) -> list[str]:
        return [folder.no for folder, _check in self.checks]

    def label_of(self, no: str) -> str:
        """과제 하나의 짧은 이름 — '202408470003 2026년도 사업비'."""
        return next((folder.short() for folder, _check in self.checks if folder.no == no), no)

    def _shown(self) -> list[QCheckBox]:
        return [check for _folder, check in self.checks if not check.isHidden()]

    def _filter(self, text: str) -> None:
        for folder, check in self.checks:
            check.setVisible(project_folders.matches(text, *self._texts.get(folder.no, (folder.no,))))
        searching = bool(text.strip())
        found = bool(self._shown())
        self.empty.setVisible(searching and not found)
        # 찾는 중이면 고르기 · 풀기는 찾은 과제에만 — 무엇에 하는지 단추 글로 알린다
        self.only.setVisible(searching)
        self.every.setText("찾은 과제 더하기" if searching else "모두 고르기")
        self.every.setToolTip("찾은 과제를 체크합니다(이미 체크한 다른 과제는 그대로)" if searching else "모든 과제를 체크합니다")
        self.none.setText("찾은 과제 빼기" if searching else "모두 풀기")
        self.none.setToolTip("찾은 과제의 체크를 풉니다(다른 과제는 그대로)" if searching else "모든 과제의 체크를 풉니다")
        for button in (self.only, self.every, self.none):
            button.setEnabled(found)
        self._sync_count()

    def _only_shown(self) -> None:
        for _folder, check in self.checks:
            check.blockSignals(True)
            check.setChecked(not check.isHidden())
            check.blockSignals(False)
        self._changed()

    def _set_shown(self, on: bool) -> None:
        for check in self._shown():
            check.blockSignals(True)
            check.setChecked(on)
            check.blockSignals(False)
        self._changed()

    def _changed(self, *_args) -> None:
        self._sync_count()
        self.changed.emit()

    def _sync_count(self) -> None:
        n, total = len(self.chosen()), len(self.checks)
        if not n:
            text = "체크한 과제가 없습니다 — 받을 과제를 하나 이상 체크하세요."
        elif n == 1:
            text = f"1개 체크 — 그 과제만 받습니다 (전체 {total}개)"
        else:
            text = f"{n}개 체크 — 위에서부터 차례로 받습니다 (전체 {total}개)"
        shown = len(self._shown())
        if self.search.text().strip() and shown < total:
            hidden = sum(1 for _folder, check in self.checks if check.isChecked() and check.isHidden())
            text += f" · 찾은 과제 {shown}개" + (f" · 안 보이는 체크 {hidden}개도 받습니다" if hidden else "")
        self.count.setText(text)
