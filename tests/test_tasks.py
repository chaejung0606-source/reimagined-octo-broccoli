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


def test_dock_holds_only_tasks_not_utilities():
    assert all(t.dock for t in tasks.TASKS)
    assert not any(t.dock for t in tasks.UTILITIES)


def test_four_tasks_in_requested_order():
    assert [t.name for t in tasks.TASKS] == ["청구서 받기", "회의록 생성", "일반청구", "카드청구"]
    assert tasks.find("download").ready
    assert not any(tasks.find(i).ready for i in ("meeting", "claim", "card"))
