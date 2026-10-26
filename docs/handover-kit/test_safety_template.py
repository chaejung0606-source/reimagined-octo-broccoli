"""안전 원칙을 코드로 지킨다 — 새 저장소의 tests/test_safety.py 로 복사해 쓰는 틀.

  - 화면에서 누르는 대상은 담당자가 허락한 것만(허용 목록). 제출 · 결재 · 삭제 단추를 누르는 코드가 들어오면 여기서 깨진다.
  - 읽기만 하는 모듈(화면 구조 저장 도구 · *_PROBE_JS)에는 누르기 · 값 넣기 · 이벤트 발생이 없다.
  - 로그인 정보를 저장하지 않는다. 브라우저 쿠키 · 프로필을 디스크에 남기지 않는다.
  - 브라우저를 띄우는 곳은 session.py 하나뿐이다.

새 기능 때문에 이 테스트를 고쳐야 한다면, 고치기 전에 CLAUDE.md '안전 원칙' 을 다시 읽는다.
COSS 업무데스크(ERP 자동화)의 tests/test_safety.py 를 줄인 것이다 — 거기서는 화면마다 누르는 상수의 수까지 센다(`text.count(".click()") == N`).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PACKAGE = "myapp"                 # ← 새 패키지 이름(src/<PACKAGE>/)
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / PACKAGE
TOOL = ROOT / "tools" / "structure_capture.py"

# 앱이 눌러도 되는 것 — 담당자가 글로 허락한 단추의 id · 글자 (CLAUDE.md 9절과 같은 목록, 날짜를 주석으로)
# (빈 중괄호 {} 는 dict 가 되므로 set() 으로 둔다 — 허락받은 것을 더할 때 {"#btnSave"} 꼴로)
ALLOWED_IDS: set[str] = set()          # 예: {"#btnSave"}   — 담당자 YYYY-MM-DD "저장은 눌러도 됩니다"
ALLOWED_TEXTS: set[str] = set()        # 예: {"저장"}
# 어디서도 누르지 않는 글자 — 제출 · 결재 · 신청 · 삭제 · 취소 … (실측 뒤 그 화면의 단추 글자로 채운다)
FORBIDDEN_TEXTS = {"제출", "결재", "신청", "삭제", "취소", "승인"}
# 값을 넣어도 되는 모듈 — 보통 form.py 하나. 파일 올리기(set_input_files)는 attach.py 하나
TYPING_MODULES = {"form.py"}
UPLOAD_MODULES = {"attach.py"}
# 로그인 정보를 다뤄도 되는 모듈 — 기본은 없음(담당자가 어느 사이트의 자동 로그인을 허락하면 그 모듈 하나만)
CREDENTIAL_MODULES: set[str] = set()


def _sources() -> list[Path]:
    if not SRC.is_dir():
        pytest.skip(f"src/{PACKAGE} 가 없습니다 — PACKAGE 를 고치세요")
    return sorted(SRC.rglob("*.py"))


def test_only_allowed_targets_are_pressed():
    """누르기 JS(CLICK_*_JS) 안에서 글자 · id 로 찾는 대상이 허용 목록 안인지. '=== '<글자>'' · '#id' 꼴을 본다."""
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for name, js in re.findall(r"^(CLICK_\w+_JS)\s*=\s*r?\"\"\"(.*?)\"\"\"", text, re.S | re.M):
            texts = set(re.findall(r"===\s*'([^']+)'", js))
            assert texts <= ALLOWED_TEXTS, (path.name, name, texts - ALLOWED_TEXTS)
            ids = set(re.findall(r"'(#[A-Za-z_][\w-]*)'", js))
            assert ids <= ALLOWED_IDS, (path.name, name, ids - ALLOWED_IDS)
            for word in FORBIDDEN_TEXTS:
                assert f"'{word}'" not in js, (path.name, name, word)


def test_readers_only_read():
    """읽기 상수(*_PROBE_JS)와 화면 구조 저장 도구는 누르거나 값을 넣거나 이벤트를 일으키지 않는다."""
    files = [TOOL] if TOOL.exists() else []
    for path in _sources() + files:
        text = path.read_text(encoding="utf-8")
        blocks = [text] if path == TOOL else re.findall(r"^\w+_PROBE_JS\s*=\s*r?\"\"\"(.*?)\"\"\"", text, re.S | re.M)
        for js in blocks:
            for forbidden in (".click(", ".submit(", "dispatchEvent", ".focus(", "setAttribute(", "fill(", "type(", "press(", "set_input_files"):
                assert forbidden not in js, (path.name, forbidden)
            assert not re.search(r"\.(value|checked|selectedIndex|innerHTML)\s*=[^=]", js), path.name


def test_typing_stays_in_form_module():
    """값 넣기(fill · type · press · keyboard)는 TYPING_MODULES 에만, 파일 올리기는 UPLOAD_MODULES 에만."""
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        if path.name not in TYPING_MODULES | CREDENTIAL_MODULES:
            for name in (".fill(", ".type(", ".press(", "keyboard."):
                assert name not in text, (path.name, name)
        if path.name not in UPLOAD_MODULES:
            assert "set_input_files" not in text, path.name


def test_no_credentials_anywhere():
    for path in _sources():
        text = path.read_text(encoding="utf-8").lower()
        for word in ("storage_state", "user_data_dir"):      # 로그인 쿠키를 디스크에 남긴다
            assert word not in text, (path.name, word)
        if path.name in CREDENTIAL_MODULES:
            continue
        for word in ("password", "passwd"):
            assert word not in text, (path.name, word)


def test_browser_is_launched_in_one_place():
    launchers = [p.name for p in _sources() if "sync_playwright" in p.read_text(encoding="utf-8")]
    assert launchers in ([], ["session.py"]), launchers
