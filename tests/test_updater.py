"""업데이트 확인이 실패해도 앱이 죽지 않는지 본다.

실제로 사용자 PC에서 '업데이트 처리 중 오류가 발생했습니다' 만 뜨고 원인을
알 수 없는 일이 있었다. git 이 실패했을 때 오류 문구를 꺼내다 IndexError 가
나서, 준비해 둔 안내 대신 예외가 위로 샜기 때문이다.
"""
from __future__ import annotations

import subprocess

import pytest

from expense_review import updater


def _fake_run(returncode: int = 0, stdout: str = "", stderr: str = ""):
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)
    return run


@pytest.fixture(autouse=True)
def looks_like_checkout(monkeypatch):
    monkeypatch.setattr(updater, "is_git_checkout", lambda: True)


# ── 오류 문구 뽑기 ────────────────────────────────────────────────────────

def test_first_line_falls_back_when_git_says_nothing():
    """stderr 가 비어 있어도 터지지 않고 준비된 문구를 쓴다."""
    assert updater._first_line("", "네트워크 오류") == "네트워크 오류"
    assert updater._first_line("   \n  \n", "네트워크 오류") == "네트워크 오류"


def test_first_line_takes_last_meaningful_line():
    assert updater._first_line("Cloning...\nfatal: 접속 실패\n", "x") == "fatal: 접속 실패"


# ── 실패해도 예외가 새지 않는다 ────────────────────────────────────────────

def test_fetch_failure_with_empty_stderr_is_reported_not_raised(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if "remote" in args:
            return subprocess.CompletedProcess(args, 0, f"https://github.com/{updater.EXPECTED_REPO}", "")
        return subprocess.CompletedProcess(args, 128, "", "")   # fetch 실패, 설명 없음

    monkeypatch.setattr(subprocess, "run", run)
    status = updater.check()
    assert status.error and not status.available


def test_missing_git_gives_installation_hint(monkeypatch):
    def run(args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", run)
    status = updater.check()
    assert "Git" in status.error


def test_timeout_is_reported(monkeypatch):
    def run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, updater.GIT_TIMEOUT)

    monkeypatch.setattr(subprocess, "run", run)
    assert "네트워크" in updater.check().error


def test_unexpected_remote_is_refused(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        _fake_run(0, "https://github.com/someone/else", ""))
    assert "예상과 다릅니다" in updater.check().error


def test_non_numeric_count_does_not_raise(monkeypatch):
    def run(args, **kwargs):
        if "remote" in args:
            return subprocess.CompletedProcess(args, 0, f"git@github.com:{updater.EXPECTED_REPO}", "")
        if "fetch" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "숫자가 아님", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert updater.check().error


# ── 인코딩 ────────────────────────────────────────────────────────────────

def test_git_is_decoded_as_utf8(monkeypatch):
    """한글 윈도우에서 CP949 로 해석하면 커밋 메시지와 '·' 이 깨진다."""
    seen = {}

    def run(args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    updater._git("log")
    assert seen["encoding"] == "utf-8"
    # 자격 증명 창이 떠서 앱이 멈추는 일이 없어야 한다
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_git_output_is_never_none(monkeypatch):
    """캡처가 비면 파이썬이 None 을 준다. 그대로 흘리면 .strip() 에서 앱이 죽는다.

    사용자 PC에서 실제로 여기서 터졌다:
        AttributeError: 'NoneType' object has no attribute 'strip'
    """
    monkeypatch.setattr(subprocess, "run",
                        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, None, None))
    done = updater._git("log")
    assert done.stdout == "" and done.stderr == ""


def test_check_survives_none_output(monkeypatch):
    """git 이 아무것도 돌려주지 않아도 화면까지 도달해야 한다."""
    def run(args, **kwargs):
        if "remote" in args:
            return subprocess.CompletedProcess(
                args, 0, f"https://github.com/{updater.EXPECTED_REPO}", None)
        if "rev-list" in args:
            return subprocess.CompletedProcess(args, 0, "3", None)
        return subprocess.CompletedProcess(args, 0, None, None)

    monkeypatch.setattr(subprocess, "run", run)
    status = updater.check()          # 예외 없이 끝나야 한다
    assert status.behind == 3
    assert status.messages == ()
