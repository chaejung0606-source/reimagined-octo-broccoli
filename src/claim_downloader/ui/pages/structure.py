"""화면 구조 저장 — 새 화면을 자동화하기 전에 실측하는 진단 모드(diagnose.py, 4절)를 한 업무로 모은 화면. 담당자 요청 2026-10-21.

전에는 청구서 받기 · 일반청구 · 주차등록 화면마다 [화면 구조 저장] 단추가 따로 있었다. 담당자: "각각 업무마다 펴져있는 화면 구조 저장을 하나의
업무카드로 만들어서 거기서 진행" · "옵션을 선택해서 브라우저를 열고 화면 구조 저장" · "다른 업무카드에서 해당 사이트를 이미 열고 작업 중이라면
로그아웃이나 재로그인 없이 바로" · "다른 곳에 있는 화면 구조 저장 버튼 및 기능 삭제".

할 차례인 단계만 위에서 아래로 떠오른다(ui/flow.py, 같은 날 담당자 — "클릭해야 하는 이동 순서대로 하나 둘 떠오르게"):
    ① 어느 사이트의 화면인가요? → ② 그 사이트 열기 → ③ 실측할 화면을 띄우고 저장 → ④ 저장한 파일 보내기
- 사이트는 둘 — ERP · 주차등록 사이트. 고른 사이트의 창(팝업 포함)만 읽는다(session.capture_structure(site)).
- 브라우저는 다른 업무와 같은 것(브라우저 스레드 하나)이다. 고른 사이트가 이미 열려 있으면 ② 는 저절로 지나가고, [열린 창 앞으로] 는 그 창을
  앞으로 가져오기만 하고 다시 불러오지 않는다 — 로그인과 띄워 둔 화면이 그대로다. 열려 있는지는 브라우저 스레드가 2초마다 알린다(worker.sites).
- 장학금 노란 띠 · 재로그인 띠에서 기다리는 중에도 바로 읽힌다(worker._wait_resume) — 그때 열어 둔 팝업을 실측한다.
- 읽기만 한다 — 누르거나 값을 넣지 않는다(tests/test_safety.py 의 diagnose 검사).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ... import settings
from ..art import Art
from ..flow import CURRENT, HIDDEN, ChoiceCard, FlowStep
from ..flowlogic import STRUCTURE_ORDER, flow_states, structure_stage
from ..report_dialog import save_structure_to_desktop, show_structure_saved
from ..widgets import Pill, muted_label
from ..worker import SessionWorker

SITES = (
    ("erp", "ERP", "산학협력단 연구비 시스템 — 청구서 받기 · 일반청구가 쓰는 곳", "claim"),
    ("parking", "주차등록 사이트", "교내 주차 사이트 — 주차등록 업무가 쓰는 곳", "parking"),
)
NAMES = {site: name for site, name, _desc, _art in SITES}
FILES = (("모음 파일 열기", settings.structure_book_path), ("마지막 화면 열기", settings.structure_path), ("폴더 열기", settings.data_dir))


class StructurePage(QWidget):
    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.worker = worker if worker is not None else SessionWorker()
        self._site = ""                # ① 에서 고른 사이트 — 고르기 전에는 ② · ③ 이 안 보인다
        self._saved = False            # 이번에 한 번이라도 저장했는지 — ④ 가 떠오른다
        self._busy = False
        self._asked = False            # 이 화면이 넣은 저장 · 열기만 창을 띄운다(다른 업무도 같은 신호를 받을 수 있다)
        self._open_note = ""           # 사이트를 열고 받은 한 줄(주차 자동 로그인 결과 등) — 지금 단계 아래에 보인다

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 30)          # 아래 26px 이상 — 접힌 독이 마지막 줄을 가리지 않게
        layout.setSpacing(12)
        layout.addLayout(self._build_head())

        self.step_site = self._build_site()
        self.step_open = self._build_open()
        self.step_save = self._build_save()
        self.step_send = self._build_send()
        self.steps = {"site": self.step_site, "open": self.step_open, "save": self.step_save, "send": self.step_send}
        for step in self.steps.values():
            layout.addWidget(step)
        layout.addStretch(1)

        w = self.worker
        w.sites_changed.connect(lambda _sites: self._sync())
        w.site_opened.connect(self._on_opened)
        w.structure_saved.connect(self._on_saved)
        w.busy.connect(self._on_busy)
        w.failed.connect(self._on_failed)
        self._sync()

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        """머리 — 그림 · 제목 · 한 줄 설명 / 오른쪽에 지금 상태 · [저장한 파일] 메뉴."""
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
        files = QPushButton("저장한 파일")
        files.setObjectName("ghost")
        files.setToolTip("전에 저장한 파일도 여기서 엽니다")
        menu = QMenu(files)
        for text, path in FILES:
            menu.addAction(text, lambda path=path: self._open_file(path()))
        files.setMenu(menu)
        head.addWidget(files, 0, Qt.AlignVCenter)
        return head

    def _build_site(self) -> FlowStep:
        """① 어느 사이트 — 카드를 누르면 바로 ② 로."""
        step = FlowStep("1", "어느 사이트의 화면인가요?", "고른 사이트의 창(팝업 포함)만 읽습니다.")
        step.edit.connect(self._edit_site)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.options: dict[str, ChoiceCard] = {}
        for site, name, description, art in SITES:
            option = ChoiceCard(site, name, description, art, pill=True)
            option.chosen.connect(self._choose)
            self.options[site] = option
            row.addWidget(option, 1)
        step.add_layout(row)
        return step

    def _build_open(self) -> FlowStep:
        """② 그 사이트 열기 — 이미 열려 있으면 저절로 지나간다."""
        step = FlowStep("2", "사이트 열기", editable=False)
        self.open_state = Pill("닫힘", "neutral")
        step.add_side(self.open_state)
        row = QHBoxLayout()
        self.open_button = QPushButton("ERP 열기")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self._open)
        row.addWidget(self.open_button)
        row.addStretch(1)
        step.add_layout(row)
        return step

    def _build_save(self) -> FlowStep:
        """③ 실측할 화면을 띄우고 저장 — 저장한 뒤에도 펼친 채(화면 여러 개를 차례로)."""
        step = FlowStep("3", "실측할 화면을 띄우고 저장하세요", editable=False)
        self.front_button = QPushButton("열린 창 앞으로")
        self.front_button.setObjectName("ghost")
        self.front_button.setToolTip("이미 열린 창을 앞으로 가져오기만 합니다 — 다시 불러오지 않아 로그인 · 띄운 화면이 그대로입니다")
        self.front_button.clicked.connect(self._open)
        step.add_side(self.front_button)
        row = QHBoxLayout()
        self.save_button = QPushButton("화면 구조 저장")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        row.addWidget(self.save_button)
        row.addStretch(1)
        step.add_layout(row)
        step.add(muted_label("읽기만 합니다 — 누르거나 값을 넣지 않고, 비밀번호 칸의 값은 적지 않습니다. 계좌번호 같은 값이 섞일 수 있으니 "
                             "작성 화면은 빈 채로 저장하세요. 장학금 노란 띠에서 기다리는 중에도 됩니다(그때 열어 둔 팝업까지)."))
        return step

    def _build_send(self) -> FlowStep:
        """④ 저장한 파일 보내기 — 모음 파일 하나면 된다."""
        step = FlowStep("4", "저장한 파일을 보내 주세요", "화면 여러 개를 차례로 저장했으면 모음 파일 하나만 보내 주세요. "
                        "다른 화면도 저장하려면 그 화면을 띄우고 위 [화면 구조 저장] 을 다시 누르세요.", editable=False)
        self.last = muted_label("")
        self.last.setWordWrap(True)
        step.add(self.last)
        row = QHBoxLayout()
        row.setSpacing(8)
        for i, (text, path) in enumerate(FILES):
            button = QPushButton(text)
            button.setObjectName("primary" if i == 0 else "ghost")
            button.clicked.connect(lambda _c=False, path=path: self._open_file(path()))
            row.addWidget(button)
        # 사용자 폴더를 찾아 들어가지 않아도 보낼 수 있게(담당자 2026-10-22 "폴더열기 버튼 옆에도 바탕화면 저장하기 버튼")
        desktop = QPushButton("바탕화면에 저장")
        desktop.setObjectName("ghost")
        desktop.setToolTip("모음 파일을 바탕화면에 복사합니다(저장한 때를 이름에 붙여, 덮어쓰지 않음)")
        desktop.clicked.connect(lambda: save_structure_to_desktop(self))
        row.addWidget(desktop)
        row.addStretch(1)
        step.add_layout(row)
        return step

    # ── 상태 ────────────────────────────────────────────────────────────
    def _opened(self) -> bool:
        return bool(self._site) and bool(self.worker.sites.get(self._site))

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
        for key, option in self.options.items():
            option.set_selected(key == self._site)

        name = NAMES.get(self._site, "")
        opened = self._opened()
        stage = structure_stage(bool(self._site), opened, self._saved)
        states = flow_states(STRUCTURE_ORDER, stage, keep_open=("save",))
        waiting = self.worker.waiting
        if self._site == "erp" and opened:
            open_text = "열림 · 로그인됨" if sites.get("erp_login") else "열림 · 로그인 전"
        else:
            open_text = "열림" if opened else "닫힘"
        self.open_state.set_status(open_text, "success" if opened else "neutral")
        self.open_button.setText(f"{name} 열기")
        self.open_button.setToolTip(f"앱 브라우저에 {name} 를 엽니다(다른 업무와 같은 브라우저)"
                                    + (" — 로그인은 직접 하세요" if self._site == "erp" else " — 설정의 로그인 정보로 한 번 자동 로그인"))
        self.open_button.setEnabled(not self._busy)
        self.front_button.setEnabled(not self._busy)
        self.save_button.setEnabled(opened and (not self._busy or waiting))
        self.step_site.edit_button.setEnabled(not self._busy)

        save_note = self._save_note(name, sites)
        if self._site == "parking" and self._open_note and not self._busy:
            save_note = self._open_note          # 자동 로그인 결과가 더 새 소식이다(ERP 는 로그인 여부가 바뀌므로 늘 지금 상태로)
        notes = {"open": self._open_note or (f"{name} 가 열려 있지 않습니다. [{name} 열기] 로 여세요"
                                             + (" — 로그인은 열린 창에서 직접 합니다." if self._site == "erp" else ".")),
                 "save": save_note}
        busy_note = "다른 업무가 브라우저를 쓰는 중입니다 — 그 일이 끝나면 저장할 수 있습니다." if self._busy and not waiting else ""
        summaries = {"site": name, "open": open_text}
        for key, step in self.steps.items():
            step.set_state(states[key], summaries.get(key))
            note = notes.get(key, "") if states[key] == CURRENT else ""
            if key == "save" and busy_note and states[key] != HIDDEN:
                note = busy_note
            step.set_note(note)

    def _save_note(self, name: str, sites: dict) -> str:
        if self._busy and self.worker.waiting:
            return "다른 업무가 띠에서 사람을 기다리는 중입니다 — 지금 저장하면 바로 읽습니다(그때 열어 둔 팝업까지)."
        if self._site == "erp" and not sites.get("erp_login"):
            return "ERP 창이 열려 있습니다. 로그인하고 실측할 화면(팝업이면 팝업까지)을 띄운 뒤 [화면 구조 저장] 을 누르세요."
        return (f"{name} 창이 열려 있습니다 — 다른 업무에서 연 창이어도 그대로 저장합니다(로그아웃 · 다시 로그인 없이). "
                "실측할 화면(팝업이면 팝업까지)을 띄운 뒤 [화면 구조 저장] 을 누르세요.")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync()

    # ── 고르기 · 열기 · 저장 ──────────────────────────────────────────────
    def _choose(self, site: str) -> None:
        if self._busy and not self.worker.waiting:
            return
        if site != self._site:
            self._saved = False
            self._open_note = ""
        self._site = site
        self.state.set_status("준비", "neutral")
        self._sync()

    def _edit_site(self) -> None:
        self._site = ""
        self._saved = False
        self._open_note = ""
        self.state.set_status("준비", "neutral")
        self._sync()

    def _open(self) -> None:
        if not self._site:
            return
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
        self._open_note = note
        self._sync()

    def _on_saved(self, path: str) -> None:
        if not self._asked:
            return
        self._asked = False
        self.state.set_status("저장함" if path else "못 함", "success" if path else "danger")
        if path:
            self._saved = True
            self.last.setText(f"{NAMES.get(self._site, '')} 화면을 저장했습니다 — {path}")
        self._sync()
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
