"""설정 화면 — 저장 폴더 · 파일 이름 형식 · 누락 검토 엑셀 · 동작.

고치는 즉시 `~/.claim-downloader/config.json` 에 저장한다. 앱 폴더에 두지
않으므로 업데이트를 받아도 그대로 남는다.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import archive, settings
from ..widgets import Card, muted_label

EXAMPLE = "(261008) 2026년 사업단 정수기 임차료(9월)_코웨이(주)_(51,900).pdf"
EXAMPLE_OLD = "09_" + EXAMPLE


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
        content = QWidget()
        content.setObjectName("page")
        scroll.setWidget(content)
        outer.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(22)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("설정")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addWidget(muted_label(
            "고치면 바로 저장됩니다. 설정은 앱 폴더 밖에 있어 업데이트해도 그대로 남습니다."))
        layout.addLayout(header)

        # 저장 폴더
        folder_card = Card("저장 폴더")
        folder_card.add(muted_label(
            "비목 폴더(01. 인건비 · 02. 장학금 …)가 바로 아래 있는 폴더를 고르세요. "
            "받은 청구서는 각 비목 폴더 바로 아래에 들어갑니다. "
            "플랫폼 업로드를 마친 파일은 직접 '업로드' 폴더로 옮기세요 — 앱은 그 폴더를 읽기만 합니다."))
        row = QHBoxLayout()
        self.out_root = QLineEdit(cfg.out_root)
        self.out_root.setPlaceholderText(r"예: C:\Users\…\지출결의서\2026년도(e나라도움)")
        self.out_root.editingFinished.connect(self._save_out_root)
        browse = QPushButton("폴더 선택")
        browse.clicked.connect(self._browse_out_root)
        row.addWidget(self.out_root, 1)
        row.addWidget(browse)
        folder_card.add_layout(row)
        self.folder_status = muted_label("")
        folder_card.add(self.folder_status)
        layout.addWidget(folder_card)

        # 파일 이름
        name_card = Card("파일 이름")
        self.name_old = QCheckBox("이름 앞에 비목 번호를 붙이기 (옛 매크로 형식)")
        self.name_old.setChecked(not cfg.name_date_first)
        self.name_old.toggled.connect(self._save_name)
        name_card.add(self.name_old)
        self.name_example = muted_label("")
        name_card.add(self.name_example)
        layout.addWidget(name_card)

        # 누락 검토
        excel_card = Card("누락 검토 (선택)")
        excel_card.add(muted_label(
            "ERP 에서 내려받은 청구내역 엑셀을 지정하면, 받기가 끝난 뒤 승인 건 중 아직 받지 않은 "
            "문서번호를 진행 기록에 알려 줍니다. 비워 두면 건너뜁니다."))
        row = QHBoxLayout()
        self.excel = QLineEdit(cfg.excel_path)
        self.excel.setPlaceholderText("청구내역 .xls / .xlsx")
        self.excel.editingFinished.connect(
            lambda: self._save(excel_path=self.excel.text().strip()))
        pick = QPushButton("파일 선택")
        pick.clicked.connect(self._browse_excel)
        clear = QPushButton("비우기")
        clear.setObjectName("ghost")
        clear.clicked.connect(lambda: (self.excel.clear(), self._save(excel_path="")))
        row.addWidget(self.excel, 1)
        row.addWidget(pick)
        row.addWidget(clear)
        excel_card.add_layout(row)
        layout.addWidget(excel_card)

        # 동작
        behave = Card("동작")
        self.freeze = QCheckBox("상세화면이 멈추면 ERP 를 새로 열고, 다시 로그인한 뒤 같은 건부터 이어받기 (건당 최대 2번)")
        self.freeze.setChecked(cfg.freeze_reload)
        self.freeze.toggled.connect(lambda v: self._save(freeze_reload=v))
        behave.add(self.freeze)
        row = QHBoxLayout()
        row.addWidget(QLabel("건마다 쉬는 시간"))
        self.wait = QDoubleSpinBox()
        # 화살표 버튼은 테마의 둥근 입력칸과 겹쳐 깨져 보인다. 숫자를 직접 넣게 한다.
        self.wait.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.wait.setFixedWidth(110)
        self.wait.setRange(0, 30)
        self.wait.setSingleStep(0.5)
        self.wait.setDecimals(1)
        self.wait.setSuffix(" 초")
        self.wait.setValue(cfg.wait_sec)
        self.wait.valueChanged.connect(lambda v: self._save(wait_sec=float(v)))
        row.addWidget(self.wait)
        row.addStretch(1)
        behave.add_layout(row)
        layout.addWidget(behave)

        # 기록
        records = Card("기록")
        records.add(muted_label(
            "받은 문서번호 기록 · 보관 목록 캐시 · 실행 로그가 이 폴더에 있습니다. "
            "문제가 생기면 _실행로그.txt 를 담당자에게 보내 주세요. "
            "보관 목록(_보관목록.json)을 지우면 다음 실행 때 보관 폴더를 처음부터 다시 읽습니다."))
        row = QHBoxLayout()
        row.addWidget(muted_label(str(settings.data_dir())), 1)
        open_dir = QPushButton("폴더 열기")
        open_dir.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.data_dir()))))
        row.addWidget(open_dir)
        records.add_layout(row)
        layout.addWidget(records)

        layout.addStretch(1)
        self._refresh()

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
        self.name_example.setText("예) " + (EXAMPLE if cfg.name_date_first else EXAMPLE_OLD))
        if not cfg.out_root:
            self.folder_status.setText("아직 지정하지 않았습니다.")
            return
        folders = archive.folder_status(cfg.out_root)
        if not folders:
            if not os.path.isdir(cfg.out_root):
                self.folder_status.setText("⚠ 이 폴더가 없습니다. 경로를 확인하세요.")
            else:
                self.folder_status.setText(
                    "⚠ 이 폴더 바로 아래에 비목 폴더(01. 인건비 …)가 없습니다. 한 단계 위나 아래 폴더가 아닌지 확인하세요.")
            return
        lines = ", ".join(f"{f.name.split('. ', 1)[0]} 대기 {f.waiting}·완료 {f.uploaded}" for f in folders)
        self.folder_status.setText(f"비목 폴더 {len(folders)}개 확인 — {lines}")
