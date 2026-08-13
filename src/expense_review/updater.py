"""자동 업데이트.

Claude 가 저장소에 기능을 올리면 앱이 그것을 받아 오도록 한다.
설치본이 git 작업본이면 `git pull --ff-only` 로 갱신한다.

안전 원칙
  - 정해진 저장소·브랜치에서만 받는다. 임의 원격은 거부한다.
  - 확인과 적용을 분리한다. 기본값은 '확인만' 이고, 적용은 사용자가 누른다.
  - 사용자가 고친 검토 기준은 `~/.expense-review/` 에 있어 pull 대상이 아니다.
    배포본 규칙 파일만 갱신되므로 수정 내용이 날아가지 않는다.
  - 로컬 변경이 있으면 덮어쓰지 않고 멈춘다.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 이 저장소·브랜치에서만 업데이트를 받는다.
EXPECTED_REPO = "chaejung0606-source/reimagined-octo-broccoli"
BRANCH = "claude/expense-document-review-criteria-yzji9p"

GIT_TIMEOUT = 60


@dataclass
class UpdateStatus:
    available: bool = False
    behind: int = 0
    current: str = ""
    latest: str = ""
    messages: tuple[str, ...] = ()
    blocked_reason: str = ""     # 적용할 수 없는 이유 (로컬 변경 등)
    error: str = ""

    @property
    def can_apply(self) -> bool:
        return self.available and not self.blocked_reason and not self.error

    def describe(self) -> str:
        if self.error:
            return f"업데이트를 확인하지 못했습니다: {self.error}"
        if not self.available:
            return "최신 상태입니다."
        head = f"새 업데이트 {self.behind}건이 있습니다."
        if self.blocked_reason:
            return f"{head} 다만 {self.blocked_reason}"
        return head


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, timeout=GIT_TIMEOUT,
    )


def is_git_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


def _remote_is_expected() -> bool:
    result = _git("remote", "get-url", "origin")
    return result.returncode == 0 and EXPECTED_REPO in result.stdout


def current_version() -> str:
    """짧은 커밋 해시 + 날짜. 화면에 '설치된 버전'으로 보여 준다."""
    if not is_git_checkout():
        return "(개발 설치)"
    result = _git("log", "-1", "--format=%h · %cd", "--date=format:%Y-%m-%d")
    return result.stdout.strip() if result.returncode == 0 else "(알 수 없음)"


def check() -> UpdateStatus:
    """원격에 새 커밋이 있는지 본다. 파일은 건드리지 않는다."""
    if not is_git_checkout():
        return UpdateStatus(error="git 작업본이 아니라 자동 업데이트를 쓸 수 없습니다.")
    if not _remote_is_expected():
        return UpdateStatus(error="원격 저장소가 예상과 다릅니다. 업데이트를 중단합니다.")

    fetched = _git("fetch", "origin", BRANCH)
    if fetched.returncode != 0:
        return UpdateStatus(error=(fetched.stderr or "네트워크 오류").strip().splitlines()[-1][:200])

    counted = _git("rev-list", "--count", f"HEAD..origin/{BRANCH}")
    if counted.returncode != 0:
        return UpdateStatus(error="변경 사항을 세지 못했습니다.")
    behind = int(counted.stdout.strip() or 0)

    status = UpdateStatus(
        available=behind > 0,
        behind=behind,
        current=current_version(),
        latest=_git("log", "-1", "--format=%h", f"origin/{BRANCH}").stdout.strip(),
    )
    if behind:
        log = _git("log", "--format=%s", f"HEAD..origin/{BRANCH}")
        status.messages = tuple(line for line in log.stdout.strip().splitlines() if line)[:10]

    dirty = _git("status", "--porcelain")
    if dirty.returncode == 0 and dirty.stdout.strip():
        status.blocked_reason = (
            "이 폴더에 저장하지 않은 변경이 있어 자동 적용을 멈췄습니다. "
            "변경을 정리한 뒤 다시 시도하세요."
        )
    return status


def apply() -> tuple[bool, str]:
    """확인된 업데이트를 적용한다. 되돌릴 수 없는 병합은 하지 않는다."""
    status = check()
    if status.error:
        return False, status.error
    if not status.available:
        return True, "이미 최신 상태입니다."
    if status.blocked_reason:
        return False, status.blocked_reason

    pulled = _git("merge", "--ff-only", f"origin/{BRANCH}")
    if pulled.returncode != 0:
        return False, (
            "빨리감기로 갱신할 수 없습니다. 로컬 커밋이 있는지 확인하세요.\n"
            + (pulled.stderr or "").strip()[:300]
        )
    return True, f"업데이트 {status.behind}건을 적용했습니다. 앱을 다시 시작하면 반영됩니다."
