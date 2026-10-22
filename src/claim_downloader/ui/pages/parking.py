"""주차등록 화면 — 교내 주차 사이트(traffic.kangwon.ac.kr). 담당자 요청 2026-10-21.

담당자가 정한 기능(같은 날): ① **할인 적용**: 차량번호로 바로 그 차에 할인을 준다 — 앱이 차량번호 → 보유 할인권 '공무확인증' → 할인 선택
'공무확인증' → [종료] 까지 한다(parking_screens.py, 담당자 "이런 과정이 어플내에서 이뤄질 수 있도록"). 적용되면 차량번호 칸을 비워
다음 차를 바로 넣게 한다. ② **할인 링크 · QR**: 정해 둔 기간 동안 쓸 수 있는 링크(사이트가 QR 도 만든다)를 앱 칸에 넣고 [등록] 하면
앱이 사이트의 [새 링크] 창에 넣고 [저장] 까지 누른다(parking_link.py). ③ **할인 내역 · 공무확인증 관리대장**(parking_ledger.py) — 누가 무엇에
썼는지 앱에 적고, 사이트 할인 내역(읽기만)과 맞춰 보고, 엑셀로 받는다.
할인 적용 · 링크가 되면 관리대장에 늘 적는다(배부 — 차량번호 · 링크 이름). 사용자 · 내용 칸은 이 화면에 두지 않는다(담당자 2026-10-22
"사용자랑 내용 넣는거는 삭제해주세요. 필요없어졌습니다") — 필요하면 관리대장 표 · 구글 시트에서 적는다.
①②③ 의 사이트 일은 **브라우저 창 없이** 한다(담당자 "브라우저 열기가 아니기 때문에" — session 의 보이지 않는 브라우저). 보이는 브라우저는
[브라우저에서 사이트 열기] · [목록 · QR 보기] 처럼 사람이 볼 때만. 로그인 정보는 이 화면에 두지 않는다 — 설정의 '주차등록 로그인 정보'.

할 차례인 단계만 위에서 아래로 떠오른다(ui/flow.py, 같은 날 담당자 — "클릭해야 하는 이동 순서대로 하나 둘 떠오르게"):
    ① 무엇을 할까요?(할인 적용 · 할인 링크 · 할인 내역) → ② 그 일의 칸 → ③ 결과
① 부터 고르게 연다 — 아무 일도 골라져 있지 않다(담당자 2026-10-22: "1단계부터 선택할 수 있도록". 전에는 할인 적용이 골라진 채 ② 가 열렸다).
고른 뒤에는 [바꾸기] 로 다른 일을 고른다. 할인 적용 카드는 여전히 맨 앞이다.
할인 내역은 ② 의 표가 곧 결과라 ③ 이 없다. 결과를 본 뒤 ② 의 칸을 고치면 ③ 은 접히고 다시 ② 차례다.
"""
from __future__ import annotations

import datetime as dt
import re

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import parking_ledger, parking_link, parking_screens, settings
from ..art import Art
from ..flow import CURRENT, ChoiceCard, FlowArea, FlowStep
from ..flowlogic import PARKING_ORDER, flow_states, parking_stage
from ..widgets import Field, Pill, WrapLabel, muted_label
from ..worker import SessionWorker
from .parking_ledger import LedgerPanel

AUTO_PRODUCT = "사이트에 하나뿐이면 그것"
APPLY, LINK, HISTORY = "apply", "link", "history"
# (일, 카드 이름, 한 줄 설명, 그림, ② 의 제목) — 할인 적용이 맨 앞 · 처음 골라진 일(담당자 요청 2026-10-21)
JOBS = (
    (APPLY, "할인 적용 (차량번호)", "들어온 차에 바로 할인을 줍니다", "register", "차량번호를 넣으세요"),
    (LINK, "할인 링크 · QR 만들기", "정한 기간 동안 쓰는 할인 링크 — 사이트가 QR 도 만듭니다", "upload", "링크 내용을 넣고 [등록] 하세요"),
    (HISTORY, "관리대장", "공무확인증을 누가 무엇에 썼는지 — 사이트 할인 내역으로 채우고 엑셀로 받기", "overview",
     "공무확인증 관리대장"),
)
NAMES = {key: name for key, name, _d, _a, _t in JOBS}
TITLES = {key: title for key, _n, _d, _a, title in JOBS}


def _qdt(value: dt.datetime) -> QDateTime:
    return QDateTime(value.year, value.month, value.day, value.hour, value.minute, 0)


def _py(value: QDateTime) -> dt.datetime:
    d, t = value.date(), value.time()
    return dt.datetime(d.year(), d.month(), d.day(), t.hour(), t.minute())


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _holder() -> tuple[QWidget, QVBoxLayout]:
    """② 안의 일 하나 — 고른 일의 것만 보인다."""
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    return holder, layout


class ParkingPage(QWidget):
    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.worker = worker if worker is not None else SessionWorker()
        self._busy = False
        self._mine = ""                       # 지금 도는 일 — 'link' · 'apply' · 'history' · 'open'. 받기 · 일반청구도 같은 스레드를 쓴다
        self._site_open = False               # 이 화면에서 사이트를 열었는지 — 브라우저가 닫히면 상태를 '닫힘' 으로
        self._applying = ""                   # 지금 적용하는 차량번호 — 결과가 오면 관리대장에(늘 — 담당자 2026-10-22 "필수")
        self._done_cars: list[str] = []      # 이번에 적용한 차(앱 화면에만 — 차량번호는 기록에 남기지 않는다)
        self._pending_link = None             # [등록] 한 링크와 관리대장 칸 — 등록되면 대장에 적는다
        self._job = APPLY                     # ① 에서 고른 일 — 고르기 전에는 단계 제목 · 칸을 채울 기본값일 뿐
        self._picked = False                  # 처음엔 ① 부터(담당자 2026-10-22)
        self._chosen = False                  # 한 번이라도 골랐는지 — 고르기 전에는 ① 의 카드를 하나도 칠하지 않는다
        self._has_result = False              # ③ 결과가 떠 있는지(할인 적용 · 할인 링크)
        self._open_note = ""                  # [브라우저에서 사이트 열기] 결과 한 줄 — 지금 단계 아래에

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 30)          # 아래 26px 이상 — 접힌 독이 마지막 줄을 가리지 않게
        layout.setSpacing(12)
        layout.addLayout(self._build_head())
        self.step_what = self._build_what()
        self.step_work = self._build_work()
        self.step_result = self._build_result()
        self.steps = {"what": self.step_what, "work": self.step_work, "result": self.step_result}
        # 단계는 스크롤 칸 안에 — 창이 낮으면(1024×640) 칸을 눌러 겹치게 하지 않고 아래로 넘긴다(ui/flow.FlowArea)
        self.area = FlowArea()
        for step in self.steps.values():
            self.area.add(step)
        layout.addWidget(self.area, 1)

        w = self.worker
        w.parking_opened.connect(self._on_opened)
        w.parking_registered.connect(self._on_registered)
        w.parking_applied.connect(self._on_applied)
        w.parking_history.connect(self.ledger.show_site)
        w.busy.connect(self._on_busy)
        w.failed.connect(self._on_failed)
        w.browser_state.connect(self._on_browser_state)
        self._load_products()
        self._sync()

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("parking", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("주차등록")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        texts.addWidget(muted_label("교내 주차 사이트(traffic.kangwon.ac.kr) — 차량번호로 할인 적용 · 할인 링크 · QR 만들기 · 할인 내역과 "
                                    "공무확인증 관리대장. 사이트 일은 브라우저 창 없이 앱이 합니다(로그인은 설정의 '주차등록 로그인 정보')."))
        head.addLayout(texts, 1)
        self.state = Pill("준비", "neutral")
        head.addWidget(self.state, 0, Qt.AlignVCenter)
        # 사이트에서 직접 입력하는 길 — 자주 쓰지 않으니 머리 오른쪽에 작게([화면 구조 저장] 은 '화면 구조 저장' 업무로 옮겼다)
        self.open_button = QPushButton("브라우저에서 사이트 열기")
        self.open_button.setObjectName("ghost")
        self.open_button.setToolTip("앱 브라우저(ERP 와 같은 창)에 사이트를 열고, 로그인 정보가 있으면 자동으로 로그인합니다 — 사이트를 직접 볼 때")
        self.open_button.clicked.connect(self._open)
        head.addWidget(self.open_button, 0, Qt.AlignVCenter)
        return head

    def _build_what(self) -> FlowStep:
        """① 무엇을 할까요 — 카드를 누르면 바로 ② 로."""
        step = FlowStep("1", "무엇을 할까요?")
        step.edit.connect(self._edit_job)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.options: dict[str, ChoiceCard] = {}
        for key, name, description, art, _title in JOBS:
            option = ChoiceCard(key, name, description, art)
            option.chosen.connect(self._choose)
            self.options[key] = option
            row.addWidget(option, 1)
        step.add_layout(row)
        return step

    def _build_work(self) -> FlowStep:
        """② 고른 일의 칸 — 셋 중 하나만 보인다(숨은 칸은 자리를 차지하지 않는다)."""
        step = FlowStep("2", TITLES[APPLY], editable=False)
        self.links_button = QPushButton("목록 · QR 보기 (브라우저)")
        self.links_button.setObjectName("ghost")
        self.links_button.setToolTip("브라우저에 사이트의 '할인 링크' 목록을 띄웁니다 — 링크마다 [QR 보기] 로 QR 을 봅니다")
        self.links_button.clicked.connect(self._show_links)
        step.add_side(self.links_button)
        self.work = {APPLY: self._build_apply(), LINK: self._build_link(), HISTORY: self._build_history()}
        for key, holder in self.work.items():
            step.add(holder, 1 if key == HISTORY else 0)
        return step

    def _build_result(self) -> FlowStep:
        """③ 결과 — 할인 적용 · 할인 링크. 할인 내역은 ② 의 표가 결과다."""
        step = FlowStep("3", "결과", editable=False)
        self.result_state = Pill("", "neutral")
        step.add_side(self.result_state)
        self.result = WrapLabel("")
        self.result.setObjectName("body")
        step.add(self.result)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.result_links_button = QPushButton("목록 · QR 보기 (브라우저)")
        self.result_links_button.setObjectName("primary")
        self.result_links_button.clicked.connect(self._show_links)
        row.addWidget(self.result_links_button)
        # 앱이 할인 적용을 끝내지 못했을 때 — 사이트에서 직접 하고, 했으면 관리대장에 적는다
        self.direct_button = QPushButton("브라우저에서 직접 하기")
        self.direct_button.setObjectName("ghost")
        self.direct_button.setToolTip("보이는 브라우저에 사이트의 '할인 적용' 화면을 엽니다")
        self.direct_button.clicked.connect(self._apply_in_browser)
        row.addWidget(self.direct_button)
        self.record_button = QPushButton("직접 적용했어요 · 관리대장에 적기")
        self.record_button.setObjectName("ghost")
        self.record_button.setToolTip("브라우저에서 직접 적용한 뒤 누르세요 — 공무확인증 관리대장에 배부 1 줄(차량번호)을 적습니다")
        self.record_button.clicked.connect(self._record_apply)
        row.addWidget(self.record_button)
        row.addStretch(1)
        step.add_layout(row)
        return step

    # ── ① 할인 적용 (차량번호) ─────────────────────────────────────────
    def _build_apply(self) -> QWidget:
        holder, layout = _holder()
        car_row = QHBoxLayout()
        car_row.setSpacing(8)
        self.car_edit = QLineEdit()
        self.car_edit.setPlaceholderText("예: 12가3456")
        self.car_edit.returnPressed.connect(self._apply)
        car_row.addWidget(self.car_edit, 1)
        self.apply_button = QPushButton("할인 적용")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self._apply)
        car_row.addWidget(self.apply_button)
        car_holder = QWidget()
        car_holder.setLayout(car_row)
        car_row.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(Field("차량번호", car_holder, "넣고 Enter — 적용되면 칸이 비워집니다. 다음 차는 번호만 넣으세요."))
        layout.addWidget(muted_label("앱이 브라우저 창 없이 사이트에 로그인해 차량번호 → 보유 할인권 '공무확인증' → 할인 선택 '공무확인증' → [종료] "
                                     "까지 하고, 적용되면 공무확인증 관리대장에 배부 1 줄(차량번호)을 적습니다. 화면이 생각과 다르면 "
                                     "[종료] 전에 멈추고 그 화면의 모양을 남깁니다(_화면구조_모음.txt — 보내 주시면 고칩니다)."))
        return holder

    def _apply(self) -> None:
        if self._busy:
            return
        car = parking_screens.car_number(self.car_edit.text())
        if not car:
            self._show_result("확인", "warning", "차량번호를 넣어 주세요.")
            self.car_edit.setFocus()
            return
        self._mine = APPLY
        self._applying = car
        self._show_result("적용 중", "info", f"{car} — 주차 사이트에서 할인을 적용하는 중입니다(창 없이)…")
        self.worker.apply_parking(car)

    def _on_applied(self, report) -> None:
        self._mine = ""
        car = self._applying
        if report.applied:
            line = f"✓ {dt.datetime.now():%H:%M} {car} — {report.ticket or '공무확인증'} 적용" + ("" if report.confirmed else "(사이트 완료 글은 못 봄)")
            entry = self.ledger.add_entry(parking_ledger.Entry(date=dt.date.today().isoformat(), given=1, car=car, source="apply"))
            line += f" · 관리대장 배부 1 · 잔여 {self.ledger.left_after(entry):,}"
            self._done_cars.insert(0, line)
            self._applying = ""
            if parking_screens.car_number(self.car_edit.text()) == car:
                self.car_edit.clear()             # 다음 차
            self.car_edit.setFocus()
            self._show_result("적용됨", "success", self._applied_text())
            return
        lines = [f"✗ {car} — " + (report.note or "할인을 적용하지 못했습니다")]
        if report.steps:
            lines.append("한 것: " + " → ".join(report.steps))
        if report.messages:
            lines.append("사이트 알림: " + " / ".join(report.messages))
        if report.pressed_finish:
            lines.append("[종료] 는 눌렀습니다 — '관리대장' 에서 사이트 할인 내역을 불러와 적용됐는지 보세요.")
        elif report.opened:
            lines.append("[종료] 는 누르지 않았습니다 — 할인은 적용되지 않았습니다. [브라우저에서 직접 하기] 로 사이트에서 할 수 있습니다.")
        if report.saved:
            lines.append(f"멈춘 화면의 모양을 {report.saved} 에 남겼습니다 — 그 파일을 보내 주시면 앱이 끝까지 하도록 고칩니다.")
        if self._done_cars:
            lines += ["", "이번에 적용한 차"] + self._done_cars[:8]
        self._show_result("못 함", "danger" if not report.pressed_finish else "warning", "\n".join(lines))
        self.record_button.setEnabled(bool(report.opened))
        self.record_button.setText("직접 적용했어요 · 관리대장에 적기")

    def _applied_text(self) -> str:
        head = self._done_cars[0] if self._done_cars else ""
        rest = self._done_cars[1:8]
        return head + ("\n\n이번에 적용한 차\n" + "\n".join(rest) if rest else "") + "\n다음 차는 위 칸에 번호만 넣고 Enter."

    def _apply_in_browser(self) -> None:
        if self._busy:
            return
        self._mine = "open"
        self.state.set_status("여는 중", "info")
        self.worker.open_parking(parking_screens.APPLY_PATH)

    # ── ② 할인 링크 · QR ────────────────────────────────────────────────
    def _build_link(self) -> QWidget:
        holder, layout = _holder()
        layout.addWidget(muted_label("[등록] 을 누르면 앱이 브라우저 창 없이 사이트의 [새 링크] 창에 넣고 [저장] 까지 누릅니다. "
                                     "QR 은 사이트가 링크마다 만듭니다 — [목록 · QR 보기] 로 브라우저에서 봅니다."))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 10/23 외부 자문위원 방문")
        self.name_edit.returnPressed.connect(self._register)
        self.name_edit.textEdited.connect(lambda _t: self._clear_result())
        layout.addWidget(Field("링크 이름", self.name_edit, "같은 이름이 목록에 있으면 넣지 않습니다."))
        self.product_box = QComboBox()
        layout.addWidget(Field("할인권 상품", self.product_box, "보기는 사이트에서 읽어 옵니다(한 번 [등록] 하면 채워집니다). 괄호 안은 남은 수."))
        dates = QHBoxLayout()
        dates.setSpacing(8)
        dates.setContentsMargins(0, 0, 0, 0)
        now = dt.datetime.now().replace(second=0, microsecond=0)
        self.start_edit = self._datetime_edit(now)
        self.end_edit = self._datetime_edit(now.replace(hour=23, minute=59))
        dates.addWidget(self.start_edit, 1)
        dates.addWidget(QLabel("~"))
        dates.addWidget(self.end_edit, 1)
        dates_holder = QWidget()
        dates_holder.setLayout(dates)
        layout.addWidget(Field("유효기간", dates_holder, "이 기간 동안 링크 · QR 로 할인을 받을 수 있습니다. 기본은 지금부터 오늘 23:59 까지."))
        checks = QHBoxLayout()
        checks.setSpacing(16)
        self.active_check = QCheckBox("활성")
        self.active_check.setChecked(True)
        checks.addWidget(self.active_check)
        self.restart_check = QCheckBox("완료 화면에 '처음으로' 버튼 표시")
        checks.addWidget(self.restart_check)
        checks.addStretch(1)
        layout.addLayout(checks)
        # 공무확인증 관리대장 — 이 링크로 나눠 줄 공무확인증 수(담당자 2026-10-21). 사용자 · 내용 칸은 걷어냈다(2026-10-22 "필요없어졌습니다")
        count_row = QHBoxLayout()
        self.link_count = QSpinBox()
        self.link_count.setRange(1, 9999)
        self.link_count.setValue(1)
        count_row.addWidget(Field("배부 수량", self.link_count, "링크로 쓸 공무확인증 수"))
        count_row.addStretch(1)
        layout.addLayout(count_row)
        layout.addWidget(muted_label("등록되면 공무확인증 관리대장에 배부 수량만큼 한 줄을 적습니다(링크 이름). 실제로 쓴 수가 다르면 "
                                     "'관리대장' 에서 고치세요."))
        row = QHBoxLayout()
        self.register_button = QPushButton("등록")
        self.register_button.setObjectName("primary")
        self.register_button.clicked.connect(self._register)
        row.addWidget(self.register_button)
        row.addStretch(1)
        layout.addLayout(row)
        return holder

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
            self._show_result("확인", "warning", "\n".join(problems))
            return
        self._mine = LINK
        self._pending_link = (request, self.link_count.value())
        self._show_result("넣는 중", "info", "주차 사이트(창 없이)의 [새 링크] 창에 넣는 중입니다…")
        self.worker.register_parking(request)

    def _show_links(self) -> None:
        if self._busy:
            return
        self._mine = "open"
        self.state.set_status("여는 중", "info")
        self.worker.open_parking(parking_link.LINKS_PATH)

    def _on_registered(self, report) -> None:
        self._mine = ""
        if report.products:
            settings.update(parking_products="\n".join(report.products))
            chosen = str(self.product_box.currentData() or "")
            self._load_products()
            if chosen:
                self.product_box.setCurrentIndex(max(self.product_box.findData(chosen), 0))
        pending, self._pending_link = self._pending_link, None
        if report.ok:
            settings.update(parking_product=str(self.product_box.currentData() or ""))
            self.name_edit.clear()
            recorded = self._record_link(pending)
            self._show_result("등록됨", "success", "\n".join(report.lines())
                              + "\nQR 은 [목록 · QR 보기] 로 연 브라우저의 '할인 링크' 목록에서 그 줄의 [QR 보기] 로 봅니다."
                              + (f"\n{recorded}" if recorded else ""))
        else:
            self._show_result("못 함", "danger", "\n".join(report.lines()))

    # ── ③ 할인 내역 · 공무확인증 관리대장 ───────────────────────────────
    def _build_history(self) -> QWidget:
        self.ledger = LedgerPanel()
        self.ledger.read_site.connect(self._read_history)
        return self.ledger

    def _read_history(self) -> None:
        if self._busy:
            return
        self._mine = HISTORY
        self.ledger.site_loading()
        self.worker.read_parking_history()

    def _record_apply(self) -> None:
        """앱이 할인 적용을 끝내지 못해 사람이 사이트에서 직접 적용한 뒤 누른다. 배부 1."""
        car = self._applying or parking_screens.car_number(self.car_edit.text())
        if not car:
            QMessageBox.information(self, "관리대장에 적기", "차량번호를 넣은 뒤 다시 눌러 주세요(관리대장에 꼭 적습니다).")
            return
        entry = self.ledger.add_entry(parking_ledger.Entry(date=dt.date.today().isoformat(), given=1, car=car, source="apply",
                                                           note="사이트에서 직접 적용"))
        self._applying = ""
        self._done_cars.insert(0, f"✓ {dt.datetime.now():%H:%M} {car} — 사이트에서 직접 적용 · 관리대장 배부 1 · 잔여 {self.ledger.left_after(entry):,}")
        if parking_screens.car_number(self.car_edit.text()) == car:
            self.car_edit.clear()
        self.car_edit.setFocus()
        self._show_result("적음", "success", self._applied_text())

    def _record_link(self, pending) -> str:
        """할인 링크가 등록되면 늘 — 담당자가 적은 배부 수량(필수, 2026-10-22). 한 줄 안내를 돌려준다."""
        if not pending:
            return ""
        request, count = pending
        product = request.product or ""
        entry = self.ledger.add_entry(parking_ledger.Entry(
            date=request.start.date().isoformat(), given=count,
            note=f"할인 링크 '{request.name}'" + (f" · {product}" if product else ""), source="link"))
        return f"관리대장에 적었습니다 — 배부 {count} · 잔여 {self.ledger.left_after(entry):,}."

    # ── 고르기 · 단계 ───────────────────────────────────────────────────
    def _choose(self, job: str) -> None:
        if self._busy:
            return
        if job != self._job:
            self._has_result = False
        self._job = job
        self._picked = self._chosen = True
        self._open_note = ""
        self._sync()
        focus = {APPLY: self.car_edit, LINK: self.name_edit}.get(job)
        if focus is not None:
            focus.setFocus()

    def _edit_job(self) -> None:
        if self._busy:
            return
        self._picked = False
        self._has_result = False
        self._sync()

    def _show_result(self, text: str, tone: str, lines: str) -> None:
        self.result_state.set_status(text, tone)
        self.result.setText(lines)
        self._has_result = True
        self._sync()
        # 칸이 길어(할인 링크) ③ 이 창 아래에 떠오르면 보이는 곳까지 내린다
        self.area.show_to(self.step_result)

    def _clear_result(self) -> None:
        """결과를 본 뒤 칸을 고치면 ③ 을 접고 다시 ② 차례 — 다음 차 · 다음 링크."""
        if self._has_result and not self._busy:
            self._has_result = False
            self._sync()

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
        self._open_note = "\n".join(report.lines())
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
        if mine in (APPLY, LINK):
            self._show_result("오류", "danger", message)
        elif mine == HISTORY:
            self.ledger.site_failed(message)
        else:
            self.state.set_status("오류", "danger")
            self._open_note = message
            self._sync()

    def _on_browser_state(self, alive: bool) -> None:
        if not alive and self._site_open:
            self._site_open = False
            self.state.set_status("닫힘", "neutral")
        self._sync()

    def _on_busy(self, busy: bool, _message: str) -> None:
        self._busy = busy
        self._sync()

    def _sync(self) -> None:
        job = self._job
        has_result = self._has_result and job != HISTORY
        stage = parking_stage(self._picked, has_result)
        states = flow_states(PARKING_ORDER, stage, keep_open=("work",))
        for key, option in self.options.items():
            option.set_selected(self._chosen and key == job)
            option.setEnabled(not self._busy)
        self.step_work.title.setText(TITLES[job])
        for key, holder in self.work.items():
            holder.setVisible(key == job)
        for key, step in self.steps.items():
            step.set_state(states[key], NAMES[job] if key == "what" else None)
            step.set_note(self._open_note if states[key] == CURRENT else "")
        # 단계가 제목 줄 오른쪽 것을 다시 보이게 하므로 그 뒤에 — 링크 일에만 쓰는 단추
        self.links_button.setVisible(job == LINK)
        self.result_links_button.setVisible(job == LINK and self.result_state.text() == "등록됨")
        failed_apply = job == APPLY and self._has_result and self.result_state.text() == "못 함"
        self.direct_button.setVisible(failed_apply)
        self.record_button.setVisible(failed_apply)
        self.ledger.set_busy(self._busy)
        # 할인 내역은 표가 남는 높이를 쓰고, 나머지는 단계가 위쪽에 모여 있게
        self.area.steps.setStretchFactor(self.step_work, 1 if job == HISTORY and self._picked else 0)
        self.area.filler.setVisible(not (job == HISTORY and self._picked))
        self.step_what.edit_button.setEnabled(not self._busy)
        for button in (self.open_button, self.register_button, self.links_button, self.apply_button, self.result_links_button,
                       self.direct_button, self.record_button):
            button.setEnabled(not self._busy)
