"""일반청구 화면 오른쪽 칸의 '카드' 패널 — 종류가 카드인 결제 기간 폴더를 고르면 '청구 내용' 칸 대신 보인다(2026-10-20).

한 폴더(claims.card.CardJob)를 비목마다 청구서 · 결제 건마다 한 줄로 보여 줄 뿐이다. 고칠 것은 폴더 이름(사용일 · 금액 · [회의비])이나
폴더 안 파일이고, 고친 뒤 [다시 읽기]. ERP 카드청구 화면에 넣기는 실측 뒤(docs/roadmap.md 3절) — 여기에는 넣기 단추가 없다.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...claims import card
from ..widgets import PillDelegate, WrapLabel, muted_label

COLUMNS = [("청구구분", 118), ("비목", 44), ("사용일", 66), ("건명", 150), ("금액", 84), ("확인할 것", None)]
COL_DIV, COL_CODE, COL_DATE, COL_TITLE, COL_AMOUNT, COL_NOTES = range(6)
DIV_TONE = {"17": "info", "85": "info", "90": "neutral"}
HOW_TO = ("결제 건 폴더 이름 = '<비목명> MMDD <건명>' (MMDD 는 사용일). 금액은 영수증 PDF · 회의록에서 찾고, 못 찾으면 이름 끝에 "
          "'45,000원' 을 적어 주세요. 청구구분은 회의록이 있으면 회의비, 물품 표(품명 엑셀)가 있으면 소모성물품, 아니면 기타 — "
          "이름에 [회의비] · [소모품] · [기타] 를 적으면 그것으로.")


def _money(value) -> str:
    return f"{value:,}" if isinstance(value, int) else ""


def item_detail(item: card.CardItem, base: str = "") -> str:
    """한 결제 건의 자세한 내용 — 패널 아래 칸 · 미리 보기 창의 '자세히' 칸."""
    lines = [f"{item.name}",
             f"사용일 {item.used:%Y-%m-%d}" if item.used else "사용일 모름",
             f"금액 {_money(item.amount) or '모름'}원" + (f" (출처: {item.amount_from})" if item.amount_from else ""),
             f"청구구분 {item.req_div_name} — {item.req_div_from}",
             f"줄 적요(기타일 때): {item.summary}"]
    found = [f"가맹점 {item.merchant}" if item.merchant else "", f"카드 …{item.card_last}" if item.card_last else "",
             f"승인번호 {item.approval}" if item.approval else ""]
    if any(found):
        lines.append("영수증 · 회의록에서: " + " · ".join(x for x in found if x))
    if item.minutes:
        lines.append(f"회의록: {os.path.basename(item.minutes)}")
    if item.notice:
        lines.append(f"공문: {os.path.basename(item.notice)}")
    if item.req_div == "17":
        # 영수증 대신 카드매출전표로 갈음할 때 — 회의 장소와 가맹점 주소의 도 · 시가 같아야 한다(담당자 2026-10-20)
        lines.append(f"회의 장소 지역: {item.meeting_region or '모름'} ({item.meeting_region_from})"
                     + (f" · 가맹점 주소: {item.shop_address}" if item.shop_address else " · 가맹점 주소는 ERP 에 넣을 때 매출전표에서 확인"))
    if item.goods:
        lines.append(f"물품 표: {os.path.basename(item.goods.path)} ({item.goods.sheet}) — {len(item.goods.rows)}줄"
                     + (f" · 합계 {item.goods.total:,}원" if item.goods.total else ""))
        lines += [f"  {r['name']} {r.get('spec') or ''} × {r.get('qty') or '?'} = {_money(r.get('amount')) or '?'}" for r in item.goods.rows[:12]]
    lines.append(f"파일 {len(item.files)}개")
    lines += ["  " + (os.path.relpath(p, base) if base else os.path.basename(p)) for p in item.files[:20]]
    lines += ["확인: " + n for n in item.blocking() + item.notes]
    return "\n".join(lines)


class CardPanel(QWidget):
    """카드 결제 기간 폴더 하나 — 청구서(비목)마다 결제 건 줄."""

    reload_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pageBody")
        self.job: card.CardJob | None = None
        self._items: list[card.CardItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.summary = WrapLabel("")
        self.summary.setObjectName("body")
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.summary)
        self.problems = WrapLabel("")
        self.problems.setObjectName("fieldError")
        layout.addWidget(self.problems)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([name for name, _ in COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setMinimumHeight(120)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setItemDelegateForColumn(COL_DIV, PillDelegate(self.table))
        self.table.itemSelectionChanged.connect(self._on_selected)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setStretchLastSection(True)
        head.setHighlightSections(False)
        for col, (_, width) in enumerate(COLUMNS):
            head.setSectionResizeMode(col, QHeaderView.Interactive)
            if width:
                self.table.setColumnWidth(col, width)
        layout.addWidget(self.table, 1)

        self.detail = WrapLabel("")
        self.detail.setObjectName("body")
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.detail)
        self.skipped = muted_label("")
        self.skipped.setWordWrap(True)
        layout.addWidget(self.skipped)
        how = muted_label(HOW_TO)
        how.setWordWrap(True)
        layout.addWidget(how)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addStretch(1)
        open_button = QPushButton("폴더 열기")
        open_button.setObjectName("ghost")
        open_button.clicked.connect(self._open_folder)
        foot.addWidget(open_button)
        reload_button = QPushButton("다시 읽기")
        reload_button.setObjectName("ghost")
        reload_button.setToolTip("폴더 이름이나 안의 파일을 고친 뒤 누르세요.")
        reload_button.clicked.connect(self.reload_requested.emit)
        foot.addWidget(reload_button)
        layout.addLayout(foot)

    def set_job(self, job: card.CardJob | None) -> None:
        self.job = job
        self._items = job.items if job else []
        self.summary.setText("\n".join(job.summary_lines()) if job else "")
        problems = job.problems() if job else []
        self.problems.setText(("확인: " + " · ".join(problems)) if problems else "")
        self.problems.setVisible(bool(problems))
        self.skipped.setText(("결제 건으로 읽지 않은 것: " + " · ".join(job.skipped)) if job and job.skipped else "")
        self.skipped.setVisible(bool(job and job.skipped))
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            div = QTableWidgetItem(item.req_div_name or "모름")
            div.setData(PillDelegate.ROLE, DIV_TONE.get(item.req_div, "warning"))
            div.setToolTip(item.req_div_from)
            self.table.setItem(row, COL_DIV, div)
            cells = {COL_CODE: item.code or "?", COL_DATE: f"{item.used:%m-%d}" if item.used else "?",
                     COL_TITLE: item.title, COL_AMOUNT: _money(item.amount) or "모름",
                     COL_NOTES: " / ".join(item.blocking() + item.notes)}
            for col, text in cells.items():
                cell = QTableWidgetItem(text)
                cell.setToolTip(f"금액 출처: {item.amount_from}" if col == COL_AMOUNT and item.amount_from else text)
                if col == COL_AMOUNT:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, cell)
        self.detail.setText("줄을 고르면 그 결제 건의 금액 출처 · 가맹점 · 카드 뒷자리 · 파일이 여기 보입니다." if self._items else "")

    def _on_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedItems()}
        if rows and self.job:
            self.detail.setText(item_detail(self._items[min(rows)], self.job.folder))

    def _open_folder(self) -> None:
        if self.job:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.job.folder))
