"""화면 구조 저장 — 새 화면을 자동화하기 전에 실측하는 진단 모드(diagnose.py, 4절)를 한 업무로 모은 화면. 담당자 요청 2026-10-21.

전에는 청구서 받기 · 일반청구 · 주차등록 화면마다 [화면 구조 저장] 단추가 따로 있었다. 담당자: "각각 업무마다 펴져있는 화면 구조 저장을 하나의
업무카드로 만들어서 거기서 진행" · "옵션을 선택해서 브라우저를 열고 화면 구조 저장" · "다른 업무카드에서 해당 사이트를 이미 열고 작업 중이라면
로그아웃이나 재로그인 없이 바로" · "다른 곳에 있는 화면 구조 저장 버튼 및 기능 삭제".

- 사이트는 둘 — ERP · 주차등록 사이트. 고른 사이트의 창(팝업 포함)만 읽는다(session.capture_structure(site)).
- 브라우저는 다른 업무와 같은 것(브라우저 스레드 하나)이다. 고른 사이트가 이미 열려 있으면 [열린 창 앞으로] 는 그 창을 앞으로 가져오기만 하고
  다시 불러오지 않는다 — 로그인과 띄워 둔 화면이 그대로다. 열려 있는지는 브라우저 스레드가 2초마다 알린다(worker.sites).
- 장학금 노란 띠 · 재로그인 띠에서 기다리는 중에도 바로 읽힌다(worker._wait_resume) — 그때 열어 둔 팝업을 실측한다.
- 읽기만 한다 — 누르거나 값을 넣지 않는다(tests/test_safety.py 의 diagnose 검사).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ... import settings
from ..art import Art
from ..report_dialog import show_structure_saved
from ..widgets import Card, Pill, WrapLabel, muted_label
from ..worker import SessionWorker

SITES = (
    ("erp", "ERP", "산학협력단 연구비 시스템 — 청구서 받기 · 일반청구가 쓰는 곳", "claim"),
    ("parking", "주차등록 사이트", "교내 주차 사이트 — 주차등록 업무가 쓰는 곳", "parking"),
)
NAMES = {site: name for site, name, _desc, _art in SITES}


class SiteOption(QFrame):
    """고를 수 있는 사이트 카드 — 그림 · 이름 · 설명 · 열림 상태. 누르거나 Space/Enter 로 고른다."""

    chosen = Signal(str)

    def __init__(self, site: str, name: str, description: str, art: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.site = site
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(name)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)
        row.addWidget(Art(art, 46), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = QLabel(name)
        title.setObjectName("cardTitle")
        texts.addWidget(title)
        texts.addWidget(muted_label(description))
        row.addLayout(texts, 1)
        self.state = Pill("닫힘", "neutral")
        row.addWidget(self.state, 0, Qt.AlignVCenter)

    def set_selected(self, on: bool) -> None:
        self.setObjectName("cardCurrent" if on else "card")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.chosen.emit(self.site)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.chosen.emit(self.site)
            return
        super().keyPressEvent(event)


class StructurePage(QWidget):
    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.worker = worker if worker is not None else SessionWorker()
        self._site = "erp"
        self._busy = False
        self._asked = False            # 이 화면이 넣은 저장 · 열기만 창을 띄운다(다른 업무도 같은 신호를 받을 수 있다)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 30)          # 아래 26px 이상 — 접힌 독이 마지막 줄을 가리지 않게
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("structure", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("화면 구조 저장")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        texts.addWidget(muted_label("ERP · 주차등록 사이트에 띄운 화면의 창 · 칸 · 단추를 읽기만 해서 파일로 남깁니다. "
                                    "새 화면을 자동화하기 전에 이 파일을 보내 주세요."))
        head.addLayout(texts, 1)
        self.state = Pill("준비", "neutral")
        head.addWidget(self.state, 0, Qt.AlignVCenter)
        layout.addLayout(head)

        # ① 사이트 고르기
        pick = Card("① 어느 사이트의 화면인가요?", "고른 사이트의 창(팝업 포함)만 읽습니다.")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.options: dict[str, SiteOption] = {}
        for site, name, description, art in SITES:
            option = SiteOption(site, name, description, art)
            option.chosen.connect(self._choose)
            self.options[site] = option
            row.addWidget(option, 1)
        pick.add_layout(row)
        layout.addWidget(pick)

        # ② 화면 띄우고 ③ 저장
        work = Card("② 실측할 화면을 띄우고 ③ 저장하세요",
                    "이미 다른 업무에서 열어 둔 창이면 그대로 씁니다 — 로그아웃하거나 다시 로그인하지 않아도 됩니다.")
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.open_button = QPushButton("ERP 열기")
        self.open_button.clicked.connect(self._open)
        buttons.addWidget(self.open_button)
        self.save_button = QPushButton("화면 구조 저장")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)
        work.add_layout(buttons)
        self.guide = WrapLabel("")
        self.guide.setObjectName("body")
        work.add(self.guide)
        work.add(muted_label("읽기만 합니다 — 누르거나 값을 넣지 않고, 비밀번호 칸의 값은 적지 않습니다. 계좌번호 같은 값이 섞일 수 있으니 "
                             "작성 화면은 빈 채로 저장하세요. 장학금 노란 띠에서 기다리는 중에도 됩니다(그때 열어 둔 팝업까지)."))
        layout.addWidget(work)

        # 저장한 파일
        files = Card("저장한 파일", "화면 여러 개를 차례로 저장했으면 모음 파일 하나만 보내 주세요.")
        self.last = muted_label("아직 저장하지 않았습니다.")
        files.add(self.last)
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        for text, path in (("마지막 화면 열기", settings.structure_path), ("모음 파일 열기", settings.structure_book_path),
                           ("폴더 열기", settings.data_dir)):
            button = QPushButton(text)
            button.setObjectName("ghost")
            button.clicked.connect(lambda _c=False, path=path: self._open_file(path()))
            file_row.addWidget(button)
        file_row.addStretch(1)
        files.add_layout(file_row)
        layout.addWidget(files)
        layout.addStretch(1)

        w = self.worker
        w.sites_changed.connect(lambda _sites: self._sync())
        w.site_opened.connect(self._on_opened)
        w.structure_saved.connect(self._on_saved)
        w.busy.connect(self._on_busy)
        w.failed.connect(self._on_failed)
        self._choose(self._site)

    # ── 고르기 · 상태 ──────────────────────────────────────────────────
    def _choose(self, site: str) -> None:
        self._site = site
        for key, option in self.options.items():
            option.set_selected(key == site)
        self._sync()

    def _open_now(self, site: str) -> bool:
        sites = self.worker.sites
        return bool(sites.get(site))

    def _sync(self) -> None:
        sites = self.worker.sites
        erp = self.options["erp"].state
        if not sites.get("erp"):
            erp.set_status("닫힘", "neutral")
        elif sites.get("erp_login"):
            erp.set_status("열림 · 로그인됨", "success")
        else:
            erp.set_status("열림 · 로그인 전", "warning")
        self.options["parking"].state.set_status(*(("열림", "success") if sites.get("parking") else ("닫힘", "neutral")))
        name = NAMES[self._site]
        opened = self._open_now(self._site)
        self.open_button.setText("열린 창 앞으로" if opened else f"{name} 열기")
        self.open_button.setToolTip("이미 열린 창을 앞으로 가져오기만 합니다 — 다시 불러오지 않아 로그인 · 띄운 화면이 그대로입니다"
                                    if opened else f"앱 브라우저에 {name} 를 엽니다(다른 업무와 같은 브라우저)")
        waiting = self.worker.waiting
        self.open_button.setEnabled(not self._busy)
        self.save_button.setEnabled(opened and (not self._busy or waiting))
        if self._busy and waiting:
            text = "다른 업무가 띠에서 사람을 기다리는 중입니다 — 지금 저장하면 바로 읽습니다(그때 열어 둔 팝업까지)."
        elif self._busy:
            text = "다른 업무가 브라우저를 쓰는 중입니다 — 그 일이 끝나면 저장할 수 있습니다."
        elif not opened:
            text = (f"{name} 가 열려 있지 않습니다. [{name} 열기] 로 열고"
                    + (" 로그인한 뒤" if self._site == "erp" else "") + " 실측할 화면을 띄우세요.")
        elif self._site == "erp" and not sites.get("erp_login"):
            text = "ERP 창이 열려 있습니다. 로그인하고 실측할 화면(팝업이면 팝업까지)을 띄운 뒤 [화면 구조 저장] 을 누르세요."
        else:
            text = (f"{name} 창이 열려 있습니다 — 다른 업무에서 연 창이어도 그대로 저장합니다. "
                    "실측할 화면(팝업이면 팝업까지)을 띄운 뒤 [화면 구조 저장] 을 누르세요.")
        self.guide.setText(text)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync()

    # ── 열기 · 저장 ───────────────────────────────────────────────────
    def _open(self) -> None:
        self._asked = True
        self.state.set_status("여는 중", "info")
        self.worker.open_site(self._site)

    def _save(self) -> None:
        self._asked = True
        self.state.set_status("읽는 중", "info")
        self.worker.capture_structure(owner="structure", site=self._site)

    def _on_opened(self, _site: str, note: str) -> None:
        if not self._asked:
            return
        self._asked = False
        self.state.set_status("열림", "success")
        self.last.setText(note)
        self._sync()

    def _on_saved(self, path: str) -> None:
        if not self._asked:
            return
        self._asked = False
        self.state.set_status("저장함" if path else "못 함", "success" if path else "danger")
        if path:
            self.last.setText(f"{NAMES[self._site]} 화면을 저장했습니다 — {path}")
        show_structure_saved(self, path)

    def _on_busy(self, busy: bool, _message: str) -> None:
        self._busy = busy
        self._sync()

    def _on_failed(self, owner: str, message: str) -> None:
        if owner != "structure":
            return
        self._asked = False
        self.state.set_status("못 함", "danger")
        QMessageBox.warning(self, "화면 구조 저장", message)
        self._sync()

    @staticmethod
    def _open_file(path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
