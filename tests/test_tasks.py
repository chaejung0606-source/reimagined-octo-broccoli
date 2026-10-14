"""업무 목록(ui/tasks.py) — 홈 카드 · 독 · 탭이 모두 읽는 표.

PySide6 없이 돈다. 표에 적힌 그림·화면 클래스가 실제로 있는지 본다.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from claim_downloader.ui import tasks

UI = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "ui"


def _art_map() -> dict[str, str]:
    tree = ast.parse((UI / "art.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "ART":
            return ast.literal_eval(node.value)
    raise AssertionError("ART 표가 없습니다")


def test_ids_are_unique_and_home_is_reserved():
    ids = [t.id for t in tasks.TASKS + tasks.UTILITIES]
    assert len(ids) == len(set(ids))
    assert tasks.HOME_ID not in ids


def test_every_task_has_art_and_page():
    art = _art_map()
    for task in tasks.TASKS + tasks.UTILITIES:
        assert task.art in art, task.id
        assert (UI / "assets" / "art" / f"{art[task.art]}.png").exists(), task.id
        module, cls = task.page.split(":")
        source = (UI / "pages" / f"{module}.py").read_text(encoding="utf-8")
        assert re.search(rf"^class {cls}\(", source, re.M), task.page


def test_every_task_has_a_line_icon():
    icons = (UI / "icons.py").read_text(encoding="utf-8")
    for task in tasks.TASKS + tasks.UTILITIES:
        assert f'"{task.icon}":' in icons, task.id
    assert f'"{tasks.HOME_ICON}":' in icons


def test_dock_holds_only_tasks_not_utilities():
    assert all(t.dock for t in tasks.TASKS)
    assert not any(t.dock for t in tasks.UTILITIES)


def test_tasks_in_requested_order():
    assert [t.name for t in tasks.TASKS] == ["청구서 받기", "회의록 생성", "일반청구", "장학금 청구", "카드청구"]
    assert all(tasks.find(i).ready for i in ("download", "meeting", "claim", "scholarship"))
    assert not tasks.find("card").ready


def test_dock_overlay_is_raised_whenever_the_page_changes():
    """QStackedWidget 이 화면을 바꿀 때 새 화면을 맨 위로 올리므로, 독을 그때마다 다시 올려야 마우스가 닿는다.

    홈에서는 펼쳐지는데 설정·회의록 탭에서는 안 펼쳐지던 문제(2026-10-13). PySide6 없이 연결만 확인한다.
    """
    source = (UI / "app.py").read_text(encoding="utf-8")
    assert re.search(r"currentChanged\.connect\(.*dock_overlay\.raise_\(\)", source)


def test_taskbar_identity_is_shared_by_app_and_shortcut():
    """창(app.py)과 바로가기(create_shortcut.py)가 같은 작업 표시줄 이름을 써야 한 단추로 묶인다."""
    from claim_downloader import settings
    app_source = (UI / "app.py").read_text(encoding="utf-8")
    tool_source = (UI.parents[2] / "tools" / "create_shortcut.py").read_text(encoding="utf-8")
    assert "settings.APP_USER_MODEL_ID" in app_source and "SetCurrentProcessExplicitAppUserModelID" in app_source
    # 이름은 settings 한 곳에만 — 도구는 그것을 읽을 뿐, 글자를 따로 적어 두지 않는다
    assert "APP_USER_MODEL_ID as APP_ID" in tool_source and settings.APP_USER_MODEL_ID not in tool_source
    assert "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3" in tool_source      # PKEY_AppUserModel_ID
