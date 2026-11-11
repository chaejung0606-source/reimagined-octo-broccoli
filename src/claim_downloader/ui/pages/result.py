"""결과 보기 탭 — 홈의 '결과 확인' 목록에서 한 건을 누르면 새 탭으로 그 결과 창의 내용을 보인다.

담당자 2026-11-11: "홈화면에 결과확인을 이어서 작업하기 오른쪽에 목록을 넣고 목록중 한건을 클릭하면 새탭에서 결과내용 확인하기. 최근 10건만 저장".
결과는 ui/result_store.py(최근 열 건), 내용은 넣은 뒤 띄웠던 결과 창과 같은 것(report_dialog.ReportDialog 를 창이 아니라 탭 안에 놓는다).
읽기만 한다 — ERP · 파일을 건드리지 않는다.
"""
from __future__ import annotations

import datetime as dt
import os

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..report_dialog import ReportDialog, entry_report


def tab_name(entry: dict, today: dt.date | None = None) -> str:
    """탭 이름 — 오늘 것은 '결과 20:20', 지난 것은 '결과 11-10 20:20'(탭 폭이 정해져 있어 짧게 — 무슨 청구인지는 탭 안 머리에)."""
    when = str(entry.get("when", ""))
    if len(when) < 16:
        return f"결과 {when}".strip()
    if when[:10] == (today or dt.date.today()).isoformat():
        return f"결과 {when[11:16]}"
    return f"결과 {when[5:16]}"


class ResultPage(QWidget):
    close_requested = Signal()

    def __init__(self, entry: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.entry = entry
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 30)       # 아래는 독의 접힌 선이 끝줄을 가리지 않게(5절)
        layout.setSpacing(8)
        folder = str(entry.get("folder", ""))
        row = QHBoxLayout()
        row.setSpacing(8)
        where = QLabel(f"넣은 폴더: {os.path.basename(os.path.normpath(folder)) or folder}")
        where.setObjectName("muted")
        where.setToolTip(folder)
        row.addWidget(where, 1)
        self.folder_button = QPushButton("폴더 열기")
        self.folder_button.setObjectName("ghost")
        self.folder_button.setEnabled(bool(folder) and os.path.isdir(folder))
        self.folder_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
        row.addWidget(self.folder_button)
        layout.addLayout(row)
        self.report = ReportDialog(self, **entry_report(entry), close_text="탭 닫기", embedded=True)
        self.report.close_requested.connect(self.close_requested.emit)
        layout.addWidget(self.report, 1)
