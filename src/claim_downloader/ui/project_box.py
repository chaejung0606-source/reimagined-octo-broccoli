"""ERP 과제 고르기 칸 — 일반청구 · 청구서 받기가 함께 쓴다(담당자 2026-10-21: "일반청구와 동일하게 옵션 선택을 넣으면 될 것 같습니다. 기본값도 동일").

보기는 로그인 뒤 메인화면 과제현황에서 읽은 과제 중 과제기간에 오늘이 든 것(navigate.choices), 기본은 마지막으로 고른 과제 → 담당자가 정한
기본 과제(settings.DEFAULT_PROJECT_NO). 고르면 settings.project_no 에 남겨 다음 로그인 뒤 그 과제의 청구서 화면으로 간다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox

from .. import navigate, settings


def project_box() -> QComboBox:
    """좁게 두고(과제번호 + 과제명 앞부분) 전체는 말풍선."""
    box = QComboBox()
    box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    box.setMinimumContentsLength(13)
    return box


def last_project() -> str:
    return str(getattr(settings.load(), "project_no", "") or settings.DEFAULT_PROJECT_NO)


def fill_project_box(box: QComboBox, selected: str) -> None:
    box.blockSignals(True)
    box.clear()
    for no, text in navigate.choices(selected, short=True):
        box.addItem(text, no)
        box.setItemData(box.count() - 1, navigate.label_of(no), Qt.ToolTipRole)
    index = box.findData(selected)
    box.setCurrentIndex(index if index >= 0 else 0)
    box.setToolTip("ERP 과제: " + navigate.label_of(str(box.currentData() or selected))
                   + "\n보기는 로그인 뒤 메인화면 과제현황에서 읽은 과제 중 과제기간에 오늘이 든 것입니다.")
    box.blockSignals(False)


def remember(no: str) -> None:
    """마지막으로 고른 과제 — 로그인 뒤 그 과제의 청구서 화면으로 간다."""
    if no and no != last_project():
        settings.update(project_no=no)
