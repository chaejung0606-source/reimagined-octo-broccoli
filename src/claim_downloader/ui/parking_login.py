"""주차등록 사이트의 로그인 정보 칸 — 설정 화면에 둔다(담당자 요청 2026-10-21: "주차등록 로그인 정보는 설정에서 입력하고 저장하는걸로").

비밀번호를 다루는 화면 코드는 여기 하나다(tests/test_safety.py 의 PARKING_FILES). 넣은 값은 이 PC 의 사용자 폴더 `_주차로그인.json` 에만
두고 비밀번호는 윈도우 DPAPI 로 감싼다(parking.py). 저장된 비밀번호는 칸에 다시 보여 주지 않는다. ERP 로그인 정보는 어디에도 두지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QMessageBox, QPushButton

from .. import parking, settings
from .widgets import Card, Field, muted_label


class ParkingLoginCard(Card):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__("주차등록 로그인 정보", "주차 사이트(traffic.kangwon.ac.kr)에 앱이 로그인할 때 씁니다 — 할인 적용 · 링크 만들기 · "
                         "할인 내역은 브라우저 창 없이 이 정보로 합니다. 이 PC 에만 두고 비밀번호는 이 윈도우 사용자 계정으로만 풀리게 "
                         "암호화합니다. ERP 로그인 정보는 저장하지 않습니다.", art="login")
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("사이트 아이디")
        self.add(Field("아이디", self.user_edit))
        self.secret_edit = QLineEdit()
        self.secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.add(Field("비밀번호", self.secret_edit, "저장한 비밀번호는 다시 보여 주지 않습니다 — 바꿀 때만 넣으세요."))
        self.auto_check = QCheckBox("[브라우저에서 사이트 열기] 때도 자동 로그인 (실패하면 다시 시도하지 않고 직접 로그인하게 둡니다)")
        self.add(self.auto_check)
        row = QHBoxLayout()
        row.setSpacing(8)
        save = QPushButton("저장")
        save.clicked.connect(self._save)
        row.addWidget(save)
        forget = QPushButton("지우기")
        forget.clicked.connect(self._forget)
        row.addWidget(forget)
        row.addStretch(1)
        self.saved_label = muted_label("")
        row.addWidget(self.saved_label, 0, Qt.AlignVCenter)
        self.add_layout(row)
        self.reload()

    def reload(self) -> None:
        user = parking.saved_user()
        self.user_edit.setText(user)
        self.secret_edit.clear()
        self.secret_edit.setPlaceholderText("저장됨 — 바꿀 때만 입력" if user else "")
        self.auto_check.setChecked(bool(settings.load().parking_auto_login))
        self.saved_label.setText(f"저장된 아이디: {user}" if user else "저장된 로그인 정보 없음 — 열면 직접 로그인합니다")

    def _save(self) -> None:
        user, secret = self.user_edit.text().strip(), self.secret_edit.text()
        settings.update(parking_auto_login=self.auto_check.isChecked())
        if not secret and user and user == parking.saved_user():
            self.reload()                                 # 비밀번호는 그대로, 자동 로그인 체크만 바꿈
            self.changed.emit()
            return
        if not user or not secret:
            QMessageBox.information(self, "주차등록 로그인 정보", "아이디와 비밀번호를 모두 넣어 주세요.")
            return
        try:
            parking.save_login(user, secret)
        except OSError as error:
            QMessageBox.warning(self, "주차등록 로그인 정보", f"저장하지 못했습니다: {error}")
            return
        self.reload()
        self.changed.emit()

    def _forget(self) -> None:
        parking.forget_login()
        self.reload()
        self.changed.emit()
