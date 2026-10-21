"""주차등록 화면 — 교내 주차 사이트(traffic.kangwon.ac.kr). 담당자 요청 2026-10-21.

담당자가 정한 짜임(같은 날): 기능은 둘 — ① **할인 링크 · QR**: 정해 둔 기간 동안 쓸 수 있는 링크(사이트가 QR 도 만든다)를 앱 칸에 넣고
[등록] 하면 앱이 사이트의 [새 링크] 창에 넣고 [저장] 까지 누른다(parking_link.py, "어플에서 등록 누르면 사이트에도 눌리는걸로").
② **할인 적용**: 차량번호로 바로 그 차에 할인을 준다 — 화면이 실측 전이라 앱은 화면을 열고 차량번호 칸에 넣어 두기만 한다(parking_screens.py).
그리고 ③ **할인 내역**(운영 → 할인 내역)을 앱에서 본다 — 읽기만.
로그인 정보는 이 화면에 두지 않는다 — 설정의 '주차등록 로그인 정보'(ui/parking_login.py, 담당자 요청 같은 날).
"""
from __future__ import annotations

import datetime as dt
import re

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ... import parking_link, settings
from ..art import Art
from ..widgets import Card, EmptyState, Field, Pill, WrapLabel, muted_label
from ..worker import SessionWorker

AUTO_PRODUCT = "사이트에 하나뿐이면 그것"
# 할인 적용이 맨 앞 · 처음 열리는 탭(담당자 요청 2026-10-21 — 들어온 차에 바로 할인하는 일이 가장 잦다)
TAB_APPLY, TAB_LINK, TAB_HISTORY = range(3)


def _qdt(value: dt.datetime) -> QDateTime:
    return QDateTime(value.year, value.month, value.day, value.hour, value.minute, 0)


def _py(value: QDateTime) -> dt.datetime:
    d, t = value.date(), value.time()
    return dt.datetime(d.year(), d.month(), d.day(), t.hour(), t.minute())


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _scrolled(widget: QWidget) -> QScrollArea:
    """입력 카드는 창이 낮으면(1024×640) 탭 안에서 스크롤된다."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    holder = QWidget()
    holder.setObjectName("pageBody")
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 12, 0, 8)
    layout.addWidget(widget)
    layout.addStretch(1)
    area.setWidget(holder)
    return area


class ParkingPage(QWidget):
    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.worker = worker if worker is not None else SessionWorker()
        self._busy = False
        self._mine = ""                       # 지금 도는 일 — 'link' · 'apply' · 'history' · 'open'. 받기 · 일반청구도 같은 스레드를 쓴다
        self._site_open = False               # 이 화면에서 사이트를 열었는지 — 브라우저가 닫히면 상태를 '닫힘' 으로
        self._history_rows: list[list[str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 30)          # 아래 26px 이상 — 접힌 독이 마지막 줄을 가리지 않게
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("parking", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("주차등록")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        texts.addWidget(muted_label("교내 주차 사이트(traffic.kangwon.ac.kr) — 차량번호로 바로 할인을 적용하거나 할인 링크 · QR 을 만들고, "
                                    "할인 내역을 봅니다. 로그인은 설정의 '주차등록 로그인 정보' 로 앱이 합니다."))
        head.addLayout(texts, 1)
        self.open_button = QPushButton("브라우저에서 사이트 열기")
        self.open_button.setToolTip("앱 브라우저(ERP 와 같은 창)에 사이트를 열고, 로그인 정보가 있으면 자동으로 로그인합니다")
        self.open_button.clicked.connect(self._open)
        head.addWidget(self.open_button, 0, Qt.AlignVCenter)
        # [화면 구조 저장] 은 '화면 구조 저장' 업무 하나로 옮겼다(담당자 요청 2026-10-21, pages/structure.py — 주차등록 사이트를 골라 저장)
        self.state = Pill("준비", "neutral")
        head.addWidget(self.state, 0, Qt.AlignVCenter)
        layout.addLayout(head)
        self.result = WrapLabel("")
        self.result.setObjectName("muted")
        self.result.hide()
        layout.addWidget(self.result)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        tabs = {TAB_APPLY: (_scrolled(self._build_apply_card()), "할인 적용 (차량번호)"),
                TAB_LINK: (_scrolled(self._build_link_card()), "할인 링크 · QR"),
                TAB_HISTORY: (self._build_history_card(), "할인 내역")}
        for index in sorted(tabs):
            self.tabs.addTab(*tabs[index])
        self.tabs.setCurrentIndex(TAB_APPLY)
        layout.addWidget(self.tabs, 1)

        w = self.worker
        w.parking_opened.connect(self._on_opened)
        w.parking_registered.connect(self._on_registered)
        w.parking_applied.connect(self._on_applied)
        w.parking_history.connect(self._on_history)
        w.busy.connect(self._on_busy)
        w.failed.connect(self._on_failed)
        w.browser_state.connect(self._on_browser_state)
        self._load_products()
        self._sync()

    # ── ① 할인 링크 · QR ────────────────────────────────────────────────
    def _build_link_card(self) -> QWidget:
        form = Card("할인 링크 · QR 만들기", "정한 기간 동안 쓸 수 있는 할인 링크를 만듭니다(사이트가 링크마다 QR 도 만듭니다). "
                    "[등록] 을 누르면 앱이 사이트의 [새 링크] 창에 넣고 [저장] 까지 누릅니다.", art="register")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 10/23 외부 자문위원 방문")
        self.name_edit.returnPressed.connect(self._register)
        form.add(Field("링크 이름", self.name_edit, "같은 이름이 목록에 있으면 넣지 않습니다."))
        self.product_box = QComboBox()
        form.add(Field("할인권 상품", self.product_box, "보기는 사이트에서 읽어 옵니다(한 번 [등록] 하면 채워집니다). 괄호 안은 남은 수."))
        dates = QHBoxLayout()
        dates.setSpacing(8)
        dates.setContentsMargins(0, 0, 0, 0)
        now = dt.datetime.now().replace(second=0, microsecond=0)
        self.start_edit = self._datetime_edit(now)
        self.end_edit = self._datetime_edit(now.replace(hour=23, minute=59))
        dates.addWidget(self.start_edit, 1)
        dates.addWidget(QLabel("~"))
        dates.addWidget(self.end_edit, 1)
        holder = QWidget()
        holder.setLayout(dates)
        form.add(Field("유효기간", holder, "이 기간 동안 링크 · QR 로 할인을 받을 수 있습니다. 기본은 지금부터 오늘 23:59 까지."))
        checks = QHBoxLayout()
        checks.setSpacing(16)
        self.active_check = QCheckBox("활성")
        self.active_check.setChecked(True)
        checks.addWidget(self.active_check)
        self.restart_check = QCheckBox("완료 화면에 '처음으로' 버튼 표시")
        checks.addWidget(self.restart_check)
        checks.addStretch(1)
        form.add_layout(checks)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.register_button = QPushButton("등록")
        self.register_button.setObjectName("primary")
        self.register_button.clicked.connect(self._register)
        buttons.addWidget(self.register_button)
        self.links_button = QPushButton("목록 · QR 보기 (브라우저)")
        self.links_button.setObjectName("ghost")
        self.links_button.setToolTip("브라우저에 사이트의 '할인 링크' 목록을 띄웁니다 — 링크마다 [QR 보기] 로 QR 을 봅니다")
        self.links_button.clicked.connect(self._show_links)
        buttons.addWidget(self.links_button)
        buttons.addStretch(1)
        self.form_state = Pill("준비", "neutral")
        buttons.addWidget(self.form_state, 0, Qt.AlignVCenter)
        form.add_layout(buttons)
        self.form_result = WrapLabel("")
        self.form_result.setObjectName("body")
        self.form_result.hide()
        form.add(self.form_result)
        return form

    @staticmethod
    def _datetime_edit(value: dt.datetime) -> QDateTimeEdit:
        edit = QDateTimeEdit(_qdt(value))
        edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        edit.setCalendarPopup(True)
        return edit

    def _load_products(self) -> None:
        cfg = settings.load()
        seen = [s for s in cfg.parking_products.splitlines() if s.strip()]
        self.product_box.clear()
        self.product_box.addItem(AUTO_PRODUCT, "")
        for label in seen:
            self.product_box.addItem(label, parking_link.product_name(label))
        index = self.product_box.findData(cfg.parking_product) if cfg.parking_product else -1
        self.product_box.setCurrentIndex(max(index, 0))

    def _request(self) -> parking_link.LinkRequest:
        return parking_link.LinkRequest(
            name=self.name_edit.text().strip(), start=_py(self.start_edit.dateTime()), end=_py(self.end_edit.dateTime()),
            product=str(self.product_box.currentData() or ""), active=self.active_check.isChecked(),
            show_restart=self.restart_check.isChecked())

    def _register(self) -> None:
        if self._busy:
            return
        request = self._request()
        problems = request.problems()
        if problems:
            self.form_state.set_status("확인", "warning")
            self.form_result.setText("\n".join(problems))
            self.form_result.show()
            return
        self._mine = "link"
        self.form_state.set_status("넣는 중", "info")
        self.form_result.setText("주차 사이트를 열고 [새 링크] 창에 넣는 중입니다…")
        self.form_result.show()
        self.worker.register_parking(request)

    def _show_links(self) -> None:
        if self._busy:
            return
        self._mine = "open"
        self.state.set_status("여는 중", "info")
        self.worker.open_parking(parking_link.LINKS_PATH)

    def _on_registered(self, report) -> None:
        self._mine = ""
        self._site_open = True
        if report.products:
            settings.update(parking_products="\n".join(report.products))
            chosen = str(self.product_box.currentData() or "")
            self._load_products()
            if chosen:
                self.product_box.setCurrentIndex(max(self.product_box.findData(chosen), 0))
        if report.ok:
            settings.update(parking_product=str(self.product_box.currentData() or ""))
            self.form_state.set_status("등록됨", "success")
            self.form_result.setText("\n".join(report.lines()) + "\nQR 은 브라우저의 '할인 링크' 목록에서 그 줄의 [QR 보기] 로 봅니다.")
            self.name_edit.clear()
        else:
            self.form_state.set_status("못 함", "danger")
            self.form_result.setText("\n".join(report.lines()))
        self.form_result.show()
        self._sync()

    # ── ② 할인 적용 (차량번호) ─────────────────────────────────────────
    def _build_apply_card(self) -> QWidget:
        card = Card("할인 적용 — 차량번호로 바로 등록", "주차장에 들어온 차에 바로 할인을 줍니다(사이트 '할인 적용' 화면).", art="register")
        self.car_edit = QLineEdit()
        self.car_edit.setPlaceholderText("예: 12가3456")
        self.car_edit.returnPressed.connect(self._apply)
        card.add(Field("차량번호", self.car_edit, "앱이 '할인 적용' 화면을 열고 차량번호 칸에 넣어 둡니다. 비워 두면 화면만 엽니다."))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.apply_button = QPushButton("할인 적용 화면에 넣기")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self._apply)
        row.addWidget(self.apply_button)
        row.addStretch(1)
        self.apply_state = Pill("준비", "neutral")
        row.addWidget(self.apply_state, 0, Qt.AlignVCenter)
        card.add_layout(row)
        self.apply_result = WrapLabel("")
        self.apply_result.setObjectName("body")
        self.apply_result.hide()
        card.add(self.apply_result)
        note = WrapLabel("지금은 [조회] · [적용] 을 브라우저에서 직접 누릅니다 — 이 화면은 아직 실측 전입니다. 차량번호를 넣고 [조회] 한 화면과 "
                         "[적용] 한 뒤 화면을 '화면 구조 저장' 업무(주차등록 사이트)로 저장해 보내 주시면 앱이 끝까지 하게 고칩니다.")
        note.setObjectName("muted")
        card.add(note)
        return card

    def _apply(self) -> None:
        if self._busy:
            return
        self._mine = "apply"
        self.apply_state.set_status("여는 중", "info")
        self.apply_result.setText("주차 사이트의 할인 적용 화면을 여는 중입니다…")
        self.apply_result.show()
        self.worker.apply_parking(self.car_edit.text())

    def _on_applied(self, report) -> None:
        self._mine = ""
        self._site_open = self._site_open or report.opened
        if report.filled:
            self.apply_state.set_status("넣음", "success")
        elif report.opened:
            self.apply_state.set_status("열림", "info" if not self.car_edit.text().strip() else "warning")
        else:
            self.apply_state.set_status("못 함", "danger")
        self.apply_result.setText("\n".join(report.lines()))
        self.apply_result.show()
        self._sync()

    # ── ③ 할인 내역 (읽기만) ───────────────────────────────────────────
    def _build_history_card(self) -> QWidget:
        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(0, 12, 0, 0)
        card = Card("할인 내역", "사이트 '운영 → 할인 내역' 이 처음 보여 주는 쪽을 읽어 옵니다(읽기만). 앱에는 남기지 않습니다.",
                    art="overview", margins=(20, 16, 20, 14))
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.history_button = QPushButton("불러오기")
        self.history_button.setObjectName("primary")
        self.history_button.clicked.connect(self._read_history)
        bar.addWidget(self.history_button)
        self.history_filter = QLineEdit()
        self.history_filter.setPlaceholderText("찾기 — 차량번호 · 상품 등")
        self.history_filter.setClearButtonEnabled(True)
        self.history_filter.textChanged.connect(self._filter_history)
        bar.addWidget(self.history_filter, 1)
        self.history_state = Pill("안 읽음", "neutral")
        bar.addWidget(self.history_state, 0, Qt.AlignVCenter)
        card.add_layout(bar)
        self.history_info = muted_label("")
        self.history_info.setWordWrap(True)
        card.add(self.history_info)

        self.history_stack = QStackedWidget()
        self.history_empty = EmptyState("overview", "아직 불러오지 않았습니다",
                                        "[불러오기] 를 누르면 앱 브라우저에서 할인 내역 화면을 열고 표를 읽어 옵니다.")
        self.history_stack.addWidget(self.history_empty)
        self.history_table = QTableWidget(0, 0)
        table = self.history_table
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(32)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        head = table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setStretchLastSection(True)
        head.setHighlightSections(False)
        head.setSectionResizeMode(QHeaderView.Interactive)
        self.history_stack.addWidget(table)
        card.add(self.history_stack, 1)
        outer.addWidget(card, 1)
        return holder

    def _read_history(self) -> None:
        if self._busy:
            return
        self._mine = "history"
        self.history_state.set_status("읽는 중", "info")
        self.history_info.setText("주차 사이트의 할인 내역 화면을 여는 중입니다…")
        self.worker.read_parking_history()

    def _on_history(self, report) -> None:
        self._mine = ""
        if not report.ok:
            self.history_state.set_status("못 읽음", "danger")
            self.history_info.setText("\n".join(report.lines()))
            self._sync()
            return
        self._site_open = True
        rows = report.rows
        width = max([len(report.headers)] + [len(r) for r in rows] + [1])
        headers = list(report.headers) + [f"칸 {i + 1}" for i in range(len(report.headers), width)]
        self._history_rows = rows
        table = self.history_table
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
        for c in range(width):
            table.setColumnWidth(c, min(max(table.columnWidth(c), 64), 260))
        self.history_stack.setCurrentIndex(1 if rows else 0)
        if not rows:
            self.history_empty.set_content("overview", "할인 내역이 없습니다",
                                           report.empty_note or "사이트가 처음 보여 주는 쪽에 줄이 없습니다 — 다른 기간은 브라우저에서 봅니다.")
        self.history_state.set_status("0줄", "neutral")
        info = [f"{report.read_at} 에 읽음" + (f" · 사이트 {report.total}" if report.total else "")]
        if report.pager:
            info.append("사이트가 처음 보여 주는 쪽만 읽었습니다 — 다른 쪽 · 다른 기간은 브라우저 화면에서 봅니다.")
        self.history_info.setText(" · ".join(info))
        self._filter_history(self.history_filter.text())
        self._sync()

    def _filter_history(self, text: str) -> None:
        word = _squash(text)
        shown = 0
        for r, cells in enumerate(self._history_rows):
            hide = bool(word) and not any(word in _squash(c) for c in cells)
            self.history_table.setRowHidden(r, hide)
            shown += not hide
        total = len(self._history_rows)
        if total:
            self.history_state.set_status(f"{shown}/{total}줄" if word else f"{total}줄", "success")

    # ── 브라우저 · 공통 ─────────────────────────────────────────────────
    def _open(self) -> None:
        if self._busy:
            return
        self._mine = "open"
        self.state.set_status("여는 중", "info")
        self.worker.open_parking()

    def _on_opened(self, report) -> None:
        self._mine = ""
        self._site_open = bool(report.opened)
        self.result.setText("\n".join(report.lines()))
        self.result.show()
        if not report.opened:
            self.state.set_status("열지 못함", "danger")
        elif report.logged_in:
            self.state.set_status("로그인됨", "success")
        elif report.tried_login:
            self.state.set_status("직접 로그인", "warning")
        else:
            self.state.set_status("열림", "info")
        self._sync()

    def _on_failed(self, owner: str, message: str) -> None:
        if owner != "parking":
            return
        mine, self._mine = self._mine, ""
        if mine == "link":
            self.form_state.set_status("오류", "danger")
            self.form_result.setText(message)
            self.form_result.show()
        elif mine == "apply":
            self.apply_state.set_status("오류", "danger")
            self.apply_result.setText(message)
            self.apply_result.show()
        elif mine == "history":
            self.history_state.set_status("오류", "danger")
            self.history_info.setText(message)
        else:
            self.state.set_status("오류", "danger")
            self.result.setText(message)
            self.result.show()

    def _on_browser_state(self, alive: bool) -> None:
        if not alive and self._site_open:
            self._site_open = False
            self.state.set_status("닫힘", "neutral")
        self._sync()

    def _on_busy(self, busy: bool, _message: str) -> None:
        self._busy = busy
        self._sync()

    def _sync(self) -> None:
        for button in (self.open_button, self.register_button, self.links_button, self.apply_button, self.history_button):
            button.setEnabled(not self._busy)
