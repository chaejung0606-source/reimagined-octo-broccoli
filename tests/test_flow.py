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


def test_download_goes_docs_project_login_list():
    # 받을 서류를 먼저, 과제를 그다음에(담당자 2026-10-22 "받을 서류를 먼저 고르고 그다음 과제를 선택하도록")
    assert DOWNLOAD_ORDER == ["docs", "project", "login", "list"]
    assert download_stage(docs_picked=False, picked=True, reading=True, listed=True) == "docs"   # 서류를 고르기 전에는 늘 ①
    assert download_stage(docs_picked=True, picked=False, reading=True, listed=True) == "project"
    assert download_stage(docs_picked=True, picked=True, reading=False, listed=False) == "login"
    assert download_stage(docs_picked=True, picked=True, reading=True, listed=False) == "list"
    assert download_stage(docs_picked=True, picked=True, reading=False, listed=True) == "list"


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


def test_done_steps_shrink_to_boxes_on_one_row():
    """담당자 2026-10-26(증빙 다운로드 그림): 마친 ① ② ③ 이 저마다 폭을 다 쓰는 줄이라 지금 단계 ④ 가 아래로 밀렸다 —
    "이전에 진행 완료된 단계들을 굳이 저렇게 가로줄을 다 차지않고 네모박스로 줄여서 컴팩하게 … 같은 행에". 마친 단계는 작은 네모로 한 줄에
    나란히(높이는 같게), 지금 단계는 폭을 다 쓴다. 줄 폭이 모자라면 다음 줄로 넘어가고, 다시 펼치면(바꾸기) 폭을 다 쓰는 줄로 돌아온다."""
    pytest.importorskip("PySide6")
    import time

    from PySide6.QtWidgets import QApplication, QLabel

    from claim_downloader.ui.flow import FlowArea, FlowStep

    app = QApplication.instance() or QApplication([])

    def settle(sec: float = 0.3) -> None:
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    area = FlowArea()
    s1, s2 = FlowStep("1", "무엇을 받을까요?"), FlowStep("2", "어느 과제의 서류를 받을까요?")
    s3, s4 = FlowStep("3", "ERP 에 로그인", editable=False), FlowStep("4", "받을 서류를 확인하고 받으세요", editable=False)
    s4.add(QLabel("표"), 1)
    for step in (s1, s2, s3):
        area.add(step)
    area.add(s4, 1)
    s1.set_state(DONE, "구매요청(계약) 서류")
    s2.set_state(DONE, "폴더 만든 과제 13개 — " + " · ".join(f"20240847000{i} 2024년도 사업비" for i in range(1, 8)))
    s3.set_state(DONE, "ERP 로그인됨")
    s4.set_state(CURRENT)
    area.resize(1200, 500)
    area.show()
    settle()
    chips = [s1, s2, s3]
    assert len({c.y() for c in chips}) == 1                                   # 같은 줄에
    assert len({c.height() for c in chips}) == 1                              # 같은 높이로
    assert s1.x() < s2.x() < s3.x() and all(c.width() < 1200 // 2 + 60 for c in chips)
    assert s1.width() < s2.width()                                            # 고른 값이 긴 네모가 더 넓다
    assert s4.y() > s1.y() + s1.height() and s4.width() == 1200 and s4.height() > 150     # 지금 단계는 폭을 다 쓰고 남는 높이를 받는다
    assert s1.width() >= s1.sizeHint().width()                                # 번호 · 제목 · [바꾸기] 는 다 보인다
    # 좁은 창 — 다 안 들어가면 다음 줄로
    area.resize(640, 500)
    settle()
    assert len({c.y() for c in chips}) >= 2 and s4.y() > max(c.y() + c.height() for c in chips)
    assert all(c.x() + c.width() <= 640 for c in chips) and s4.width() == 640
    # 다시 펼치면(바꾸기) 폭을 다 쓰는 줄로
    area.resize(1200, 500)
    s2.set_state(CURRENT)
    s4.set_state(HIDDEN)
    settle()
    assert s2.width() == 1200 and s1.width() < 1200 and s2.y() > s1.y()
    area.deleteLater()
    app.processEvents()
