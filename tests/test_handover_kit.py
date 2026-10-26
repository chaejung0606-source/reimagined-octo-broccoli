"""다른 저장소로 옮길 노하우 묶음(docs/handover-kit, 담당자 2026-10-26 "다른 레포에 노하우를 전달") — 묶음이 온전하고 도구가 읽기만 하는지.

독립 실행 도구 structure_capture.py 는 diagnose.py 의 읽기 JS 를 그대로 떼어 낸 것이다 — diagnose.py 의 JS 를 고치면 묶음의 도구에도 옮긴다(둘이 같은지 본다).
Playwright 는 도구의 main() 안에서만 들여오므로 브라우저 없이 글 만들기 · 가림 규칙을 본다. JS 는 모의 화면으로 따로 돌렸다(실제 Chromium).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import re
from pathlib import Path

from claim_downloader import diagnose

KIT = Path(__file__).resolve().parents[1] / "docs" / "handover-kit"
FILES = ("README.md", "structure_capture.py", "CLAUDE.md.template", "test_safety_template.py", "gitignore.template", "ci.yml.template")


def _tool():
    spec = importlib.util.spec_from_file_location("structure_capture", KIT / "structure_capture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _el(**kw):
    base = {"tag": "input", "type": "text", "id": "", "name": "", "cls": "", "label": "", "text": "",
            "value": "", "options": None, "onclick": "", "href": "", "disabled": False, "readonly": False, "visible": True}
    base.update(kw)
    return base


def test_kit_is_complete_and_readme_names_every_file():
    readme = (KIT / "README.md").read_text(encoding="utf-8")
    for name in FILES:
        assert (KIT / name).is_file(), name
        assert f"`{name}`" in readme, name
    # 묶음 안에는 실측 · 기록 파일이 없다(개인정보)
    assert not list(KIT.glob("*.txt")) and not list(KIT.glob("*.json"))


def test_tool_only_reads_and_imports_playwright_lazily():
    """진단 모드와 같은 규칙 — 누르거나 값을 넣거나 이벤트를 일으키는 코드가 없고, Playwright 는 main() 안에서만."""
    text = (KIT / "structure_capture.py").read_text(encoding="utf-8")
    for forbidden in (".click(", ".submit(", "dispatchEvent", ".focus(", "setAttribute(", "fill(", "type(", "press(",
                      "set_input_files", "keyboard.", "mouse."):
        assert forbidden not in text, forbidden
    assert not re.search(r"\.(value|checked|selectedIndex|innerHTML)\s*=[^=]", text)
    assert text.count(".goto(") == 1                      # 처음 주소를 여는 것뿐
    head, body = text.split("def main(")
    assert "import playwright" not in head and "from playwright" not in head
    assert "from playwright.sync_api import sync_playwright" in body


def test_tool_js_matches_diagnose():
    tool = _tool()
    assert tool._PROBE_JS == diagnose._PROBE_JS
    assert tool._GRID_JS == diagnose._GRID_JS


def test_tool_masks_and_formats(tmp_path):
    tool = _tool()
    line = tool._element_line(_el(type="password", id="pw", value="secret123"))
    assert "secret123" not in line and "값:" not in line
    assert "값:" not in tool._element_line(_el(type="file", value="C:/x.pdf"))
    assert "1" * 41 not in tool._element_line(_el(id="acct", value="1" * 100))
    assert tool.frame_kind("https://kcloud.kangwon.ac.kr/websquare/websquare.jsp?w2xPath=/cm/main/index.xml&m=1") == "w2xPath /cm/main/index.xml"
    assert tool.frame_kind("https://erp/rtask.act?PRJ_NO=1") == ""
    windows = [{"title": "K", "url": "https://kcloud/x", "frames": [
        {"url": "https://kcloud/websquare.jsp?w2xPath=/a.xml", "title": "", "kind": "w2xPath /a.xml", "framework": "WebSquare 5.0 · w2 요소 3",
         "elements": [_el(tag="button", type="", id="mf_btn", text="저장"), _el(type="hidden", id="authKey", value="(가림)", visible=False)],
         "aria": [{"role": "grid", "id": "grd", "cls": "w2grid", "visible": True, "rows": 2, "heads": ["학번", "이름"], "first": ["20…", "홍길동"]}]},
        {"url": "about:blank", "title": "", "kind": "", "elements": [], "error": "시간 초과 — 확인 창"},
    ]}]
    text = tool.format_report(windows, when="2026-10-26 10:00", label="첫 화면", target="kcloud")
    assert text.startswith("화면 구조  (2026-10-26 10:00) · 첫 화면 · 대상: kcloud")
    assert "<== w2xPath /a.xml" in text and "틀: WebSquare 5.0 · w2 요소 3" in text
    assert "role=grid 표 #grd class=w2grid: 행 2 · 머리글: 학번 | 이름" in text and "첫 행: 20… | 홍길동" in text
    assert "<button>  #mf_btn  '저장'" in text and "[숨김] <input hidden>  #authKey  값: (가림)" in text
    assert "(읽지 못함: 시간 초과 — 확인 창)" in text
    # 파일 이름은 때로, 같은 분이면 _2 — 덮어쓰지 않는다. 모음은 번호가 붙어 쌓인다
    now = dt.datetime(2026, 10, 26, 10, 0)
    first = tool.new_file(tmp_path, now)
    assert first.name == "화면구조_20261026_1000.txt"
    first.write_text("x", encoding="utf-8")
    assert tool.new_file(tmp_path, now).name == "화면구조_20261026_1000_2.txt"
    book = tmp_path / tool.BOOK_NAME
    assert tool.append_to_book(book, text) == 1 and tool.append_to_book(book, text) == 2
    assert book.read_text(encoding="utf-8").count("════ 화면 구조 ") == 2


def test_templates_keep_the_safety_rules():
    safety = (KIT / "test_safety_template.py").read_text(encoding="utf-8")
    for word in ("storage_state", "user_data_dir", "password", "FORBIDDEN_TEXTS", "set_input_files"):
        assert word in safety, word
    claude = (KIT / "CLAUDE.md.template").read_text(encoding="utf-8")
    assert "추측으로 바꾸지 않는다" in claude and "로그인은 앱이 연 브라우저에서 사람이 직접" in claude
    ignore = (KIT / "gitignore.template").read_text(encoding="utf-8")
    for pattern in ("*.pdf", "*.xlsx", "화면구조_*.txt", "_실행로그.txt", "config.json"):
        assert pattern in ignore, pattern
    ci = (KIT / "ci.yml.template").read_text(encoding="utf-8")
    assert "ruff check --select F821" in ci and "git ls-files" in ci
