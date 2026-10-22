"""단계 흐름(ui/flowlogic.py) — 담당자 2026-10-21 "클릭해야 하는 이동 순서대로 버튼 및 기능이 하나 둘 떠올라서 순서대로 선택하게"."""
from __future__ import annotations

import pytest

from claim_downloader.ui.flowlogic import (
    CLAIM_ORDER, CURRENT, DONE, DOWNLOAD_ORDER, HIDDEN, MINUTES_ORDER, OPEN, STRUCTURE_ORDER, claim_stage, download_stage,
    flow_states, minutes_stage, parking_stage, structure_stage,
)


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


def test_structure_goes_site_open_save_send():
    assert structure_stage(picked=False, opened=True, saved=True) == "site"
    assert structure_stage(picked=True, opened=False, saved=True) == "open"         # 닫히면 다시 열기부터(파일은 머리 메뉴에)
    assert structure_stage(picked=True, opened=True, saved=False) == "save"          # 다른 업무에서 열어 둔 창이면 ② 는 저절로 지난다
    states = flow_states(STRUCTURE_ORDER, "send", keep_open=("save",))
    assert states == {"site": DONE, "open": DONE, "save": OPEN, "send": CURRENT}    # 저장한 뒤에도 다른 화면을 이어서 저장


def test_parking_goes_what_work_result():
    assert parking_stage(picked=False, has_result=True) == "what"
    assert parking_stage(picked=True, has_result=False) == "work"       # 처음엔 ① 부터(화면이 picked=False 로 연다 — 담당자 2026-10-22)
    assert parking_stage(picked=True, has_result=True) == "result"


def test_minutes_goes_folders_make_result():
    assert minutes_stage(has_dirs=False, finished=True) == "folders"
    assert minutes_stage(has_dirs=True, finished=False) == "make"          # 폴더를 더 넣으면(finished 를 푼다) 다시 ②
    assert minutes_stage(has_dirs=True, finished=True) == "result"
    # 폴더를 넣으면 ① 은 '회의 N건' 으로 접히고, [폴더 더 넣기] 를 누르면 펼친 채
    assert flow_states(MINUTES_ORDER, "make", keep_open=("make",))["folders"] == DONE
    assert flow_states(MINUTES_ORDER, "result", keep_open=("make", "folders")) == {"folders": OPEN, "make": OPEN, "result": CURRENT}


def test_claim_goes_add_check_put():
    assert claim_stage(has_dirs=False, ready=True) == "add"
    assert claim_stage(has_dirs=True, ready=False) == "check"          # 일반 폴더는 AI 로 읽기 전
    assert claim_stage(has_dirs=True, ready=True) == "put"
    # ② 는 표와 값을 보며 넣으므로 ③ 차례에도 펼친 채
    assert flow_states(CLAIM_ORDER, "put", keep_open=("check",)) == {"add": DONE, "check": OPEN, "put": CURRENT}


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
