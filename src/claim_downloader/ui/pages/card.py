"""일반청구 화면 오른쪽 칸의 '카드' 패널 — 종류가 카드인 결제 기간 폴더를 고르면 '청구 내용' 칸 대신 보인다(2026-10-20).

한 폴더(claims.card.CardJob)를 비목마다 청구서 · 결제 건마다 한 줄로 보여 준다. 고칠 것은 폴더 이름(사용일 · 금액 · [회의비])이나
폴더 안 파일이고, 고친 뒤 [다시 읽기]. ERP 에 넣는 것은 청구서(비목) 하나씩 — 위의 '넣을 청구서' 로 고르고 아래 막대의 [ERP 에 넣기]
(claims/card_erp.py). 넣은 결제 건은 '저장됨' 으로 남아 다시 누르면 남은 것만 넣는다.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...claims import card, card_erp
from ..widgets import Field, PillDelegate, WrapLabel, muted_label

COLUMNS = [("상태", 84), ("청구구분", 112), ("비목", 40), ("사용일", 70), ("건명", 140), ("금액", 80), ("확인할 것", None)]
COL_STATE, COL_DIV, COL_CODE, COL_DATE, COL_TITLE, COL_AMOUNT, COL_NOTES = range(7)
DIV_TONE = {"17": "info", "85": "info", "90": "neutral"}
STATE_TEXT = {"saved": ("저장됨", "success"), "running": ("넣는 중", "info"), "review": ("저장·확인", "warning"),
              "stopped": ("멈춤", "danger"), "skipped": ("건너뜀", "neutral"), "planned": ("미리 봄", "neutral")}
HOW_TO = ("결제 건 폴더 이름 = '<비목명> MMDD <건명>' (MMDD 는 사용일). 금액은 영수증 PDF · 회의록에서 찾고, 못 찾으면 이름 끝에 "
          "'45,000원' 을 적어 주세요. 청구구분은 회의록이 있으면 회의비, 물품 표(품명 엑셀)가 있으면 소모성물품, 아니면 기타 — "
          "이름에 [회의비] · [소모품] · [기타] 를 적으면 그것으로.")


def _money(value) -> str:
    return f"{value:,}" if isinstance(value, int) else ""


def item_detail(item: card.CardItem, base: str = "", plan: card_erp.ItemResult | None = None) -> str:
    """한 결제 건의 자세한 내용 — 패널 아래 칸 · 미리 보기 창의 '자세히' 칸. plan 이 있으면 ERP 에 넣을 값(card_erp.plan_item)도."""
    lines = [f"{item.name}" + (" — ERP 에 임시저장함" if item.status == "saved" else ""),
             f"사용일 {item.used:%Y-%m-%d}" if item.used else "사용일 모름",
             f"금액 {_money(item.amount) or '모름'}원" + (f" (출처: {item.amount_from})" if item.amount_from else ""),
             f"청구구분 {item.req_div_name} — {item.req_div_from}"]
    if plan is not None:
        lines.append("ERP 에 넣을 것:" if plan.status == "planned" else "ERP 에 넣은 것:" if plan.lines else "")
        lines += ["  " + line for line in plan.lines]
    else:
        lines.append(f"줄 적요(기타일 때): {item.summary}")
    found = [f"가맹점 {item.merchant}" if item.merchant else "", f"카드 …{item.card_last}" if item.card_last else "",
             f"승인번호 {item.approval}" if item.approval else ""]
    if any(found):
        lines.append("영수증 · 회의록에서: " + " · ".join(x for x in found if x))
    if item.minutes:
        lines.append(f"회의록: {os.path.basename(item.minutes)}")
    if item.notice:
        lines.append(f"공문: {os.path.basename(item.notice)}" + (f" (비목 {item.notice_code})" if item.notice_code else ""))
    if item.req_div == "17":
        # 영수증 대신 카드매출전표로 갈음할 때 — 회의 장소와 가맹점 주소의 도 · 시가 같아야 한다(담당자 2026-10-20)
        lines.append(f"회의 장소 지역: {item.meeting_region or '모름'} ({item.meeting_region_from})"
                     + (f" · 가맹점 주소: {item.shop_address}" if item.shop_address else " · 가맹점 주소는 ERP 에 넣을 때 회의록등록 창에서 확인"))
    if item.goods:
        lines.append(f"물품 표: {os.path.basename(item.goods.path)} ({item.goods.sheet}) — {len(item.goods.rows)}줄"
                     + (f" · 합계 {item.goods.total:,}원" if item.goods.total else ""))
        lines += [f"  {r['name']} {r.get('spec') or ''} × {r.get('qty') or '?'} = {_money(r.get('amount')) or '?'}" for r in item.goods.rows[:12]]
    lines.append(f"파일 {len(item.files)}개")
    lines += ["  " + (os.path.relpath(p, base) if base else os.path.basename(p)) for p in item.files[:20]]
    lines += ["확인: " + n for n in item.blocking() + item.notes]
    return "\n".join(lines)


def sheet_label(sheet: card.CardSheet) -> str:
    left = sum(1 for i in sheet.items if i.status != "saved")
    done = len(sheet.items) - left
    return (f"{sheet.main_summary or '(비목 모름)'} — 결제 {len(sheet.items)}건 · {sheet.total:,}원"
            + (f" · 저장 {done}건" if done else "") + (f" · 결의번호 {sheet.req_cnt}" if sheet.req_cnt else ""))


class CardPanel(QWidget):
    """카드 결제 기간 폴더 하나 — 청구서(비목)마다 결제 건 줄. 넣을 청구서를 고른다."""

    reload_requested = Signal()
    sheet_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("pageBody")
        self.job: card.CardJob | None = None
        self._items: list[card.CardItem] = []
        self._rows: dict[tuple[int, int], int] = {}          # (청구서 번호, 결제 건 번호) → 표 줄 — 고른 청구서의 것만
        self._plans: dict[int, card_erp.ItemResult] = {}     # 표 줄 → 미리 보기 계획

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
        self.sheet_box = QComboBox()
        self.sheet_box.currentIndexChanged.connect(self._on_sheet)
        layout.addWidget(Field("넣을 청구서", self.sheet_box, "청구서(비목) 하나에 결제 건이 줄로 들어갑니다. 하나를 끝내면 ERP 에서 새 카드청구 화면을 띄우고 다음 것을."))

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
        self.table.setItemDelegateForColumn(COL_STATE, PillDelegate(self.table))
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
        self.reload_button = QPushButton("다시 읽기")
        self.reload_button.setObjectName("ghost")
        self.reload_button.setToolTip("폴더 이름이나 안의 파일을 고친 뒤 누르세요.")
        self.reload_button.clicked.connect(self.reload_requested.emit)
        foot.addWidget(self.reload_button)
        layout.addLayout(foot)

    # ── 채우기 ──────────────────────────────────────────────────────────
    def set_job(self, job: card.CardJob | None) -> None:
        same = job is not None and self.job is job          # 같은 폴더를 다시 보이면 고른 청구서를 그대로
        self.job = job
        self._plans = {}
        self.summary.setText("\n".join(job.summary_lines()) if job else "")
        problems = job.problems() if job else []
        self.problems.setText(("확인: " + " · ".join(problems)) if problems else "")
        self.problems.setVisible(bool(problems))
        self.skipped.setText(("결제 건으로 읽지 않은 것: " + " · ".join(job.skipped)) if job and job.skipped else "")
        self.skipped.setVisible(bool(job and job.skipped))
        keep = self.sheet_box.currentIndex()
        self.sheet_box.blockSignals(True)
        self.sheet_box.clear()
        for sheet in job.sheets if job else []:
            self.sheet_box.addItem(sheet_label(sheet))
        if job and job.sheets:
            first_left = next((i for i, s in enumerate(job.sheets) if any(it.status != "saved" for it in s.items)), 0)
            self.sheet_box.setCurrentIndex(keep if same and 0 <= keep < len(job.sheets) else first_left)
        self.sheet_box.blockSignals(False)
        self._fill_table()

    def _fill_table(self) -> None:
        """고른 청구서(비목)의 결제 건만 — 청구서마다 ERP 에 따로 넣으므로."""
        index = self.chosen_sheet()
        sheet = self.job.sheets[index] if index >= 0 else None
        self._items = list(sheet.items) if sheet else []
        self._rows = {(index, ii): ii for ii in range(len(self._items))}
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            self._set_state_cell(row, "saved" if item.status == "saved" else "", "")
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

    def _on_sheet(self, _index: int) -> None:
        self._plans = {}
        self._fill_table()
        self.sheet_changed.emit()

    def _set_state_cell(self, row: int, status: str, note: str) -> None:
        text, tone = STATE_TEXT.get(status, ("대기", "neutral"))
        cell = QTableWidgetItem(text)
        cell.setData(PillDelegate.ROLE, tone)
        cell.setToolTip(note or text)
        self.table.setItem(row, COL_STATE, cell)

    def chosen_sheet(self) -> int:
        index = self.sheet_box.currentIndex()
        return index if self.job and 0 <= index < len(self.job.sheets) else -1

    def set_item_status(self, sheet_index: int, item_index: int, status: str, note: str) -> None:
        row = self._rows.get((sheet_index, item_index))
        if row is not None:
            self._set_state_cell(row, status, note)
            self.table.scrollToItem(self.table.item(row, COL_STATE))

    def set_plans(self, sheet_index: int, plans: list[card_erp.ItemResult]) -> None:
        for plan in plans:
            row = self._rows.get((sheet_index, plan.index))
            if row is not None:
                self._plans[row] = plan
        self._on_selected()

    def set_locked(self, locked: bool) -> None:
        self.sheet_box.setEnabled(not locked)
        self.reload_button.setEnabled(not locked)

    def _on_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedItems()}
        if rows and self.job:
            row = min(rows)
            self.detail.setText(item_detail(self._items[row], self.job.folder, self._plans.get(row)))

    def _open_folder(self) -> None:
        if self.job:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.job.folder))
