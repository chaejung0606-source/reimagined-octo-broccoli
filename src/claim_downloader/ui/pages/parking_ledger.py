"""주차등록 화면의 '할인 내역 · 관리대장' — 공무확인증 관리대장(앱에 적은 것) + 사이트 할인 내역(읽기만). 담당자 요청 2026-10-21.

담당자: "할인내역을 볼때 공무확인증 관리대장으로 확인하고 엑셀파일로 다운받을 수 있도록" · "이전 공무확인증 관리대장에는 일자, 수량(구입,배부,잔여),
내용, 사용자 항목이 있었습니다". 대장은 parking_ledger.py(사용자 폴더의 _공무확인증관리대장.json)에 있다.

- 표의 내용 · 사용자 · 차량번호 · 비고 · 구입 · 배부 · 일자는 그 자리에서 고친다(두 번 누르기). 잔여는 앱이 셈한다.
- [줄 추가] 로 구입(이월) · 배부를 적는다. 할인 적용 · 할인 링크에서 적은 줄은 그 화면이 넣는다(pages/parking.py).
- [사이트 할인 내역 불러오기] 는 사이트 '운영 → 할인 내역' 의 첫 쪽을 읽어(읽기만) 대장과 차량번호 · 일자로 맞춰 보고, 대장에 없는 줄은
  [대장에 넣기] 로 배부 1 줄씩 넣는다 — 사용자 · 내용은 표에서 채운다. 그 화면의 열 이름은 실측 전이라 못 맞추면 그렇다고만 알린다.
"""
from __future__ import annotations

import datetime as dt
import re

from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import parking_ledger as ledger
from ... import settings
from ..widgets import Card, EmptyState, Field, Pill, muted_label

# (머리글, Entry 칸) — 잔여 · 적은 곳은 앱이 채운다(고칠 수 없음)
COLUMNS = [("일자", "date"), ("구입", "bought"), ("배부", "given"), ("잔여", ""), ("내용", "content"), ("사용자", "user"),
           ("차량번호", "car"), ("비고", "note"), ("적은 곳", "")]
COL_LEFT = 3


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


class AddDialog(QDialog):
    """[줄 추가] — 일자 · 구입/배부 · 수량 · 내용 · 사용자 · 차량번호 · 비고."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("reportDialog")
        self.setWindowTitle("관리대장 줄 추가")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        layout.addWidget(Field("일자", self.date))
        kinds = QHBoxLayout()
        self.buy = QRadioButton("구입 (이월 포함)")
        self.give = QRadioButton("배부 (쓴 것)")
        self.give.setChecked(True)
        group = QButtonGroup(self)
        for button in (self.buy, self.give):
            group.addButton(button)
            kinds.addWidget(button)
        kinds.addStretch(1)
        holder = QWidget()
        holder.setLayout(kinds)
        layout.addWidget(Field("구분", holder))
        self.count = QSpinBox()
        self.count.setRange(1, 99999)
        layout.addWidget(Field("수량", self.count))
        self.content = QLineEdit()
        self.content.setPlaceholderText("예: 외부 자문위원 방문 · 공무확인증 구입")
        layout.addWidget(Field("내용", self.content))
        self.user = QLineEdit()
        layout.addWidget(Field("사용자", self.user))
        self.car = QLineEdit()
        self.car.setPlaceholderText("배부면 차량번호(있으면)")
        layout.addWidget(Field("차량번호", self.car))
        self.note = QLineEdit()
        layout.addWidget(Field("비고", self.note))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("적기")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def entry(self) -> ledger.Entry:
        count = self.count.value()
        return ledger.Entry(date=self.date.date().toString("yyyy-MM-dd"), bought=count if self.buy.isChecked() else 0,
                            given=count if self.give.isChecked() else 0, content=self.content.text().strip(),
                            user=self.user.text().strip(), car=self.car.text().strip(), note=self.note.text().strip(),
                            source="manual")


class LedgerPanel(QWidget):
    """관리대장 표 + 사이트 할인 내역(불러오면 아래에)."""

    read_site = Signal()           # [사이트 할인 내역 불러오기] — 화면이 브라우저 스레드에 맡긴다
    changed = Signal()             # 대장이 바뀜 — 할인 적용 · 링크 칸의 사용자 · 내용 보기를 다시 채운다

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._entries: list[ledger.Entry] = []
        self._filling = False
        self._site_headers: list[str] = []
        self._site_rows: list[list[str]] = []
        self._match: ledger.SiteMatch | None = None

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.add_button = QPushButton("줄 추가")
        self.add_button.setObjectName("primary")
        self.add_button.setToolTip("구입(이월) · 배부를 직접 적습니다")
        self.add_button.clicked.connect(self._add)
        bar.addWidget(self.add_button)
        self.remove_button = QPushButton("줄 지우기")
        self.remove_button.setObjectName("ghost")
        self.remove_button.clicked.connect(self._remove)
        bar.addWidget(self.remove_button)
        self.export_button = QPushButton("엑셀로 받기")
        self.export_button.clicked.connect(self._export)
        bar.addWidget(self.export_button)
        bar.addStretch(1)
        self.site_button = QPushButton("사이트 할인 내역 불러오기")
        self.site_button.setToolTip("사이트 '운영 → 할인 내역' 의 첫 쪽을 읽어(읽기만) 대장과 맞춰 봅니다")
        self.site_button.clicked.connect(self.read_site.emit)
        bar.addWidget(self.site_button)
        layout.addLayout(bar)
        self.totals = muted_label("")
        self.totals.setWordWrap(True)
        layout.addWidget(self.totals)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([name for name, _ in COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.itemChanged.connect(self._edited)
        self.table.itemSelectionChanged.connect(self._sync)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setStretchLastSection(True)
        head.setHighlightSections(False)
        head.setSectionResizeMode(QHeaderView.Interactive)
        # 창이 낮아도 대장 몇 줄은 보이게 — 줄 높이로(단계 칸이 스크롤된다)
        self.table.setMinimumHeight(self.table.verticalHeader().defaultSectionSize() * 5 + head.sizeHint().height())
        layout.addWidget(self.table, 1)

        # 사이트 할인 내역 — 불러오면 보인다
        self.site_card = Card("사이트 할인 내역", "사이트 '운영 → 할인 내역' 이 처음 보여 주는 쪽입니다(읽기만). 앱에는 남기지 않습니다.",
                              margins=(16, 14, 16, 12))
        site_bar = QHBoxLayout()
        site_bar.setSpacing(8)
        self.site_filter = QLineEdit()
        self.site_filter.setPlaceholderText("찾기 — 차량번호 · 상품 등")
        self.site_filter.setClearButtonEnabled(True)
        self.site_filter.textChanged.connect(self._filter_site)
        site_bar.addWidget(self.site_filter, 1)
        self.site_state = Pill("안 읽음", "neutral")
        site_bar.addWidget(self.site_state, 0, Qt.AlignVCenter)
        self.site_card.add_layout(site_bar)
        self.site_info = muted_label("")
        self.site_info.setWordWrap(True)
        self.site_card.add(self.site_info)
        match_row = QHBoxLayout()
        self.match_label = muted_label("")
        self.match_label.setWordWrap(True)
        match_row.addWidget(self.match_label, 1)
        self.import_button = QPushButton("대장에 넣기")
        self.import_button.setObjectName("primary")
        self.import_button.setToolTip("대장에 없는 사이트 줄을 배부 1 줄씩 넣습니다 — 사용자 · 내용은 표에서 채우세요")
        self.import_button.clicked.connect(self._import_site)
        match_row.addWidget(self.import_button, 0, Qt.AlignVCenter)
        self.site_card.add_layout(match_row)
        self.site_stack = QStackedWidget()
        self.site_empty = EmptyState("overview", "할인 내역이 없습니다", "")
        self.site_stack.addWidget(self.site_empty)
        self.site_table = QTableWidget(0, 0)
        table = self.site_table
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(32)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        site_head = table.horizontalHeader()
        site_head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        site_head.setStretchLastSection(True)
        site_head.setHighlightSections(False)
        site_head.setSectionResizeMode(QHeaderView.Interactive)
        table.setMinimumHeight(table.verticalHeader().defaultSectionSize() * 4 + site_head.sizeHint().height())
        self.site_stack.addWidget(table)
        self.site_card.add(self.site_stack, 1)
        self.site_card.hide()
        layout.addWidget(self.site_card, 1)
        self.reload()

    # ── 대장 ────────────────────────────────────────────────────────────
    def reload(self) -> None:
        self._show(ledger.load())

    def _show(self, entries: list[ledger.Entry]) -> None:
        self._entries = ledger.ordered(entries)
        self._filling = True
        table = self.table
        table.setRowCount(0)
        rows = ledger.with_balance(self._entries)
        table.setRowCount(len(rows))
        for r, (e, left) in enumerate(rows):
            values = [e.date, str(e.bought or ""), str(e.given or ""), str(left), e.content, e.user, e.car, e.note,
                      ledger.SOURCES.get(e.source, e.source)]
            for c, ((_name, key), text) in enumerate(zip(COLUMNS, values)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if not key:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if c in (1, 2, COL_LEFT):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        self._filling = False
        bought, given, left = ledger.totals(self._entries)
        text = f"구입 {bought:,} · 배부 {given:,} · 잔여 {left:,}"
        site = ledger.site_left(settings.load().parking_products, settings.load().parking_product)
        if site is not None:
            text += f"  ·  사이트 잔량 {site:,}(마지막으로 [등록] 할 때 읽은 값)"
        if not self._entries:
            text = "아직 적은 줄이 없습니다 — 처음이면 [줄 추가] 로 지금 남은 공무확인증 수를 '구입(이월)' 으로 적으세요."
        elif any(left < 0 for _e, left in rows):
            text += "  ·  잔여가 0 아래인 줄이 있습니다 — 구입(이월) 줄을 그보다 앞 일자로 적으세요."
        self.totals.setText(text)
        self._rematch()
        self._sync()

    def _edited(self, item: QTableWidgetItem) -> None:
        if self._filling or not (0 <= item.row() < len(self._entries)):
            return
        key = COLUMNS[item.column()][1]
        if not key:
            return
        value = item.text().strip()
        if key == "date":
            day = ledger.day_of(value)
            if not day:
                QMessageBox.information(self, "일자", "일자는 2026-10-21 처럼 적어 주세요.")
                self._show(self._entries)
                return
            value = day
        entry = self._entries[item.row()]
        self._show(ledger.update(entry.id, **{key: value}))
        self.changed.emit()

    def add_entry(self, entry: ledger.Entry) -> ledger.Entry:
        """할인 적용 · 할인 링크 화면이 부른다. (적은 줄, 그 뒤 잔여) 를 알리려고 줄을 돌려준다."""
        self._show(ledger.add(entry))
        self.changed.emit()
        return entry

    def left_after(self, entry: ledger.Entry) -> int:
        for e, left in ledger.with_balance(self._entries):
            if e.id == entry.id:
                return left
        return ledger.totals(self._entries)[2]

    def _add(self) -> None:
        dialog = AddDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.add_entry(dialog.entry())

    def _remove(self) -> None:
        rows = {i.row() for i in self.table.selectedItems()}
        if not rows:
            return
        entry = self._entries[min(rows)]
        what = f"{entry.date} · " + (f"구입 {entry.bought}" if entry.bought else f"배부 {entry.given}") + (f" · {entry.content}" if entry.content else "")
        if QMessageBox.question(self, "줄 지우기", f"이 줄을 관리대장에서 지울까요?\n\n{what}",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._show(ledger.remove(entry.id))
        self.changed.emit()

    def _export(self) -> None:
        name = f"{ledger.TITLE}_{dt.date.today():%Y%m%d}.xlsx"
        start = settings.load().out_root or ""
        target, _ = QFileDialog.getSaveFileName(self, "관리대장 엑셀로 받기", f"{start}/{name}" if start else name, "엑셀 (*.xlsx)")
        if not target:
            return
        if not target.lower().endswith(".xlsx"):
            target += ".xlsx"
        try:
            path = ledger.export_xlsx(self._entries, target)
        except (OSError, ImportError) as error:
            QMessageBox.warning(self, "엑셀로 받기", f"엑셀 파일을 만들지 못했습니다.\n{error}\n\n(같은 파일이 엑셀에 열려 있으면 닫고 다시 하세요.)")
            return
        if QMessageBox.question(self, "엑셀로 받기", f"관리대장을 엑셀로 저장했습니다.\n{path}\n\n지금 열까요?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def users(self) -> list[str]:
        return sorted({e.user for e in self._entries if e.user})

    def contents(self) -> list[str]:
        return sorted({e.content for e in self._entries if e.content})

    # ── 사이트 할인 내역 ─────────────────────────────────────────────────
    def site_loading(self) -> None:
        self.site_card.show()
        self.site_state.set_status("읽는 중", "info")
        self.site_info.setText("주차 사이트의 할인 내역 화면을 여는 중입니다…")

    def site_failed(self, message: str) -> None:
        self.site_card.show()
        self.site_state.set_status("못 읽음", "danger")
        self.site_info.setText(message)

    def show_site(self, report) -> None:
        self.site_card.show()
        if not report.ok:
            self.site_failed("\n".join(report.lines()))
            return
        rows = report.rows
        width = max([len(report.headers)] + [len(r) for r in rows] + [1])
        headers = list(report.headers) + [f"칸 {i + 1}" for i in range(len(report.headers), width)]
        self._site_headers, self._site_rows = headers, rows
        table = self.site_table
        table.clearContents()
        table.setColumnCount(width)
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(headers)
        for r, cells in enumerate(rows):
            for c in range(width):
                text = cells[c] if c < len(cells) else ""
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        self.site_stack.setCurrentIndex(1 if rows else 0)
        if not rows:
            self.site_empty.set_content("overview", "할인 내역이 없습니다",
                                        report.empty_note or "사이트가 처음 보여 주는 쪽에 줄이 없습니다 — 다른 기간은 브라우저에서 봅니다.")
        info = [f"{report.read_at} 에 읽음" + (f" · 사이트 {report.total}" if report.total else "")]
        if report.pager:
            info.append("사이트가 처음 보여 주는 쪽만 읽었습니다 — 다른 쪽 · 다른 기간은 브라우저 화면에서 봅니다.")
        self.site_info.setText(" · ".join(info))
        self._rematch()
        self._filter_site(self.site_filter.text())

    def _rematch(self) -> None:
        """사이트 줄마다 대장에 있는지 — 차량번호 · 일자. 없는 줄은 [대장에 넣기]."""
        if not self._site_rows:
            self._match = None
            self.match_label.setText("")
            self.import_button.hide()
            return
        match = self._match = ledger.match_site(self._entries, self._site_headers, self._site_rows)
        if not match.ok:
            self.match_label.setText(match.note + " — 표를 보고 [줄 추가] 로 직접 적으세요.")
            self.import_button.hide()
            return
        self.match_label.setText(f"대장에 있는 줄 {len(match.matched)} · 대장에 없는 줄 {len(match.missing)}"
                                 + (" — 대장에 넣은 뒤 표에서 사용자 · 내용을 채우세요." if match.missing else " — 모두 대장에 있습니다."))
        self.import_button.setVisible(bool(match.missing))
        self.import_button.setText(f"대장에 넣기 ({len(match.missing)}줄)")
        missing = set(match.missing)
        for r in range(self.site_table.rowCount()):
            for c in range(self.site_table.columnCount()):
                item = self.site_table.item(r, c)
                if item is not None:
                    font = item.font()
                    font.setBold(r in missing)            # 대장에 없는 줄은 굵게 — 색만으로 알리지 않는다
                    item.setFont(font)

    def _import_site(self) -> None:
        match = self._match
        if match is None or not match.ok or not match.missing:
            return
        entries = ledger.from_site(self._site_headers, self._site_rows, match.missing, match)
        if QMessageBox.question(self, "대장에 넣기", f"사이트 할인 내역 {len(entries)}줄을 배부 1 줄씩 관리대장에 넣을까요?\n"
                                "사용자 · 내용은 비어 있으니 넣은 뒤 표에서 두 번 눌러 채우세요.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        stored = ledger.load() + entries
        ledger.save(stored)
        self._show(stored)
        self.changed.emit()

    def _filter_site(self, text: str) -> None:
        word = _squash(text)
        shown = 0
        for r, cells in enumerate(self._site_rows):
            hide = bool(word) and not any(word in _squash(c) for c in cells)
            self.site_table.setRowHidden(r, hide)
            shown += not hide
        total = len(self._site_rows)
        if total:
            self.site_state.set_status(f"{shown}/{total}줄" if word else f"{total}줄", "success")
        elif self._site_headers or self.site_card.isVisible():
            self.site_state.set_status("0줄", "neutral")

    def set_busy(self, busy: bool) -> None:
        self.site_button.setEnabled(not busy)

    def _sync(self) -> None:
        self.remove_button.setEnabled(bool(self.table.selectedItems()))
        self.export_button.setEnabled(bool(self._entries))
