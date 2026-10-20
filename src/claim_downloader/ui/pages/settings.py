"""설정 화면 — 저장 폴더 · AI 플랫폼 · 파일 이름 형식 · 누락 검토 엑셀 · 동작 · 기록.

고치는 즉시 `~/.claim-downloader/config.json` 에 저장한다. 앱 폴더에 두지
않으므로 업데이트를 받아도 그대로 남는다.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import ai, archive, settings
from .. import ai_status
from ..widgets import Card, ElideLabel, Field, PageHeader, Pill, muted_label

EXAMPLE_DATE = "(261008) 2026년 사업단 정수기 임차료(9월)_코웨이(주)_(51,900).pdf"
EXAMPLE_CODE = "09_" + EXAMPLE_DATE

# 긴 입력줄이 화면 끝까지 늘어나면 읽기 어렵다
FORM_MAX_WIDTH = 920


class SettingsPage(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        cfg = settings.load()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("pageBody")
        scroll.setWidget(content)
        outer.addWidget(scroll)

        page = QVBoxLayout(content)
        page.setContentsMargins(28, 24, 28, 34)
        page.setSpacing(16)
        page.addWidget(PageHeader(
            "관리  ›  설정", "설정",
            "고치면 바로 저장됩니다. 설정은 앱 폴더 밖에 있어 업데이트해도 그대로 남습니다."))

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(16)
        holder = QWidget()
        holder.setMaximumWidth(FORM_MAX_WIDTH)
        holder.setLayout(column)
        page.addWidget(holder)
        page.addStretch(1)

        # 저장 폴더 — 가장 중요하므로 맨 위, 그림을 붙인다
        folder_card = Card("저장 폴더", "받은 청구서가 들어갈 곳", art="archive")
        self.out_root = QLineEdit(cfg.out_root)
        self.out_root.setPlaceholderText(r"예: C:\Users\…\지출결의서\2026년도(e나라도움)")
        self.out_root.editingFinished.connect(self._save_out_root)
        self.folder_field = Field(
            "폴더 경로", self.out_root,
            "비목 폴더(01. 인건비 · 02. 장학금 …)가 바로 아래 있는 폴더를 고르세요. "
            "플랫폼 업로드를 마친 파일은 직접 '업로드' 폴더로 옮기세요 — 앱은 그 폴더를 읽기만 합니다.",
            required=True)
        browse = QPushButton("폴더 선택")
        browse.clicked.connect(self._browse_out_root)
        self.folder_field.add_button(browse)
        folder_card.add(self.folder_field)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.folder_pill = Pill()
        status_row.addWidget(self.folder_pill, 0, Qt.AlignTop)
        self.folder_status = muted_label("")
        status_row.addWidget(self.folder_status, 1)
        folder_card.add_layout(status_row)
        column.addWidget(folder_card)

        column.addWidget(self._build_ai_card(cfg))

        # 파일 이름
        name_card = Card("파일 이름")
        self.name_old = QCheckBox("이름 앞에 비목 번호를 붙이기 (끄면 날짜로 시작)")
        self.name_old.setChecked(not cfg.name_date_first)
        self.name_old.toggled.connect(self._save_name)
        name_card.add(self.name_old)
        self.name_example = QLineEdit()
        self.name_example.setReadOnly(True)
        self.name_example.setFocusPolicy(Qt.NoFocus)
        name_card.add(Field("미리 보기", self.name_example))
        column.addWidget(name_card)

        # 누락 검토
        excel_card = Card("누락 검토", "선택 — 비워 두면 건너뜁니다")
        self.excel = QLineEdit(cfg.excel_path)
        self.excel.setPlaceholderText("청구내역 .xls / .xlsx")
        self.excel.editingFinished.connect(
            lambda: self._save(excel_path=self.excel.text().strip()))
        self.excel_field = Field(
            "ERP 청구내역 엑셀", self.excel,
            "지정하면 받기가 끝난 뒤 승인 건 중 아직 받지 않은 문서번호를 [진행 기록] 에 알려 줍니다.")
        pick = QPushButton("파일 선택")
        pick.clicked.connect(self._browse_excel)
        clear = QPushButton("비우기")
        clear.setObjectName("ghost")
        clear.clicked.connect(lambda: (self.excel.clear(), self._save(excel_path="")))
        self.excel_field.add_button(pick)
        self.excel_field.add_button(clear)
        excel_card.add(self.excel_field)
        column.addWidget(excel_card)

        # 일반청구 — 세금계산서 조회 팝업에는 산학협력단 전체 계산서가 다 떠서, 내 계산서수신메일로 걸러야 내 건만 보인다
        # (담당자 설명 2026-10-13). 사람마다 다른 값이라 코드에 두지 않고 여기서 받는다.
        claim_card = Card("일반청구", "세금계산서 · 카드 회의비 건을 ERP 에 채울 때 씁니다")
        self.taxbill_email = QLineEdit(getattr(cfg, "taxbill_email", "") or "")
        self.taxbill_email.setPlaceholderText("예: 홍길동@kangwon.ac.kr")
        self.taxbill_email.editingFinished.connect(
            lambda: self._save(taxbill_email=self.taxbill_email.text().strip()))
        claim_card.add(Field(
            "계산서수신메일", self.taxbill_email,
            "세금계산서 조회 팝업의 '계산서수신메일' 에 넣을 내 메일. 비우면 메일 없이 거래처 사업자번호로만 조회합니다."))
        # 카드청구 회의비 — 회의록 참석자 중 학교 안 사람을 참여인력 · 내부참석자로 가르는 명단(담당자 2026-10-20). 실명이 든 파일이라 위치만 둔다
        self.participants = QLineEdit(getattr(cfg, "participants_file", "") or "")
        self.participants.setPlaceholderText("ERP '참여연구원 현황표' 엑셀 또는 PDF (Prn_PrjPartInfo)")
        self.participants.editingFinished.connect(
            lambda: self._save(participants_file=self.participants.text().strip()))
        self.participants_field = Field(
            "참여연구원 명단", self.participants,
            "카드 회의비의 참석자 중 이 명단에 있는 사람은 참여인력으로 넣습니다. 비우면 카드 폴더 · 그 위 폴더에서 '참여연구원' 이 든 파일을 찾습니다.")
        pick_part = QPushButton("파일 선택")
        pick_part.clicked.connect(self._browse_participants)
        clear_part = QPushButton("비우기")
        clear_part.setObjectName("ghost")
        clear_part.clicked.connect(lambda: (self.participants.clear(), self._save(participants_file="")))
        self.participants_field.add_button(pick_part)
        self.participants_field.add_button(clear_part)
        claim_card.add(self.participants_field)
        column.addWidget(claim_card)

        # 동작
        behave = Card("동작", "받는 방식을 조절합니다", art="settings")
        self.freeze = QCheckBox("상세화면이 멈추면 ERP 를 새로 열고, 다시 로그인한 뒤 같은 건부터 이어받기 (건당 최대 2번)")
        self.freeze.setChecked(cfg.freeze_reload)
        self.freeze.toggled.connect(lambda v: self._save(freeze_reload=v))
        behave.add(self.freeze)
        self.auto_list = QCheckBox("브라우저를 연 뒤 결의서내역 목록이 보이면 [목록 읽기] 를 저절로 하기 (읽기만 합니다)")
        self.auto_list.setChecked(cfg.auto_read_list)
        self.auto_list.toggled.connect(lambda v: self._save(auto_read_list=v))
        behave.add(self.auto_list)
        # 과제는 일반청구 화면에서 폴더마다 고른다(담당자 2026-10-19) — 로그인 뒤 이동은 마지막으로 고른 과제로(settings.project_no)
        self.auto_project = QCheckBox("로그인하면 일반청구에서 마지막으로 고른 과제의 청구서(결의서내역)까지 앱이 이동하기 (로그인은 직접 합니다)")
        self.auto_project.setChecked(cfg.auto_open_project)
        self.auto_project.toggled.connect(lambda v: self._save(auto_open_project=v))
        behave.add(self.auto_project)
        self.auto_sheet = QCheckBox("청구서를 넣을 때 다른(저장된) 청구서가 떠 있으면 결의서내역의 [일반청구] · [카드청구] 로 새 청구서를 앱이 띄우기")
        self.auto_sheet.setChecked(cfg.auto_new_sheet)
        self.auto_sheet.toggled.connect(lambda v: self._save(auto_new_sheet=v))
        behave.add(self.auto_sheet)
        self.wait = QDoubleSpinBox()
        # 화살표는 스타일시트에서 폭 0 으로 숨긴다(theme.py). setButtonSymbols(NoButtons) 를 쓰면
        # 스타일시트가 걸린 칸에서 Qt 가 글자 칸 폭을 1px 로 잡아 값이 안 보인다.
        self.wait.setRange(0, 30)
        self.wait.setSingleStep(0.5)
        self.wait.setDecimals(1)
        self.wait.setSuffix(" 초")
        self.wait.setValue(cfg.wait_sec)
        # 숫자 칸 안쪽 글자 칸에는 스타일시트 여백이 먹지 않아 코드로 띄운다
        self.wait.lineEdit().setTextMargins(10, 0, 0, 0)
        self.wait.valueChanged.connect(lambda v: self._save(wait_sec=float(v)))
        wait_field = Field("건마다 쉬는 시간", self.wait, "ERP 가 느릴 때만 늘리세요. 기본 2초.")
        wait_field.setMaximumWidth(320)
        behave.add(wait_field)
        column.addWidget(behave)

        # 기록
        records = Card("기록", "문제가 생기면 _실행로그.txt 를 담당자에게 보내 주세요", art="journal")
        data_path = QLineEdit(str(settings.data_dir()))
        data_path.setReadOnly(True)
        records_field = Field(
            "기록 폴더", data_path,
            "받은 문서번호 기록 · 보관 목록 캐시 · 실행 로그가 있습니다. "
            "보관 목록(_보관목록.json)을 지우면 다음 실행 때 보관 폴더를 처음부터 다시 읽습니다.")
        open_dir = QPushButton("폴더 열기")
        open_dir.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.data_dir()))))
        records_field.add_button(open_dir)
        records.add(records_field)
        column.addWidget(records)

        # 바로가기 · 작업 표시줄 — 고정한 단추와 실행 중인 창이 둘로 보일 때 여기서 다시 만든다
        shortcut_card = Card("바로가기 · 작업 표시줄", "바탕화면 · 시작 메뉴 바로가기와 고정한 단추를 앱과 같은 이름으로 맞춥니다")
        shortcut_card.add(muted_label(
            "작업 표시줄에 고정한 단추 옆에 실행 중인 창이 따로 뜨면 누르세요. 그래도 둘이면 고정을 풀고, "
            "앱이 떠 있는 상태에서 작업 표시줄의 앱 단추를 우클릭 → '작업 표시줄에 고정' 을 다시 하세요."))
        self.shortcut_button = QPushButton("바로가기 다시 만들기")
        self.shortcut_button.clicked.connect(self._rebuild_shortcuts)
        row = QHBoxLayout()
        row.addWidget(self.shortcut_button)
        row.addStretch(1)
        shortcut_card.add_layout(row)
        column.addWidget(shortcut_card)

        self._refresh()
        ai_status.instance().changed.connect(self._sync_ai)
        self._sync_ai()

    # ── AI 플랫폼 ────────────────────────────────────────────────────
    def _build_ai_card(self, cfg: settings.Settings) -> Card:
        """회의록 생성 · 일반청구에 쓸 AI 를 여기서 정한다(담당자 요청 2026-10-14). 로그인 상태도 여기서 본다.

        로그인은 그 플랫폼의 로그인 창에서 사람이 한다 — 앱은 창을 열어 주기만 하고 비밀번호는 어디에도 두지 않는다.
        """
        self.ai_card = Card("AI 플랫폼", "회의록 생성 · 일반청구가 자료를 읽힐 AI", art="login")
        self.ai_boxes: dict[str, QComboBox] = {}
        helps = {
            "minutes": "회의 자료를 읽고 회의록을 씁니다.",
            "claim": "일반 지출 폴더의 [내용 읽기] 에 씁니다. 장학금은 명단 엑셀을 바로 읽어 AI 를 쓰지 않습니다.",
        }
        row = QHBoxLayout()
        row.setSpacing(16)
        for use, (title, field) in ai.USES.items():
            box = QComboBox()
            for key, label in ai.platforms(use):
                box.addItem(label, key)
            index = box.findData(ai.chosen(use, cfg))
            box.setCurrentIndex(index if index >= 0 else 0)
            box.currentIndexChanged.connect(lambda _i, use=use, field=field: self._save_platform(use, field))
            self.ai_boxes[use] = box
            row.addWidget(Field(title, box, helps.get(use, "")), 1, Qt.AlignTop)   # 도움말 줄 수가 달라도 칸이 나란히
        self.ai_card.add_layout(row)
        if all(len(ai.platforms(use)) <= 1 for use in ai.USES):
            self.ai_card.add(muted_label("지금 고를 수 있는 것은 Claude Code 하나입니다. 다른 AI 플랫폼이 추가되면 여기에서 고릅니다."))

        # 로그인 상태 — 쓰기로 정한 플랫폼마다 한 줄
        self.ai_rows = QVBoxLayout()
        self.ai_rows.setSpacing(8)
        self._ai_row_widgets: dict[str, tuple[QWidget, Pill, ElideLabel, QPushButton]] = {}
        self.ai_card.add_layout(self.ai_rows)

        self.claude_email = QLineEdit(cfg.claude_email)
        self.claude_email.setPlaceholderText("예: 홍길동@kangwon.ac.kr")
        self.claude_email.editingFinished.connect(self._save_email)
        email_field = Field(
            "로그인 이메일", self.claude_email,
            "로그인 창에 미리 채워 넣을 주소입니다. 이 PC 에만 저장되고, 비밀번호는 저장하지 않습니다.")
        email_field.setMaximumWidth(520)
        self.ai_card.add(email_field)
        return self.ai_card

    def _save_email(self) -> None:
        value = self.claude_email.text().strip()
        if value != settings.load().claude_email:
            self._save(claude_email=value)

    def _save_platform(self, use: str, field: str) -> None:
        key = self.ai_boxes[use].currentData()
        if key and key != getattr(settings.load(), field, ""):
            self._save(**{field: key})

    def _ai_row(self, key: str) -> tuple[QWidget, Pill, ElideLabel, QPushButton]:
        if key in self._ai_row_widgets:
            return self._ai_row_widgets[key]
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(10)
        name = QLabel(ai.short_label(key))
        name.setObjectName("body")
        line.addWidget(name)
        pill = Pill("확인 중", "neutral")
        line.addWidget(pill, 0, Qt.AlignVCenter)
        note = ElideLabel("")
        note.setObjectName("muted")
        line.addWidget(note, 1)
        login = QPushButton("로그인")
        login.clicked.connect(lambda _c=False, key=key: ai_status.instance().login(self, key))
        line.addWidget(login)
        recheck = QPushButton("다시 확인")
        recheck.setObjectName("ghost")
        recheck.clicked.connect(ai_status.instance().check)
        line.addWidget(recheck)
        self.ai_rows.addWidget(holder)
        self._ai_row_widgets[key] = (holder, pill, note, login)
        return self._ai_row_widgets[key]

    def _sync_ai(self) -> None:
        status_of = ai_status.instance()
        used = ai.used_keys()
        for key, (holder, *_rest) in self._ai_row_widgets.items():
            holder.setVisible(key in used)
        for key in used:
            _holder, pill, note, login = self._ai_row(key)
            status = status_of.status(key)
            if status.state == ai.CHECKING or (status_of.checking and not status.checked_at):
                pill.set_status("확인 중", "neutral")
            else:
                pill.set_status(status.text, status.tone)
            uses = " · ".join(title for use, (title, _f) in ai.USES.items() if ai.chosen(use) == key)
            note.setText(f"{uses} — {status.note}" if status.note else uses)
            note.setToolTip(status.note)
            login.setVisible(ai.can_login(key) and status.state != ai.MISSING)
            # 로그인돼 있으면 계정을 바꿀 때만 쓴다 — 주된 단추로 보이지 않게
            login.setText("다시 로그인" if status.state == ai.OK else "로그인")
            login.setObjectName("ghost" if status.state == ai.OK else "primary")
            login.style().unpolish(login)
            login.style().polish(login)

    def focus_ai(self, use: str = "minutes") -> None:
        """위쪽 AI 단추 · 업무 화면의 [설정에서 바꾸기] 로 왔을 때 AI 플랫폼 칸을 보이게 — 그 업무의 고르기 칸에 초점."""
        self._scroll.ensureWidgetVisible(self.ai_card, 0, 24)
        box = self.ai_boxes.get(use) or self.ai_boxes.get("minutes")
        if box is not None:
            box.setFocus()

    def _rebuild_shortcuts(self) -> None:
        from ... import shortcuts
        self.shortcut_button.setEnabled(False)
        self.shortcut_button.setText("만드는 중…")
        QApplication.processEvents()
        try:
            ok, text = shortcuts.refresh()
        finally:
            self.shortcut_button.setEnabled(True)
            self.shortcut_button.setText("바로가기 다시 만들기")
        box = QMessageBox.information if ok else QMessageBox.warning
        box(self, "바로가기", ("바로가기를 다시 만들었습니다.\n\n" if ok else "바로가기를 다 만들지 못했습니다. 아래 내용을 담당자에게 보내 주세요.\n\n") + text)

    def _save(self, **changes) -> None:
        settings.update(**changes)
        self._refresh()
        self.changed.emit()

    def _save_out_root(self) -> None:
        value = self.out_root.text().strip().strip('"')
        self.out_root.setText(value)
        if value != settings.load().out_root:
            self._save(out_root=value)

    def _save_name(self, old: bool) -> None:
        self._save(name_date_first=not old)

    def _browse_out_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "저장 폴더", self.out_root.text())
        if path:
            self.out_root.setText(path)
            self._save_out_root()

    def _browse_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "청구내역 엑셀", self.excel.text(), "엑셀 (*.xls *.xlsx)")
        if path:
            self.excel.setText(path)
            self._save(excel_path=path)

    def _browse_participants(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "참여연구원 명단", self.participants.text(), "엑셀 · PDF (*.xlsx *.xlsm *.pdf)")
        if path:
            self.participants.setText(path)
            self._save(participants_file=path)

    def _refresh(self) -> None:
        cfg = settings.load()
        self.name_example.setText(EXAMPLE_DATE if cfg.name_date_first else EXAMPLE_CODE)
        self.excel_field.set_error(
            "이 파일이 없습니다. 경로를 확인하세요." if cfg.excel_path and not os.path.exists(cfg.excel_path) else "")
        part = getattr(cfg, "participants_file", "") or ""
        self.participants_field.set_error("이 파일이 없습니다. 경로를 확인하세요." if part and not os.path.exists(part) else "")

        if not cfg.out_root:
            self.folder_field.set_error("")
            self.folder_pill.set_status("지정 안 됨", "warning")
            self.folder_status.setText("저장 폴더를 지정해야 청구서를 받을 수 있습니다.")
            return
        folders = archive.folder_status(cfg.out_root)
        if not folders:
            if not os.path.isdir(cfg.out_root):
                self.folder_field.set_error("이 폴더가 없습니다. 경로를 확인하세요.")
                self.folder_pill.set_status("폴더 없음", "danger")
                self.folder_status.setText("이대로 받으면 이미 받은 건까지 다시 받게 됩니다.")
            else:
                self.folder_field.set_error("")
                self.folder_pill.set_status("확인 필요", "warning")
                self.folder_status.setText(
                    "이 폴더 바로 아래에 비목 폴더(01. 인건비 …)가 없습니다. 한 단계 위나 아래 폴더가 아닌지 확인하세요.")
            return
        self.folder_field.set_error("")
        self.folder_pill.set_status(f"비목 폴더 {len(folders)}개", "success")
        self.folder_status.setText(
            " · ".join(f"{f.name.split('. ', 1)[0]} 대기 {f.waiting} / 완료 {f.uploaded}" for f in folders))
