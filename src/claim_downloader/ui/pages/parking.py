"""주차등록 화면 — 교내 주차 사이트(traffic.kangwon.ac.kr)의 할인 링크. 담당자 요청 2026-10-21.

기본은 '앱에서 입력해 등록' — 앱 칸에 넣고 [등록] 을 누르면 앱이 사이트의 [새 링크] 창에 넣고 그 창의 [저장] 까지 누른다
(담당자 허락 2026-10-21: "어플에서 등록 누르면 사이트에도 눌리는걸로", 실측은 CLAUDE.md 20절 · parking_link.py).
[브라우저에서 직접 입력] 은 앱 브라우저(ERP 와 같은 창)에 사이트를 열고 로그인 정보가 있으면 한 번 자동 로그인한다(parking.py).
로그인 정보는 설정 화면에서 넣는다(담당자 요청 같은 날 — ui/parking_login.py).
"""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import parking, parking_link, settings
from ..art import Art
from ..report_dialog import show_structure_saved
from ..widgets import Card, Field, Pill, WrapLabel, muted_label
from ..worker import SessionWorker

AUTO_PRODUCT = "사이트에 하나뿐이면 그것"


def _qdt(value: dt.datetime) -> QDateTime:
    return QDateTime(value.year, value.month, value.day, value.hour, value.minute, 0)


def _py(value: QDateTime) -> dt.datetime:
    d, t = value.date(), value.time()
    return dt.datetime(d.year(), d.month(), d.day(), t.hour(), t.minute())


class ParkingPage(QWidget):
    need_settings = Signal()            # [설정에서 로그인 정보 넣기]

    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.worker = worker if worker is not None else SessionWorker()
        self._busy = False
        self._mine = False                    # 지금 도는 일이 이 화면이 넣은 것인지 — 받기 · 일반청구도 같은 스레드를 쓴다
        self._capture_asked = False
        self._site_open = False               # 이 화면에서 사이트를 연 뒤에만 [화면 구조 저장] — 닫힌 브라우저를 읽으면 빈 파일이 된다

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("pageBody")
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 18, 24, 32)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("parking", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("주차등록")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        texts.addWidget(muted_label("교내 주차 사이트(traffic.kangwon.ac.kr)에 할인 링크를 만듭니다. 앱이 로그인하고 [새 링크] 창에 넣은 뒤 [저장] 까지 누릅니다."))
        head.addLayout(texts, 1)
        layout.addLayout(head)

        # 1) 앱에서 입력해 등록 — 기본 방식(담당자 2026-10-21)
        form = Card("앱에서 입력해 등록", "[등록] 을 누르면 사이트의 [새 링크] 창에 넣고 [저장] 까지 누릅니다. 만든 링크는 사이트 '할인 링크' 목록에 생깁니다.",
                    art="register")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 10/23 외부 자문위원 방문")
        self.name_edit.returnPressed.connect(self._register)
        form.add(Field("링크 이름", self.name_edit, "같은 이름이 목록에 있으면 넣지 않습니다."))
        self.product_box = QComboBox()
        form.add(Field("할인권 상품", self.product_box, "보기는 사이트에서 읽어 옵니다(한 번 [등록] 하면 채워집니다). 괄호 안은 남은 수."))
        dates = QHBoxLayout()
        dates.setSpacing(8)
        now = dt.datetime.now().replace(second=0, microsecond=0)
        self.start_edit = self._datetime_edit(now)
        self.end_edit = self._datetime_edit(now.replace(hour=23, minute=59))
        dates.addWidget(self.start_edit, 1)
        dates.addWidget(QLabel("~"))
        dates.addWidget(self.end_edit, 1)
        holder = QWidget()
        holder.setLayout(dates)
        dates.setContentsMargins(0, 0, 0, 0)
        form.add(Field("유효기간", holder, "기본은 지금부터 오늘 23:59 까지."))
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
        buttons.addStretch(1)
        self.form_state = Pill("준비", "neutral")
        buttons.addWidget(self.form_state, 0, Qt.AlignVCenter)
        form.add_layout(buttons)
        self.form_result = WrapLabel("")
        self.form_result.setObjectName("body")
        self.form_result.hide()
        form.add(self.form_result)
        layout.addWidget(form)

        # 2) 브라우저에서 직접 입력
        direct = Card("브라우저에서 직접 입력", "앱 브라우저(ERP 와 같은 창)에 사이트를 열고, 로그인 정보가 있으면 자동으로 로그인합니다",
                      art="login")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.open_button = QPushButton("브라우저에서 직접 입력")
        self.open_button.clicked.connect(self._open)
        row.addWidget(self.open_button)
        self.structure_button = QPushButton("화면 구조 저장")
        self.structure_button.setToolTip("지금 열린 화면의 칸 · 단추를 읽기만 해서 _화면구조.txt 로 남깁니다(사이트 모양이 바뀌었을 때 보내 주세요)")
        self.structure_button.clicked.connect(self._capture)
        row.addWidget(self.structure_button)
        row.addStretch(1)
        self.state = Pill("준비", "neutral")
        row.addWidget(self.state, 0, Qt.AlignVCenter)
        direct.add_layout(row)
        self.result = WrapLabel("")
        self.result.setObjectName("body")
        self.result.hide()
        direct.add(self.result)
        layout.addWidget(direct)

        # 3) 로그인 정보 — 설정에서 넣는다(담당자 요청 2026-10-21)
        account = Card("로그인 정보", "", art="settings")
        line = QHBoxLayout()
        line.setSpacing(8)
        self.account_label = muted_label("")
        line.addWidget(self.account_label, 1, Qt.AlignVCenter)
        to_settings = QPushButton("설정에서 넣기")
        to_settings.setObjectName("ghost")
        to_settings.clicked.connect(self.need_settings.emit)
        line.addWidget(to_settings)
        account.add_layout(line)
        layout.addWidget(account)
        layout.addStretch(1)

        w = self.worker
        w.parking_opened.connect(self._on_opened)
        w.parking_registered.connect(self._on_registered)
        w.busy.connect(self._on_busy)
        w.failed.connect(self._on_failed)
        w.structure_saved.connect(self._on_structure_saved)
        w.browser_state.connect(self._on_browser_state)
        self._load_products()
        self.refresh_account()
        self._sync()

    @staticmethod
    def _datetime_edit(value: dt.datetime) -> QDateTimeEdit:
        edit = QDateTimeEdit(_qdt(value))
        edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        edit.setCalendarPopup(True)
        return edit

    # ── 보기 · 로그인 정보 ─────────────────────────────────────────────
    def _load_products(self) -> None:
        cfg = settings.load()
        seen = [s for s in cfg.parking_products.splitlines() if s.strip()]
        self.product_box.clear()
        self.product_box.addItem(AUTO_PRODUCT, "")
        for label in seen:
            self.product_box.addItem(label, parking_link.product_name(label))
        index = self.product_box.findData(cfg.parking_product) if cfg.parking_product else -1
        self.product_box.setCurrentIndex(max(index, 0))

    def refresh_account(self) -> None:
        """설정에서 로그인 정보를 바꾸면 앱이 부른다(app.py) — 이 화면은 보여 주기만 한다."""
        user = parking.saved_user()
        self.account_label.setText(f"저장된 아이디: {user} · 설정 → '주차등록 로그인 정보' 에서 바꿉니다" if user
                                   else "저장된 로그인 정보가 없습니다 — 설정 → '주차등록 로그인 정보' 에 넣으면 앱이 로그인합니다")

    # ── 등록 ────────────────────────────────────────────────────────────
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
        self._mine = True
        self.form_state.set_status("넣는 중", "info")
        self.form_result.setText("주차 사이트를 열고 [새 링크] 창에 넣는 중입니다…")
        self.form_result.show()
        self.worker.register_parking(request)

    def _on_registered(self, report) -> None:
        self._mine = False
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
            self.form_result.setText("\n".join(report.lines()) + "\nQR 은 브라우저의 '할인 링크' 목록에서 [QR 보기] 로 봅니다.")
            self.name_edit.clear()
        else:
            self.form_state.set_status("못 함", "danger")
            self.form_result.setText("\n".join(report.lines()))
        self.form_result.show()
        self._sync()

    # ── 사이트 열기 ─────────────────────────────────────────────────────
    def _open(self) -> None:
        self.state.set_status("여는 중", "info")
        self.worker.open_parking()

    def _capture(self) -> None:
        self._capture_asked = True                       # 다른 화면도 같은 신호를 받는다 — 누른 쪽만 창을 띄운다
        self.worker.capture_structure(owner="parking")

    def _on_opened(self, report) -> None:
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

    def _on_structure_saved(self, path: str) -> None:
        if not self._capture_asked:
            return
        self._capture_asked = False
        show_structure_saved(self, path)

    def _on_failed(self, owner: str, message: str) -> None:
        if owner != "parking":
            return
        self._capture_asked = False
        if self._mine:
            self._mine = False
            self.form_state.set_status("오류", "danger")
            self.form_result.setText(message)
            self.form_result.show()
            return
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
        self.open_button.setEnabled(not self._busy)
        self.register_button.setEnabled(not self._busy)
        self.structure_button.setEnabled(not self._busy and self._site_open)
