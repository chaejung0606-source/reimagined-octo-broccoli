"""주차등록 화면의 '관리대장'(1단계 카드 이름 — 담당자 2026-10-22) — 공무확인증 관리대장 하나만 보인다. 담당자 요청 2026-10-21.

담당자: "할인내역을 볼때 공무확인증 관리대장으로 확인하고 엑셀파일로 다운받을 수 있도록" · "이전 공무확인증 관리대장에는 일자, 수량(구입,배부,잔여),
내용, 사용자 항목이 있었습니다". 대장은 parking_ledger.py(사용자 폴더의 _공무확인증관리대장.json)에 있다.

- 표의 내용 · 사용자 · 차량번호 · 비고 · 구입 · 배부 · 일자는 그 자리에서 고친다(두 번 누르기). 잔여는 앱이 셈한다.
- [줄 추가] 로 구입(이월) · 배부를 적는다. 할인 적용 · 할인 링크에서 적은 줄은 그 화면이 넣는다(pages/parking.py).
- 사이트 할인 내역은 화면에 보이지 않는다(담당자 2026-10-22 "어플에서는 사이트 할인 내역을 보지 않고 관리대장 양식으로만 사용내역을 파악") —
  1단계에서 관리대장을 고를 때마다(1분 안에 다시 열면 그대로) · 열어 둔 동안 10분마다 · [사이트에서 가져오기] 로 창 없이 읽어(읽기만) 대장과 차량번호 · 일자로 맞춰 보고, 대장에 없는 공무확인증 사용은
  링크 · QR 로 쓴 것까지 바로 관리대장 양식으로 넣는다 — 사용자 · 내용은 공란. 같이 읽은 보유 잔량으로 처음 수량 · 줄마다 잔여를 다시 센다(fit_to_site).
- 구글 시트를 연결했으면(설정 → 관리대장 구글 시트, parking_sheet.py) 화면을 열 때 · 대장을 고친 뒤 시트의 '관리대장' 탭과 맞추고(뒤 스레드 — ui/sheet_sync.py),
  불러온 사이트 할인 내역은 '할인내역' 탭에 쌓는다.
"""
from __future__ import annotations

import datetime as dt
import re
import time

from PySide6.QtCore import QDate, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import parking_ledger as ledger
from ... import parking, parking_sheet, settings
from ...minutes import logbook
from ..sheet_sync import instance as sheet_sync
from ..widgets import Field, Pill, muted_label

REREAD_GAP_S = 60                   # 관리대장을 닫았다 곧 다시 열면(탭을 오가면) 다시 가져오지 않는다
AUTO_READ_MS = 10 * 60 * 1000       # 관리대장을 열어 둔 동안 사이트에서 다시 가져오는 간격 — 링크 · QR 로 쓴 것도 바로바로(담당자 2026-10-22)

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


class LeftBox(QFrame):
    """표 위의 잔여 상자 — 남은 공무확인증 수를 크게(담당자 2026-10-22 "잔여만 바로 확인할 수 있도록 … 잘보이는 크기로").
    옆에는 사이트 보유 잔량과 맞는지 배지와 처음 수량 · 구입 · 배부 한 줄."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("leftBox")
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 12, 20, 12)
        row.setSpacing(16)
        number = QVBoxLayout()
        number.setSpacing(0)
        number.addWidget(QLabel("공무확인증 잔여", objectName="leftLabel"))
        value_row = QHBoxLayout()
        value_row.setSpacing(4)
        self.value = QLabel("—", objectName="leftValue")
        value_row.addWidget(self.value, 0, Qt.AlignBottom)
        self.unit = QLabel("개", objectName="leftUnit")
        value_row.addWidget(self.unit, 0, Qt.AlignBottom)
        value_row.addStretch(1)
        number.addLayout(value_row)
        row.addLayout(number, 0)
        notes = QVBoxLayout()
        notes.setSpacing(6)
        notes.addStretch(1)
        self.state = Pill("사이트 잔량 아직 안 읽음", "neutral")
        notes.addWidget(self.state, 0, Qt.AlignLeft)
        self.site = QLabel("", objectName="leftNote")
        self.site.setWordWrap(True)
        notes.addWidget(self.site)
        self.counts = QLabel("", objectName="leftNote")
        self.counts.setWordWrap(True)
        notes.addWidget(self.counts)
        # 적용금액 0 인 사용(무료 시간 안)이 공무확인증을 쓰는지 — 앱이 잔량 변화로 확인한 결과(담당자 2026-10-22 "확인해주세요")
        self.rule = QLabel("", objectName="leftNote")
        self.rule.setWordWrap(True)
        notes.addWidget(self.rule)
        notes.addStretch(1)
        row.addLayout(notes, 1)

    def show_counts(self, entries: list[ledger.Entry], rows) -> None:
        bought, given, left = ledger.totals(entries)
        start = sum(e.bought for e in entries if e.source == ledger.CARRY)
        cfg = settings.load()
        site = cfg.parking_left if cfg.parking_left >= 0 else None
        shown = left if entries else site
        self.value.setText(f"{shown:,}" if shown is not None else "—")
        self.unit.setVisible(shown is not None)
        if not entries:
            self.counts.setText("아직 적은 줄이 없습니다 — 사이트에서 사용내역 · 보유 잔량을 가져오면 채워집니다.")
        else:
            self.counts.setText((f"처음 수량 {start:,} · " if start else "") + f"구입 {bought - start:,} · 배부 {given:,}")
        self.site.setText(f"사이트 보유 잔량 {site:,} ({cfg.parking_left_at} 읽음)" if site is not None
                          else "사이트 보유 잔량은 아직 읽지 않았습니다.")
        rule, at = cfg.parking_free_rule, cfg.parking_free_rule_at
        self.rule.setText({"all": f"적용금액 0 인 사용도 공무확인증이 차감됩니다({at} 잔량 변화로 확인)",
                           "paid": f"적용금액 0 인 사용은 차감되지 않습니다({at} 잔량 변화로 확인) — 대장에서 배부 0"}.get(
            rule, "적용금액 0 인 사용이 차감되는지는 아직 모릅니다 — 두 번 읽는 사이에 그런 사용이 있으면 잔량 변화로 앱이 확인합니다"))
        if entries and any(n < 0 for _e, n in rows):
            self.state.set_status("잔여가 0 아래인 줄이 있음 — 사이트에서 가져오면 다시 셈", "danger")
        elif site is None:
            self.state.set_status("사이트 잔량 아직 안 읽음", "neutral")
        elif not entries or left == site:
            self.state.set_status("사이트 잔량과 같음", "success")
        else:
            self.state.set_status(f"사이트 잔량과 {abs(left - site):,} 다름 — 사이트에서 가져오면 맞춤", "warning")


class LedgerPanel(QWidget):
    """관리대장 표 — 사이트에서 가져온 사용까지 이 양식 하나로 본다."""

    read_site = Signal()           # 사이트에서 사용내역 · 보유 잔량 가져오기 — 화면이 브라우저 스레드에 맡긴다
    changed = Signal()             # 대장이 바뀜

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._entries: list[ledger.Entry] = []
        self._filling = False
        self._busy = False
        self._read_at = 0.0                # 마지막으로 사이트에서 가져온 때(time.monotonic) — 열 때마다 가져오되 1분 안에는 다시 안 함
        self._auto = QTimer(self)
        self._auto.setInterval(AUTO_READ_MS)
        self._auto.timeout.connect(self._auto_read)

        self.left_box = LeftBox()              # 표보다 먼저 — 남은 수가 맨 위에 크게
        layout.addWidget(self.left_box)

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
        self.site_button = QPushButton("사이트에서 가져오기")
        self.site_button.setToolTip("주차 사이트의 할인 내역(첫 쪽)과 보유 잔량을 창 없이 읽어, 대장에 없는 사용을 넣고 잔여를 다시 셉니다(사이트는 읽기만)")
        self.site_button.clicked.connect(self.read_site.emit)
        bar.addWidget(self.site_button)
        layout.addLayout(bar)
        self.site_line = muted_label("")             # 사이트에서 가져온 결과 한 줄 — 표는 보이지 않는다
        self.site_line.setWordWrap(True)
        layout.addWidget(self.site_line)
        # 구글 시트 — 연결했으면 맞춘 때 · [지금 맞추기] · [시트 열기]
        sheet_row = QHBoxLayout()
        sheet_row.setSpacing(8)
        self.sheet_state = Pill("구글 시트 연결 안 됨", "neutral")
        sheet_row.addWidget(self.sheet_state, 0, Qt.AlignVCenter)
        self.sheet_note = muted_label("")
        self.sheet_note.setWordWrap(True)
        sheet_row.addWidget(self.sheet_note, 1, Qt.AlignVCenter)
        self.sync_button = QPushButton("지금 맞추기")
        self.sync_button.setObjectName("ghost")
        self.sync_button.setToolTip("구글 시트의 '관리대장' 탭과 맞춥니다 — 시트에서 고친 것을 가져오고, 앱에서 고친 것을 올립니다")
        self.sync_button.clicked.connect(lambda: (self._sheet_busy(), sheet_sync().run_now()))
        sheet_row.addWidget(self.sync_button)
        self.sheet_button = QPushButton("시트 열기")
        self.sheet_button.setObjectName("ghost")
        self.sheet_button.clicked.connect(self._open_sheet)
        sheet_row.addWidget(self.sheet_button)
        layout.addLayout(sheet_row)
        sheet_sync().synced.connect(self._on_synced)
        sheet_sync().history_saved.connect(self._on_history_saved)

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
        self.left_box.show_counts(self._entries, rows)
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
        self._local_change()

    def add_entry(self, entry: ledger.Entry) -> ledger.Entry:
        """할인 적용 · 할인 링크 화면이 부른다. (적은 줄, 그 뒤 잔여) 를 알리려고 줄을 돌려준다."""
        self._show(ledger.add(entry))
        self._local_change()
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
        self._local_change()

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

    # ── 구글 시트 ────────────────────────────────────────────────────────
    def _local_change(self) -> None:
        """앱에서 대장을 고쳤다 — 화면들에 알리고 시트와 맞춘다(잇달아 고치면 한 번에)."""
        self.changed.emit()
        sheet_sync().request()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload()
        self._sheet_row()
        self._auto.start()
        # 1단계에서 관리대장을 고를 때마다 사이트에서 가져온다(담당자 2026-10-22 — 전에는 [사이트 할인 내역 불러오기] 를 눌러야 했다)
        if time.monotonic() - self._read_at > REREAD_GAP_S:
            QTimer.singleShot(400, self._auto_read)
        if sheet_sync().connected():
            self._sheet_busy()
            sheet_sync().run_now()             # 열 때마다 시트에서 고친 것을 가져온다

    def _sheet_busy(self) -> None:
        if sheet_sync().connected():
            self.sheet_state.set_status("구글 시트와 맞추는 중", "info")

    def _sheet_row(self, result=None) -> None:
        config = parking_sheet.load_config()
        self.sync_button.setVisible(config.connected)
        self.sheet_button.setVisible(bool(config.connected and config.sheet_url))
        if not config.connected:
            self.sheet_state.set_status("구글 시트 연결 안 됨", "neutral")
            self.sheet_note.setText("설정 → '관리대장 구글 시트' 에서 연결하면 시트에서도 보고 고칠 수 있습니다.")
            return
        result = result or sheet_sync().last
        name = f"'{config.sheet_name}' " if config.sheet_name else ""
        if result is None:
            self.sheet_state.set_status("구글 시트 연결됨", "success")
            self.sheet_note.setText(f"시트 {name}— 열 때 · 고친 뒤 맞춥니다.")
        elif result.ok:
            self.sheet_state.set_status("구글 시트와 맞춤", "success")
            self.sheet_note.setText(f"{result.when} 에 시트 {name}의 '관리대장' 탭과 맞췄습니다(대장 {result.total}줄).")
        else:
            self.sheet_state.set_status("구글 시트 못 맞춤", "danger")
            self.sheet_note.setText(result.note)

    def _on_synced(self, result) -> None:
        if result.ok and result.changed:
            self._show(ledger.load())
            self.changed.emit()                # 다시 맞추지는 않는다
        self._sheet_row(result)

    def _on_history_saved(self, result) -> None:
        if result.ok and result.added:
            self.site_line.setText(self.site_line.text() + f" · 구글 시트 '할인내역' 탭에 {result.added}줄 쌓음")
        elif not result.ok and result.note not in ("연결 안 됨", "줄 없음"):
            self.site_line.setText(self.site_line.text() + " · " + result.note)

    def _open_sheet(self) -> None:
        url = parking_sheet.load_config().sheet_url
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # ── 사이트에서 가져오기 ───────────────────────────────────────────────
    def _auto_read(self) -> None:
        """화면을 열어 둔 동안 — 다른 일을 하는 중이 아니고 주차 로그인 정보가 있을 때만."""
        if not self.isVisible() or self._busy:
            return
        if not parking.saved_user():
            self.site_line.setText("설정 → '주차등록 로그인 정보' 를 넣으면 관리대장을 열 때마다 사이트 사용내역 · 보유 잔량을 저절로 가져옵니다.")
            return
        self.read_site.emit()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._auto.stop()

    def site_loading(self) -> None:
        self.site_line.setText("사이트에서 사용내역 · 보유 잔량을 가져오는 중입니다(창 없이)…")

    def site_failed(self, message: str) -> None:
        self.site_line.setText("사이트에서 가져오지 못했습니다 — " + message)

    def show_site(self, report) -> None:
        """사이트 할인 내역(모든 쪽)과 보유 잔량 — 표로 보이지 않고 대장에만 넣는다(담당자 2026-10-22)."""
        if not report.ok:
            self.site_failed(" ".join(report.lines()).lstrip("✗ "))
            return
        self._read_at = time.monotonic()
        headers = [ledger.clean_header(h) for h in report.headers]
        sheet_sync().save_history(headers, report.rows)        # 구글 시트 '할인내역' 탭에 쌓기(연결했으면)
        parts = [f"{report.read_at} 에 사이트에서 가져옴({report.pages}쪽 {len(report.rows)}줄"
                 + (f" · {report.since}부터" if report.since else "") + ")"]
        cfg = settings.load()
        count = ledger.site_count(report.products)
        with ledger._LOCK:
            entries = ledger.load()
            match = ledger.match_site(entries, headers, report.rows)
            changed = ledger.note_applied(report.rows, match) if match.ok else 0
            drain = (ledger.check_drain(cfg.parking_seen_left, cfg.parking_seen_at, count, report.rows, match)
                     if count is not None else None)
            rule = cfg.parking_free_rule
            if drain is not None:
                logbook.log("주차 잔량 확인: " + drain.text())
                if drain.verdict and drain.verdict != rule:
                    if rule:
                        logbook.log(f"⚠ 적용금액 0 인 사용의 차감 판정이 앞과 다릅니다({rule} → {drain.verdict})")
                    rule = drain.verdict
                    settings.update(parking_free_rule=rule, parking_free_rule_at=dt.datetime.now().strftime("%m-%d %H:%M"))
                    parts.append(drain.text())
            new = ledger.from_site(headers, report.rows, match.missing, match, free_drawn=rule != "paid") if match.ok else []
            entries += new
            changed += ledger.apply_free_rule(entries) if rule == "paid" else ledger.restore_free(entries)
            if new or changed:
                ledger.save(entries)
        if count is not None:
            settings.update(parking_seen_left=count, parking_seen_at=report.read_stamp)
        if not match.ok:
            parts.append(match.note)
        elif new:
            parts.append(f"새 사용 {len(new)}건을 관리대장에 넣음(사용자 · 내용은 공란)")
        else:
            parts.append("새 사용 없음")
        if report.pager:
            parts.append(report.pager)
        if count is not None:
            fit = self.fit_site(count, save=False)
            parts.append(f"보유 잔량 {count:,} → 처음 수량 {fit.start:,}")
            if fit.short:
                parts.append(f"대장의 구입이 보유 잔량보다 {fit.short:,} 많습니다 — 대장에 없는 사용이 있거나 구입 줄이 틀렸습니다")
            free = sum(1 for e in fit.entries if e.given == 1 and ledger.is_free(e.note))
            if free and not rule:
                parts.append(f"적용금액 0 인 사용 {free}건 — 그것도 차감되면 처음 수량 {fit.start:,}, 적용금액 있는 것만 차감되면 "
                             f"{max(fit.start - free, 0):,}(산 수와 맞는 쪽이 맞습니다)")
        elif report.products:
            parts.append("할인권 보기에 공무확인증 잔량이 없어 잔여는 그대로")
        self.reload()
        self._local_change()
        self.site_line.setText(" · ".join(parts))

    def fit_site(self, count: int, save: bool = True) -> ledger.Fit:
        """사이트 보유 잔량을 막 읽었을 때 — 처음 수량 줄을 다시 셈하고 줄마다 잔여를 다시 그린다(parking_ledger.fit_to_site)."""
        when = dt.datetime.now().strftime("%m-%d %H:%M")
        settings.update(parking_left=count, parking_left_at=when)
        with ledger._LOCK:
            fit = ledger.fit_to_site(ledger.load(), count, when)
            if fit.changed:
                ledger.save(fit.entries)
        if save:
            self.reload()
            self._local_change()
        return fit

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.site_button.setEnabled(not busy)

    def _sync(self) -> None:
        self.remove_button.setEnabled(bool(self.table.selectedItems()))
        self.export_button.setEnabled(bool(self._entries))
