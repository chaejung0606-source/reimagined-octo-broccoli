"""설정 화면 — 저장 폴더 · 파일 이름 형식 · 누락 검토 엑셀 · 동작 · 기록.

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
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import archive, settings
from ..widgets import Card, Field, PageHeader, Pill, muted_label

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
        claim_card = Card("일반청구", "세금계산서 건을 ERP 에 채울 때 씁니다")
        self.taxbill_email = QLineEdit(getattr(cfg, "taxbill_email", "") or "")
        self.taxbill_email.setPlaceholderText("예: 홍길동@kangwon.ac.kr")
        self.taxbill_email.editingFinished.connect(
            lambda: self._save(taxbill_email=self.taxbill_email.text().strip()))
        claim_card.add(Field(
            "계산서수신메일", self.taxbill_email,
            "세금계산서 조회 팝업의 '계산서수신메일' 에 넣을 내 메일. 비우면 메일 없이 거래처 사업자번호로만 조회합니다."))
        column.addWidget(claim_card)

        # 동작
        behave = Card("동작", "받는 방식을 조절합니다", art="settings")
        self.freeze = QCheckBox("상세화면이 멈추면 ERP 를 새로 열고, 다시 로그인한 뒤 같은 건부터 이어받기 (건당 최대 2번)")
        self.freeze.setChecked(cfg.freeze_reload)
        self.freeze.toggled.connect(lambda v: self._save(freeze_reload=v))
        behave.add(self.freeze)
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

    def _refresh(self) -> None:
        cfg = settings.load()
        self.name_example.setText(EXAMPLE_DATE if cfg.name_date_first else EXAMPLE_CODE)
        self.excel_field.set_error(
            "이 파일이 없습니다. 경로를 확인하세요." if cfg.excel_path and not os.path.exists(cfg.excel_path) else "")

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
