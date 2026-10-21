"""주차등록 화면 — 교내 주차 등록 사이트(traffic.kangwon.ac.kr). 담당자 요청 2026-10-21.

기본은 '앱에서 입력해 등록'(앱 칸에 넣으면 사이트에 들어간다) — 사이트의 등록 화면을 실측하기 전이라 준비 중으로 두고, 무엇을 실측해
보내면 되는지 적는다(동작하지 않는 입력 · 등록 단추는 만들지 않는다). 지금 되는 것은 [브라우저에서 직접 입력]: 앱 브라우저(ERP 와 같은
창)에 사이트를 열고, 로그인 정보가 있으면 한 번 자동 로그인한다(parking.py). 같은 화면의 [화면 구조 저장] 으로 실측을 남긴다.

로그인 정보는 이 화면에서 넣는다 — 이 PC 의 사용자 폴더에만 두고 비밀번호는 윈도우 DPAPI 로 감싼다. 칸에는 저장된 비밀번호를 다시
보여 주지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import parking, settings
from ..art import Art
from ..report_dialog import show_structure_saved
from ..widgets import Card, Field, Pill, WrapLabel, muted_label
from ..worker import SessionWorker

GUIDE_MEASURE = (
    "사이트의 등록 화면 구조를 받으면 여기에 입력 칸(차량번호 · 방문일 등)이 생기고, [등록] 을 누르면 앱이 사이트에 넣습니다.\n"
    "그 전에 한 번만 실측을 부탁드립니다:\n"
    "  1. 아래 [브라우저에서 직접 입력] 으로 사이트를 엽니다.\n"
    "  2. 주차 등록 입력 화면(칸이 보이는 화면)을 띄우고 [화면 구조 저장] 을 누릅니다 — 칸은 비워 둔 채로.\n"
    "  3. 등록을 마친 뒤 나오는 화면(등록 목록 · 완료 안내)에서도 한 번 누릅니다.\n"
    "  4. 사용자 폴더의 _화면구조_모음.txt 를 보내 주세요."
)


class ParkingPage(QWidget):
    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.worker = worker if worker is not None else SessionWorker()
        self._busy = False
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
        texts.addWidget(muted_label("교내 주차 등록 사이트(traffic.kangwon.ac.kr)에 앱이 로그인해 등록합니다."))
        head.addLayout(texts, 1)
        layout.addLayout(head)

        # 1) 앱에서 입력해 등록 — 기본 방식(담당자 2026-10-21). 실측 전이라 준비 중
        app_card = Card("앱에서 입력해 등록", "기본 방식 — 앱 칸에 넣으면 앱이 사이트에 입력합니다", art="register")
        app_card.add_header_widget(Pill("준비 중", "neutral"))
        app_card.add(WrapLabel(GUIDE_MEASURE))
        layout.addWidget(app_card)

        # 2) 브라우저에서 직접 입력
        direct = Card("브라우저에서 직접 입력", "앱 브라우저(ERP 와 같은 창)에 사이트를 열고, 로그인 정보가 있으면 자동으로 로그인합니다",
                      art="login")
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.open_button = QPushButton("브라우저에서 직접 입력")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self._open)
        buttons.addWidget(self.open_button)
        self.structure_button = QPushButton("화면 구조 저장")
        self.structure_button.setToolTip("지금 열린 화면의 칸 · 단추를 읽기만 해서 _화면구조.txt 로 남깁니다(앱 입력을 만들 때 씁니다)")
        self.structure_button.clicked.connect(self._capture)
        buttons.addWidget(self.structure_button)
        buttons.addStretch(1)
        self.state = Pill("준비", "neutral")
        buttons.addWidget(self.state, 0, Qt.AlignVCenter)
        direct.add_layout(buttons)
        self.result = WrapLabel("")
        self.result.setObjectName("body")
        self.result.hide()
        direct.add(self.result)
        layout.addWidget(direct)

        # 3) 로그인 정보 — 이 PC 에만
        account = Card("로그인 정보", "이 PC 에만 둡니다. 비밀번호는 이 윈도우 사용자 계정으로만 풀리게 암호화합니다. "
                       "ERP 로그인 정보는 저장하지 않습니다.", art="settings")
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("사이트 아이디")
        account.add(Field("아이디", self.user_edit))
        self.secret_edit = QLineEdit()
        self.secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        account.add(Field("비밀번호", self.secret_edit, "저장한 비밀번호는 다시 보여 주지 않습니다 — 바꿀 때만 넣으세요."))
        self.auto_check = QCheckBox("사이트를 열 때 자동 로그인 (실패하면 다시 시도하지 않고 직접 로그인하게 둡니다)")
        account.add(self.auto_check)
        row = QHBoxLayout()
        row.setSpacing(8)
        save = QPushButton("저장")
        save.clicked.connect(self._save_login)
        row.addWidget(save)
        forget = QPushButton("지우기")
        forget.clicked.connect(self._forget_login)
        row.addWidget(forget)
        row.addStretch(1)
        self.saved_label = muted_label("")
        row.addWidget(self.saved_label, 0, Qt.AlignVCenter)
        account.add_layout(row)
        layout.addWidget(account)
        layout.addStretch(1)

        w = self.worker
        w.parking_opened.connect(self._on_opened)
        w.busy.connect(self._on_busy)
        w.failed.connect(self._on_failed)
        w.structure_saved.connect(self._on_structure_saved)
        w.browser_state.connect(self._on_browser_state)
        self._load_account()
        self._sync()

    # ── 로그인 정보 ─────────────────────────────────────────────────────
    def _load_account(self) -> None:
        user = parking.saved_user()
        self.user_edit.setText(user)
        self.secret_edit.clear()
        self.secret_edit.setPlaceholderText("저장됨 — 바꿀 때만 입력" if user else "")
        self.auto_check.setChecked(bool(settings.load().parking_auto_login))
        self.saved_label.setText(f"저장된 아이디: {user}" if user else "저장된 로그인 정보 없음 — 열면 직접 로그인합니다")

    def _save_login(self) -> None:
        user, secret = self.user_edit.text().strip(), self.secret_edit.text()
        settings.update(parking_auto_login=self.auto_check.isChecked())
        if not secret and user and user == parking.saved_user():
            self._load_account()                          # 비밀번호는 그대로, 자동 로그인 체크만 바꿈
            return
        if not user or not secret:
            QMessageBox.information(self, "로그인 정보", "아이디와 비밀번호를 모두 넣어 주세요.")
            return
        try:
            parking.save_login(user, secret)
        except OSError as error:
            QMessageBox.warning(self, "로그인 정보", f"저장하지 못했습니다: {error}")
            return
        self._load_account()

    def _forget_login(self) -> None:
        parking.forget_login()
        self._load_account()

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
        self.structure_button.setEnabled(not self._busy and self._site_open)
