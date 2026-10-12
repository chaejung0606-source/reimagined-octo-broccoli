"""업데이트 확인이 실패해도 앱이 죽지 않는지 본다.

실제로 사용자 PC에서 '업데이트 처리 중 오류가 발생했습니다' 만 뜨고 원인을
알 수 없는 일이 있었다. git 이 실패했을 때 오류 문구를 꺼내다 IndexError 가
나서, 준비해 둔 안내 대신 예외가 위로 샜기 때문이다.
"""
from __future__ import annotations

import subprocess

import pytest

from claim_downloader import updater


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


# ── 무슨 일이 있어도 예외가 밖으로 새지 않는다 ─────────────────────────────

def test_check_never_raises(monkeypatch):
    """예상 못 한 예외도 화면에 띄울 문구로 바뀐다."""
    def boom(*args, **kwargs):
        raise RuntimeError("알 수 없는 무언가")

    monkeypatch.setattr(updater, "is_git_checkout", boom)
    status = updater.check()
    assert not status.available
    assert "예상 못 한 문제" in status.error


def test_apply_never_raises(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("알 수 없는 무언가")

    monkeypatch.setattr(updater, "check", boom)
    ok, message = updater.apply()
    assert ok is False and "예상 못 한 문제" in message


def test_fetch_failure_suggests_zip(monkeypatch):
    """망에서 막히면 대안을 함께 알려 준다."""
    def run(args, **kwargs):
        if "remote" in args:
            return subprocess.CompletedProcess(
                args, 0, f"https://github.com/{updater.EXPECTED_REPO}", "")
        return subprocess.CompletedProcess(args, 128, "", "fatal: unable to access")

    monkeypatch.setattr(subprocess, "run", run)
    assert "zip" in updater.check().error


# ── 윈도우에서 실제로 막혔던 것들 ───────────────────────────────────────

def test_git_disables_line_ending_conversion(monkeypatch):
    """autocrlf 가 켜진 윈도우 git 은 CRLF 배치 파일을 늘 '수정됨' 으로 봐 업데이트를 막았다."""
    seen = {}

    def run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(updater.subprocess, "run", run)
    updater._git("status", "--porcelain")
    assert "core.autocrlf=false" in seen["args"]
    assert seen["args"][0].endswith("git") and seen["args"][-2:] == ["status", "--porcelain"]


def test_git_hides_console_window_on_windows(monkeypatch):
    """pythonw 아래서 git 이 호출마다 검은 창을 띄웠다 닫았다."""
    seen = {}

    def run(args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(updater.subprocess, "run", run)
    monkeypatch.setattr(updater.os, "name", "nt")
    monkeypatch.setattr(updater.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    updater._git("status")
    assert seen.get("creationflags") == 0x08000000


def test_untracked_files_do_not_block_update(monkeypatch):
    """담당자가 폴더에 메모 파일을 두어도 빨리감기 갱신은 막히지 않아야 한다."""
    calls = []

    def git(*args):
        calls.append(args)
        if args[:2] == ("remote", "get-url"):
            return subprocess.CompletedProcess(args, 0, "https://github.com/" + updater.EXPECTED_REPO, "")
        if args[0] == "rev-list":
            return subprocess.CompletedProcess(args, 0, "2\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(updater, "_git", git)
    status = updater.check()
    assert status.available and not status.blocked_reason
    assert ("status", "--porcelain", "--untracked-files=no") in calls


def test_git_is_found_next_to_app_when_not_on_path(monkeypatch, tmp_path):
    """설치 스크립트가 둔 휴대용 MinGit(앱 옆 tools/MinGit) — PATH 에 git 이 없어도 업데이트가 된다."""
    monkeypatch.setattr(updater.shutil, "which", lambda name: None)
    monkeypatch.setattr(updater, "REPO_ROOT", tmp_path / "app")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    assert updater._git_executable() == "git"            # 아무 데도 없으면 그대로 'git' (설치 안내로 이어진다)
    exe = tmp_path / "tools" / "MinGit" / "cmd" / "git.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert updater._git_executable() == str(exe)
    seen = {}

    def run(command, **kwargs):
        seen["exe"] = command[0]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(updater.subprocess, "run", run)
    updater._git("status")
    assert seen["exe"] == str(exe)
