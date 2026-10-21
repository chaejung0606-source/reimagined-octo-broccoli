"""단계 흐름(ui/flowlogic.py) — 담당자 2026-10-21 "클릭해야 하는 이동 순서대로 버튼 및 기능이 하나 둘 떠올라서 순서대로 선택하게"."""
from __future__ import annotations

import pytest

from claim_downloader.ui.flowlogic import CURRENT, DONE, DOWNLOAD_ORDER, HIDDEN, OPEN, download_stage, flow_states


def test_steps_before_are_folded_and_after_are_hidden():
    assert flow_states(["a", "b", "c"], "a") == {"a": CURRENT, "b": HIDDEN, "c": HIDDEN}
    assert flow_states(["a", "b", "c"], "b") == {"a": DONE, "b": CURRENT, "c": HIDDEN}
    assert flow_states(["a", "b", "c"], "c", keep_open=("a",)) == {"a": OPEN, "b": DONE, "c": CURRENT}


def test_download_goes_what_login_list():
    assert DOWNLOAD_ORDER == ["what", "login", "list"]
    assert download_stage(picked=False, reading=True, listed=True) == "what"      # 고르기 전에는 늘 ①
    assert download_stage(picked=True, reading=False, listed=False) == "login"
    assert download_stage(picked=True, reading=True, listed=False) == "list"
    assert download_stage(picked=True, reading=False, listed=True) == "list"


def test_badges_take_only_their_text_width():
    """담당자 2026-10-21: 단계 번호 · 상태 배지가 줄 폭을 나눠 받아 길게 늘어났다 — 글자만큼만(폭을 숫자로 박지 않고)."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

    from claim_downloader.ui.flow import FlowStep
    from claim_downloader.ui.widgets import Pill

    app = QApplication.instance() or QApplication([])
    holder = QWidget()
    row = QHBoxLayout(holder)
    pill = Pill("로그인 기다리는 중", "warning")
    row.addWidget(pill)                          # 늘려 받을 곳이 배지뿐인 줄에서도
    holder.resize(900, 60)
    holder.show()
    app.processEvents()
    assert pill.width() == pill.sizeHint().width()

    step = FlowStep("2", "ERP 에 로그인", editable=False)
    side = Pill("로그인 기다리는 중", "warning")
    step.add_side(side)
    step.set_state(CURRENT)
    step.resize(1200, 120)
    app.processEvents()
    assert step.number.width() == step.number.sizeHint().width()
    assert side.width() == side.sizeHint().width()
