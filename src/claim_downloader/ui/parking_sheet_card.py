"""설정 화면의 '구글 시트 연동' 칸 — 담당자 2026-10-22: "할인내역을 구글시트에 저장하고 그 구글시트를 연동해서 어플에서 관리대장을 확인".
같은 날 [로그 보내기] 도 이 시트의 '로그' 탭으로 보낸다("깃허브를 사용하지 않고 구글시트를 사용해서") — 같은 스크립트 · 같은 주소.

담당자가 할 일은 넷: 시트 만들기 → [스크립트 복사] 를 Apps Script 에 붙여 넣기 → 웹 앱으로 배포 → 그 주소를 여기에 붙여 넣고 [연결 확인].
주소 · 토큰은 이 PC 의 `_구글시트연동.json` 에만(parking_sheet.py).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QMessageBox, QPushButton

from .. import parking_sheet
from .sheet_sync import instance as sheet_sync
from .widgets import Card, Field, Pill, WrapLabel, muted_label

STEPS = ("1. 구글 드라이브에서 새 스프레드시트를 만듭니다(이름은 자유 — 예: 공무확인증 관리대장).\n"
         "2. 그 시트의 메뉴 확장 프로그램 → Apps Script 를 열고, 원래 있던 글을 모두 지운 뒤 아래 [스크립트 복사] 로 복사한 글을 붙여 넣고 저장합니다.\n"
         "3. 오른쪽 위 배포 → 새 배포 → 유형 선택(톱니) '웹 앱' → 실행 사용자 '나', 액세스 권한이 있는 사용자 '모든 사용자' → 배포 → 권한 허용.\n"
         "4. 나온 웹 앱 URL(https://script.google.com/…/exec)을 아래 칸에 붙여 넣고 [저장하고 연결 확인].\n"
         "이미 연결해 두었는데 스크립트를 새로 붙여 넣었으면: 배포 → 배포 관리 → (연필) 수정 → 버전 '새 버전' → 배포 (주소는 그대로).")


class ParkingSheetCard(Card):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__("구글 시트 연동 — 관리대장 · 로그 보내기 · 다운로드 현황",
                         "주차등록 사이트의 할인 내역을 구글 시트 '할인내역' 탭에 쌓고, 공무확인증 관리대장을 그 시트의 '관리대장' 탭과 "
                         "맞춥니다 — 시트에서 고친 것도 앱에 보입니다. 업무 화면의 [로그 보내기] 는 이 시트의 '로그' 탭으로, 증빙 다운로드의 "
                         "[다운로드 현황] 은 '다운로드 현황' 탭으로 씁니다. 시트는 담당자 구글 계정에 만듭니다.", art="overview")
        self.add(WrapLabel(STEPS))
        row = QHBoxLayout()
        row.setSpacing(8)
        copy = QPushButton("스크립트 복사")
        copy.setToolTip("시트의 Apps Script 에 붙여 넣을 글을 복사합니다 — 이 PC 만의 토큰이 들어 있습니다")
        copy.clicked.connect(self._copy)
        row.addWidget(copy)
        self.copied = muted_label("")
        row.addWidget(self.copied, 1, Qt.AlignVCenter)
        self.add_layout(row)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://script.google.com/macros/s/…/exec")
        self.add(Field("웹 앱 URL", self.url_edit, "배포할 때 나온 주소 — '/exec' 로 끝납니다."))
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.save_button = QPushButton("저장하고 연결 확인")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        self.open_button = QPushButton("시트 열기")
        self.open_button.setObjectName("ghost")
        self.open_button.clicked.connect(self._open_sheet)
        buttons.addWidget(self.open_button)
        # Claude 가 묻지 않고 로그를 읽는 고정 주소(열쇠 든 주소, id 없음 = 가장 최근) — 클라우드 환경 변수 COSS_LOG_URL 에 한 번 넣어 두면
        # 담당자는 [로그 보내기] 만 누르면 된다(담당자 2026-10-23: 보낼 때마다 채팅에 주소를 붙여 넣는 것이 전과 같은 불편). 주소에 열쇠가 있으니 채팅 · 문서에 두지 않는다
        self.log_url_button = QPushButton("로그 읽기 주소 복사")
        self.log_url_button.setObjectName("ghost")
        self.log_url_button.setToolTip("Claude 가 읽을 고정 주소(열쇠 포함)를 복사합니다 — 클라우드 환경 설정의 변수 COSS_LOG_URL 에 넣어 두면\n"
                                       "앞으로는 [로그 보내기] 만 누르고 채팅에 주소를 붙여 넣지 않아도 됩니다. 주소는 채팅 · 문서에 올리지 마세요.")
        self.log_url_button.clicked.connect(self._copy_log_url)
        buttons.addWidget(self.log_url_button)
        forget = QPushButton("연동 끊기")
        forget.setObjectName("ghost")
        forget.clicked.connect(self._forget)
        buttons.addWidget(forget)
        buttons.addStretch(1)
        self.state = Pill("연결 안 됨", "neutral")
        buttons.addWidget(self.state, 0, Qt.AlignVCenter)
        self.add_layout(buttons)
        self.note = muted_label("")
        self.note.setWordWrap(True)
        self.add(self.note)
        sheet_sync().checked.connect(self._on_checked)
        self.reload()

    def reload(self) -> None:
        config = parking_sheet.load_config()
        self.url_edit.setText(config.url)
        self.open_button.setVisible(bool(config.sheet_url))
        self.log_url_button.setVisible(bool(config.connected and config.log_key))
        if config.connected:
            self.state.set_status("연결됨" if config.sheet_url else "확인 전", "success" if config.sheet_url else "warning")
            self.note.setText(f"시트 '{config.sheet_name}'" if config.sheet_name else "[저장하고 연결 확인] 을 눌러 확인하세요.")
        else:
            self.state.set_status("연결 안 됨", "neutral")
            self.note.setText("")

    def _copy(self) -> None:
        text, _config = parking_sheet.script_text()
        QGuiApplication.clipboard().setText(text)
        self.copied.setText("복사했습니다 — Apps Script 에 붙여 넣고 저장하세요")

    def _save(self) -> None:
        url = self.url_edit.text().strip()
        if not parking_sheet.looks_like_web_app(url):
            QMessageBox.information(self, "관리대장 구글 시트", "웹 앱 URL 은 https://script.google.com/ 으로 시작하고 /exec 로 끝납니다.\n"
                                    "Apps Script 의 배포 → 배포 관리에서 '웹 앱' URL 을 복사해 넣어 주세요.")
            return
        _text, config = parking_sheet.script_text()      # 토큰이 없으면 만든다(스크립트를 아직 복사하지 않았으면 확인이 '토큰이 다름' 으로 알린다)
        if config.url != url:
            config.url, config.sheet_url, config.sheet_name = url, "", ""
            parking_sheet.save_config(config)
            # 다른 웹 앱(= 다른 시트)에 연결한다 — 지난 시트와 맞춘 기록을 잊어야 이 PC 의 관리대장이 새 시트에 올라간다(2026-10-23)
            parking_sheet.ledger.reset_sync()
        self.state.set_status("확인 중", "info")
        self.save_button.setEnabled(False)
        sheet_sync().check()

    def _on_checked(self, result) -> None:
        self.save_button.setEnabled(True)
        if result.ok:
            self.state.set_status("연결됨", "success")
            missing = [name for name, ok in (("[로그 보내기]", result.logs), ("[다운로드 현황]", result.status)) if not ok]
            self.note.setText(result.note + " — 주차등록 → 관리대장에서 시트와 맞춥니다."
                              + (" [로그 보내기] · [다운로드 현황] 도 됩니다." if not missing else
                                 f"\n스크립트가 옛 판이라 {' · '.join(missing)} 은 아직 안 됩니다 — [스크립트 복사] 로 새 글을 붙여 넣고 "
                                 "배포 → 배포 관리 → (연필) 수정 → 버전 '새 버전' → 배포."))
            self.open_button.show()
            sheet_sync().run_now()
        else:
            self.state.set_status("연결 안 됨", "danger")
            self.note.setText(result.note)
        self.changed.emit()

    def _copy_log_url(self) -> None:
        from ..log_send import read_url
        config = parking_sheet.load_config()
        if not (config.connected and config.log_key):
            return
        QGuiApplication.clipboard().setText(read_url(config))
        self.note.setText("로그 읽기 주소를 복사했습니다 — 클라우드 환경 설정(세션 제목 줄의 환경 메뉴 → Edit)의 변수 COSS_LOG_URL 에 붙여 넣으세요. "
                          "열쇠가 든 주소라 채팅 · 문서에는 올리지 마세요. 그 뒤로는 [로그 보내기] 만 누르면 Claude 가 읽습니다.")

    def _open_sheet(self) -> None:
        url = parking_sheet.load_config().sheet_url
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _forget(self) -> None:
        if QMessageBox.question(self, "연동 끊기", "이 PC 와 구글 시트의 연동을 끊을까요?\n시트와 이 PC 의 관리대장은 그대로 남습니다.",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        parking_sheet.forget()
        self.copied.setText("")
        self.reload()
        self.changed.emit()
