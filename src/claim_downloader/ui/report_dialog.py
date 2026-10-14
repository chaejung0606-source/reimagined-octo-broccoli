"""표로 보는 결과 창 — 길어지는 미리 보기 · 결과를 메시지 상자 한 덩어리 글 대신 표로 보인다.

담당자 요청(2026-10-14): 장학금 미리 보기가 메시지 상자에 줄글로 이어져 사람끼리 구분이 안 되고, 창이 화면보다 길어져
아래 내용과 단추가 보이지 않았다. 그래서
- 창 크기는 화면의 90%(폭) · 80%(높이)를 넘지 않게 정하고, 늘어나는 것은 표 안에서 스크롤한다.
- 사람마다 한 줄. 긴 값(첨부 파일 목록 · 진행 단계)은 줄을 고르면 아래 '자세히' 칸에 보인다.
- 확인할 것(문제 · ERP 알림)도 따로 칸을 두고 길면 그 안에서 스크롤한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .widgets import Pill, PillDelegate, WrapLabel

MAX_WIDTH, MAX_HEIGHT = 1120, 720


@dataclass
class ReportRow:
    status: str                      # 첫 칸 배지 글자
    tone: str                        # 배지 색 — success · warning · danger · info · neutral
    cells: list[str]                 # 나머지 칸
    detail: str = ""                 # 줄을 고르면 아래 '자세히' 칸에
    tips: dict[int, str] = field(default_factory=dict)    # 칸 번호(cells 기준) → 마우스를 올리면 보일 전체 글
    right: tuple[int, ...] = ()      # 오른쪽 정렬할 칸 번호(cells 기준) — 금액 · 개수


class ReportDialog(QDialog):
    """머리(배지 + 제목) · 요약 줄 · 확인할 것 · 표 · 자세히 · 단추. accept_text 를 주면 [그 글자] [취소] 를 묻는다."""

    def __init__(self, parent: QWidget | None, title: str, heading: str, tone: str = "info",
                 summary: list[str] | None = None, columns: list[tuple[str, int | None]] | None = None,
                 rows: list[ReportRow] | None = None, notes: list[str] | None = None, notes_title: str = "확인할 것",
                 footer: str = "", accept_text: str = "", close_text: str = "닫기"):
        super().__init__(parent)
        self.setObjectName("reportDialog")
        self.setWindowTitle(title)
        self.setSizeGripEnabled(True)
        self._rows = rows or []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(Pill(title, tone), 0, Qt.AlignVCenter)
        heading_label = QLabel(heading)
        heading_label.setObjectName("cardTitle")
        head.addWidget(heading_label, 1)
        layout.addLayout(head)

        if summary:
            text = WrapLabel("\n".join(summary))
            text.setObjectName("body")
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(text)

        if notes:
            label = QLabel(f"{notes_title} {len(notes)}건")
            label.setObjectName("fieldLabel")
            layout.addWidget(label)
            self.notes = QPlainTextEdit("\n".join("· " + n for n in notes))
            self.notes.setReadOnly(True)
            self.notes.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            # 몇 줄이면 그만큼만, 많으면 네 줄 높이에서 스크롤
            lines = min(4, sum(1 + len(n) // 90 for n in notes))
            self.notes.setFixedHeight(18 + 21 * max(1, lines))
            layout.addWidget(self.notes)

        self.table = None
        self.detail = None
        if columns:
            self.table = QTableWidget(len(self._rows), len(columns))
            self.table.setHorizontalHeaderLabels([name for name, _ in columns])
            self.table.verticalHeader().hide()
            self.table.verticalHeader().setDefaultSectionSize(38)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SingleSelection)
            self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)     # 아래에 더 있다는 것이 늘 보이게
            self.table.setShowGrid(False)
            self.table.setWordWrap(False)
            self.table.setTextElideMode(Qt.ElideRight)
            self.table.setItemDelegateForColumn(0, PillDelegate(self.table))
            header = self.table.horizontalHeader()
            header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.setHighlightSections(False)
            header.setStretchLastSection(True)
            for col, (_, width) in enumerate(columns):
                header.setSectionResizeMode(col, QHeaderView.Interactive)
                if width:
                    self.table.setColumnWidth(col, width)
            for r, row in enumerate(self._rows):
                badge = QTableWidgetItem(row.status)
                badge.setData(PillDelegate.ROLE, row.tone)
                self.table.setItem(r, 0, badge)
                for c, value in enumerate(row.cells):
                    item = QTableWidgetItem(value)
                    item.setToolTip(row.tips.get(c, value))
                    if c in row.right:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(r, c + 1, item)
            layout.addWidget(self.table, 1)

            if any(row.detail for row in self._rows):
                label = QLabel("자세히 — 표에서 줄을 고르세요")
                label.setObjectName("fieldLabel")
                layout.addWidget(label)
                self.detail = QPlainTextEdit()
                self.detail.setReadOnly(True)
                self.detail.setFixedHeight(132)
                layout.addWidget(self.detail)
                self.table.currentCellChanged.connect(lambda row, _c, _pr, _pc: self._show_detail(row))
                if self._rows:
                    self.table.selectRow(0)
                    self._show_detail(0)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        if footer:
            note = WrapLabel(footer)
            note.setObjectName("muted")
            buttons.addWidget(note, 1)
        else:
            buttons.addStretch(1)
        if accept_text:
            cancel = QPushButton("취소")
            cancel.clicked.connect(self.reject)
            buttons.addWidget(cancel)
            ok = QPushButton(accept_text)
            ok.setObjectName("primary")
            # ERP 에 넣는 단추는 기본 단추로 두지 않는다 — 표를 읽다 Enter 를 누르면 그대로 넣기가 시작됐다(2026-10-14 점검).
            # 마우스로 누르거나 Tab 으로 옮겨 Space 로만.
            ok.setAutoDefault(False)
            ok.setDefault(False)
            cancel.setAutoDefault(False)
            ok.clicked.connect(self.accept)
            buttons.addWidget(ok)
        else:
            close = QPushButton(close_text)
            close.setObjectName("primary")
            close.setDefault(True)
            close.clicked.connect(self.accept)
            buttons.addWidget(close)
        layout.addLayout(buttons)
        if self.table is not None:
            self.table.setFocus()           # 첫 칸(확인할 것)이 초점을 받아 테두리가 강조돼 보이지 않게 — 표에서 위아래 키로 넘긴다
        self._fit_to_screen(parent)

    def _show_detail(self, row: int) -> None:
        if self.detail is not None and 0 <= row < len(self._rows):
            self.detail.setPlainText(self._rows[row].detail)

    def _fit_to_screen(self, parent: QWidget | None) -> None:
        """화면보다 커지지 않게 — 폭 90% · 높이 80% 안에서, 줄이 적으면 그만큼 낮게."""
        screen = (parent.screen() if parent is not None else None) or self.screen()
        area = screen.availableGeometry() if screen is not None else None
        width = min(MAX_WIDTH, int(area.width() * 0.9)) if area else MAX_WIDTH
        limit = min(MAX_HEIGHT, int(area.height() * 0.8)) if area else MAX_HEIGHT
        wanted = self.sizeHint().height()
        if self.table is not None:
            # 표가 줄 수만큼 다 보이는 높이 — 그보다 화면이 작으면 표 안에서 스크롤
            wanted += max(0, 38 * len(self._rows) + 44 - self.table.sizeHint().height())
        self.resize(width, max(320, min(limit, wanted)))


def show_report(parent: QWidget | None, **kwargs) -> bool:
    """창을 띄우고 기다린다. accept_text 가 있으면 [그 단추] 를 눌렀는지 돌려준다."""
    dialog = ReportDialog(parent, **kwargs)
    return dialog.exec() == QDialog.Accepted


def show_structure_saved(parent: QWidget | None, path: str) -> None:
    """[화면 구조 저장] 을 마친 뒤 — 청구서 받기 · 일반청구 화면이 같이 쓴다. path 가 비었으면 못 한 것."""
    if not path:
        QMessageBox.warning(parent, "화면 구조 저장", "화면 구조를 저장하지 못했습니다. [진행 기록] 을 보세요.")
        return
    answer = QMessageBox.question(
        parent, "화면 구조 저장",
        f"지금 열린 화면의 구조를 저장했습니다.\n{path}\n\n"
        "이 파일을 담당자(Claude)에게 보내면 그 화면의 자동화를 설계할 수 있습니다. "
        "계좌번호 같은 값이 섞일 수 있으니 빈 작성 화면에서 저장한 것인지 확인하세요.\n\n지금 열어 볼까요?",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
    if answer == QMessageBox.Yes:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
