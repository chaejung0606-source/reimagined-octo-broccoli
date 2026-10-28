"""AI 플랫폼 고르기 · 로그인 상태 (claim_downloader/ai.py) — PySide6 없이 돈다.

위쪽 바 단추 · 홈 띠 · 설정이 모두 이 판단을 본다. 실제 claude 명령은 부르지 않는다 — check_claude 를 갈아끼운다.
"""
from __future__ import annotations

import pathlib

import pytest

from claim_downloader import ai, settings
from claim_downloader.minutes.backends import claude_cli

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "claim_downloader"


@pytest.fixture
def claude(monkeypatch):
    """check_claude 의 결과를 정한다: ok · no_login · no_claude."""
    result = {"state": "ok"}

    def fake():
        state = result["state"]
        if state == "no_claude":
            return ("no_claude", "claude 명령을 찾을 수 없습니다.")
        if state == "no_login":
            return ("no_login", claude_cli.LOGIN_HELP)
        return ("ok", "2.1.0 (Claude Code)")

    monkeypatch.setattr(claude_cli, "check_claude", fake)
    return result


def test_minutes_defaults_to_claude_code():
    """일반청구의 AI 읽기는 2026-10-28 걷어냈다 — AI 를 쓰는 업무는 회의록 생성 하나."""
    cfg = settings.load()
    assert ai.chosen("minutes", cfg) == claude_cli.ClaudeCliBackend.key
    assert list(ai.USES) == ["minutes"]
    # 같은 플랫폼이면 한 번만 확인한다
    assert ai.used_keys(cfg) == [claude_cli.ClaudeCliBackend.key]


def test_unknown_platform_in_settings_falls_back_to_first():
    settings.update(minutes_backend="없는-플랫폼")
    assert ai.chosen("minutes") == claude_cli.ClaudeCliBackend.key


def test_each_use_has_its_own_setting():
    assert ai.USES["minutes"][1] == "minutes_backend"
    cfg = settings.load()
    for _use, (_title, field) in ai.USES.items():
        assert hasattr(cfg, field)


def test_probe_logged_in(claude):
    status = ai.probe(claude_cli.ClaudeCliBackend.key)
    assert status.state == ai.OK
    assert status.usable
    assert status.text == "로그인됨" and status.tone == "success"
    assert status.checked_at > 0


def test_probe_logged_out_is_usable_but_needs_login(claude):
    claude["state"] = "no_login"
    status = ai.probe(claude_cli.ClaudeCliBackend.key)
    assert status.state == ai.NO_LOGIN
    # 로그인 확인은 틀릴 수 있어 막지 않는다 — 화면이 묻는다
    assert status.usable
    assert status.text == "로그인 필요" and status.tone == "warning"
    # 위쪽 바 설명에 들어가므로 긴 안내문이 아니라 한 줄
    assert "\n" not in status.note and len(status.note) < 80


def test_probe_missing(claude):
    claude["state"] = "no_claude"
    status = ai.probe(claude_cli.ClaudeCliBackend.key)
    assert status.state == ai.MISSING
    assert not status.usable


def test_probe_error_does_not_raise(monkeypatch):
    def boom():
        raise OSError("뜻밖의 문제")
    monkeypatch.setattr(claude_cli, "check_claude", boom)
    status = ai.probe(claude_cli.ClaudeCliBackend.key)
    assert status.state == ai.ERROR
    assert "뜻밖의 문제" in status.note
    assert not status.usable


def test_summary_shows_what_needs_a_hand_first():
    ok = ai.Status("a", ai.OK)
    login = ai.Status("b", ai.NO_LOGIN)
    missing = ai.Status("c", ai.MISSING)
    checking = ai.Status("d", ai.CHECKING)
    assert ai.summary([]) is None
    assert ai.summary([ok]) is ok
    assert ai.summary([ok, login]) is login
    assert ai.summary([checking, login, missing]) is missing
    assert ai.summary([ok, checking]) is checking


def test_short_label_drops_explanation():
    key = claude_cli.ClaudeCliBackend.key
    assert ai.short_label(key) == ai.label_of(key).split(" (", 1)[0]
    assert "(" not in ai.short_label(key)
    assert ai.label_of("모르는-키") == "모르는-키"


def test_login_only_for_platforms_that_can_open_a_login_window(monkeypatch):
    opened = []
    monkeypatch.setattr(claude_cli, "open_login", lambda email="": opened.append(email))
    assert ai.can_login(claude_cli.ClaudeCliBackend.key)
    ai.open_login(claude_cli.ClaudeCliBackend.key, "someone@example.com")
    assert opened == ["someone@example.com"]
    assert not ai.can_login("모르는-키")
    with pytest.raises(RuntimeError):
        ai.open_login("모르는-키")


def test_no_password_is_kept_for_ai_login():
    """로그인은 그 플랫폼의 창에서 사람이 한다 — 이메일(미리 채우기)만 설정에 남는다."""
    fields = set(vars(settings.load()))
    assert not {f for f in fields if "password" in f.lower() or "token" in f.lower()}
    for path in (SRC / "ai.py", SRC / "ui" / "ai_status.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "password" not in text and "token" not in text


def test_pages_no_longer_pick_platform_or_open_login_themselves():
    """회의록 생성은 설정의 플랫폼을 쓰고, 로그인은 위쪽 단추(ai_status)로 한다(2026-10-14). 일반청구는 AI 를 쓰지 않는다(2026-10-28)."""
    text = (SRC / "ui" / "pages" / "minutes.py").read_text(encoding="utf-8")
    assert "backend_box" not in text
    assert "claude_cli.open_login" not in text
    assert "PlatformRow" in text
    claim = (SRC / "ui" / "pages" / "claim.py").read_text(encoding="utf-8")
    assert "PlatformRow" not in claim and "claude_cli" not in claim
