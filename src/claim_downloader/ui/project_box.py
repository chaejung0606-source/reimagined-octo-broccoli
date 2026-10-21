"""ERP 과제 고르기 칸 — 일반청구 · 청구서 받기가 함께 쓴다(담당자 2026-10-21: "일반청구와 동일하게 옵션 선택을 넣으면 될 것 같습니다. 기본값도 동일").

보기는 로그인 뒤 메인화면 과제현황에서 읽은 과제 중 과제기간에 오늘이 든 것(navigate.choices), 기본은 마지막으로 고른 과제 → 담당자가 정한
기본 과제(settings.DEFAULT_PROJECT_NO). 고르면 settings.project_no 에 남겨 다음 로그인 뒤 그 과제의 청구서 화면으로 간다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox

from .. import navigate, project_folders, settings


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


def folder_projects() -> list[project_folders.ProjectFolder]:
    """저장 폴더 아래 과제 폴더 — 과제번호마다 하나(같은 번호 폴더가 둘이면 앞의 것만 보이고, 받을 때 save_root 가 막는다)."""
    seen, out = set(), []
    for folder in project_folders.folders(settings.load().out_root):
        if folder.no not in seen:
            seen.add(folder.no)
            out.append(folder)
    return out


def fill_download_box(box: QComboBox, selected: str) -> None:
    """청구서 받기의 과제 칸(담당자 2026-10-21: "과제번호로 과제 구분해서" · "지금 폴더 만든 과제만") — 저장 폴더 아래에 `(과제번호)_…`
    폴더가 있으면 그 과제들과 맨 위 '폴더 만든 과제 모두'. 과제 폴더가 없는 옛 저장 폴더면 일반청구와 같은 보기."""
    found = folder_projects()
    if not found:
        fill_project_box(box, selected if selected != project_folders.ALL else last_project())
        return
    box.blockSignals(True)
    box.clear()
    box.addItem(f"폴더 만든 과제 모두 ({len(found)}개)", project_folders.ALL)
    box.setItemData(0, "저장 폴더 아래 과제 폴더가 있는 과제를 차례로 읽고 받습니다:\n" + "\n".join(f.path.name for f in found), Qt.ToolTipRole)
    for folder in found:
        box.addItem(folder.short(), folder.no)
        known = navigate.label_of(folder.no)
        box.setItemData(box.count() - 1, folder.path.name + ("" if known == folder.no else "\nERP: " + known), Qt.ToolTipRole)
    index = box.findData(selected)
    box.setCurrentIndex(index if index >= 0 else 0)
    box.setToolTip("받을 과제 — 청구서는 그 과제의 폴더(저장 폴더 아래 '(과제번호)_…') 안 비목 폴더에 둡니다.\n"
                   "폴더가 없는 과제는 받지 않습니다.")
    box.blockSignals(False)
