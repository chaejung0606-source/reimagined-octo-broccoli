"""설정의 '출장 차량 연료' 칸 — 출장자 이름마다 차량 연료(담당자 2026-11-10 "설정에서 연료 종류 설정할 수 있도록 기능추가" · "이름으로 사람을 구별").

출장증빙(ui/pages/travel.py)은 하이패스가 있는 출장자(자차)의 연료를 여기서 이름으로 찾아 미리 고르고, 그 화면에서 고른 연료도 여기에 남긴다.
값은 config.json 의 travel_fuels('이름=연료' 줄들, travel.model.parse_fuels) 하나다.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from .. import settings
from ..travel import fuels, model
from .widgets import Card, WrapLabel


def fuel_box(options: list[str], current: str = "", placeholder: str = "연료 고르기") -> QComboBox:
    """연료 고르기 칸 — 보기 글자가 잘리지 않게(표 칸 안에서 '…' 로만 보이던 것, 담당자 2026-11-10 그림) 칸과 펼친 목록 폭을 글자만큼."""
    box = QComboBox()
    box.addItem(placeholder, "")
    for option in options:
        box.addItem(option, option)
    if current and box.findData(current) < 0:
        box.addItem(current, current)
    box.setCurrentIndex(max(box.findData(current), 0))
    box.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    box.setMinimumContentsLength(max(6, max((len(o) for o in options), default=6)))
    box.view().setMinimumWidth(box.view().sizeHintForColumn(0) + 32)
    return box


class TravelFuelCard(Card):
    changed = Signal()

    def __init__(self):
        super().__init__("출장 차량 연료", "출장증빙 — 하이패스가 있어 자차인 출장자의 연료를 이름으로 찾아 미리 채웁니다", art="travel")
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(("이름", "연료"))
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.options, source = fuels.options()
        self.source_label = WrapLabel(source)
        self.source_label.setObjectName("muted")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, max(180, fuel_box(self.options).sizeHint().width() + 24))
        self.table.setMinimumHeight(120)
        self.table.itemChanged.connect(lambda _item: self._save())
        self.add(self.table)
        self.add(self.source_label)
        row = QHBoxLayout()
        add = QPushButton("사람 추가")
        add.clicked.connect(lambda: self._add_row("", ""))
        drop = QPushButton("고른 줄 빼기")
        drop.setObjectName("ghost")
        drop.clicked.connect(self._drop)
        row.addWidget(add)
        row.addWidget(drop)
        row.addStretch(1)
        self.add_layout(row)
        self._loading = True
        for name, fuel in model.parse_fuels(settings.load().travel_fuels).items():
            self._add_row(name, fuel)
        self._loading = False

    def _add_row(self, name: str, fuel: str) -> None:
        row = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        box = fuel_box(self.options, fuel)
        box.currentIndexChanged.connect(lambda _i: self._save())
        self.table.setCellWidget(row, 1, box)
        self.table.setRowHeight(row, box.sizeHint().height() + 6)
        self.table.blockSignals(False)
        if not name:
            self.table.editItem(self.table.item(row, 0))

    def _drop(self) -> None:
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self._save()

    def fuels(self) -> dict[str, str]:
        out = {}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            box = self.table.cellWidget(row, 1)
            name = item.text().strip() if item else ""
            fuel = box.currentData() if box is not None else ""
            if name and fuel:
                out[name] = fuel
        return out

    def _save(self) -> None:
        if self._loading:
            return
        text = model.format_fuels(self.fuels())
        if text != settings.load().travel_fuels:
            settings.update(travel_fuels=text)
            self.changed.emit()
