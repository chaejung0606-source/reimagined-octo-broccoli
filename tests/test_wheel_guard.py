"""드롭다운 위 마우스 휠 — 값은 그대로, 휠은 감싼 스크롤 칸으로(담당자 2026-10-26 "드롭다운 박스를 클릭하고 옵션을 클릭해서 선택하는 기능만")."""
from __future__ import annotations

import pytest


def _wheel(widget, dy: int = -120) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    pos = QPointF(widget.rect().center())
    event = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(), QPoint(0, dy),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def test_wheel_over_combo_scrolls_the_area_instead_of_changing_the_value():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QVBoxLayout, QWidget

    from claim_downloader.ui.widgets import WheelGuard

    app = QApplication.instance() or QApplication([])
    guard = WheelGuard(app)
    app.installEventFilter(guard)
    try:
        area = QScrollArea()
        body = QWidget()
        column = QVBoxLayout(body)
        combo = QComboBox()
        combo.addItems(["새 청구서에 넣기", "첨부만 다시 올리기", "셋째"])
        column.addWidget(combo)
        column.addSpacing(2000)                       # 콤보가 든 칸이 스크롤되게
        area.setWidget(body)
        area.resize(400, 300)
        area.show()
        app.processEvents()
        bar = area.verticalScrollBar()
        assert bar.maximum() > 0 and bar.value() == 0

        assert combo.focusPolicy() == Qt.StrongFocus  # 휠이 지나가며 초점(테두리)을 가져가지 않게 — 클릭 · Tab 은 그대로

        _wheel(combo)
        assert combo.currentIndex() == 0              # 값은 그대로
        assert bar.value() > 0                        # 휠은 스크롤 칸이 받는다
        before = bar.value()
        _wheel(combo, dy=120)
        assert combo.currentIndex() == 0 and bar.value() < before
        bar.setValue(bar.maximum())
        _wheel(combo)                                 # 스크롤 칸이 끝까지 내려가 있어도 값은 안 바뀐다
        assert combo.currentIndex() == 0

        alone = QComboBox()                           # 스크롤 칸 밖의 콤보도
        alone.addItems(["가", "나"])
        alone.show()
        app.processEvents()
        _wheel(alone)
        assert alone.currentIndex() == 0
        alone.close()

        app.removeEventFilter(guard)                  # 가드가 없으면 전처럼 바뀐다 — 시험이 가드를 보고 있다는 증거
        _wheel(combo)
        assert combo.currentIndex() == 1
    finally:
        app.removeEventFilter(guard)
        area.close()


def test_main_installs_the_guard_once():
    """새 콤보를 만들 때 따로 할 일이 없도록 app.main() 이 앱 전체에 한 번 깐다."""
    from pathlib import Path

    import claim_downloader.ui.app as app_module

    source = Path(app_module.__file__).read_text(encoding="utf-8")
    assert source.count("app.installEventFilter(WheelGuard(app))") == 1
