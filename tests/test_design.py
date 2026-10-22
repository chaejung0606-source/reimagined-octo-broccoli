"""디자인 토큰 대비와 입체 그림 에셋.

글자가 놓이는 바탕마다 WCAG AA(일반 글자 4.5:1)를 넘는지 본다. 토큰 하나를
고쳤다가 회색 글씨가 바탕에 묻히는 일을 막으려는 것이다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from claim_downloader.ui.tokens import COLORS, contrast

UI = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "ui"

SURFACES = ["bg", "surface", "surface_alt", "selection", "hover", "tabbar"]
TEXTS = ["text", "text_muted", "text_faint"]


@pytest.mark.parametrize("fg", TEXTS)
@pytest.mark.parametrize("bg", SURFACES)
def test_text_contrast(fg, bg):
    assert contrast(COLORS[fg], COLORS[bg]) >= 4.5, (fg, bg)


def test_buttons_and_selected_menu():
    assert contrast(COLORS["on_primary"], COLORS["primary"]) >= 4.5
    assert contrast(COLORS["on_primary"], COLORS["primary_hover"]) >= 4.5
    assert contrast(COLORS["primary_hover"], COLORS["selection"]) >= 4.5   # 선택된 메뉴 글자


@pytest.mark.parametrize("name", ["success", "warning", "danger", "info", "neutral"])
def test_status_pills(name):
    assert contrast(COLORS[name], COLORS[f"{name}_bg"]) >= 4.5


def _art_map() -> dict[str, str]:
    """art.py 의 ART 표를 PySide6 없이 읽는다."""
    tree = ast.parse((UI / "art.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "ART":
            return ast.literal_eval(node.value)
    raise AssertionError("ART 표가 없습니다")


def test_every_art_meaning_has_an_asset():
    for meaning, name in _art_map().items():
        assert (UI / "assets" / "art" / f"{name}.png").exists(), meaning


def test_fonts_are_bundled():
    """글꼴 선언만 있고 파일이 없으면 동료 PC 에서 대체 글꼴이 나온다."""
    fonts = sorted(p.name for p in (UI / "assets" / "fonts").glob("Pretendard-*"))
    # TrueType 판 — OTF 는 윈도우의 작은 글씨에서 가로획(ㅡ)이 지워졌다(담당자 2026-10-22, app.load_fonts)
    assert fonts == ["Pretendard-Bold.ttf", "Pretendard-Medium.ttf", "Pretendard-Regular.ttf", "Pretendard-SemiBold.ttf"]


def test_pages_use_art_by_meaning_only():
    """화면 코드는 파일 이름이 아니라 업무 의미로 그림을 부른다."""
    meanings = set(_art_map())
    files = list((UI / "pages").glob("*.py")) + [UI / "app.py", UI / "widgets.py", UI / "shell.py"]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("Art", "KpiCard", "StepCard", "EmptyState"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value in {
                            "envelope", "signed-doc", "folder-papers", "send-tray", "monitor-lock",
                            "panels", "tray-pen", "book-pen", "dial"}:
                        raise AssertionError(f"{path.name}: 파일 이름 '{arg.value}' 대신 의미 이름을 쓰세요")
    assert {"receive", "approved", "archive", "upload", "login", "overview", "register", "journal",
            "meeting", "claim", "card", "recent", "done"} <= meanings
